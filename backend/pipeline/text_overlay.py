"""Texto de gancho/marketing quemado sobre el video (estilo caption de ads).

El FFmpeg del sistema no trae el filtro drawtext (sin libfreetype), asi que
renderizamos el texto con Pillow a un PNG transparente (fuente TTF, caja
redondeada semitransparente y contorno negro) y lo superponemos con 'overlay'.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from .ffmpeg_utils import run, probe

# ─────────────────── ZONAS SEGURAS (regla dura del dueño — CLAUDE.md §7) ───────────────────
# Referencia sobre lienzo 9:16 = 1080×1920. Todo se escala al tamaño REAL del video.
# Estas constantes son el contrato compartido: offer_banner.py las importa de acá.
SAFE_REF_W, SAFE_REF_H = 1080, 1920
SAFE_SIDE_PX = 64          # margen lateral mínimo: ninguna letra toca el borde (ancho útil ≈950px)
SAFE_TOP_PX = 90           # el banner de arriba empieza a ≥90px (reloj/UI de la plataforma)
SAFE_TOP_ZONE = 0.12       # el banner vive dentro del 12% superior (best effort si son 2+ líneas)
SAFE_BANNER_PAD_PX = 24    # padding interno mínimo de la caja del banner (letras no tocan la caja)
SAFE_BOTTOM_DEAD = 0.78125  # (1920−420)/1920: de acá para abajo la UI tapa → CERO texto clave
SAFE_SUB_ZONE = (0.55, 0.78125)  # franja segura de subtítulos (55%–78%; y máx = 1500/1920)
SAFE_MIN_SUB_PX = 48       # tamaño mínimo legible de subtítulo en el celular
SAFE_MIN_BANNER_PX = 44    # tamaño mínimo legible del banner


def safe_margin_x(W: int) -> int:
    """Margen lateral mínimo en px reales (≥64px sobre 1080 de ancho)."""
    return max(8, round(SAFE_SIDE_PX * W / SAFE_REF_W))


def safe_top_min(H: int) -> int:
    """y mínima del banner superior en px reales (≥90px sobre 1920 de alto)."""
    return max(8, round(SAFE_TOP_PX * H / SAFE_REF_H))


def safe_bottom_limit(H: int) -> int:
    """y MÁXIMA (borde inferior) para texto clave: nunca dentro de la zona muerta de abajo."""
    return int(H * SAFE_BOTTOM_DEAD)


def safe_px(H: int, ref_px: int) -> int:
    """Escala un tamaño de referencia (px sobre 1920 de alto) al alto real del video."""
    return max(12, round(ref_px * H / SAFE_REF_H))


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
                max_frac: float = 0.20, min_px: int | None = None) -> int:
    """Renderiza el texto centrado a un PNG del ancho del video. Devuelve alto del bloque.

    El bloque NUNCA ocupa más de `max_frac` del alto (default 1/5): arranca en un tamaño MEDIANO
    y encoge la letra hasta que quepa. ZONAS SEGURAS: la caja (texto + padding) queda dentro del
    ancho útil (márgenes ≥64px escalados); el piso legible es `min_px` (default 48px escalados),
    pero si una palabra sola no entra en el ancho útil se sigue achicando — JAMÁS texto cortado."""
    meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    floor = safe_px(vh, SAFE_MIN_SUB_PX) if min_px is None else int(min_px)
    font_size = max(floor, int(vh * 0.040))       # medio (antes 0.052 = gigante)
    max_h = int(vh * max_frac)
    margin = safe_margin_x(vw)
    for _ in range(40):                            # encoge hasta caber (alto Y ancho)
        font = ImageFont.truetype(font_path, font_size)
        pad = int(font_size * 0.5)
        max_w = min(int(vw * 0.84), vw - 2 * margin - 2 * pad)   # caja completa dentro del margen
        lines = _wrap(text.upper(), font, max_w)
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
        gap = int(line_h * 0.18)
        block_h = line_h * len(lines) + gap * (len(lines) - 1) + pad * 2
        widest = max(meas.textlength(l, font=font) for l in lines)
        # ancho SIEMPRE tiene que caber (aunque haya que bajar del piso); alto cede en el piso
        if widest <= max_w and (block_h <= max_h or font_size <= floor):
            break
        if font_size <= 14:
            break
        font_size = max(14, int(font_size * 0.9))
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
    """y del bloque, SIEMPRE dentro de las zonas seguras: 'abajo' apoya la base en el límite
    seguro (nunca en los últimos ~420px que tapa la UI); 'arriba' arranca a ≥90px escalados."""
    limit = safe_bottom_limit(vh)                # borde inferior máximo para texto clave
    if position == "centro":
        y = max(0, (vh - block_h) // 2)
    elif position == "abajo":
        y = limit - block_h                      # antes: vh−block−8% → caía en la zona muerta
    else:
        y = max(int(vh * 0.06), safe_top_min(vh))  # arriba
    return max(0, min(y, limit - block_h))


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
