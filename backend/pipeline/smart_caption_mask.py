"""Tapado PRECISO de SOLO las captions (frame por frame, con IA que supervisa).

El camino viejo (Gemini analiza el video entero y estima cajas) ponía el blur en lugares
RANDOM — encima del producto, el volante, el tablero — porque los modelos de video localizan
mal en el espacio. Esto lo hace bien:

  1) EAST detecta el texto FRAME POR FRAME (localización exacta a nivel de píxel; solo donde
     REALMENTE hay una línea de texto horizontal — nunca en el volante/producto sin texto).
  2) Gemini CLASIFICA cada región detectada: ¿es una CAPTION promocional (texto sobrepuesto)
     o es parte de la escena (producto, tablero, cara, letrero, logo, placa)? → deja solo captions.
  3) Se DESENFOCA solo las captions confirmadas, ajustado y frame por frame.
  4) (opcional) Claude (capitán) revisa el resultado y puede reintentar.

Reusa el detector EAST de text_detect.py. Si no hay EAST o no hay Gemini, degrada con cabeza.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable

import cv2
import numpy as np

from . import text_detect as td
from .assemble import venc
from .ffmpeg_utils import run

_MODEL = "gemini-2.5-flash"
_MAX_REGIONS = 12   # tope de regiones a clasificar (contact sheet manejable)


def _cluster_regions(confirmed: dict) -> list[dict]:
    """Agrupa las cajas confirmadas de TODOS los frames en REGIONES estables (por IoU).

    Devuelve [{box:(x,y,w,h) unión, rep_frame:idx, count:N}], ordenado por count desc.
    """
    regions: list[dict] = []
    for fidx, boxes in sorted(confirmed.items()):
        for b in boxes:
            placed = False
            for r in regions:
                if td._iou(b, r["box"]) >= 0.25:
                    # unión de cajas (para cubrir todo lo que ocupó la caption)
                    x0 = min(r["box"][0], b[0]); y0 = min(r["box"][1], b[1])
                    x1 = max(r["box"][0] + r["box"][2], b[0] + b[2])
                    y1 = max(r["box"][1] + r["box"][3], b[1] + b[3])
                    r["box"] = (x0, y0, x1 - x0, y1 - y0)
                    r["count"] += 1
                    placed = True
                    break
            if not placed:
                regions.append({"box": b, "rep_frame": fidx, "count": 1})
    regions.sort(key=lambda r: r["count"], reverse=True)
    return regions[:_MAX_REGIONS]


def _context_crop(frame, box, W, H, pad=0.6):
    """Recorta la región con CONTEXTO alrededor (para que Gemini juzgue caption vs escena)."""
    x, y, w, h = box
    px, py = int(w * pad) + 24, int(h * pad) + 24
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(W, x + w + px), min(H, y + h + py)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    # normaliza a alto 160 para el contact sheet
    scale = 160.0 / max(1, crop.shape[0])
    return cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), 160))


def _classify_gemini(regions, frames, W, H, gemini_key) -> set[int]:
    """1 llamada a Gemini con un contact-sheet de las regiones -> índices que SON captions."""
    try:
        from google import genai
        from google.genai import types
    except Exception:  # noqa: BLE001
        return set(range(len(regions)))   # sin SDK: confía en EAST

    tiles, labels = [], []
    for idx, r in enumerate(regions):
        fr = frames.get(r["rep_frame"])
        if fr is None:
            continue
        crop = _context_crop(fr, r["box"], W, H)
        if crop is None:
            continue
        # etiqueta el número arriba-izquierda
        cv2.rectangle(crop, (0, 0), (34, 22), (0, 0, 0), -1)
        cv2.putText(crop, str(idx), (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        tiles.append(crop)
        labels.append(idx)
    if not tiles:
        return set()
    # apila los tiles en una columna (mismo ancho)
    maxw = max(t.shape[1] for t in tiles)
    padded = [cv2.copyMakeBorder(t, 6, 6, 0, maxw - t.shape[1], cv2.BORDER_CONSTANT, value=(40, 40, 40))
              for t in tiles]
    sheet = np.vstack(padded)
    ok, buf = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return set(labels)

    prompt = (
        "Cada recorte NUMERADO (con su contexto alrededor) es una zona de un frame de video. Marca "
        "caption=true si contiene TEXTO SOBREPUESTO LEGIBLE que el editor quemó encima del video: "
        "títulos, subtítulos, captions, hashtags, 'repost @...', marcas de agua de texto, ofertas, "
        "'link in bio', antes/después — CUALQUIER texto editorial.\n"
        "Marca caption=false si NO hay texto legible sobrepuesto, o si eso es en realidad: reflejos, "
        "ventanas, rejillas, estantería, partes del carro o del producto, tablero, placas de vehículo, "
        "o letreros FÍSICOS de la escena real filmada.\n"
        "Devuelve SOLO un JSON array: [{\"n\":0,\"caption\":true}, {\"n\":1,\"caption\":false}, ...]"
    )
    try:
        # rápido por REST (thinkingBudget=0, ~2s por corte vs ~5-15s "pensando"); fallback SDK
        from . import gemini_fast
        texto = gemini_fast.generate(gemini_key, [prompt, (buf.tobytes(), "image/jpeg")])
        if not texto:
            client = genai.Client(api_key=gemini_key)
            resp = client.models.generate_content(
                model=_MODEL,
                contents=[prompt, types.Part.from_bytes(data=buf.tobytes(), mime_type="image/jpeg")])
            texto = resp.text or ""
        m = re.search(r"\[.*\]", texto, re.DOTALL)
        data = json.loads(m.group(0)) if m else []
        keep = {int(d["n"]) for d in data if d.get("caption") is True}
        return keep
    except Exception:  # noqa: BLE001
        return set(labels)   # si Gemini falla, no borres todo: confía en EAST


def mask_captions_smart(in_path: str, out_path: str, *, gemini_key: str | None = None,
                        strength: str = "medio",
                        progress: Callable[[str, int], None] | None = None) -> str:
    """Tapa SOLO las captions (EAST localiza + Gemini clasifica). Devuelve out_path o in_path.
    `strength` (suave/medio/fuerte): intensidad del desenfoque (ajuste de Jack)."""
    def rep(m, p):
        if progress:
            progress(m, p)

    td._BLUR_STRENGTH = strength if strength in td._BLUR_LEVELS else "medio"
    if not td.available():
        return in_path
    net = td._load()
    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        return in_path
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    NF = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    # Pase 1: detectar (EAST) frame por frame; guarda cajas + algunos frames para clasificar.
    # EAST AFINADO: input más grande (640x1280) + umbral más bajo para captar TAMBIÉN captions
    # grandes-abajo y chicas (hashtags/disclaimers) que el default (320x640) se saltaba. Capta de
    # MÁS a propósito (incluye reflejos/estantería); Gemini descarta lo que no es caption después.
    # Los tamaños van POR PARÁMETRO a _detect (antes se mutaban globales → race entre hilos que hacía
    # perder captions y dejaba pasar el texto del proveedor).
    rep("Detectando texto (EAST) frame por frame...", 10)
    detections, frames, i = [], {}, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % td.DETECT_EVERY == 0:
            try:
                boxes = td._detect(net, frame, conf=0.5, min_wh=1.4,
                                   inw=640, inh=1280, min_h=0.013)
            except Exception:  # noqa: BLE001
                boxes = []
            detections.append((i, boxes))
            if boxes and len(frames) < 60:
                frames[i] = frame.copy()
        i += 1
    cap.release()

    confirmed = td._confirm(detections, td._MIN_DETECTIONS if len(detections) >= 3 else 1)
    if not confirmed:
        return in_path   # no hay texto real -> no toca nada

    # Clustear regiones + clasificar con Gemini (¿caption o escena/producto?)
    regions = _cluster_regions(confirmed)
    rep("Clasificando con IA: ¿caption o producto?...", 40)
    keep_idx = _classify_gemini(regions, frames, W, H, gemini_key) if gemini_key else set(range(len(regions)))
    caption_regions = [regions[i] for i in range(len(regions)) if i in keep_idx]
    if not caption_regions:
        # FAIL-SAFE (pedido de Angelo "sigue el problema del blur"): EAST SÍ vio texto persistente,
        # pero Gemini lo descartó TODO como escena/producto. Antes se devolvía el clip ORIGINAL con
        # el texto del proveedor visible. Ahora, si hay texto en la ZONA típica de captions (banda
        # inferior ~55%+ o superior ~18%), se tapa igual — mejor cubrir de más que dejar el texto ajeno.
        def _en_zona_caption(r) -> bool:
            x, y, w, h = r["box"]
            cy = (y + h / 2.0) / max(1, H)
            return cy >= 0.55 or cy <= 0.18
        caption_regions = [r for r in regions if _en_zona_caption(r)]
        if not caption_regions:
            return in_path   # texto solo en el centro (parte de la escena) -> no tapa nada

    # Marca por frame solo las cajas que caen en una región-caption confirmada
    cap_boxes = {}
    for fidx, boxes in confirmed.items():
        keep = [b for b in boxes if any(td._iou(b, r["box"]) >= 0.25 for r in caption_regions)]
        if keep:
            cap_boxes[fidx] = keep
    if not cap_boxes:
        return in_path

    # Pase 3: TAPAR SOLO las captions — MISMO endurecimiento que text_detect.mask_video:
    # bloques unidos (párrafo entero, no líneas sueltas) + tracking temporal (relleno de huecos =
    # sin parpadeo) + relleno ILEGIBLE (miniatura, no el gaussiano débil que dejaba letras leíbles).
    # Antes esta ruta (la que corre CON Gemini) tenía las 2 fallas que ya se arreglaron en la ruta EAST.
    rep("Tapando solo las captions...", 65)
    last_frame = (NF - 1) if NF > 0 else (max(cap_boxes) + td.DETECT_EVERY + td._PAD_FRAMES)
    tracks = td._track(cap_boxes, last_frame)     # une bloques + tramos continuos con colchón
    frame_boxes: dict[int, list[tuple]] = {}
    for t in tracks:
        for fi in range(t["start"], t["end"] + 1):
            frame_boxes.setdefault(fi, []).append(td._box_at(t, fi))

    cap = cv2.VideoCapture(in_path)
    tmp = out_path + ".noaudio.mp4"
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        for (x, y, w, h) in frame_boxes.get(i, []):
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(W, x + w), min(H, y + h)
            if x1 > x0 and y1 > y0:
                frame[y0:y1, x0:x1] = td._obscure(frame[y0:y1, x0:x1])
        writer.write(frame)
        i += 1
    writer.release()
    cap.release()

    # Re-mux con el audio original (GPU si hay)
    try:
        run(["ffmpeg", "-y", "-i", tmp, "-i", in_path, "-map", "0:v:0", "-map", "1:a:0?",
             *venc(), "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out_path])
        os.remove(tmp)
    except Exception:  # noqa: BLE001
        return tmp if os.path.exists(tmp) else in_path
    rep("Captions tapadas", 100)
    return out_path
