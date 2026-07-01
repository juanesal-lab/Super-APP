"""Generacion automatica del texto de gancho con Gemini.

Combina: descripcion del producto + contenido de la pagina (si se da el link) +
un frame del producto -> Gemini escribe un gancho corto e impactante en espanol.
"""
from __future__ import annotations

import os
import re
import urllib.request

import cv2

from .analyze import Segment

_MODEL = "gemini-2.5-flash"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def fetch_page_text(url: str, max_chars: int = 3000) -> str:
    """Descarga la pagina y extrae el texto util (titulo, meta, JSON-LD, cuerpo)."""
    url = (url or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        html = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
    except Exception:
        return ""

    parts: list[str] = []
    patterns = [
        r"<title[^>]*>(.*?)</title>",
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I | re.S)
        if m:
            parts.append(m.group(1))
    # JSON-LD (suele traer nombre/descripcion/precio del producto)
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.I | re.S):
        parts.append(block[:800])
    # Cuerpo sin etiquetas como respaldo
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body)
    parts.append(body[:1500])

    text = " ".join(p.strip() for p in parts if p and p.strip())
    return text[:max_chars]


def _frame_bytes(seg: Segment) -> bytes | None:
    cap = cv2.VideoCapture(seg.video)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, (seg.start + seg.end) / 2.0 * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    h, w = frame.shape[:2]
    if max(h, w) > 640:
        sc = 640.0 / max(h, w)
        frame = cv2.resize(frame, (int(w * sc), int(h * sc)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None


def generate_hook(api_key: str | None, product_desc: str = "",
                  page_text: str = "", sample_seg: Segment | None = None) -> str:
    """Devuelve un gancho corto e impactante, o '' si no se pudo."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return ""
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
    except Exception:
        return ""

    info = ""
    if product_desc.strip():
        info += f"\nProducto: {product_desc.strip()}"
    if page_text.strip():
        info += f"\nInfo de la pagina de venta: {page_text.strip()[:2500]}"

    prompt = (
        "Eres un copywriter experto en anuncios de dropshipping para LATAM (Colombia). "
        "Con base en el producto y su pagina (y el frame que te muestro), escribe UN solo "
        "gancho para el PRIMER segundo de un video de TikTok/Reels.\n"
        "Reglas: en espanol, IMPACTANTE (curiosidad, deseo, o problema->solucion), "
        "maximo 6 palabras, en MAYUSCULAS, sin comillas, sin hashtags, sin emojis. "
        "Que se entienda al instante y de ganas de seguir viendo.\n"
        "Devuelve SOLO el texto del gancho." + info
    )

    contents = [prompt]
    if sample_seg is not None:
        fb = _frame_bytes(sample_seg)
        if fb:
            contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))

    try:
        resp = client.models.generate_content(model=_MODEL, contents=contents)
        hook = (resp.text or "").strip().splitlines()[0] if resp.text else ""
        hook = hook.strip().strip('"').strip("'").strip()
        return hook[:50].upper()
    except Exception:
        return ""
