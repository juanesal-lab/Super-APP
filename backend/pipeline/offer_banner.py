"""Banner de OFERTA arriba del creativo (opcional): 'ENVÍO GRATIS · PAGAS AL RECIBIR' + 'OFERTA 2X1'.

Lo pone ARRIBA, pero la IA elige una y-fracción donde NO tape nada importante (cara/producto/texto).
Estilo de la foto de Jack: pill roja arriba + segunda línea blanca con contorno. Fuente Poppins.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from .caption_styles import _fontpath
from .ffmpeg_utils import probe, run
from .assemble import venc

_ROJO = (226, 45, 44, 255)
_MODEL = "gemini-2.5-flash"


def render_banner(W: int, H: int, y_frac: float = 0.04,
                  line1: str = "ENVÍO GRATIS · PAGAS AL RECIBIR",
                  line2: str = "OFERTA 2X1") -> Image.Image:
    """PNG full-frame con el banner cerca del top (en y_frac). line2 opcional (vacío = sin 2ª línea)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fp = _fontpath(True)
    y = int(H * y_frac)

    line1 = (line1 or "").strip()
    if line1:
        s1 = max(18, int(H * 0.026))
        f1 = ImageFont.truetype(fp, s1)
        tw = d.textlength(line1, font=f1)
        padx, pady = int(s1 * 0.7), int(s1 * 0.45)
        x0 = (W - tw) / 2 - padx
        x1 = (W + tw) / 2 + padx
        d.rounded_rectangle([x0, y, x1, y + s1 + 2 * pady], radius=int((s1 + 2 * pady) / 2), fill=_ROJO)
        d.text(((W - tw) / 2, y + pady), line1, font=f1, fill=(255, 255, 255, 255))
        y += s1 + 2 * pady + int(H * 0.012)

    line2 = (line2 or "").strip()
    if line2:
        s2 = max(22, int(H * 0.036))
        f2 = ImageFont.truetype(fp, s2)
        tw2 = d.textlength(line2, font=f2)
        st = max(3, s2 // 7)
        d.text(((W - tw2) / 2, y), line2, font=f2, fill=(255, 255, 255, 255),
               stroke_width=st, stroke_fill=(0, 0, 0, 255))
    return img


def safe_top_y(video_path: str, gemini_key: str | None) -> float:
    """La IA elige una y-fracción (0.02-0.30) para el banner donde NO tape cara/producto/texto. Default .04."""
    if not gemini_key:
        return 0.04
    try:
        import cv2
        from google import genai
        from google.genai import types
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, 600)
        ok, fr = cap.read()
        cap.release()
        if not ok or fr is None:
            return 0.04
        ok, buf = cv2.imencode(".jpg", fr)
        if not ok:
            return 0.04
        prompt = ("Mira este frame vertical de un anuncio. Voy a poner un BANNER de oferta ARRIBA (2 líneas). "
                  "¿A qué fracción vertical (0.02 a 0.30, desde arriba) lo pongo para que NO tape la cara, el "
                  "producto ni texto importante? Prefiere lo más ARRIBA posible con espacio libre. "
                  "Responde SOLO el número (ej. 0.04).")
        resp = genai.Client(api_key=gemini_key).models.generate_content(
            model=_MODEL, contents=[prompt, types.Part.from_bytes(data=buf.tobytes(),
                                                                  mime_type="image/jpeg")])
        import re
        m = re.search(r"0?\.\d+", resp.text or "")
        if m:
            return max(0.02, min(0.30, float(m.group(0))))
    except Exception:  # noqa: BLE001
        pass
    return 0.04


def add_offer_banner(video_path: str, out_path: str, work_dir: str, *,
                     line1: str = "ENVÍO GRATIS · PAGAS AL RECIBIR", line2: str = "OFERTA 2X1",
                     gemini_key: str | None = None) -> str:
    """Pone el banner arriba (en la y que la IA juzgó libre). Devuelve out_path o el original si falla."""
    try:
        info = probe(video_path)
        W, H = info.width, info.height
        y = safe_top_y(video_path, gemini_key)
        png = os.path.join(work_dir, "offer_banner.png")
        render_banner(W, H, y_frac=y, line1=line1, line2=line2).save(png)
        run(["ffmpeg", "-y", "-i", video_path, "-i", png,
             "-filter_complex", "[0:v][1:v]overlay=0:0[v]", "-map", "[v]", "-map", "0:a?",
             "-c:a", "copy", *venc(), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path])
        return out_path
    except Exception:  # noqa: BLE001
        return video_path
