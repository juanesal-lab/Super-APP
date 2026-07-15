"""Banner de OFERTA arriba del creativo (opcional): 'ENVÍO GRATIS · PAGAS AL RECIBIR' + 'OFERTA 2X1'.

Lo pone ARRIBA, pero la IA elige una y-fracción donde NO tape nada importante (cara/producto/texto).
Estilo de la foto de Jack: pill roja arriba + segunda línea blanca con contorno. Fuente Poppins.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from .caption_styles import _fontpath, _fit
from .ffmpeg_utils import probe, run
from .assemble import venc
# Zonas seguras (regla dura del dueño — CLAUDE.md §7 de Vidaria): contrato compartido.
from .text_overlay import (SAFE_BANNER_PAD_PX, SAFE_MIN_BANNER_PX, safe_bottom_limit,
                           safe_margin_x, safe_px, safe_top_min)

_ROJO = (226, 45, 44, 255)
_NARANJA = (240, 120, 18, 255)      # naranja alto contraste (banner inferior de oferta)
_MODEL = "gemini-2.5-flash"


def render_banner(W: int, H: int, y_frac: float = 0.04,
                  line1: str = "ENVÍO GRATIS · PAGAS AL RECIBIR",
                  line2: str = "OFERTA 2X1") -> Image.Image:
    """PNG full-frame con el banner cerca del top (en y_frac). line2 opcional (vacío = sin 2ª línea)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fp = _fontpath(True)
    # Regla del dueño: el banner arranca a ≥90px del borde superior (que el reloj/UI no lo tape).
    y = max(int(H * y_frac), safe_top_min(H))
    margin = safe_margin_x(W)               # ninguna letra toca el borde (≥64px laterales)
    pad_min = safe_px(H, SAFE_BANNER_PAD_PX)  # padding interno de la caja ≥24px

    line1 = (line1 or "").strip()
    if line1:
        s1 = max(safe_px(H, SAFE_MIN_BANNER_PX), int(H * 0.026))   # banner ≥44px legible
        f1 = ImageFont.truetype(fp, s1)
        tw = d.textlength(line1, font=f1)
        padx, pady = max(pad_min, int(s1 * 0.7)), max(pad_min, int(s1 * 0.45))
        # que la pill COMPLETA quepa dentro de los márgenes: si no cabe, achica la letra
        # (nunca bajo 24px absolutos) — jamás texto cortado por el borde.
        while tw + 2 * padx > W - 2 * margin and s1 > 24:
            s1 -= 2
            f1 = ImageFont.truetype(fp, s1)
            tw = d.textlength(line1, font=f1)
            padx, pady = max(pad_min, int(s1 * 0.7)), max(pad_min, int(s1 * 0.45))
        x0 = (W - tw) / 2 - padx
        x1 = (W + tw) / 2 + padx
        d.rounded_rectangle([x0, y, x1, y + s1 + 2 * pady], radius=int((s1 + 2 * pady) / 2), fill=_ROJO)
        d.text(((W - tw) / 2, y + pady), line1, font=f1, fill=(255, 255, 255, 255))
        y += s1 + 2 * pady + int(H * 0.012)

    line2 = (line2 or "").strip()
    if line2:
        s2 = max(safe_px(H, SAFE_MIN_BANNER_PX), int(H * 0.036))
        f2 = ImageFont.truetype(fp, s2)
        tw2 = d.textlength(line2, font=f2)
        while tw2 > W - 2 * margin and s2 > 24:    # completa dentro del margen, nunca cortada
            s2 -= 2
            f2 = ImageFont.truetype(fp, s2)
            tw2 = d.textlength(line2, font=f2)
        st = max(3, s2 // 7)
        d.text(((W - tw2) / 2, y), line2, font=f2, fill=(255, 255, 255, 255),
               stroke_width=st, stroke_fill=(0, 0, 0, 255))
    return img


def safe_top_y(video_path: str, gemini_key: str | None) -> float:
    """La IA elige una y-fracción (0.05-0.30) para el banner donde NO tape cara/producto/texto.

    Piso duro = 90px/1920 (regla del dueño: el banner arranca a ≥90px para que el reloj/UI
    no lo tape); render_banner además re-clampa en píxeles reales. Default .048 (~92px)."""
    _floor = 0.048                      # ≈ 92px sobre 1920: cumple el "≥90px del borde superior"
    if not gemini_key:
        return _floor
    try:
        import cv2
        from google import genai
        from google.genai import types
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, 600)
        ok, fr = cap.read()
        cap.release()
        if not ok or fr is None:
            return _floor
        ok, buf = cv2.imencode(".jpg", fr)
        if not ok:
            return _floor
        prompt = ("Mira este frame vertical de un anuncio. Voy a poner un BANNER de oferta ARRIBA (2 líneas). "
                  "¿A qué fracción vertical (0.05 a 0.30, desde arriba) lo pongo para que NO tape la cara, el "
                  "producto ni texto importante? Prefiere lo más ARRIBA posible con espacio libre. "
                  "Responde SOLO el número (ej. 0.05).")
        # rápido por REST (thinkingBudget=0, ~2s por versión vs ~10s "pensando"); fallback SDK
        from . import gemini_fast
        texto = gemini_fast.generate(gemini_key, [prompt, (buf.tobytes(), "image/jpeg")])
        if not texto:
            resp = genai.Client(api_key=gemini_key).models.generate_content(
                model=_MODEL, contents=[prompt, types.Part.from_bytes(data=buf.tobytes(),
                                                                      mime_type="image/jpeg")])
            texto = resp.text or ""
        import re
        m = re.search(r"0?\.\d+", texto)
        if m:
            return max(_floor, min(0.30, float(m.group(0))))
    except Exception:  # noqa: BLE001
        pass
    return _floor


