"""Clasifica clips por FASE narrativa (problema / solución / funcionamiento / características / producto /
resultado) usando visión de Gemini — para que los "gifs" (WebM) de Cortar clips tengan SENTIDO.

Cómo: saca el frame del MEDIO de cada clip, los manda TODOS en UNA sola llamada a Gemini (numerados) y
recibe la fase de cada uno. Barato (1 llamada, frames chicos) y 100% opcional: si falla o no hay key,
devuelve None y el pipeline usa la heurística vieja (no rompe nada).
"""
from __future__ import annotations

import json
import re

import cv2

_MODEL = "gemini-2.5-flash"

# Fases canónicas (en orden de historia). El round-robin del orchestrator las intercala en este orden.
FASES = ["problema", "solucion", "funcionamiento", "producto", "caracteristicas", "resultado"]

_PROMPT = (
    "Te paso frames de clips cortos de videos de UN producto ({desc}). Clasifica CADA imagen, por número, "
    "en UNA de estas fases del anuncio:\n"
    "- problema: se ve el DOLOR o la situación molesta (la persona sufriendo la necesidad), el producto NO protagoniza\n"
    "- solucion: el producto EN ACCIÓN resolviendo el problema\n"
    "- funcionamiento: se ve CÓMO SE USA (manos manipulándolo, pasos, demostración)\n"
    "- producto: el producto presentado claro y protagonista (qué es)\n"
    "- caracteristicas: primer plano / detalle de partes, materiales, botones, texturas\n"
    "- resultado: el DESPUÉS — el resultado final, la persona feliz con el problema resuelto\n"
    "Si dudas entre dos, elige la que mejor cuenta la historia del anuncio. Responde SOLO un JSON array: "
    '[{{"i": 0, "fase": "problema"}}, ...] con TODAS las imágenes (índices 0..{last}).'
)


def _frame_medio(seg, max_w: int = 320) -> bytes | None:
    """Frame JPEG del punto medio del segmento (chico, para que la llamada sea liviana)."""
    try:
        cap = cv2.VideoCapture(seg.video)
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_POS_MSEC, (seg.start + seg.end) / 2.0 * 1000.0)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return None
        h, w = frame.shape[:2]
        if w > max_w:
            frame = cv2.resize(frame, (max_w, int(h * max_w / w)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None
    except Exception:  # noqa: BLE001
        return None


def clasificar(segments: list, api_key: str | None, product_desc: str = "") -> list[str] | None:
    """Devuelve la fase de cada segmento (lista alineada) o None si no se pudo (→ usar heurística)."""
    if not (api_key and segments):
        return None
    try:
        from google import genai
        from google.genai import types
        frames = [(i, _frame_medio(s)) for i, s in enumerate(segments)]
        con_frame = [(i, f) for i, f in frames if f]
        if len(con_frame) < max(3, len(segments) // 2):   # muy pocos frames legibles → mejor heurística
            return None
        contents: list = [_PROMPT.format(desc=product_desc or "producto", last=len(con_frame) - 1)]
        for k, (_, fb) in enumerate(con_frame):
            contents.append(f"IMAGEN {k}:")
            contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))
        resp = genai.Client(api_key=api_key).models.generate_content(model=_MODEL, contents=contents)
        m = re.search(r"\[.*\]", resp.text or "", re.DOTALL)
        if not m:
            return None
        por_k: dict[int, str] = {}
        for item in json.loads(m.group(0)):
            try:
                k, fase = int(item.get("i")), str(item.get("fase", "")).strip().lower()
            except (TypeError, ValueError):
                continue
            if fase in FASES:
                por_k[k] = fase
        if not por_k:
            return None
        # re-mapea del índice k (solo frames legibles) al índice real del segmento
        fases = ["producto"] * len(segments)           # default neutro para los que no se pudieron leer
        for k, (idx, _) in enumerate(con_frame):
            fases[idx] = por_k.get(k, "producto")
        return fases
    except Exception:  # noqa: BLE001
        return None
