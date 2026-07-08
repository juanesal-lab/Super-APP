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


def _render_png(text: str, vw: int, vh: int, font_path: str, png_path: str,
                max_frac: float = 0.20) -> int:
    """Renderiza el texto centrado a un PNG del ancho del video. Devuelve alto del bloque.

    El bloque NUNCA ocupa más de `max_frac` del alto (default 1/5): arranca en un tamaño MEDIANO
    y encoge la letra hasta que quepa (antes salía gigante — hasta 1/3 de pantalla — y se veía feo)."""
    meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    font_size = max(24, int(vh * 0.040))          # medio (antes 0.052 = gigante)
    max_h = int(vh * max_frac)
    for _ in range(14):                            # encoge hasta caber en 1/5 de pantalla
        font = ImageFont.truetype(font_path, font_size)
        lines = _wrap(text.upper(), font, int(vw * 0.84))
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
        gap = int(line_h * 0.18)
        pad = int(font_size * 0.5)
        block_h = line_h * len(lines) + gap * (len(lines) - 1) + pad * 2
        if block_h <= max_h or font_size <= 26:
            break
        font_size = int(font_size * 0.9)
    text_w = max(meas.textlength(l, font=font) for l in lines)
    block_w = int(text_w) + pad * 2

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


def _render_pill_png(text: str, vw: int, vh: int, font_path: str, png_path: str,
                     max_frac: float = 0.16) -> int:
    """Pastilla BLANCA con texto NEGRO en negrita (estilo de la referencia de Jack: 'MIRA LA
    SOLUCIÓN' arriba). Centrada, ancho ajustado al texto, alto ≤ `max_frac` de la pantalla.
    Devuelve el alto del bloque. Igual que _render_png pero look pill blanco → alto contraste."""
    meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    font_size = max(26, int(vh * 0.044))
    max_h = int(vh * max_frac)
    max_text_w = int(vw * 0.80)
    for _ in range(16):
        font = ImageFont.truetype(font_path, font_size)
        lines = _wrap(text.upper(), font, max_text_w)
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
        gap = int(line_h * 0.14)
        pad_y = int(font_size * 0.42)
        pad_x = int(font_size * 0.75)
        block_h = line_h * len(lines) + gap * (len(lines) - 1) + pad_y * 2
        if block_h <= max_h or font_size <= 26:
            break
        font_size = int(font_size * 0.9)
    text_w = max(meas.textlength(l, font=font) for l in lines)
    block_w = int(text_w) + pad_x * 2

    img = Image.new("RGBA", (vw, block_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x0 = (vw - block_w) // 2
    # sombra suave para despegar la pastilla del fondo claro/oscuro
    sh = max(2, block_h // 22)
    draw.rounded_rectangle([x0 + sh, sh, x0 + block_w + sh, block_h - 1],
                           radius=int(block_h * 0.30), fill=(0, 0, 0, 70))
    draw.rounded_rectangle([x0, 0, x0 + block_w, block_h - sh],
                           radius=int(block_h * 0.30), fill=(255, 255, 255, 240))
    y = pad_y
    for l in lines:
        lw = meas.textlength(l, font=font)
        x = (vw - lw) / 2
        draw.text((x, y), l, font=font, fill=(17, 17, 17, 255))
        y += line_h + gap
    img.save(png_path)
    return block_h


def burn_hook_pill(video_path: str, out_path: str, work_dir: str, text: str,
                   seconds: float = 3.0, uid: str = "") -> tuple[str, bool]:
    """🎯 Quema un HOOK de texto como PASTILLA BLANCA arriba (referencia de Jack), visible SOLO
    los primeros `seconds` seg (default 3). `uid` hace único el PNG (varias versiones en paralelo).
    Devuelve (ruta, ok). No re-codifica si no hay texto/fuente."""
    text = (text or "").strip()
    if not text:
        return video_path, False
    font = _font_path()
    if not font:
        return video_path, False
    info = probe(video_path)
    vw, vh = info.width or 1080, info.height or 1920
    png = os.path.join(work_dir, f"_hookpill_{uid or os.path.basename(out_path)}.png")
    try:
        block_h = _render_pill_png(text, vw, vh, font, png)
        y = int(vh * 0.055)   # arriba, dentro de la safe zone
        enable = f":enable='lt(t,{float(seconds):.2f})'" if seconds and seconds > 0 else ""
        from .assemble import venc
        run([
            "ffmpeg", "-y", "-i", video_path, "-i", png,
            "-filter_complex", f"[0:v][1:v]overlay=0:{y}{enable}",
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


def burn_hook(video_path: str, out_path: str, work_dir: str, text: str,
              position: str = "arriba", seconds: float = 0.0) -> tuple[str, bool]:
    """Quema el texto de gancho en el video. Devuelve (ruta, ok).

    `seconds`>0: el gancho SOLO aparece durante los primeros `seconds` segundos (después se quita).
    0 = toda la duración (como antes)."""
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
        enable = f":enable='lt(t,{float(seconds):.2f})'" if seconds and seconds > 0 else ""
        from .assemble import venc   # GPU si hay (antes libx264 CPU: ~4x más lento por versión)
        run([
            "ffmpeg", "-y", "-i", video_path, "-i", png,
            "-filter_complex", f"[0:v][1:v]overlay=0:{y}{enable}",
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
