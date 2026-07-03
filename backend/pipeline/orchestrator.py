"""Orquesta el pipeline completo: analizar -> rankear -> seleccionar -> ensamblar -> subtitular."""
from __future__ import annotations

import os
from typing import Callable

from .ffmpeg_utils import probe, run
from .analyze import analyze_video, Segment, MAX_CLIP, segment_signature, segment_signatures, sig_distance
from .gemini_rank import rank_with_gemini
from concurrent.futures import ThreadPoolExecutor

from .assemble import (build_variations, render_clip, export_resolution, dims_for,
                       add_voiceover, add_voiceover_and_sfx, WORKERS)
from .text_detect import mask_video as mask_video_text, available as east_available
from .text_translate import traducir_texto_pantalla as translate_screen_text
from .smart_caption_mask import mask_captions_smart
from .text_overlay import burn_hook
from .hook_gen import generate_hook, fetch_page_text
from .captions import add_captions
from . import supervisor
from . import gif_export
from . import phase_classify


# Cuántas veces el capitán (Claude) puede mandar a re-tapar un corte hasta aprobarlo
_MAX_CORRECCIONES = 1
# El capitán es LENTO (1 llamada a Claude por corte). Con muchos cortes no se pueden revisar
# todos sin frenar el pipeline: se revisa solo una MUESTRA espaciada (spot-check).
_CAPITAN_MAX_REVISIONES = 5


# Umbral de similitud visual: firmas con distancia < este valor se consideran el mismo plano
_DUP_THRESHOLD = 8


_N_VERSIONS = 8


