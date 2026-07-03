"""Re-puntuacion inteligente de clips con Gemini, orientada a MOSTRAR EL PRODUCTO.

Eficiente en cuota: en lugar de una llamada por clip, arma UNA hoja de contactos
(todos los candidatos en una sola imagen numerada) y pide a Gemini que los califique
todos en una sola peticion. Asi un trabajo gasta ~1 request en vez de 30
(clave por el limite gratis de 20 requests/dia).

Gemini evalua por cada clip: si se ve el producto, si muestra como se usa/funciona,
y que tan vendedor es. Con eso reordenamos priorizando clips de producto.
Si no hay API key o falla, se conserva el score local sin romper el flujo.
"""
from __future__ import annotations

import json
import math
import os
import re

import cv2
import numpy as np

from .analyze import Segment

_MODEL = "gemini-2.5-flash"
_MAX_CANDIDATES = 24   # cuantos clips evalua Gemini por trabajo (1 sola imagen)
_CELL = 300            # px por celda de la hoja de contactos


def _prompt(product_desc: str, n: int) -> str:
    prod = product_desc.strip()
    contexto = (
        f"El producto que se anuncia es: \"{prod}\". " if prod
        else "Identifica el producto principal que se esta anunciando. "
    )
    return (
        "Eres un editor experto de video para landing pages de e-commerce (dropshipping). "
        + contexto +
        f"Te muestro una grilla con {n} fotogramas, cada uno numerado en su esquina (0 a {n-1}). "
        "Cada uno es un clip candidato. Evalua TODOS para una pagina de ventas.\n"
        "Devuelve SOLO un JSON valido (un array), sin texto extra, con esta forma:\n"
        '[{"i":0,"producto_visible":true,"muestra_uso":false,"venta":7,"etiqueta":"3-5 palabras"}, ...]\n'
        "Para CADA numero i de la grilla:\n"
        "- producto_visible: el PRODUCTO en si se ve claramente (no solo el resultado ni personas sueltas).\n"
        "- muestra_uso: se ve el producto EN ACCION, como se usa o como funciona.\n"
        "- venta: 0 a 10, que tan atractivo/vendedor es (nitidez, encuadre, deseo de compra).\n"
        "- etiqueta: descripcion corta de la escena.\n"
        "Prioriza alto los clips donde se ve el producto y como funciona."
    )


def _grab_frame(seg: Segment) -> np.ndarray | None:
    cap = cv2.VideoCapture(seg.video)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, (seg.start + seg.end) / 2.0 * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    return frame


def _cell_image(frame: np.ndarray, idx: int) -> np.ndarray:
    """Recorta a cuadrado, escala a _CELL y dibuja el numero de indice."""
    h, w = frame.shape[:2]
    m = min(h, w)
    y0, x0 = (h - m) // 2, (w - m) // 2
    sq = frame[y0:y0 + m, x0:x0 + m]
    cell = cv2.resize(sq, (_CELL, _CELL))
    # etiqueta con numero: rectangulo negro + texto blanco
    label = str(idx)
    cv2.rectangle(cell, (0, 0), (62, 46), (0, 0, 0), -1)
    cv2.putText(cell, label, (8, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    return cell


def _contact_sheet(segments: list[Segment]):
    """Devuelve (jpg_bytes, lista_de_segmentos_en_orden) o (None, [])."""
    cells, used_segs = [], []
    for seg in segments:
        frame = _grab_frame(seg)
        if frame is None:
            continue
        cells.append(_cell_image(frame, len(used_segs)))
        used_segs.append(seg)
    if not cells:
        return None, []

    n = len(cells)
    cols = min(5, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / cols)
    sheet = np.zeros((rows * _CELL, cols * _CELL, 3), dtype=np.uint8)
    for k, cell in enumerate(cells):
        r, c = divmod(k, cols)
        sheet[r * _CELL:(r + 1) * _CELL, c * _CELL:(c + 1) * _CELL] = cell

    ok, buf = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        return None, []
    return buf.tobytes(), used_segs


def _parse_array(text: str) -> list[dict] | None:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def _call_rest_fast(api_key: str, prompt: str, sheet: bytes) -> str | None:
    """Llamada REST directa con thinkingBudget=0 (sin 'pensamiento'): la MISMA respuesta
    en ~3s en vez de ~25s. El SDK instalado (google-genai 0.8.0) no expone ese parametro,
    por eso va por REST. Si algo falla devuelve None y el caller usa el SDK (camino viejo)."""
    import base64
    import urllib.request
    body = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/jpeg",
                             "data": base64.b64encode(sheet).decode()}},
        ]}],
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent"
    # La key va por HEADER (no en la URL) para que no quede en logs/proxies ni en mensajes de error.
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "x-goog-api-key": api_key})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=75).read())
        return resp["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:  # noqa: BLE001
        return None


def rank_with_gemini(segments: list[Segment], api_key: str | None = None,
                     product_desc: str = "", max_candidates: int = _MAX_CANDIDATES
                     ) -> tuple[list[Segment], bool]:
    """Devuelve (segmentos con score combinado orientado a producto, usado_gemini)."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return segments, False

    candidates = sorted(segments, key=lambda s: s.local_score, reverse=True)[:max_candidates]
    sheet, ordered = _contact_sheet(candidates)
    if sheet is None:
        return segments, False

    # 1) Camino RAPIDO: REST sin thinking (~3s). 2) Fallback: SDK como siempre (~25s).
    data = None
    text = _call_rest_fast(api_key, _prompt(product_desc, len(ordered)), sheet)
    if text:
        data = _parse_array(text)
    if not data:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model=_MODEL,
                contents=[
                    _prompt(product_desc, len(ordered)),
                    types.Part.from_bytes(data=sheet, mime_type="image/jpeg"),
                ],
            )
            data = _parse_array(resp.text or "")
        except Exception:
            return segments, False

    if not data:
        return segments, False

    by_idx = {int(d["i"]): d for d in data if isinstance(d, dict) and "i" in d}
    for idx, seg in enumerate(ordered):
        d = by_idx.get(idx)
        if not d:
            continue
        venta = max(0.0, min(10.0, float(d.get("venta", 5)))) * 10.0  # 0..100
        seg.product_visible = bool(d.get("producto_visible", False))
        seg.shows_use = bool(d.get("muestra_uso", False))
        seg.tag = str(d.get("etiqueta", ""))[:60]
        base = 0.4 * seg.local_score + 0.6 * venta
        bonus = (18 if seg.product_visible else 0) + (22 if seg.shows_use else 0)
        penalty = 0 if seg.product_visible else 25
        seg.score = round(max(0.0, min(120.0, base + bonus - penalty)), 1)

    return segments, True