def add_offer_banner(video_path: str, out_path: str, work_dir: str, *,
                     line1: str = "ENVÍO GRATIS · PAGAS AL RECIBIR", line2: str = "OFERTA 2X1",
                     start: float = 0.0, dur: float = 0.0,
                     gemini_key: str | None = None) -> str:
    """Pone el banner arriba (en la y que la IA juzgó libre). Devuelve out_path o el original si falla.

    `start`>0: el banner APARECE en ese segundo (no desde el inicio → no choca con el gancho).
    `dur`>0: se queda visible `dur` segundos desde `start`; 0 = hasta el final."""
    try:
        info = probe(video_path)
        W, H = info.width, info.height
        y = safe_top_y(video_path, gemini_key)
        # PNG con nombre ÚNICO por salida: las versiones ahora se procesan EN PARALELO
        # (app._agregar_banner_oferta) y con un nombre fijo se pisaban entre sí.
        png = os.path.join(work_dir, os.path.basename(out_path) + ".banner.png")
        render_banner(W, H, y_frac=y, line1=line1, line2=line2).save(png)
        if start and start > 0:
            cond = (f"between(t,{float(start):.2f},{float(start) + float(dur):.2f})"
                    if dur and dur > 0 else f"gte(t,{float(start):.2f})")
            ov = f"[0:v][1:v]overlay=0:0:enable='{cond}'[v]"
        elif dur and dur > 0:
            ov = f"[0:v][1:v]overlay=0:0:enable='lt(t,{float(dur):.2f})'[v]"
        else:
            ov = "[0:v][1:v]overlay=0:0[v]"
        run(["ffmpeg", "-y", "-i", video_path, "-i", png,
             "-filter_complex", ov, "-map", "[v]", "-map", "0:a?",
             "-c:a", "copy", *venc(), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path])
        return out_path
    except Exception:  # noqa: BLE001
        return video_path


# ==================================================================== 🏆 MODO GANADOR
# Dos capas persistentes que exige el blueprint de ganadores:
#   - banner SUPERIOR = HOOK (autoridad/problema/curiosidad) en MAYÚSCULAS + etiqueta "OFERTA 2X1".
#   - banner INFERIOR = "¡ENVÍO GRATIS! · PAGAS AL RECIBIR · 2X1" naranja, en la safe zone de abajo.
# Ambos van TODO el video (overlay 0:0 sin enable). Motor PIL común con render_banner.


