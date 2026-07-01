"""Capitán de control de calidad con Claude (Anthropic).

Revisa con VISIÓN la salida de una etapa del pipeline y decide si aprobar o mandar a
corregir. Es un "embudo de filtros": cada etapa pasa por el capitán y, si algo falla,
se reintenta con la corrección que Claude indica.

100% OPCIONAL: sin `ANTHROPIC_API_KEY` (en el entorno o en `.env`), `available()` da
False y la app funciona EXACTAMENTE igual que antes. Nunca rompe el flujo existente.

Primer filtro implementado: `revisar_blur` — el tapado de textos del proveedor
(`text_detect`). Es el caso de más valor: Claude mira ANTES/DESPUÉS y caza los falsos
positivos (blur sobre árboles/tela/producto) o el texto que quedó sin tapar.

Modelo: Claude Opus 4.8 (el mejor en visión y juicio).
"""
from __future__ import annotations

import base64
import os

import cv2
import numpy as np

_MODEL = "claude-opus-4-8"
_MAX_TOKENS = 1024
# `.env` en la raíz del repo (misma ruta que usa app.py para las otras keys)
_ENV_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")

_client = None


def _key() -> str | None:
    """Lee ANTHROPIC_API_KEY del entorno o del .env (igual que las demás keys de la app)."""
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k:
        return k.strip()
    if os.path.exists(_ENV_FILE):
        for line in open(_ENV_FILE):
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def available() -> bool:
    """True si hay API key: el capitán puede supervisar. Si no, la app sigue sin supervisión."""
    return bool(_key())


def _get_client():
    global _client
    if _client is None:
        key = _key()
        if not key:
            return None
        try:
            from anthropic import Anthropic
        except Exception:
            return None
        _client = Anthropic(api_key=key)
    return _client


# ─────────────────────────── utilidades de imagen ───────────────────────────

def _jpeg_b64(img) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.standard_b64encode(buf).decode()


def _frame_at(cap, idx):
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, idx))
    ok, frame = cap.read()
    return frame if ok else None


def _comparison_sheet(raw_path: str, masked_path: str, n: int = 3, cell_w: int = 460):
    """Arma UNA imagen con `n` filas [ANTES | DESPUÉS] de frames del mismo instante.

    Devuelve un ndarray BGR, o None si no se pudo leer. Se limita el lado largo a 2000 px
    para acotar el costo de visión (Claude escala a máx. 2576 px de todas formas).
    """
    capr, capm = cv2.VideoCapture(raw_path), cv2.VideoCapture(masked_path)
    total = int(capm.get(cv2.CAP_PROP_FRAME_COUNT)) or int(capr.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        capr.release(); capm.release(); return None
    idxs = [int(total * (k + 1) / (n + 1)) for k in range(n)]
    rows = []
    for i in idxs:
        fr, fm = _frame_at(capr, i), _frame_at(capm, i)
        if fr is None or fm is None:
            continue
        h = max(1, int(cell_w * fr.shape[0] / fr.shape[1]))
        fr = cv2.resize(fr, (cell_w, h))
        fm = cv2.resize(fm, (cell_w, h))
        sep = np.full((h, 8, 3), 255, np.uint8)
        rows.append(np.hstack([fr, sep, fm]))
    capr.release(); capm.release()
    if not rows:
        return None
    gap = np.full((12, rows[0].shape[1], 3), 255, np.uint8)
    sheet = rows[0]
    for r in rows[1:]:
        sheet = np.vstack([sheet, gap, r])
    long_edge = max(sheet.shape[:2])
    if long_edge > 2000:
        s = 2000 / long_edge
        sheet = cv2.resize(sheet, (int(sheet.shape[1] * s), int(sheet.shape[0] * s)))
    return sheet


# ─────────────────────────── filtro: tapado de textos ───────────────────────────

_SYS_BLUR = (
    "Eres el supervisor de calidad de una app que edita anuncios de dropshipping para "
    "Facebook/Instagram. Revisas el 'tapado de textos del proveedor': la app difumina "
    "(mosaico/blur) el texto sobrepuesto que trae el video original del proveedor "
    "(subtítulos, marcas de agua, precios, @usuarios) para que no salga en el anuncio.\n\n"
    "Te doy UNA imagen con varias filas. En cada fila: IZQUIERDA = el frame ORIGINAL, "
    "DERECHA = el mismo frame DESPUÉS del tapado. Compara ambos y evalúa el tapado.\n\n"
    "Busca DOS fallas:\n"
    "1) FALSOS POSITIVOS (lo más grave): en la derecha hay mosaico/blur sobre algo que en "
    "la izquierda claramente NO es texto sobrepuesto — el producto, una cara, o el fondo "
    "(árboles, cielo, pasto, arrugas de tela, bordes). Tapar eso ARRUINA el anuncio.\n"
    "2) TEXTO SIN TAPAR: en la derecha quedó visible texto del proveedor que debió taparse.\n\n"
    "OJO: el texto de marketing propio del anuncio (ganchos grandes, emojis) NO es texto del "
    "proveedor y NO debe taparse; si sigue visible, eso está bien. Sé estricto con los falsos "
    "positivos. Llama a la herramienta 'reportar_veredicto' con tu evaluación."
)

_TOOL_VEREDICTO = {
    "name": "reportar_veredicto",
    "description": "Reporta el veredicto de calidad del tapado de textos del proveedor.",
    "input_schema": {
        "type": "object",
        "properties": {
            "aprobado": {
                "type": "boolean",
                "description": "true si el tapado está bien (ni falsos positivos ni texto sin tapar).",
            },
            "falsos_positivos": {
                "type": "boolean",
                "description": "true si se difuminó algo que NO era texto del proveedor "
                               "(producto, cara, árboles, cielo, tela, fondo).",
            },
            "texto_sin_tapar": {
                "type": "boolean",
                "description": "true si quedó texto del proveedor visible sin difuminar.",
            },
            "detalle": {
                "type": "string",
                "description": "1-2 frases explicando qué viste (en español).",
            },
            "confianza": {
                "type": "number",
                "description": "Qué tan seguro estás, de 0.0 a 1.0.",
            },
        },
        "required": ["aprobado", "falsos_positivos", "texto_sin_tapar", "detalle", "confianza"],
    },
}


def revisar_blur(raw_path: str, masked_path: str) -> dict | None:
    """Pide a Claude que revise el tapado comparando ANTES/DESPUÉS.

    Devuelve el veredicto {aprobado, falsos_positivos, texto_sin_tapar, detalle, confianza}
    o None si no hay key / falla la API / no se pudo armar la comparación (degradación elegante).
    """
    client = _get_client()
    if client is None:
        return None
    sheet = _comparison_sheet(raw_path, masked_path)
    if sheet is None:
        return None
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": _jpeg_b64(sheet)}},
        {"type": "text", "text": "Revisa el tapado de textos de este corte y reporta el veredicto."},
    ]
    try:
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYS_BLUR,
            tools=[_TOOL_VEREDICTO],
            tool_choice={"type": "tool", "name": "reportar_veredicto"},
            messages=[{"role": "user", "content": content}],
        )
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Supervisor (blur) no disponible: {e}")
        return None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "reportar_veredicto":
            v = dict(block.input)
            # normaliza por si falta algún campo
            return {
                "aprobado": bool(v.get("aprobado", True)),
                "falsos_positivos": bool(v.get("falsos_positivos", False)),
                "texto_sin_tapar": bool(v.get("texto_sin_tapar", False)),
                "detalle": str(v.get("detalle", "")),
                "confianza": float(v.get("confianza", 0.0) or 0.0),
            }
    return None
