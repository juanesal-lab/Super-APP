"""Encuentra la BANDA EXACTA donde están los subtítulos quemados del original.

Híbrido (lo mejor de dos mundos, tras 20+ pruebas con videos reales):
  1) GEMINI confirma que hay un subtítulo CONSISTENTE (aparece en varios frames) y da la zona
     aproximada. Es semántico: distingue subtítulo de texto de escena (envases, letreros, UI).
     Si el texto sale en pocos frames -> NO es subtítulo -> no se tapa nada (evita blur en videos
     sin subtítulo o sobre etiquetas de producto).
  2) EAST afina la caja TIGHT dentro de esa zona (cajas ajustadas por línea) -> blur justo ahí.

Devuelve {x,y,w,h} en fracciones 0..1, o None si no hay subtítulo que tapar.
"""
from __future__ import annotations

import os
import statistics as st

import cv2
import numpy as np

from . import text_detect


def _pct(vals: list[float], p: float) -> float:
    return float(np.percentile(vals, p)) if vals else 0.0


def detect_subtitle_band(video_path: str, api_key: str | None = None,
                         min_frames: int = 3, east_frames: int = 24) -> dict | None:
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    # ---- 1) GEMINI: ¿hay subtítulo consistente? ¿en qué zona? -------------------
    try:
        from .caption_mask import detect_text_boxes_timed
        cajas = detect_text_boxes_timed(api_key, video_path)
    except Exception:  # noqa: BLE001
        cajas = []
    by_t: dict = {}
    for c in cajas:
        by_t.setdefault(round(c["t"], 1), []).append(c)
    if len(by_t) < min_frames:          # texto en pocos frames -> no es un subtítulo real
        return None
    tops = [min(c["y"] for c in cs) for cs in by_t.values()]
    bots = [max(c["y"] + c["h"] for c in cs) for cs in by_t.values()]
    cys = [st.median([c["y"] + c["h"] / 2 for c in cs]) for cs in by_t.values()]
    if st.median(cys) < 0.28:           # zona muy arriba -> es texto de escena/encabezado, no subtítulo
        return None
    zone_lo = max(0.0, _pct(tops, 20) - 0.04)     # zona aproximada del subtítulo (robusta a outliers)
    zone_hi = min(1.0, _pct(bots, 80) + 0.04)
    gemini_band = {"x": 0.04, "y": round(zone_lo, 4), "w": 0.92, "h": round(zone_hi - zone_lo, 4)}

    # ---- 2) EAST: afinar la caja TIGHT dentro de esa zona ----------------------
    try:
        if not text_detect.available():
            text_detect.ensure_model()
        net = text_detect._load() if text_detect.available() else None
    except Exception:  # noqa: BLE001
        net = None
    if net is None:
        return gemini_band

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1920
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1080
    dur = total / fps if fps else 0
    if dur <= 0:
        cap.release()
        return gemini_band

    rows = np.zeros(H, dtype=float)
    xs0: list[int] = []
    xs1: list[int] = []
    seen = 0
    for i in range(east_frames):
        cap.set(cv2.CAP_PROP_POS_MSEC, dur * (i + 0.5) / east_frames * 1000)
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        seen += 1
        for (x, y, w, h) in text_detect._detect(net, fr):
            cy = (y + h / 2) / H
            if cy < zone_lo - 0.02 or cy > zone_hi + 0.02:   # solo dentro de la zona del subtítulo
                continue
            rows[max(0, int(y)):min(H, int(y + h))] += 1
            xs0.append(max(0, int(x)))
            xs1.append(min(W, int(x + w)))
    cap.release()

    if seen == 0 or not xs0:
        return gemini_band
    thr = max(2.0, seen * 0.30)          # filas con texto en >=30% de los frames = banda del subtítulo
    hot = np.where(rows >= thr)[0]
    if len(hot) == 0:
        peak = rows.max()
        if peak >= 2:
            hot = np.where(rows >= peak * 0.5)[0]
    if len(hot) == 0:
        return gemini_band

    # Si la franja caliente es muy alta (escena con texto de producto debajo del subtítulo),
    # quedarse con el BLOQUE MÁS DENSO (= el subtítulo, que está en todos los frames) con tope de alto.
    lo, hi = int(hot.min()), int(hot.max())
    max_h = int(0.34 * H)
    if (hi - lo) > max_h:
        cs = np.cumsum(rows)
        best_y, best_s = lo, -1.0
        for yy in range(lo, hi - max_h + 2):
            s = cs[min(yy + max_h, H - 1)] - cs[yy]
            if s > best_s:
                best_s, best_y = s, yy
        lo, hi = best_y, best_y + max_h
    y0 = max(0.0, lo / H - 0.012)
    y1 = min(1.0, hi / H + 0.018)
    x0 = max(0.0, min(xs0) / W - 0.02)
    x1 = min(1.0, max(xs1) / W + 0.02)
    if (y1 - y0) < 0.02 or (x1 - x0) < 0.05:
        return gemini_band
    return {"x": round(float(x0), 4), "y": round(float(y0), 4),
            "w": round(float(x1 - x0), 4), "h": round(float(y1 - y0), 4)}


def detect_top_band(video_path: str, east_frames: int = 24, persist: float = 0.40) -> dict | None:
    """Banda de texto quemado pegado ARRIBA (títulos/captions en el top), que detect_subtitle_band
    ignora a propósito. EAST local (sin Gemini, rápido). Solo devuelve banda si el texto está en el
    top (cy<0.30) y es PERSISTENTE (>=persist de los frames) — así NO tapa texto de escena de una
    sola toma. Devuelve {x,y,w,h} en fracciones o None."""
    try:
        if not text_detect.available():
            text_detect.ensure_model()
        net = text_detect._load() if text_detect.available() else None
    except Exception:  # noqa: BLE001
        net = None
    if net is None:
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
    top_lo, top_hi = int(0.02 * H), int(0.30 * H)     # solo la franja de arriba
    rows = np.zeros(H, dtype=float)
    xs0: list[int] = []
    xs1: list[int] = []
    seen = 0
    for i in range(east_frames):
        cap.set(cv2.CAP_PROP_POS_MSEC, dur * (i + 0.5) / east_frames * 1000)
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        seen += 1
        for (x, y, w, h) in text_detect._detect(net, fr):
            cy = y + h / 2
            if cy < top_lo or cy > top_hi:
                continue
            rows[max(0, int(y)):min(H, int(y + h))] += 1
            xs0.append(max(0, int(x)))
            xs1.append(min(W, int(x + w)))
    cap.release()
    if seen == 0 or not xs0:
        return None
    thr = max(2.0, seen * persist)          # persistente = caption quemado, no texto de una toma
    hot = np.where(rows >= thr)[0]
    if len(hot) == 0:
        return None
    lo, hi = int(hot.min()), int(hot.max())
    max_h = int(0.22 * H)
    if (hi - lo) > max_h:
        hi = lo + max_h
    y0 = max(0.0, lo / H - 0.012)
    y1 = min(1.0, hi / H + 0.018)
    x0 = max(0.0, min(xs0) / W - 0.02)
    x1 = min(1.0, max(xs1) / W + 0.02)
    if (y1 - y0) < 0.02 or (x1 - x0) < 0.05:
        return None
    return {"x": round(float(x0), 4), "y": round(float(y0), 4),
            "w": round(float(x1 - x0), 4), "h": round(float(y1 - y0), 4)}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps({"bottom": detect_subtitle_band(sys.argv[1]),
                      "top": detect_top_band(sys.argv[1])}, ensure_ascii=False))
