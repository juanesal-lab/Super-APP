"""Reemplazo de producto: detecta los momentos donde aparece el producto viejo
y los sustituye por las tomas del producto nuevo, conservando el AUDIO original.

NO edita pixel por pixel (eso es imposible). Reemplaza TOMAS/segmentos completos:
durante los segundos donde sale el producto viejo, se ve el video nuevo; el audio
(voz, sonido) sigue intacto de principio a fin.
"""
from __future__ import annotations

import json
import math
import os
import re

import cv2
import numpy as np

from .ffmpeg_utils import run, probe

_MODEL = "gemini-2.5-flash"
_CELL = 340


def _grab(path: str, t: float):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, fr = cap.read()
    cap.release()
    return fr if ok else None


def _contact_sheet(path: str, times: list[float]):
    cells = []
    for i, t in enumerate(times):
        fr = _grab(path, t)
        if fr is None:
            continue
        h, w = fr.shape[:2]
        m = min(h, w)
        sq = fr[(h - m) // 2:(h - m) // 2 + m, (w - m) // 2:(w - m) // 2 + m]
        cell = cv2.resize(sq, (_CELL, _CELL))
        cv2.rectangle(cell, (0, 0), (70, 40), (0, 0, 0), -1)
        cv2.putText(cell, str(i), (6, 31), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)
        cells.append(cell)
    if not cells:
        return None
    cols = min(6, math.ceil(math.sqrt(len(cells))))
    rows = math.ceil(len(cells) / cols)
    sheet = np.zeros((rows * _CELL, cols * _CELL, 3), np.uint8)
    for k, c in enumerate(cells):
        r, cc = divmod(k, cols)
        sheet[r * _CELL:(r + 1) * _CELL, cc * _CELL:(cc + 1) * _CELL] = c
    ok, buf = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return buf.tobytes() if ok else None


def detect_product_ranges(api_key: str | None, video_path: str, product_desc: str = "",
                          step: float = 0.0, gap: float = 1.2,
                          min_len: float = 0.6) -> list[tuple]:
    """Devuelve [(start, end)] de los momentos donde se VE el producto."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return []
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
    except Exception:
        return []

    dur = probe(video_path).duration
    if dur <= 0:
        return []
    # muestreo denso (~32 frames) para no dejar escapar momentos cortos del producto
    step = step or max(0.4, dur / 32.0)
    times = [round(t, 2) for t in np.arange(step / 2, dur, step)][:32]
    sheet = _contact_sheet(video_path, times)
    if sheet is None:
        return []

    prod = product_desc.strip() or "el producto que se anuncia (el objeto principal)"
    prompt = (
        f"Esta grilla tiene {len(times)} fotogramas numerados de un video. "
        f"El producto es: {prod}. Marca TODOS los fotogramas donde SE VE ese producto, "
        "AUNQUE aparezca pequeño, parcial, borroso, de lado o solo una parte. "
        "Solo descarta los fotogramas donde el producto NO se ve para nada. "
        "Ante la duda, INCLÚYELO. "
        "Devuelve SOLO un JSON array con los numeros donde se ve: [0,1,2,...]. "
        "Si se ve en todos, devuelve todos."
    )
    idxs = set()
    for _ in range(2):  # reintenta una vez si no parsea
        try:
            resp = client.models.generate_content(
                model=_MODEL,
                contents=[prompt, types.Part.from_bytes(data=sheet, mime_type="image/jpeg")])
            m = re.search(r"\[[\d,\s]*\]", resp.text or "", re.DOTALL)
            if m:
                idxs = set(int(x) for x in re.findall(r"\d+", m.group(0)))
                break
        except Exception:
            continue

    # agrupar tiempos con hueco tolerado, luego AÑADIR MARGEN y fusionar solapados
    hits = sorted(times[i] for i in idxs if 0 <= i < len(times))
    if not hits:
        return []
    merge_gap = max(gap, step) + step       # fusiona momentos cercanos (tapa huecos)
    pad = 0.45                               # margen a cada lado (caza frames del borde)
    groups, a, prev = [], hits[0], hits[0]
    for t in hits[1:]:
        if t - prev <= merge_gap:
            prev = t
        else:
            groups.append((a, prev)); a = t; prev = t
    groups.append((a, prev))

    out = []
    for s, e in groups:
        s, e = max(0.0, s - pad), min(dur, e + pad)
        if out and s <= out[-1][1] + 0.15:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return [(s, e) for s, e in out if e - s >= min_len]


def _scale_cover(w, h):
    return (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"setsar=1,fps=30")


def find_new_clips(api_key: str | None, new_paths: list[str],
                   new_desc: str = "") -> list[tuple]:
    """Devuelve [(path, start, end)] de las tomas donde se VE el producto NUEVO.
    Si en un video no detecta el producto, usa el video completo como respaldo."""
    clips = []
    for p in new_paths:
        if not os.path.exists(p):
            continue
        ranges = detect_product_ranges(api_key, p, new_desc)
        if ranges:
            clips += [(p, a, b) for a, b in ranges]
        else:
            clips.append((p, 0.0, max(0.5, probe(p).duration)))
    return clips


def swap_product(old_path: str, new_clips: list[tuple], ranges: list[tuple],
                 out_path: str, work_dir: str) -> str:
    """Reemplaza los rangos del producto viejo con las TOMAS del producto nuevo
    (new_clips = [(path,start,end)]); conserva el audio del viejo."""
    info = probe(old_path)
    W, H, dur = info.width, info.height, info.duration
    os.makedirs(work_dir, exist_ok=True)
    vf = _scale_cover(W, H)

    # pre-extraer y normalizar cada toma del producto nuevo
    new_files = []
    for j, (p, cs, ce) in enumerate(new_clips):
        if not os.path.exists(p):
            continue
        cd = max(0.4, ce - cs)
        nf = os.path.join(work_dir, f"newclip_{j:03d}.mp4")
        run(["ffmpeg", "-y", "-ss", f"{cs:.3f}", "-i", p, "-t", f"{cd:.3f}", "-an",
             "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", nf])
        new_files.append((nf, cd))
    if not new_files:
        new_files = [(old_path, dur)]

    # línea de tiempo: viejo / nuevo / viejo / ...
    ranges = sorted(ranges)
    segs, cur = [], 0.0
    for a, b in ranges:
        a, b = max(0, a), min(dur, b)
        if b - a < 0.2:
            continue
        if a > cur + 0.05:
            segs.append(("old", cur, a))
        segs.append(("new", a, b))
        cur = b
    if cur < dur - 0.05:
        segs.append(("old", cur, dur))
    if not segs:
        segs = [("old", 0, dur)]

    pieces, n_i = [], 0
    for k, (typ, a, b) in enumerate(segs):
        d = b - a
        p = os.path.join(work_dir, f"seg_{k:03d}.mp4")
        if typ == "old":
            run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-i", old_path, "-t", f"{d:.3f}",
                 "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-pix_fmt", "yuv420p", p])
        else:
            nf, nd = new_files[n_i % len(new_files)]; n_i += 1
            loop = ["-stream_loop", "-1"] if d > nd else []
            run(["ffmpeg", "-y", *loop, "-i", nf, "-t", f"{d:.3f}", "-an",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", p])
        pieces.append(p)

    # concatenar el video y luego pegarle el AUDIO original completo
    listf = os.path.join(work_dir, "_swap_list.txt")
    with open(listf, "w") as f:
        for p in pieces:
            f.write(f"file '{os.path.abspath(p)}'\n")
    silent = os.path.join(work_dir, "_swap_video.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf, "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", silent])
    run(["ffmpeg", "-y", "-i", silent, "-i", old_path,
         "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac",
         "-movflags", "+faststart", "-shortest", out_path])
    return out_path
