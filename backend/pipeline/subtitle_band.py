"""Encuentra la BANDA EXACTA donde están los subtítulos quemados del original.

En vez de una caja gigante, detecta con EAST (cajas ajustadas por línea) en muchos frames
y se queda con la franja donde el texto aparece de forma CONSISTENTE (los subtítulos salen
casi siempre en el mismo sitio; el texto suelto de la escena, no). Devuelve una banda tight
{x,y,w,h} en fracciones 0..1 para taparla con blur SOLO ahí — nada de blur gigante.
"""
from __future__ import annotations

import cv2
import numpy as np

from . import text_detect


def detect_subtitle_band(video_path: str, max_frames: int = 26,
                         min_presence: float = 0.30) -> dict | None:
    """Banda tight de los subtítulos, o None si no hay una franja consistente.

    min_presence: fracción de frames muestreados en que una fila debe tener texto para
    contar como 'banda de subtítulos' (así descartamos texto esporádico de la escena)."""
    if not text_detect.available():
        text_detect.ensure_model()
    if not text_detect.available():
        return None
    try:
        net = text_detect._load()
    except Exception:  # noqa: BLE001
        return None

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1920
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1080
    dur = total / fps if fps else 0
    if dur <= 0:
        cap.release()
        return None

    times = [dur * (i + 0.5) / max_frames for i in range(max_frames)]
    rows = np.zeros(H, dtype=float)          # en cuántos frames hay texto en cada fila
    xs0: list[int] = []
    xs1: list[int] = []
    seen = 0
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        seen += 1
        for (x, y, w, h) in text_detect._detect(net, fr):
            cy = (y + h / 2) / H
            if cy < 0.45:                    # solo la zona baja (ahí van los subtítulos)
                continue
            if h > 0.26 * H:                 # demasiado alto para ser una línea -> descartar
                continue
            y0i, y1i = max(0, int(y)), min(H, int(y + h))
            rows[y0i:y1i] += 1
            xs0.append(max(0, int(x)))
            xs1.append(min(W, int(x + w)))
    cap.release()

    if seen == 0 or not xs0:
        return None

    thr = max(2.0, seen * min_presence)
    hot = np.where(rows >= thr)[0]
    if len(hot) == 0:                        # nada consistente: usar el pico como respaldo
        peak = rows.max()
        if peak < 2:
            return None
        hot = np.where(rows >= peak * 0.5)[0]
    if len(hot) == 0:
        return None

    y0 = max(0.0, hot.min() / H - 0.015)
    y1 = min(1.0, hot.max() / H + 0.02)
    x0 = max(0.0, min(xs0) / W - 0.02)
    x1 = min(1.0, max(xs1) / W + 0.02)
    if (y1 - y0) < 0.02 or (x1 - x0) < 0.05:
        return None
    return {"x": round(float(x0), 4), "y": round(float(y0), 4),
            "w": round(float(x1 - x0), 4), "h": round(float(y1 - y0), 4)}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(detect_subtitle_band(sys.argv[1]), ensure_ascii=False))