def render_hook_top(W: int, H: int, hook_text: str, y_frac: float = 0.045,
                    con_2x1: bool = True) -> Image.Image:
    """PNG full-frame: barra SÓLIDA oscura arriba con el HOOK (MAYÚSCULAS, bold, alto contraste,
    auto-ajustado a varias líneas) + pill naranja 'OFERTA 2X1' justo debajo.

    La barra sólida va en la safe zone superior: como es un fondo opaco no importa qué haya detrás,
    y al estar pegada arriba no tapa la cara/producto (que van al centro)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fp = _fontpath(True)
    hook = (hook_text or "").strip().upper() or "MÍRALO ANTES DE QUE SE AGOTE"

    margin_x = max(int(W * 0.045), safe_margin_x(W))     # laterales ≥64px (regla del dueño)
    max_w = W - 2 * margin_x
    size0 = int(H * 0.032)
    # piso legible del banner ≥44px (si no cabe, _fit parte en más líneas — nunca corta)
    font, lines, line_h, size = _fit(d, hook, fp, max_w, int(H * 0.22), size0,
                                     min_size=max(safe_px(H, SAFE_MIN_BANNER_PX), int(H * 0.020)))

    pad = max(int(size * 0.55), safe_px(H, SAFE_BANNER_PAD_PX))   # padding interno ≥24px
    bar_top = max(int(H * y_frac), safe_top_min(H))      # arranca a ≥90px del borde superior
    text_h = line_h * len(lines)
    bar_h = text_h + 2 * pad
    # barra sólida oscura (dorado/oscuro estilo BEE), full-width, alto contraste
    d.rectangle([0, bar_top, W, bar_top + bar_h], fill=(22, 19, 14, 236))
    stroke = max(2, size // 14)
    y = bar_top + pad
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text(((W - w) / 2, y), ln, font=font, fill=(255, 255, 255, 255),
               stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        y += line_h

    # pill naranja "OFERTA 2X1" centrada justo bajo la barra (opcional)
    if not con_2x1:
        return img
    tag = "OFERTA 2X1"
    ts = max(safe_px(H, SAFE_MIN_BANNER_PX), int(H * 0.030))     # banner ≥44px legible
    tf = ImageFont.truetype(fp, ts)
    tw = d.textlength(tag, font=tf)
    px = max(int(ts * 0.65), safe_px(H, SAFE_BANNER_PAD_PX))     # padding ≥24px
    py = max(int(ts * 0.34), safe_px(H, SAFE_BANNER_PAD_PX))
    tag_top = bar_top + bar_h + int(H * 0.008)
    x0 = (W - tw) / 2 - px
    x1 = (W + tw) / 2 + px
    d.rounded_rectangle([x0, tag_top, x1, tag_top + ts + 2 * py],
                        radius=int((ts + 2 * py) / 2), fill=_NARANJA)
    d.text(((W - tw) / 2, tag_top + py), tag, font=tf, fill=(255, 255, 255, 255))
    return img


def render_offer_bottom(W: int, H: int, y_frac: float = 0.72,
                        text: str | None = None, con_2x1: bool = True) -> Image.Image:
    """PNG full-frame: barra NARANJA alto contraste ABAJO, pero SIEMPRE por ENCIMA de la zona
    muerta inferior (regla del dueño: los últimos ~420px/22% los tapa el caption y los botones
    de TikTok/Reels → cero texto clave ahí; la base de la barra queda a y ≤ 1500/1920)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fp = _fontpath(True)
    if text is None:
        text = ("¡ENVÍO GRATIS!   ·   PAGAS AL RECIBIR   ·   2X1" if con_2x1
                else "¡ENVÍO GRATIS!   ·   PAGAS AL RECIBIR")
    txt = (text or "").strip().upper()

    margin_x = max(int(W * 0.04), safe_margin_x(W))      # laterales ≥64px
    max_w = W - 2 * margin_x
    size0 = int(H * 0.028)
    font, lines, line_h, size = _fit(d, txt, fp, max_w, int(H * 0.12), size0,
                                     min_size=max(safe_px(H, SAFE_MIN_BANNER_PX), int(H * 0.018)))

    pad = max(int(size * 0.5), safe_px(H, SAFE_BANNER_PAD_PX))   # padding interno ≥24px
    bar_h = line_h * len(lines) + 2 * pad
    limite = safe_bottom_limit(H)           # y máxima del texto clave (~78% del alto)
    bar_top = min(int(H * y_frac), limite - bar_h)
    bar_top = max(0, bar_top)
    d.rectangle([0, bar_top, W, bar_top + bar_h], fill=_NARANJA)
    stroke = max(2, size // 16)
    y = bar_top + pad
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text(((W - w) / 2, y), ln, font=font, fill=(255, 255, 255, 255),
               stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        y += line_h
    return img


def _overlay_full(video_path: str, png: str, out_path: str) -> str:
    """Overlay del PNG (full-frame) TODO el video. Devuelve out_path o el original si falla."""
    try:
        run(["ffmpeg", "-y", "-i", video_path, "-i", png,
             "-filter_complex", "[0:v][1:v]overlay=0:0[v]", "-map", "[v]", "-map", "0:a?",
             "-c:a", "copy", *venc(), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path])
        return out_path
    except Exception:  # noqa: BLE001
        return video_path


def add_hook_banner_top(video_path: str, out_path: str, work_dir: str, hook_text: str,
                        con_2x1: bool = True) -> str:
    """🏆 Banner SUPERIOR persistente = HOOK (MAYÚSCULAS) + 'OFERTA 2X1' (si con_2x1). Todo el video."""
    try:
        info = probe(video_path)
        png = os.path.join(work_dir, os.path.basename(out_path) + ".hook.png")
        render_hook_top(info.width, info.height, hook_text, con_2x1=con_2x1).save(png)
        return _overlay_full(video_path, png, out_path)
    except Exception:  # noqa: BLE001
        return video_path


def add_offer_banner_bottom(video_path: str, out_path: str, work_dir: str,
                            text: str | None = None, con_2x1: bool = True) -> str:
    """🏆 Banner INFERIOR persistente = envío gratis · pagas al recibir (· 2x1 si con_2x1), naranja."""
    try:
        info = probe(video_path)
        png = os.path.join(work_dir, os.path.basename(out_path) + ".oferta.png")
        render_offer_bottom(info.width, info.height, text=text, con_2x1=con_2x1).save(png)
        return _overlay_full(video_path, png, out_path)
    except Exception:  # noqa: BLE001
        return video_path
