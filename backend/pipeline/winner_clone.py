"""CLON GANADOR CON MI PRODUCTO — clona un creativo ganador mostrando NUESTRO producto real.

El usuario mete: (1) un creativo GANADOR (de otro producto, mismo ángulo), (2) foto y/o
clips de SU producto, (3) una descripción. El sistema:
  1. Deja la voz original O la dobla a español colombiano (opción).
  2. Detecta los momentos EXACTOS donde aparece el producto ORIGINAL (Gemini visión).
  3. REEMPLAZO INTELIGENTE por movimiento en cada momento:
       - producto quieto/primer plano  -> reemplaza por una toma NUESTRA quieta (limpio)
       - mucho movimiento/manos/ángulos -> corta a una toma NUESTRA dinámica
       - si no hay buena toma para un momento movido -> DEJA el original (no fuerza -> no se ve falso)
  4. Traduce el texto en pantalla, verticaliza 9:16 con blur, música/efectos por fase,
     subtítulos y normaliza el audio.
  -> SALIDA: el ganador mostrando nuestro producto, listo para subir.

Terreno propio. REUSA (sin editar): product_swap (detect/ find_new_clips/ swap_product),
auto_studio (finalización), dub_colombia, text_translate, narrative, phase_effects, angle_clone.
Cada paso aislado (si falla, sigue y reporta). Gemini + ElevenLabs + FFmpeg.

Nota: buscar tomas en TikTok (sonar-auto / tiktok-creative-scout) es una capa EXTERNA (skill +
navegador); no se llama inline. El usuario alimenta esas tomas por `our_videos`/`our_photos`
(que puede sacar del scout + descargador). Queda anotado como enganche futuro.
"""
from __future__ import annotations

import os
import tempfile
from typing import Callable

import cv2
import numpy as np

from .product_swap import detect_product_ranges, find_new_clips, swap_product
from .angle_clone import _photo_to_clip
from .narrative import analyze_narrative, mmss_to_seconds
from .phase_effects import phase_effect_plan
from .dub_colombia import generar_dub
from .text_translate import traducir_texto_pantalla
from . import auto_studio as A

# Umbrales de movimiento (diff media 0..255 sobre gris 64x64, muestreando ~8 frames). Tuneables.
# Calibrados sobre datos reales: quieto/primer plano ~0-4, moderado ~4-11, mucho movimiento >11.
_MOTION_LOW = 4.0     # por debajo = quieto / primer plano
_MOTION_HIGH = 11.0   # por encima = mucho movimiento / manos / ángulos difíciles


