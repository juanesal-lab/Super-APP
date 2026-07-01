"""Detección PRECISA de texto fotograma por fotograma con EAST (OpenCV DNN).

Mucho más preciso que cajas de Gemini: detecta el texto justo donde está, en cada
frame, y lo tapa con desenfoque solo en esas cajas (sigue el caption sin tapar de más).
"""
from __future__ import annotations

import os

import cv2
import numpy as np

from .ffmpeg_utils import run

_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "models", "east.pb")
_LAYERS = ["feature_fusion/Conv_7/Sigmoid", "feature_fusion/concat_3"]

_net = None
_face = None
DETECT_EVERY = 4      # detecta cada N frames (reutiliza entre medio: el texto casi no se mueve)
_INW, _INH = 320, 640  # entrada de la red (múltiplos de 32, ratio vertical)
_CONF = 0.6           # confianza mínima (más alta = menos falsos positivos)
_MIN_H = 0.022        # alto mínimo del texto (fracción): descarta texto chico (envase/ruido)


def available() -> bool:
    return os.path.exists(_MODEL_PATH)


def _load():
    global _net
    if _net is None:
        _net = cv2.dnn.readNet(_MODEL_PATH)
    return _net


def _faces(frame):
    """Detecta caras (para NO taparlas aunque EAST se confunda)."""
    global _face
    if _face is None:
        _face = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return _face.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
    except Exception:
        return []


def _on_face(box, faces) -> bool:
    bx, by, bw, bh = box
    cx, cy = bx + bw / 2, by + bh / 2
    for (fx, fy, fw, fh) in faces:
        ex, ey = fx - fw * 0.12, fy - fh * 0.18
        ew, eh = fw * 1.24, fh * 1.36
        if ex <= cx <= ex + ew and ey <= cy <= ey + eh:
            return True
    return False


def _detect(net, frame, conf=_CONF) -> list[tuple]:
    """Devuelve cajas de texto (x,y,w,h) en pixeles del frame, sin caras ni texto chico."""
    H, W = frame.shape[:2]
    rW, rH = W / float(_INW), H / float(_INH)
    blob = cv2.dnn.blobFromImage(frame, 1.0, (_INW, _INH),
                                 (123.68, 116.78, 103.94), swapRB=True, crop=False)
    net.setInput(blob)
    scores, geo = net.forward(_LAYERS)
    nR, nC = scores.shape[2:4]
    rects, confs = [], []
    for y in range(nR):
        sc = scores[0, 0, y]
        x0, x1, x2, x3 = geo[0, 0, y], geo[0, 1, y], geo[0, 2, y], geo[0, 3, y]
        ang = geo[0, 4, y]
        for x in range(nC):
            if sc[x] < conf:
                continue
            ox, oy = x * 4.0, y * 4.0
            a = ang[x]; co, si = np.cos(a), np.sin(a)
            h = x0[x] + x2[x]; w = x1[x] + x3[x]
            ex = int(ox + co * x1[x] + si * x2[x])
            ey = int(oy - si * x1[x] + co * x2[x])
            rects.append((int((ex - w) * rW), int((ey - h) * rH), int(w * rW), int(h * rH)))
            confs.append(float(sc[x]))
    idx = cv2.dnn.NMSBoxes(rects, confs, conf, 0.4)
    faces = _faces(frame)
    boxes = []
    for i in (idx.flatten() if len(idx) else []):
        x, y, w, h = rects[i]
        if h < _MIN_H * H:            # texto muy chico (envase/ruido) -> ignorar
            continue
        if _on_face((x, y, w, h), faces):   # está sobre una cara -> no es caption
            continue
        # padding: un poco horizontal, más vertical (EAST recorta alto)
        px, py = int(w * 0.10) + 4, int(h * 0.35) + 6
        boxes.append((x - px, y - py, w + 2 * px, h + 2 * py))
    return _merge_lines(boxes, W)


def _merge_lines(boxes: list[tuple], W: int) -> list[tuple]:
    """Une cajas de la misma línea (y similar) en una sola, para tapar limpio."""
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: b[1])
    merged = []
    for b in boxes:
        x, y, w, h = b
        cy = y + h / 2
        placed = False
        for m in merged:
            mx, my, mw, mh = m
            mcy = my + mh / 2
            if abs(cy - mcy) < max(h, mh) * 0.6:   # misma línea
                nx = min(mx, x); ny = min(my, y)
                nx2 = max(mx + mw, x + w); ny2 = max(my + mh, y + h)
                m[0], m[1], m[2], m[3] = nx, ny, nx2 - nx, ny2 - ny
                placed = True
                break
        if not placed:
            merged.append([x, y, w, h])
    return [tuple(m) for m in merged]


def mask_video(in_path: str, out_path: str) -> str:
    """Tapa el texto detectado frame por frame y conserva el audio."""
    if not available():
        return in_path
    net = _load()
    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        return in_path
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    tmp = out_path + ".noaudio.mp4"
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))

    boxes, i = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % DETECT_EVERY == 0:
            try:
                boxes = _detect(net, frame)
            except Exception:
                boxes = []
        for (x, y, w, h) in boxes:
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(W, x + w), min(H, y + h)
            if x1 > x0 and y1 > y0:
                roi = frame[y0:y1, x0:x1]
                # mosaico (downscale+upscale) + blur -> tapa el texto por completo
                small = cv2.resize(roi, (max(1, (x1 - x0) // 14), max(1, (y1 - y0) // 14)),
                                   interpolation=cv2.INTER_LINEAR)
                roi = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
                frame[y0:y1, x0:x1] = cv2.GaussianBlur(roi, (0, 0), sigmaX=14)
        writer.write(frame)
        i += 1
    writer.release()
    cap.release()

    try:
        run(["ffmpeg", "-y", "-i", tmp, "-i", in_path,
             "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264", "-profile:v", "high",
             "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-c:a", "aac", "-shortest", out_path])
        os.remove(tmp)
    except Exception:
        os.replace(tmp, out_path)
    return out_path
