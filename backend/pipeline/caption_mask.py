"""Detecta textos/captions quemados (que se MUEVEN) y devuelve cajas CON TIEMPO.

Muestrea varios frames a lo largo del video, le pide a Gemini las cajas del texto
sobrepuesto en cada uno, y devuelve (caja + momento) para taparlas justo donde y
CUANDO aparecen (los captions del proveedor suelen moverse palabra por palabra).
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import cv2

_MODEL = "gemini-2.5-flash"

_PROMPT = (
    "Mira esta imagen (frame de un video de producto). Detecta CUALQUIER texto, "
    "caption, subtitulo o watermark SOBREPUESTO/quemado por un editor encima del video "
    "(graficos anadidos), NO el texto real de la escena (envases, letreros del lugar, "
    "logos de ropa). Se PRECISO con la posicion. "
    "Devuelve SOLO un JSON array de cajas como fracciones 0..1 (esquina sup-izq): "
    '[{"x":0.1,"y":0.62,"w":0.8,"h":0.09}]. Si no hay texto sobrepuesto, []. '
    "Incluye TODA la altura de las letras en h."
)


def _clamp(v, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _sample_times(path: str, max_frames: int = 8) -> list[float]:
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    cap.release()
    dur = total / fps if fps else 0
    if dur <= 0:
        return [0.0]
    n = max(2, min(max_frames, int(dur / 1.2) + 1))
    return [dur * (i + 0.5) / n for i in range(n)]


def _frame_jpg(path: str, t: float) -> bytes | None:
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, fr = cap.read()
    cap.release()
    if not ok or fr is None:
        return None
    h, w = fr.shape[:2]
    if max(h, w) > 768:
        sc = 768.0 / max(h, w)
        fr = cv2.resize(fr, (int(w * sc), int(h * sc)))
    ok, buf = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None


def detect_text_boxes_timed(api_key: str | None, video_path: str,
                            pad_x: float = 0.04, pad_y: float = 0.07) -> list[dict]:
    """Devuelve [{'x','y','w','h','t'}] de los textos sobrepuestos en cada momento.
    Margen generoso (sobre todo vertical) para cubrir todo el texto aunque Gemini
    ubique la caja un poco corrida."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return []
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
    except Exception:
        return []

    times = _sample_times(video_path)

    def _detect(t):
        fb = _frame_jpg(video_path, t)
        if fb is None:
            return []
        try:
            resp = client.models.generate_content(
                model=_MODEL,
                contents=[_PROMPT, types.Part.from_bytes(data=fb, mime_type="image/jpeg")])
            m = re.search(r"\[.*\]", resp.text or "", re.DOTALL)
            if not m:
                return []
            out = []
            for b in json.loads(m.group(0)):
                if not isinstance(b, dict):
                    continue
                x = _clamp(b.get("x", 0) - pad_x)
                y = _clamp(b.get("y", 0) - pad_y)
                w = min(_clamp(b.get("w", 0) + pad_x * 2), 1 - x)
                h = min(_clamp(b.get("h", 0) + pad_y * 2), 1 - y)
                if w < 0.03 or h < 0.015:
                    continue
                out.append({"x": round(x, 4), "y": round(y, 4),
                            "w": round(w, 4), "h": round(h, 4), "t": round(t, 2)})
            return out
        except Exception:
            return []

    boxes: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(_detect, times):
            boxes.extend(res)
    return boxes[:40]