def _motion_score(path: str, a: float, b: float, samples: int = 8) -> float:
    """Movimiento promedio en el tramo [a,b]: diff media entre frames (0 quieto ... alto = movido)."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return 0.0
    dur = max(0.1, b - a)
    diffs, prev = [], None
    for i in range(samples):
        t = a + dur * i / max(1, samples - 1)
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        g = cv2.cvtColor(cv2.resize(fr, (64, 64)), cv2.COLOR_BGR2GRAY).astype(np.int16)
        if prev is not None:
            diffs.append(float(np.abs(g - prev).mean()))
        prev = g
    cap.release()
    return sum(diffs) / len(diffs) if diffs else 0.0


def _clasificar_tomas(our_photos, our_videos, api_key, product_desc, work_dir):
    """Devuelve (quietas, dinamicas): listas de tomas nuestras (path,start,end) según su movimiento.

    Fotos -> clip estable (quieta). Videos -> se miden y se reparten por movimiento.
    """
    quietas, dinamicas = [], []
    for i, ph in enumerate(our_photos or []):
        if os.path.exists(ph):
            cf = _photo_to_clip(ph, 2.5, os.path.join(work_dir, f"ourphoto_{i:02d}.mp4"))
            quietas.append((cf, 0.0, 2.5))
    if our_videos:
        for (p, a, b) in find_new_clips(api_key, [v for v in our_videos if os.path.exists(v)], product_desc):
            (quietas if _motion_score(p, a, b) < _MOTION_LOW else dinamicas).append((p, a, b))
    return quietas, dinamicas


def clonar_ganador(
    winner_path: str,
    our_photos: list[str] | None = None,
    our_videos: list[str] | None = None,
    *,
    product_desc: str = "",
    old_desc: str = "",
    doblar: bool = False,
    voz: str = "juan_carlos",
    verticalizar: bool = True,
    gemini_key: str | None = None,
    eleven_key: str | None = None,
    work_dir: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Clona el ganador mostrando nuestro producto, con reemplazo inteligente + finalización.

    Devuelve {"ok":True,"video":ruta,"pasos":[...],"decisiones":[{rango,movimiento,accion}]}.
    """
    pasos, decisiones = [], []

    def report(m, p):
        if progress:
            progress(m, p)

    def paso(n, ok, det=""):
        pasos.append({"paso": n, "ok": ok, "detalle": det})

    gemini_key = gemini_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    eleven_key = eleven_key or os.environ.get("ELEVENLABS_API_KEY")
    if not os.path.exists(winner_path):
        return {"ok": False, "error": "No encuentro el creativo ganador.", "pasos": pasos}
    our_photos = [p for p in (our_photos or []) if p and os.path.exists(p)]
    our_videos = [v for v in (our_videos or []) if v and os.path.exists(v)]
    if not our_photos and not our_videos:
        return {"ok": False, "error": "Sube al menos una foto o un clip de tu producto.", "pasos": pasos}

    work_dir = work_dir or tempfile.mkdtemp(prefix="wclone_")
    os.makedirs(work_dir, exist_ok=True)
    current = winner_path
    dub_segments: list[dict] = []
    word_timings: list[dict] = []

    # 0) Narrativa + detección del producto EN PARALELO (2 llamadas Gemini independientes = más rápido)
    report("📖 Analizando el ganador (narrativa + producto)...", 8)
    blueprint = None
    ranges: list = []
    from concurrent.futures import ThreadPoolExecutor

    def _narr():
        try:
            bp = analyze_narrative(winner_path, api_key=gemini_key, product_desc=product_desc)
            return bp if bp.get("ok") else None
        except Exception:  # noqa: BLE001
            return None

    def _det():
        if not gemini_key:
            return []
        try:
            return detect_product_ranges(gemini_key, winner_path, old_desc) or []
        except Exception:  # noqa: BLE001
            return []

    with ThreadPoolExecutor(max_workers=2) as ex:
        fb, fd = ex.submit(_narr), ex.submit(_det)
        blueprint, ranges = fb.result(), fd.result()
    paso("Narrativa", bool(blueprint), f"{len(blueprint['segments'])} fases" if blueprint else "no")
    paso("Detectar producto", bool(ranges), f"{len(ranges)} momento(s)" if ranges else "no detectado")

    # 1) Voz: original o doblada a español colombiano
    if doblar and eleven_key:
        report("🇨🇴 Doblando la voz a español colombiano...", 20)
        try:
            wd = os.path.join(work_dir, "dub"); os.makedirs(wd, exist_ok=True)
            d = generar_dub(current, api_key=gemini_key, eleven_key=eleven_key,
                            product_desc=product_desc, voz=voz, generar_video=True,
                            work_dir=wd, blueprint=blueprint)
            if d.get("ok") and d.get("video"):
                current = d["video"]; dub_segments = d.get("segments", [])
                word_timings = d.get("word_timings", [])
                paso("Doblaje CO", True, f"voz {d.get('voz')}")
            else:
                paso("Doblaje CO", False, d.get("error", ""))
        except Exception as e:  # noqa: BLE001
            paso("Doblaje CO", False, str(e))
    else:
        paso("Voz", True, "se conserva la voz original")

    # (la detección del producto ya se hizo en paralelo con la narrativa, arriba)

    # 3) Clasificar nuestras tomas por movimiento
    report("🎬 Preparando tus tomas...", 46)
    quietas, dinamicas = _clasificar_tomas(our_photos, our_videos, gemini_key, product_desc, work_dir)
    paso("Tus tomas", bool(quietas or dinamicas), f"{len(quietas)} quietas, {len(dinamicas)} dinámicas")

    # 4) DECISIÓN por movimiento: reemplazar (quieto) / cortar (movido) / dejar original
    report("🧠 Decidiendo reemplazo inteligente por movimiento...", 58)
    rep_ranges, rep_clips = [], []
    qi = di = 0
    for (a, b) in sorted(ranges):
        m = _motion_score(winner_path, a, b)
        chosen, accion = None, ""
        if m < _MOTION_LOW:                                   # quieto -> reemplazar por toma quieta
            pool = quietas or dinamicas
            if pool:
                chosen = pool[qi % len(pool)]; qi += 1
                accion = "reemplazar (producto quieto)"
        elif m > _MOTION_HIGH:                                # movido -> cortar a toma dinámica
            if dinamicas:
                chosen = dinamicas[di % len(dinamicas)]; di += 1
                accion = "cortar a toma propia (movido)"
            else:
                accion = "dejar original (movido, sin toma dinámica)"
        else:                                                 # medio -> la mejor disponible
            pool = dinamicas or quietas
            if pool:
                chosen = pool[di % len(pool)]; di += 1
                accion = "cortar a toma propia (medio)"
        if chosen:
            rep_ranges.append((a, b)); rep_clips.append(chosen)
        decisiones.append({"rango": f"{a:.1f}-{b:.1f}s", "movimiento": round(m, 1), "accion": accion})

    # 5) Empalme (reusa swap_product): nuestras tomas en los rangos elegidos, conserva el audio
    if rep_ranges:
        report("🔄 Metiendo tu producto en los momentos elegidos...", 68)
        try:
            out = os.path.join(work_dir, "clonado.mp4")
            wd = os.path.join(work_dir, "swap"); os.makedirs(wd, exist_ok=True)
            swap_product(current, rep_clips, rep_ranges, out, wd)
            current = out
            paso("Reemplazo", True, f"{len(rep_ranges)} momento(s) con tu producto")
        except Exception as e:  # noqa: BLE001
            paso("Reemplazo", False, str(e))
    else:
        paso("Reemplazo", False, "sin momentos aptos (se deja el ganador tal cual)")

    # 6) Traducir texto en pantalla
    report("🔤 Traduciendo el texto en pantalla...", 78)
    try:
        out = os.path.join(work_dir, "traducido.mp4")
        t = traducir_texto_pantalla(current, api_key=gemini_key, out_path=out)
        if t.get("ok"):
            current = t["video"]; paso("Traducir texto", True, f"{len(t.get('bloques', []))} bloque(s)")
        else:
            paso("Traducir texto", False, t.get("error", ""))
    except Exception as e:  # noqa: BLE001
        paso("Traducir texto", False, str(e))

    # 7) Música + SFX por fase
    report("🎵 Música y efectos por fase...", 85)
    if blueprint:
        try:
            plan = phase_effect_plan(blueprint, A._dur(current), A._sfx_files())
            if plan.get("ok"):
                out = os.path.join(work_dir, "musica.mp4")
                current = A._add_music_sfx(current, plan, eleven_key, product_desc, work_dir, out)
                paso("Música + SFX", True)
            else:
                paso("Música + SFX", False, plan.get("error", ""))
        except Exception as e:  # noqa: BLE001
            paso("Música + SFX", False, str(e))

    # 8) Subtítulos: palabra por palabra si hay doblaje (tiempos reales); si no, bloque por fase
    report("💬 Subtítulos...", 90)
    subs = dub_segments or (blueprint.get("segments") if blueprint else [])
    if word_timings:
        try:
            from .caption_styles import burn_word_captions
            out = os.path.join(work_dir, "subs.mp4")
            current = burn_word_captions(current, word_timings, work_dir, out, style="karaoke")
            paso("Subtítulos", True, f"palabra x palabra ({len(word_timings)})")
        except Exception as e:  # noqa: BLE001
            paso("Subtítulos", False, str(e))
    elif subs:
        try:
            out = os.path.join(work_dir, "subs.mp4")
            current = A._burn_subs(current, subs, work_dir, out); paso("Subtítulos", True)
        except Exception as e:  # noqa: BLE001
            paso("Subtítulos", False, str(e))

    # 9) Verticalizar 9:16 (blur, nunca estirar) + normalizar audio
    if verticalizar:
        report("📱 Verticalizando 9:16 (fondo desenfocado)...", 94)
        try:
            out = os.path.join(work_dir, "vertical.mp4")
            current = A._verticalize(current, out); paso("Vertical 9:16", True)
        except Exception as e:  # noqa: BLE001
            paso("Vertical 9:16", False, str(e))
    if A._has_audio(current):
        report("🔊 Normalizando audio...", 97)
        try:
            out = os.path.join(work_dir, "final.mp4")
            current = A._normalize(current, out); paso("Normalizar audio", True)
        except Exception as e:  # noqa: BLE001
            paso("Normalizar audio", False, str(e))

    report("✅ Clon terminado", 100)
    ok_n = sum(1 for p in pasos if p["ok"])
    return {"ok": True, "video": current, "pasos": pasos, "decisiones": decisiones,
            "resumen": f"{ok_n}/{len(pasos)} pasos OK"}


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("Uso: python -m backend.pipeline.winner_clone <ganador.mp4> [--foto f.jpg] "
              "[--video v.mp4] [--desc 'mi producto'] [--old 'producto viejo'] [--doblar]")
        raise SystemExit(1)
    winner = sys.argv[1]
    fotos, vids = [], []
    desc = old = ""
    doblar = "--doblar" in sys.argv
    args = sys.argv[2:]
    for i, a in enumerate(args):
        if a == "--foto" and i + 1 < len(args): fotos.append(args[i + 1])
        elif a == "--video" and i + 1 < len(args): vids.append(args[i + 1])
        elif a == "--desc" and i + 1 < len(args): desc = args[i + 1]
        elif a == "--old" and i + 1 < len(args): old = args[i + 1]

    def _p(m, p):
        print(f"[{p:3d}%] {m}", file=sys.stderr)

    r = clonar_ganador(winner, fotos or None, vids or None, product_desc=desc, old_desc=old,
                       doblar=doblar, progress=_p)
    print(json.dumps({k: v for k, v in r.items()}, ensure_ascii=False, indent=2))
