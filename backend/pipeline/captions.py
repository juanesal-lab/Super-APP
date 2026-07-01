"""Subtitulos animados palabra-por-palabra (estilo TikTok/CapCut).

Usa los tiempos por palabra de ElevenLabs, agrupa en chunks de 1-3 palabras y
superpone cada uno como PNG (Pillow) en su ventana de tiempo via overlay+enable.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from .ffmpeg_utils import run, probe
from .text_overlay import _font_path


def _group(words: list[dict], max_words: int = 2) -> list[dict]:
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        end_chunk = len(cur) >= max_words or w["word"][-1:] in ".,!?¿¡"
        if end_chunk:
            chunks.append({"text": " ".join(x["word"] for x in cur),
                           "start": cur[0]["start"], "end": cur[-1]["end"]})
            cur = []
    if cur:
        chunks.append({"text": " ".join(x["word"] for x in cur),
                       "start": cur[0]["start"], "end": cur[-1]["end"]})
    return chunks


_MEAS = ImageDraw.Draw(Image.new("RGBA", (8, 8)))


def _png(text: str, vw: int, vh: int, font_path: str, out: str):
    """Renderiza el chunk AUTO-AJUSTADO para que NUNCA se salga del ancho del video."""
    text = text.upper()
    max_w = vw * 0.86
    fs = int(vh * 0.058)
    # encoger la fuente hasta que quepa en una linea
    while fs > 26:
        font = ImageFont.truetype(font_path, fs)
        if _MEAS.textlength(text, font=font) <= max_w:
            break
        fs -= 3
    font = ImageFont.truetype(font_path, fs)
    tw = _MEAS.textlength(text, font=font)
    asc, desc = font.getmetrics()
    pad = int(fs * 0.42)
    h = asc + desc + pad * 2
    img = Image.new("RGBA", (vw, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text(((vw - tw) / 2, pad), text, font=font, fill=(255, 240, 60, 255),
           stroke_width=max(3, fs // 11), stroke_fill=(0, 0, 0, 255))
    img.save(out)
    return h


def add_captions(video_path: str, out_path: str, work_dir: str,
                 words: list[dict], position: str = "centro") -> tuple[str, bool]:
    """Quema subtitulos animados. Devuelve (ruta, ok)."""
    words = [w for w in (words or []) if w.get("word") and w.get("start") is not None]
    font = _font_path()
    if not words or not font:
        return video_path, False

    info = probe(video_path)
    vw, vh = info.width or 1080, info.height or 1920
    chunks = _group(words)[:40]

    cap_dir = os.path.join(work_dir, "_caps")
    os.makedirs(cap_dir, exist_ok=True)
    pngs = []
    for i, ch in enumerate(chunks):
        p = os.path.join(cap_dir, f"c{i}.png")
        h = _png(ch["text"], vw, vh, font, p)
        pngs.append((p, ch["start"], ch["end"], h))

    if position == "abajo":
        y = int(vh * 0.74)
    elif position == "arriba":
        y = int(vh * 0.14)
    else:
        y = int(vh * 0.60)

    inputs = ["-i", video_path]
    for p, _, _, _ in pngs:
        inputs += ["-i", p]
    fc, last = [], "[0:v]"
    for i, (p, s, e, h) in enumerate(pngs):
        tag = "[v]" if i == len(pngs) - 1 else f"[k{i}]"
        fc.append(f"{last}[{i + 1}:v]overlay=0:{y}:enable='between(t,{s:.2f},{e:.2f})'{tag}")
        last = f"[k{i}]"
    try:
        run([
            "ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc),
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "copy",
            out_path,
        ])
    except Exception:
        return video_path, False
    return out_path, True
