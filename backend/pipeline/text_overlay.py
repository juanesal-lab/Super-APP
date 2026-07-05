"""Texto de gancho/marketing quemado sobre el video (estilo caption de ads).

El FFmpeg del sistema no trae el filtro drawtext (sin libfreetype), asi que
renderizamos el texto con Pillow a un PNG transparente (fuente TTF, caja
redondeada semitransparente y contorno negro) y lo superponemos con 'overlay'.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from .ffmpeg_utils import run, probe

_FONTS = [
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    # Windows
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _font_path() -> str | None:
    for f in _FONTS:
        if os.path.exists(f):
            return f
    return None


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if not cur or meas.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [text]


def _render_png(text: str, vw: int, vh: int, font_path: str, png_path: str) -> int:
    """Renderiza el texto centrado a un PNG del ancho del video. Devuelve alto del bloque."""
    font_size = max(28, int(vh * 0.052))
    font = ImageFont.truetype(font_path, font_size)
    lines = _wrap(text.upper(), font, int(vw * 0.84))

    meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    gap = int(line_h * 0.18)
    pad = int(font_size * 0.55)
    text_w = max(meas.textlength(l, font=font) for l in lines)
    block_w = int(text_w) + pad * 2
    block_h = line_h * len(lines) + gap * (len(lines) - 1) + pad * 2

    img = Image.new("RGBA", (vw, block_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x0 = (vw - block_w) // 2
    draw.rounded_rectangle([x0, 0, x0 + block_w, block_h],
                           radius=int(pad * 0.7), fill=(0, 0, 0, 140))
    stroke = max(2, font_size // 16)
    y = pad
    for l in lines:
        lw = meas.textlength(l, font=font)
        x = (vw - lw) / 2
        draw.text((x, y), l, font=font, fill=(255, 255, 255, 255),
                  stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        y += line_h + gap
    img.save(png_path)
    return block_h


def _y_pos(position: str, vh: int, block_h: int) -> int:
    if position == "centro":
        return max(0, (vh - block_h) // 2)
    if position == "abajo":
        return max(0, vh - block_h - int(vh * 0.08))
    return int(vh * 0.06)  # arriba


def burn_hook(video_path: str, out_path: str, work_dir: str, text: str,
              position: str = "arriba") -> tuple[str, bool]:
    """Quema el texto de gancho en el video. Devuelve (ruta, ok)."""
    text = (text or "").strip()
    if not text:
        return video_path, False
    font = _font_path()
    if not font:
        return video_path, False

    info = probe(video_path)
    vw, vh = info.width or 1080, info.height or 1920
    png = os.path.join(work_dir, "_hook.png")
    try:
        block_h = _render_png(text, vw, vh, font, png)
        y = _y_pos(position, vh, block_h)
        from .assemble import venc   # GPU si hay (antes libx264 CPU: ~4x más lento por versión)
        run([
            "ffmpeg", "-y", "-i", video_path, "-i", png,
            "-filter_complex", f"[0:v][1:v]overlay=0:{y}",
            *venc(),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "copy",
            out_path,
        ])
    except Exception:
        return video_path, False
    finally:
        try:
            os.remove(png)
        except OSError:
            pass
    return out_path, True
