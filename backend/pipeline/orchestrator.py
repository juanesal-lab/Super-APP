"""Orquesta el pipeline completo: analizar -> rankear -> seleccionar -> ensamblar -> subtitular."""
from __future__ import annotations

import os
import subprocess
from typing import Callable

from .ffmpeg_utils import probe, run
from .analyze import analyze_video, Segment, MAX_CLIP, segment_signature, segment_signatures, sig_distance
from .gemini_rank import rank_with_gemini
from concurrent.futures import ThreadPoolExecutor

from .assemble import (build_variations, plan_variations, render_clip, export_resolution,
                       dims_for, add_voiceover, add_voiceover_and_sfx, sound_design_events,
                       venc, WORKERS)
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

    # Firmas perceptuales PRE-CALCULADAS EN PARALELO (cv2 abre/lee video: suelta el GIL).
    # Antes se calculaban una a una dentro del loop de dedup (~1-2s por corte, en serie).
    sig_cache: dict[int, list] = {}
    precalc = ranked[:pool_size + 40]
    try:
        with ThreadPoolExecutor(max_workers=min(8, max(2, len(precalc)))) as _ex:
            for seg, sigs in zip(precalc, _ex.map(segment_signatures, precalc)):
                sig_cache[id(seg)] = sigs
    except Exception:  # noqa: BLE001
        sig_cache = {}

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
            sigs = sig_cache.get(id(seg))
            if sigs is None:
                sigs = segment_signatures(seg)
                sig_cache[id(seg)] = sigs
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
    # Analisis EN PARALELO por video (OpenCV y ffmpeg sueltan el GIL / son subprocesos).
    # El orden de all_segments se conserva (se juntan los resultados en orden de entrada).
    done_ct = [0]

    def _analyze_one(item):
        i, path = item
        try:
            info = probe(path)
            segs = analyze_video(info, i, max_clip=max_clip_seconds)
            return i, info, segs, None
        except Exception as e:  # noqa: BLE001
            return i, None, [], f"{os.path.basename(path)} ({e})"
        finally:
            done_ct[0] += 1
            report(f"Analizando videos ({min(done_ct[0], len(video_paths))}/{len(video_paths)})...",
                   5 + int(35 * done_ct[0] / max(1, len(video_paths))))

    n_workers = min(4, max(1, len(video_paths)))
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        results = list(ex.map(_analyze_one, list(enumerate(video_paths))))
    for i, info, segs, err in results:
        if err:
            skipped.append(err)
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
    hook_seconds: float = 0.0,
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
    caption_size: str = "mediano",
    destino: str = "tiktok",      # "tiktok" | "meta": safe zone de captions + cut 4:5 (Manual §10)
    word_timings: list | None = None,
    used_gemini: bool = False,
    n_sources: int = 0,
    target_seconds: float = 15.0,
    max_clip_seconds: float = 3.0,
    broll_fases: dict | None = None,   # {ruta fuente B-roll: fase forzada (problema/resultado/...)}
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

    # ── PLAN PRIMERO ──────────────────────────────────────────────────────────────
    # Decidir QUÉ cortes se usan de verdad (versiones + clips sueltos) ANTES de tapar
    # textos: el masking procesa SOLO esos (antes tapaba TODO el pool, hasta 60 cortes,
    # con ~1 llamada a Gemini/Claude por corte). Además el plan se calcula con los
    # tiempos ORIGINALES (el masking remapea video/start/end de cada corte en sitio).
    #
    # El plan cubre la VOZ REAL, no solo el target pedido: el guion puede pasarse de
    # palabras y ElevenLabs habla más lento que el ritmo teórico → la voz sale más larga
    # que el target y el montaje quedaba CORTO (el video se repetía con el loop viejo, o
    # congela el final con el tpad nuevo — queja de Juan). Las voces ya están en disco
    # en este punto: se mide la más larga y el montaje se planea para alcanzarla.
    def _audio_dur(p):
        try:
            o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", p], capture_output=True, text=True, timeout=15)
            return float((o.stdout or "").strip() or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    vo_paths = [vp for vp, _ in (version_vos or []) if vp]
    if voiceover_path:
        vo_paths.append(voiceover_path)
    vo_max = max((_audio_dur(p) for p in vo_paths if p and os.path.exists(p)), default=0.0)
    plan_seconds = max(float(target_seconds), vo_max + 0.5) if vo_max else float(target_seconds)

    # FASE VISUAL de cada clip — AHORA ANTES del plan (el montaje por guion la necesita).
    # Gemini mira un frame de cada clip del pool (1 sola llamada, tiempos ORIGINALES — el
    # masking aún no corre); si no hay key o falla, heurística vieja. También alimenta los gifs.
    def _fase_heur(s):
        if s.shows_use:
            return "solucion"
        if s.product_visible:
            return "producto"
        return "problema"

    pool_idx = sorted(range(len(selected)), key=lambda k: selected[k].score, reverse=True)[:60]
    fases_pool = None
    if gemini_key:
        report("Clasificando los clips por fase (problema/solución/producto)...", 50)
        fases_pool = phase_classify.clasificar([selected[i] for i in pool_idx],
                                               gemini_key, product_desc)
    if not fases_pool:
        fases_pool = [_fase_heur(selected[i]) for i in pool_idx]
    fases_por_idx = dict(zip(pool_idx, fases_pool))
    # TODO el pool disponible para el montaje por guion (no solo el top-60 de Gemini): los
    # demás clips entran con fase heurística → más material = menos clips repetidos entre
    # versiones (queja de Juan: "es como el mismo video, solo cambia el guion").
    for _i in range(len(selected)):
        if _i not in fases_por_idx:
            fases_por_idx[_i] = _fase_heur(selected[_i])

    # B-ROLL con intención: los clips que vienen de fuentes marcadas como B-roll usan la fase que
    # el usuario/Claude les dio (dolor/resultado/uso) en vez de la clasificación visual — así la
    # escena de DOLOR cae en el momento del dolor del guion, no donde sea (idea de Jack).
    if broll_fases:
        _bmap = {os.path.abspath(p): f for p, f in broll_fases.items()}
        for _i in pool_idx:
            _f = _bmap.get(os.path.abspath(getattr(selected[_i], "video", "") or ""))
            if _f in phase_classify.FASES:
                fases_por_idx[_i] = _f
        fases_pool = [fases_por_idx[i] for i in pool_idx]

    version_orders = plan_variations(selected, target_seconds=plan_seconds)

    # ── MONTAJE GUIADO POR EL GUION (flujo de Juan: primero el guion, después la edición) ──
    # Si la voz de cada versión ya existe con tiempos por palabra, el plan ciego se REEMPLAZA:
    # cada FRASE de la voz recibe el clip que mejor ilustra lo que se dice (guion_match) y el
    # corte cae en el límite de frase. Si algo falta (sin voz/timings), la versión conserva
    # su plan clásico — nunca rompe.
    version_caps: dict[str, list[float]] = {}
    frases_por_nombre: dict[str, list[dict]] = {}   # frases del guion por versión (para los SFX)
    regen_usage: dict[int, int] = {}                # uso por clip (para regenerar sin repetir)
    vos_pv = list(version_vos or [])
    if not vos_pv and voiceover_path and word_timings:
        vos_pv = [(voiceover_path, word_timings)] * len(version_orders)
    if vos_pv:
        from . import guion_match
        frases_pv = []
        for v_i in range(len(version_orders)):
            vp, wt = vos_pv[v_i] if v_i < len(vos_pv) else (None, None)
            frases_pv.append(guion_match.frases_de_vo(wt or [], _audio_dur(vp) if vp else 0.0)
                             if (vp and wt) else [])
        if any(frases_pv):
            report("Montaje por guion: eligiendo el mejor clip para cada frase...", 51)
            guion_match.etiquetar_frases([f for f in frases_pv if f], gemini_key, product_desc)
            # firma perceptual de cada clip del pool: detecta "misma escena" aunque venga de
            # ARCHIVOS distintos (varios TikToks de la misma creadora = se veía congelado).
            # EN PARALELO (cv2 suelta el GIL); antes era ~1-2s por clip EN SERIE.
            firmas: dict[int, object] = {}

            def _firma_uno(_i):
                try:
                    return _i, segment_signature(selected[_i])
                except Exception:  # noqa: BLE001
                    return _i, None

            with ThreadPoolExecutor(max_workers=8) as _ex:
                for _i, _f in _ex.map(_firma_uno, list(fases_por_idx)):
                    if _f is not None:
                        firmas[_i] = _f
            usage: dict[int, int] = {}
            hook_srcs: set[int] = set()           # cada versión abre con una FUENTE distinta
            # TOPE DURO de reuso entre versiones: un clip solo puede salir en ~su cuota justa
            # (slots totales / clips disponibles). Con material de sobra la cuota es 1 → versiones
            # con clips 100% distintos; con poco material sube lo mínimo necesario.
            import math
            slots_est = sum(max(1, round((f[-1]["fin"] - f[0]["inicio"]) / 1.4))
                            for f in frases_pv if f)
            max_usos = max(1, math.ceil(slots_est / max(1, len(fases_por_idx))))
            if max_usos > 3:      # material escaso: las versiones van a compartir clips sí o sí
                report(f"⚠️ Hay {len(fases_por_idx)} clips para ~{slots_est} espacios: las "
                       "versiones van a repetir material entre sí. Sube MÁS videos para "
                       "versiones realmente distintas.", 51)
            nuevos = []
            for v_i, ((name, order), frases) in enumerate(zip(version_orders, frases_pv)):
                plan_g = (guion_match.plan_montaje(selected, fases_por_idx, frases, usage,
                                                   version_i=v_i,
                                                   n_versiones=len(version_orders),
                                                   hook_srcs=hook_srcs, max_usos=max_usos,
                                                   firmas=firmas)
                          if frases else None)
                if frases:
                    frases_por_nombre[name] = frases
                if plan_g:
                    nuevos.append((name, plan_g[0]))
                    version_caps[name] = plan_g[1]
                    voz_d = float(frases[-1]["fin"]) if frases else 0.0
                    cubierto = sum(plan_g[1])
                    if voz_d - cubierto > 1.5:   # el final quedaría CONGELADO: que se sepa
                        report(f"⚠️ {name}: los clips cubren {cubierto:.0f}s de {voz_d:.0f}s de "
                               "voz — el cierre queda quieto (sube más videos o baja la duración)", 51)
                else:
                    nuevos.append((name, order))
            version_orders = nuevos
            regen_usage = usage           # para regenerar versiones sin repetir clips
    # ───────────────────────────────────────────────────────────────────────────────────────

    # Clips sueltos: MEZCLA por FASE narrativa para que los "gifs" tengan SENTIDO (reusa la
    # clasificación de arriba).
    _orden_fases = list(phase_classify.FASES)
    _grupos = {k: [] for k in _orden_fases}
    for _i, _f in zip(pool_idx, fases_pool):
        _grupos.setdefault(_f, []).append((_i, _f))
    _pares, _ptr = [], {k: 0 for k in _grupos}   # round-robin: intercala fases, mejor score primero
    while len(_pares) < 24 and any(_ptr[k] < len(_grupos[k]) for k in _grupos):
        for k in _orden_fases:
            if _ptr.get(k, 0) < len(_grupos.get(k, [])) and len(_pares) < 24:
                _pares.append(_grupos[k][_ptr[k]])
                _ptr[k] += 1
    loose_idx = [i for i, _ in _pares]
    loose_fases = [f for _, f in _pares]
    used_all = sorted({i for _, order in version_orders for i in order} | set(loose_idx))
    # ──────────────────────────────────────────────────────────────────────────────

    # Tapar textos del proveedor: Gemini DETECTA las cajas y se enmascara la FUENTE
    # (antes de cortar), para que la mascara quede justo donde esta cada caption.
    if blur_captions and gemini_key and text_mode == "traducir":
        # "traducir" SÍ necesita Gemini (lee el texto y lo reescribe en español). Se procesa cada
        # FUENTE única UNA vez. (El modo "tapar" YA NO va por aquí: Gemini estimaba cajas mirando el
        # video entero y ponía blur en lugares random -> ahora "tapar" usa EAST por-corte, abajo.)
        report("Traduciendo el texto...", 56)
        fuentes = list({selected[i].video for i in used_all})   # solo las fuentes que se usan
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
        # OPTIMIZADO: enmascara SOLO los cortes que las versiones y los clips sueltos usan
        # de verdad (used_all), no todo el pool. Antes procesaba hasta 60 cortes (con ~1
        # llamada a Gemini por corte en el tapado inteligente) aunque solo se usara una parte.
        report("Tapando textos del proveedor (frame por frame)...", 56)
        done = [0]
        n_mask = len(used_all)
        # El capitán (Claude) es lento: revisa solo una MUESTRA espaciada de los cortes,
        # no todos (si no, con 60 cortes serían 60+ llamadas a Claude y se traba).
        capitan = supervisor.available()
        cap_cada = max(1, n_mask // _CAPITAN_MAX_REVISIONES) if capitan else 0

        def _mask_seg(item):
            # pos = posición SECUENCIAL (0..n_mask-1) para el muestreo del capitán;
            # idx = índice original en `selected` (puede ser salteado).
            pos, idx, seg = item
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
                revisar = capitan and not gemini_key and (pos % cap_cada == 0)
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
                report(f"Tapando textos ({done[0]}/{n_mask})...", 56)
                if final == masked and os.path.exists(masked):
                    return idx, masked
            except Exception:
                pass
            return idx, None

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for idx, masked in ex.map(_mask_seg,
                                      [(pos, i, selected[i]) for pos, i in enumerate(used_all)]):
                if masked:
                    selected[idx].video = masked
                    selected[idx].start = 0.0
                    selected[idx].end = probe(masked).duration

    report("Recortando clips..." + (" (mejorando calidad)" if enhance else ""), 62)
    clip_dims = dims_for("1:1")   # los clips sueltos siempre en 1:1 (cuadrado)
    # Clips sueltos: los elegidos por FASE en el PLAN de arriba (ya con el masking aplicado
    # en sitio a esos mismos cortes). Las fases (loose_fases) vienen del plan (Gemini o heurística).
    loose_set = [selected[i] for i in loose_idx]
    outs = [os.path.join(clips_dir, f"clip_{idx:02d}_{fase}.mp4")
            for idx, fase in enumerate(loose_fases)]

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
                             target_seconds=target_seconds, version_orders=version_orders,
                             version_caps=version_caps)
    versions = built["versions"]

    # ACENTO DINÁMICO de captions: el color de resalte CONTRASTA con el color dominante del
    # producto/video (se calcula 1 vez sobre el primer montaje). Si falla → colores clásicos.
    try:
        from . import caption_styles as _cs
        _cs.set_destino(destino)      # safe zone: TikTok ~80% | Meta bloque a ~60% (35% inf. libre)
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
            new_path, burned = burn_hook(v["path"], hook_out, work_dir, final_hook, hook_pos,
                                         seconds=hook_seconds)
            v["path"] = new_path

    # Voz en off: una sola para todas, o UNA DISTINTA por version (version_vos)
    def _cut_times(v):
        if v.get("cut_times"):          # tiempos REALES post-dissolve (los deja build_variations)
            return list(v["cut_times"])
        cuts, acc = [], 0.0
        for sg in v["segments"][:-1]:
            acc += float(sg.get("duration", 0))
            cuts.append(acc)
        return cuts

    def _apply_vo(v, v_i, vo_path, wt):
        if not vo_path or not os.path.exists(vo_path):
            return
        vo_out = v["path"].replace(".mp4", "_vo.mp4")
        # fases del guion → el mezclador sabe dónde está el DOLOR (sin SFX), el producto
        # (chime protagonista) y la OFERTA/CTA (cha-ching)
        fr = frases_por_nombre.get(v.get("name") or "")
        phases_mix = ([{"etiqueta": str(f.get("fase", "")).upper(),
                        "inicio_s": f["inicio"], "fin_s": f["fin"]} for f in fr] if fr else None)
        # SOUND DESIGN CON INTENCIÓN: riser→revelación del producto, whoosh rotado en cortes,
        # pop al arrancar, cash_register en el CTA, ding en la prueba (sound_design_events).
        # Si el cálculo falla → None → add_voiceover_and_sfx cae al plan viejo (pro_mix).
        sd_events = None
        vo_d = _audio_dur(vo_path)
        if vo_d > 1.0:
            try:
                sd_events = sound_design_events(v.get("segments") or [], vo_d,
                                                vo_dur=vo_d, cut_times=_cut_times(v))
            except Exception:  # noqa: BLE001
                sd_events = None
        # SUBTÍTULOS EN LA MISMA PASADA de la voz (caption_events + caption_pngs): antes eran
        # 2 re-encodes del video entero por versión (mezcla y luego captions) — ahora 1.
        # Los PNG se renderizan igual que siempre (mismo look); los tiempos van en la línea
        # de tiempo de la voz = la del video final, así que la sincronía es idéntica.
        cap_specs = None
        if captions and wt:
            try:
                from .caption_styles import caption_events
                _info = probe(v["path"])
                cap_specs = caption_events(_info.width, _info.height, wt, work_dir,
                                           style=caption_style, cap_size=caption_size,
                                           prefix=f"wc_{v.get('name', 'v')}")
            except Exception:  # noqa: BLE001
                cap_specs = None
        # Cut 4:5 para Meta TAMBIÉN en la misma pasada (split+crop dentro del mismo ffmpeg):
        # antes era otro re-encode entero (y en libx264 CPU) por versión.
        out45 = (vo_out.replace(".mp4", "_45.mp4")
                 if destino == "meta" and aspect == "9:16" else None)
        try:
            # SFX ya no dependen del toggle "efectos": el plan pro (pro_mix) los pone SUTILES
            # y solo donde tocan; "efectos" sigue mandando en lo VISUAL (punch/zoom fuerte).
            add_voiceover_and_sfx(v["path"], vo_path, vo_out,
                                  sfx_paths=sfx_paths,
                                  cut_times=_cut_times(v), music_path=music_path,
                                  phases=phases_mix, sfx_events=sd_events,
                                  caption_pngs=cap_specs, out_45=out45)
            v["path"] = vo_out
            v["voiceover"] = True
            if cap_specs:
                v["captions"] = True
            if out45 and os.path.exists(out45):
                v["path_45"] = out45
        except Exception:
            v["voiceover"] = False
        if captions and wt and not v.get("captions"):   # fallback: la pasada fusionada no los quemó
            cap_out = v["path"].replace(".mp4", "_cap.mp4")
            try:
                from .caption_styles import burn_word_captions
                prev = v["path"]
                np = burn_word_captions(prev, wt, work_dir, cap_out, style=caption_style, cap_size=caption_size)
                v["path"] = np
                v["captions"] = (np != prev)
            except Exception:  # noqa: BLE001 — fallback al motor viejo
                new_path, ok = add_captions(v["path"], cap_out, work_dir, wt, "centro")
                v["path"] = new_path
                v["captions"] = ok

    # VOZ+SUBTÍTULOS+4:5 POR VERSIÓN EN PARALELO (antes en serie): cada versión es independiente
    # (archivos y prefijos únicos) y el tope de sesiones GPU lo pone WORKERS (=3 con VideoToolbox).
    if version_vos or voiceover_path:
        done_vo = [0]

        def _vo_one(item):
            v_i, v = item
            if version_vos:
                vo_path, wt = version_vos[v_i] if v_i < len(version_vos) else (None, None)
            else:
                vo_path, wt = voiceover_path, word_timings
            _apply_vo(v, v_i, vo_path, wt)
            done_vo[0] += 1
            report(f"Voz en off + subtítulos por versión ({done_vo[0]}/{len(versions)})...",
                   86 + done_vo[0])

        report("Voz en off por versión (en paralelo)...", 86)
        with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(versions)))) as ex:
            list(ex.map(_vo_one, list(enumerate(versions))))

    # ── Cut 4:5 para Meta feed (Manual §10.2): mismo master, recorte central 1080x1350 ──
    # Las versiones CON voz ya lo traen de la pasada fusionada (v["path_45"]); esto cubre solo
    # las que faltan (sin voz) — ahora con GPU (venc) y en paralelo, antes libx264 CPU en serie.
    if destino == "meta" and aspect == "9:16":
        pend45 = [v for v in versions if not v.get("path_45")]
        if pend45:
            report("Generando el cut 4:5 para Meta feed...", 96)

            def _mk45(v):
                try:
                    out45 = v["path"].replace(".mp4", "_45.mp4")
                    run(["ffmpeg", "-y", "-i", v["path"],
                         "-vf", "crop=iw:iw*5/4:0:(ih-iw*5/4)/2,setsar=1",
                         *venc(),
                         "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "copy", out45])
                    v["path_45"] = out45
                except Exception:  # noqa: BLE001
                    pass

            with ThreadPoolExecutor(max_workers=min(WORKERS, len(pend45))) as ex:
                list(ex.map(_mk45, pend45))

    # ── QA GATE (Manual §11.1): ¿el producto se ve en los primeros 3s? (1 llamada Gemini) ──
    if gemini_key and versions and product_desc.strip():
        try:
            report("QA: verificando que el producto salga en los primeros segundos...", 97)
            import json as _json
            import re as _re
            prompt_qa = (f"Producto: {product_desc.strip()}. Te paso 1 frame del segundo ~2.5 de "
                         "cada video (numerados). Responde SOLO un JSON array "
                         '[{"i":0,"producto_visible":true}, ...] indicando si el PRODUCTO (o su uso '
                         "directo) se alcanza a ver en ese frame.")
            frames_qa, oks = [], []
            for k, v in enumerate(versions):
                fj = os.path.join(work_dir, f"_qa_{k}.jpg")
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "2.5", "-i", v["path"],
                                "-frames:v", "1", "-vf", "scale=320:-2", fj],
                               capture_output=True, timeout=30)
                if os.path.exists(fj):
                    with open(fj, "rb") as fh:
                        frames_qa.append(fh.read())
                    oks.append(k)
            if oks:
                # rápido por REST (thinkingBudget=0, ~2s); fallback SDK como siempre
                from . import gemini_fast
                texto_qa = gemini_fast.generate(
                    gemini_key, [prompt_qa] + [(fb, "image/jpeg") for fb in frames_qa])
                if not texto_qa:
                    from google import genai as _genai
                    from google.genai import types as _types
                    partes = [prompt_qa] + [_types.Part.from_bytes(data=fb, mime_type="image/jpeg")
                                            for fb in frames_qa]
                    rq = _genai.Client(api_key=gemini_key).models.generate_content(
                        model="gemini-2.5-flash", contents=partes)
                    texto_qa = rq.text or ""
                m = _re.search(r"\[.*\]", texto_qa, _re.DOTALL)
                if m:
                    for item in _json.loads(m.group(0)):
                        k = int(item.get("i", -1))
                        if 0 <= k < len(oks) and not item.get("producto_visible", True):
                            versions[oks[k]]["qa_aviso"] = ("El producto no se alcanza a ver en "
                                                            "los primeros 3s (regla del manual)")
        except Exception:  # noqa: BLE001
            pass

    # SOUND DESIGN para el flujo SIN voz (Cortar clips: la música/SFX se mezclan en app.py
    # DESPUÉS, con el manifest — que no trae segments): los eventos con intención se calculan
    # AQUÍ (donde están los flags product_visible/shows_use) y viajan en el manifest.
    for v in versions:
        if not v.get("voiceover"):
            try:
                v["sfx_events"] = sound_design_events(v.get("segments") or [],
                                                      probe(v["path"]).duration,
                                                      vo_dur=None, cut_times=_cut_times(v))
            except Exception:  # noqa: BLE001
                v["sfx_events"] = None

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
                # aditivos (no rompen el shape): para la mezcla música+SFX de app.py
                "cut_times": list(v.get("cut_times") or []),
                "sfx_events": v.get("sfx_events"),
                "path_45": v.get("path_45"),      # cut 4:5 para Meta (§10.2)
                "qa_aviso": v.get("qa_aviso"),     # ⚠️ producto no visible ≤3s (§11.1)
            }
            for v in versions
        ],
        "max_clip_seconds": max_clip_seconds,
    }

    # ── ESTADO para REGENERAR una versión suelta (pedido de Juan): pool + fases + uso +
    #    ajustes + por-versión (orden, topes, guion, voz). Solo si hubo montaje por guion. ──
    try:
        vo_por_nombre: dict[str, tuple] = {}      # name → (vo_path, words, version_i)
        for _vi, (nm, _order) in enumerate(version_orders):
            vp, wt = (vos_pv[_vi] if _vi < len(vos_pv) else (None, None))
            vo_por_nombre[nm] = (vp, wt, _vi)
        if frases_por_nombre:
            regen_versions = {}
            for v in versions:
                nm = v["name"]
                fr = frases_por_nombre.get(nm) or []
                vp, wt, vi = vo_por_nombre.get(nm, (None, None, 0))
                order = next((o for n2, o in version_orders if n2 == nm), [])
                regen_versions[nm] = {
                    "order": list(order), "caps": version_caps.get(nm, []),
                    "frases": fr, "words": wt or [], "vo_path": vp,
                    "guion": " ".join(f.get("texto", "") for f in fr).strip(),
                    "hook": final_hook, "version_i": vi, "regen": 0,
                }
            manifest["_regen"] = {
                "selected": [s.to_dict() for s in selected],
                "fases": {str(k): val for k, val in fases_por_idx.items()},
                "usage": {str(k): val for k, val in regen_usage.items()},
                "n_versiones": len(version_orders),
                "work_dir": work_dir,
                "sfx_paths": sfx_paths or [],
                "music_path": music_path,
                "settings": {
                    "aspect": aspect, "enhance": enhance, "effects": effects,
                    "captions": captions, "caption_style": caption_style,
                    "caption_size": caption_size, "destino": destino,
                    "product_desc": product_desc, "page_url": page_url,
                    "hook_pos": hook_pos, "target_seconds": target_seconds,
                },
                "versions": regen_versions,
            }
    except Exception:  # noqa: BLE001
        pass

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
    hook_seconds: float = 0.0,
    auto_hook: bool = False,
    page_url: str = "",
    enhance: bool = False,
    effects: bool = False,
    blur_captions: bool = False,
    text_mode: str = "tapar",
    caption_pos: str = "abajo",
    voiceover_path: str | None = None,
    version_vos: list | None = None,
    sfx_paths: list | None = None,
    music_path: str | None = None,
    captions: bool = False,
    caption_style: str = "hormozi",
    caption_size: str = "mediano",
    destino: str = "tiktok",
    gemini_key: str | None = None,
    broll_fases: dict | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Pipeline de una pasada: analiza y renderiza. Si `version_vos` viene (voz por versión ya
    narrada con tiempos), el montaje se hace GUIADO POR EL GUION (guion_match) y la voz +
    subtítulos + mezcla pro se queman adentro del render (flujo de Mi producto)."""
    a = analyze_select(
        video_paths, target_seconds=target_seconds, max_clip_seconds=max_clip_seconds,
        use_gemini=use_gemini, product_desc=product_desc, gemini_key=gemini_key, progress=progress)
    if not a["ok"]:
        return a
    return render_versions(
        a["selected"], a["has_audio_by_src"], work_dir,
        aspect=aspect, enhance=enhance, hook_text=hook_text, hook_pos=hook_pos,
        hook_seconds=hook_seconds,
        auto_hook=auto_hook, page_url=page_url, product_desc=product_desc,
        gemini_key=gemini_key, voiceover_path=voiceover_path, version_vos=version_vos,
        sfx_paths=sfx_paths, music_path=music_path, effects=effects,
        captions=captions, caption_style=caption_style, caption_size=caption_size,
        destino=destino,
        blur_captions=blur_captions, text_mode=text_mode, caption_pos=caption_pos,
        used_gemini=a["used_gemini"], n_sources=a["n_sources"],
        target_seconds=target_seconds, max_clip_seconds=max_clip_seconds,
        broll_fases=broll_fases, progress=progress)