def _select_for_target(segments: list[Segment], target_seconds: float,
                       max_clips: int | None = None) -> list[Segment]:
    """Arma un POOL grande y diverso de clips (de muchos videos distintos) para que
    las 6 versiones puedan usar clips DIFERENTES y no se repitan entre ellas."""
    n_sources = len({s.source_index for s in segments}) or 1
    clips_per_ver = max(4, min(10, round(target_seconds / 2.2)))
    # pool ideal = las N versiones COMPLETAS con clips distintos (NV*cpv) + MARGEN (el dedup visual
    # descarta varios): antes se capaba en 60 con 56 necesarios → cualquier descarte causaba reciclaje.
    pool_size = min(100, max(_N_VERSIONS * clips_per_ver + 16, n_sources * 3 + _N_VERSIONS))
    if max_clips:
        pool_size = min(pool_size, max_clips)
    # repartir entre fuentes: con muchos videos, pocos clips por video (más variedad)
    cap_per_source = max(2, (pool_size + n_sources - 1) // n_sources)

    ranked = sorted(segments, key=lambda s: s.score, reverse=True)
    chosen: list[Segment] = []
    chosen_sigs: list = []
    per_source: dict[int, int] = {}

    def is_duplicate(sigs) -> bool:
        # Duplicado REAL solo si: (a) algún frame es casi IDÉNTICO (<4 bits), o (b) COINCIDEN ≥2 de las
        # 3 firmas (misma escena de verdad). Con 1 sola coincidencia floja NO se descarta: con 30 videos
        # del mismo producto, tomas VÁLIDAS pero parecidas se estaban botando → pool chico → reciclaje.
        if not sigs:
            return False
        flojas = 0
        for a in sigs:
            if a is None:
                continue
            dmin = min((sig_distance(a, s) for s in chosen_sigs if s is not None), default=99)
            if dmin < 4:
                return True
            if dmin < _DUP_THRESHOLD:
                flojas += 1
        return flojas >= 2

    # 1ra pasada: respetando el tope por fuente (asegura variedad de videos)
    # 2da pasada: si falta, relajar el tope por fuente
    for relax in (False, True):
        for seg in ranked:
            if len(chosen) >= pool_size:
                break
            if seg in chosen:
                continue
            if not relax and per_source.get(seg.source_index, 0) >= cap_per_source:
                continue
            sigs = segment_signatures(seg)
            if is_duplicate(sigs):
                continue
            chosen.append(seg)
            chosen_sigs.extend(sigs)
            per_source[seg.source_index] = per_source.get(seg.source_index, 0) + 1
        if len(chosen) >= pool_size:
            break

    if not chosen and ranked:
        chosen = ranked[:min(max_clips, len(ranked))]
    return chosen


def analyze_select(
    video_paths: list[str],
    *,
    target_seconds: float = 15.0,
    max_clip_seconds: float = 3.0,
    use_gemini: bool = True,
    product_desc: str = "",
    gemini_key: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Analiza los videos, rankea con Gemini y selecciona los mejores cortes.
    Devuelve los segmentos elegidos (para luego renderizar o generar guiones)."""
    def report(msg, pct):
        if progress:
            progress(msg, pct)

    all_segments: list[Segment] = []
    infos: dict[int, object] = {}
    skipped: list[str] = []
    for i, path in enumerate(video_paths):
        report(f"Analizando video {i + 1}/{len(video_paths)}...", 5 + int(35 * i / max(1, len(video_paths))))
        try:
            info = probe(path)
            segs = analyze_video(info, i, max_clip=max_clip_seconds)
        except Exception as e:  # noqa: BLE001
            skipped.append(f"{os.path.basename(path)} ({e})")
            continue
        infos[i] = info
        all_segments.extend(segs)

    if not all_segments:
        detail = (" Videos omitidos: " + "; ".join(skipped)) if skipped else ""
        return {"ok": False, "error": "No se encontraron segmentos utilizables en los videos." + detail}

    used_gemini = False
    if use_gemini:
        report("Evaluando los mejores clips con Gemini (buscando el producto)...", 48)
        all_segments, used_gemini = rank_with_gemini(
            all_segments, api_key=gemini_key, product_desc=product_desc)

    report("Seleccionando los mejores cortes...", 58)
    selected = _select_for_target(all_segments, target_seconds)

    return {
        "ok": True,
        "selected": selected,
        "has_audio_by_src": {i: info.has_audio for i, info in infos.items()},
        "used_gemini": used_gemini,
        "n_sources": len(video_paths),
    }


def render_versions(
    selected: list[Segment],
    has_audio_by_src: dict,
    work_dir: str,
    *,
    aspect: str = "1:1",
    enhance: bool = False,
    hook_text: str = "",
    hook_pos: str = "arriba",
    auto_hook: bool = False,
    page_url: str = "",
    product_desc: str = "",
    gemini_key: str | None = None,
    voiceover_path: str | None = None,
    version_vos: list | None = None,
    effects: bool = False,
    sfx_paths: list | None = None,
    music_path: str | None = None,
    blur_captions: bool = False,
    text_mode: str = "tapar",   # "tapar" (blur) | "traducir" (reescribe el texto en español)
    caption_pos: str = "abajo",
    captions: bool = False,
    caption_style: str = "hormozi",
    word_timings: list | None = None,
    used_gemini: bool = False,
    n_sources: int = 0,
    target_seconds: float = 15.0,
    max_clip_seconds: float = 3.0,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Construye clips sueltos, las 3 versiones, el gancho, voz en off y efectos."""
    def report(msg, pct):
        if progress:
            progress(msg, pct)

    os.makedirs(work_dir, exist_ok=True)
    clips_dir = os.path.join(work_dir, "clips")
    os.makedirs(clips_dir, exist_ok=True)
    dims = dims_for(aspect)

    # Tapar textos del proveedor: Gemini DETECTA las cajas y se enmascara la FUENTE
    # (antes de cortar), para que la mascara quede justo donde esta cada caption.
    if blur_captions and gemini_key and text_mode == "traducir":
        # "traducir" SÍ necesita Gemini (lee el texto y lo reescribe en español). Se procesa cada
        # FUENTE única UNA vez. (El modo "tapar" YA NO va por aquí: Gemini estimaba cajas mirando el
        # video entero y ponía blur en lugares random -> ahora "tapar" usa EAST por-corte, abajo.)
        report("Traduciendo el texto...", 56)
        fuentes = list({seg.video for seg in selected})
        remap, done_t = {}, [0]
        pref = "es_" if text_mode == "traducir" else "cov_"

        def _proc_src(src):
            out = os.path.join(work_dir, pref + os.path.basename(src))
            try:
                r = translate_screen_text(src, api_key=gemini_key, out_path=out, modo=text_mode)
                done_t[0] += 1
                report(f"Procesando textos en pantalla ({done_t[0]}/{len(fuentes)})...", 56)
                if r.get("ok"):
                    return src, r.get("video", src)   # el video procesado (o el mismo si no había texto)
            except Exception:
                pass
            return src, src

        with ThreadPoolExecutor(max_workers=2) as ex:   # poca concurrencia por el límite de Gemini
            for src, v in ex.map(_proc_src, fuentes):
                remap[src] = v
        for seg in selected:
            seg.video = remap.get(seg.video, seg.video)   # remapea cada corte a su fuente procesada
    elif blur_captions and east_available():
        # OPTIMIZADO: enmascara SOLO los cortes que se usan (2s c/u), no los videos
        # completos. Antes con 40 videos tardaba muchísimo; ahora procesa poquísimos
        # frames y en paralelo.
        report("Tapando textos del proveedor (frame por frame)...", 56)
        done = [0]
        # El capitán (Claude) es lento: revisa solo una MUESTRA espaciada de los cortes,
        # no todos (si no, con 60 cortes serían 60+ llamadas a Claude y se traba).
        capitan = supervisor.available()
        cap_cada = max(1, len(selected) // _CAPITAN_MAX_REVISIONES) if capitan else 0

        def _mask_seg(item):
            idx, seg = item
            raw = os.path.join(work_dir, f"segraw_{idx:03d}.mp4")
            masked = os.path.join(work_dir, f"segmask_{idx:03d}.mp4")
            d = max(0.1, seg.end - seg.start)
            try:
                run(["ffmpeg", "-y", "-ss", f"{seg.start:.3f}", "-i", seg.video, "-t", f"{d:.3f}",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", raw])
                # Con key de Gemini: tapado INTELIGENTE por corte (EAST afinado localiza el texto
                # frame por frame + Gemini clasifica cada zona -> solo CAPTIONS, nunca el producto).
                # Sin key: EAST puro (con el capitán de Claude abajo).
                if gemini_key:
                    final = mask_captions_smart(raw, masked, gemini_key=gemini_key)
                else:
                    final = mask_video_text(raw, masked)   # == masked (tapó algo) o == raw (nada)

                # ── Capitán (Claude): revisa el tapado del path EAST puro y corrige si hace falta ──
                # (No aplica al tapado inteligente con Gemini, que ya filtra por su cuenta.)
                revisar = capitan and not gemini_key and (idx % cap_cada == 0)
                if revisar and final == masked and os.path.exists(masked):
                    mw = cf = None
                    for _ in range(_MAX_CORRECCIONES):
                        v = supervisor.revisar_blur(raw, masked)
                        if not v or v.get("aprobado"):
                            break
                        if v.get("falsos_positivos"):        # tapó de más -> más preciso
                            mw = round((mw or 1.5) + 0.4, 2)
                            cf = min((cf or 0.6) + 0.1, 0.9)
                        elif v.get("texto_sin_tapar"):       # tapó de menos -> menos preciso
                            mw = round(max((mw or 1.5) - 0.3, 1.0), 2)
                            cf = max((cf or 0.6) - 0.1, 0.4)
                        else:
                            break
                        report(f"El capitán corrige el tapado del corte {idx + 1}...", 56)
                        if os.path.exists(masked):
                            os.remove(masked)
                        final = mask_video_text(raw, masked, min_wh=mw, conf=cf)
                        if final != masked:                  # la corrección lo dejó sin blur -> ok
                            break

                done[0] += 1
                report(f"Tapando textos ({done[0]}/{len(selected)})...", 56)
                if final == masked and os.path.exists(masked):
                    return idx, masked
            except Exception:
                pass
            return idx, None

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for idx, masked in ex.map(_mask_seg, list(enumerate(selected))):
                if masked:
                    selected[idx].video = masked
                    selected[idx].start = 0.0
                    selected[idx].end = probe(masked).duration

    report("Recortando clips..." + (" (mejorando calidad)" if enhance else ""), 62)
    clip_dims = dims_for("1:1")   # los clips sueltos siempre en 1:1 (cuadrado)
    # Clips sueltos: MEZCLA por FASE narrativa (problema / solución / funcionamiento / producto /
    # características / resultado) para que los "gifs" tengan SENTIDO y cuenten la historia.
    # La fase la decide GEMINI mirando un frame de cada clip (1 sola llamada); si no hay key o falla,
    # cae a la heurística vieja (shows_use/product_visible) sin romper nada.
    def _fase_heur(s):
        if s.shows_use:
            return "solucion"
        if s.product_visible:
            return "producto"
        return "problema"
    pool = sorted(selected, key=lambda s: s.score, reverse=True)[:30]
    fases_pool = None
    if gemini_key:
        report("Clasificando los clips por fase (problema/solución/producto)...", 66)
        fases_pool = phase_classify.clasificar(pool, gemini_key, product_desc)
    if not fases_pool:
        fases_pool = [_fase_heur(s) for s in pool]
    _orden_fases = list(phase_classify.FASES)
    _grupos = {k: [] for k in _orden_fases}
    for s, f in zip(pool, fases_pool):
        _grupos.setdefault(f, []).append((s, f))
    loose_pairs, _idx = [], {k: 0 for k in _grupos}   # round-robin: intercala fases, mejor score primero
    while len(loose_pairs) < 24 and any(_idx[k] < len(_grupos[k]) for k in _grupos):
        for k in _orden_fases:
            if _idx.get(k, 0) < len(_grupos.get(k, [])) and len(loose_pairs) < 24:
                loose_pairs.append(_grupos[k][_idx[k]])
                _idx[k] += 1
    loose_set = [s for s, _ in loose_pairs]
    loose_fases = [f for _, f in loose_pairs]
    outs = [os.path.join(clips_dir, f"clip_{idx:02d}_{fase}.mp4")
            for idx, (seg, fase) in enumerate(loose_pairs)]

    def _render_one(pair):
        seg, out = pair
        render_clip(seg, out, clip_dims, has_audio=has_audio_by_src.get(seg.source_index, True),
                    enhance=enhance, fx=effects)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(_render_one, zip(loose_set, outs)))

    # "GIFs" (en formato WebM 1:1, ≤500KB) de cada clip suelto — ADEMÁS del .mp4.
    gifs = [None] * len(outs)
    if gif_export.webm_available():
        report("Generando los GIFs (WebM 1:1) de los clips...", 68)

        def _gif_one(item):
            i, mp4 = item
            return i, gif_export.to_webm(mp4, os.path.splitext(mp4)[0] + ".webm")

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for i, g in ex.map(_gif_one, list(enumerate(outs))):
                gifs[i] = g

    _FASE_LBL = {"problema": "🔴 Problema", "solucion": "🟢 Solución", "funcionamiento": "⚙️ Cómo funciona",
                 "producto": "📦 Producto", "caracteristicas": "🔎 Características", "resultado": "✨ Resultado"}
    loose_clips = [{"path": o, "gif": g, "segment": s.to_dict(),
                    "fase": f, "fase_label": _FASE_LBL.get(f, "")}
                   for s, f, o, g in zip(loose_set, loose_fases, outs, gifs)]

    report("Armando las versiones del video..." + (" (con efectos)" if effects else ""), 72)
    built = build_variations(selected, work_dir, dims, enhance, fx=effects,
                             target_seconds=target_seconds)
    versions = built["versions"]

    # ACENTO DINÁMICO de captions: el color de resalte CONTRASTA con el color dominante del
    # producto/video (se calcula 1 vez sobre el primer montaje). Si falla → colores clásicos.
    try:
        from . import caption_styles as _cs
        _cs.set_accent(_cs.accent_for_video(versions[0]["path"]) if versions else None)
    except Exception:  # noqa: BLE001
        pass

    # Gancho: el del usuario o uno generado con IA
    final_hook = hook_text.strip()
    if not final_hook and auto_hook:
        report("Generando gancho impactante con IA...", 80)
        page_text = fetch_page_text(page_url)
        sample = max(selected, key=lambda s: (s.shows_use, s.score)) if selected else None
        final_hook = generate_hook(gemini_key, product_desc, page_text, sample)
    if final_hook.strip():
        for v in versions:
            hook_out = v["path"].replace(".mp4", "_hook.mp4")
            new_path, burned = burn_hook(v["path"], hook_out, work_dir, final_hook, hook_pos)
            v["path"] = new_path

    # Voz en off: una sola para todas, o UNA DISTINTA por version (version_vos)
    def _cut_times(v):
        cuts, acc = [], 0.0
        for sg in v["segments"][:-1]:
            acc += float(sg.get("duration", 0))
            cuts.append(acc)
        return cuts

    def _apply_vo(v, v_i, vo_path, wt):
        if not vo_path or not os.path.exists(vo_path):
            return
        vo_out = v["path"].replace(".mp4", "_vo.mp4")
        try:
            add_voiceover_and_sfx(v["path"], vo_path, vo_out,
                                  sfx_paths=sfx_paths if effects else None,
                                  cut_times=_cut_times(v), music_path=music_path)
            v["path"] = vo_out
            v["voiceover"] = True
        except Exception:
            v["voiceover"] = False
        if captions and wt:
            cap_out = v["path"].replace(".mp4", "_cap.mp4")
            try:
                from .caption_styles import burn_word_captions
                prev = v["path"]
                np = burn_word_captions(prev, wt, work_dir, cap_out, style=caption_style)
                v["path"] = np
                v["captions"] = (np != prev)
            except Exception:  # noqa: BLE001 — fallback al motor viejo
                new_path, ok = add_captions(v["path"], cap_out, work_dir, wt, "centro")
                v["path"] = new_path
                v["captions"] = ok

    if version_vos:                                  # un guion/voz distinto por version
        for v_i, v in enumerate(versions):
            report(f"Voz en off por versión ({v_i + 1}/{len(versions)})...", 86 + v_i)
            vo_path, wt = version_vos[v_i] if v_i < len(version_vos) else (None, None)
            _apply_vo(v, v_i, vo_path, wt)
    elif voiceover_path:                             # una sola voz para todas
        for v_i, v in enumerate(versions):
            report(f"Agregando voz en off{' y efectos' if effects else ''} ({v_i + 1}/{len(versions)})...", 86 + v_i)
            _apply_vo(v, v_i, voiceover_path, word_timings)

    report("Finalizando...", 98)
    manifest = {
        "ok": True,
        "used_gemini": used_gemini,
        "enhanced": enhance,
        "hook_used": final_hook,
        "aspect": aspect,
        "n_sources": n_sources,
        "target_seconds": target_seconds,
        "clips": loose_clips,
        "versions": [
            {
                "name": v["name"], "path": v["path"],
                "filename": os.path.basename(v["path"]),
                "n_clips": len(v["segments"]),
                "voiceover": v.get("voiceover", False),
            }
            for v in versions
        ],
        "max_clip_seconds": max_clip_seconds,
    }
    report("Listo", 100)
    return manifest


def process_job(
    video_paths: list[str],
    work_dir: str,
    *,
    target_seconds: float = 15.0,
    max_clip_seconds: float = 3.0,
    use_gemini: bool = True,
    product_desc: str = "",
    aspect: str = "1:1",
    hook_text: str = "",
    hook_pos: str = "arriba",
    auto_hook: bool = False,
    page_url: str = "",
    enhance: bool = False,
    effects: bool = False,
    blur_captions: bool = False,
    text_mode: str = "tapar",
    caption_pos: str = "abajo",
    voiceover_path: str | None = None,
    gemini_key: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Pipeline de una pasada (sin paso de guiones): analiza y renderiza."""
    a = analyze_select(
        video_paths, target_seconds=target_seconds, max_clip_seconds=max_clip_seconds,
        use_gemini=use_gemini, product_desc=product_desc, gemini_key=gemini_key, progress=progress)
    if not a["ok"]:
        return a
    return render_versions(
        a["selected"], a["has_audio_by_src"], work_dir,
        aspect=aspect, enhance=enhance, hook_text=hook_text, hook_pos=hook_pos,
        auto_hook=auto_hook, page_url=page_url, product_desc=product_desc,
        gemini_key=gemini_key, voiceover_path=voiceover_path, effects=effects,
        blur_captions=blur_captions, text_mode=text_mode, caption_pos=caption_pos,
        used_gemini=a["used_gemini"], n_sources=a["n_sources"],
        target_seconds=target_seconds, max_clip_seconds=max_clip_seconds, progress=progress)
