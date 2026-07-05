"""Llamada RÁPIDA a Gemini Flash por REST con thinkingBudget=0 (sin "pensamiento").

El SDK instalado (google-genai 0.8.0) no expone thinkingConfig y cada llamada de
clasificación simple tarda ~10-25s "pensando"; por REST con thinkingBudget=0 la MISMA
respuesta sale en ~2-5s (patrón ya probado en gemini_rank._call_rest_fast desde 2026-07).

Uso: generate(api_key, ["texto", (jpg_bytes, "image/jpeg"), ...]) -> texto o None.
Si devuelve None, el caller debe caer al SDK (camino viejo) — nunca romper.
"""
from __future__ import annotations

import base64
import json
import urllib.request

_MODEL = "gemini-2.5-flash"


def generate(api_key: str, parts: list, model: str = _MODEL, timeout: int = 75) -> str | None:
    """parts: lista de str (texto) y/o tuplas (bytes, mime_type) (imágenes).
    Devuelve el texto de la respuesta o None si algo falla (el caller usa el SDK)."""
    if not api_key or not parts:
        return None
    body_parts = []
    try:
        for p in parts:
            if isinstance(p, str):
                body_parts.append({"text": p})
            elif isinstance(p, (tuple, list)) and len(p) == 2 and isinstance(p[0], (bytes, bytearray)):
                body_parts.append({"inline_data": {
                    "mime_type": p[1], "data": base64.b64encode(bytes(p[0])).decode()}})
            else:
                return None       # parte desconocida: mejor el SDK
        body = {
            "contents": [{"parts": body_parts}],
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        # La key va por HEADER (no en la URL): no queda en logs/proxies ni en mensajes de error.
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "x-goog-api-key": api_key})
        resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        return resp["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:  # noqa: BLE001
        return None
