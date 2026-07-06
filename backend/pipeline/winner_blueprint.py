"""🏆 MODO GANADOR — carga el blueprint de creativos GANADORES y elige el HOOK del banner superior.

`blueprint_ganador.json` es la ingeniería inversa de los 2 creativos con VENTAS reales
(BEE VENOM ROAS 7.5, PLAGAS ROAS 9.3). Este módulo:
  - `load_blueprint()`  -> carga el JSON una vez (cacheado).
  - `elegir_hook(...)`  -> con Gemini flash elige/adapta UN hook de `blueprint.libreria_hooks`
                          según el producto; fallback a un hook genérico del blueprint si no hay
                          Gemini o si algo falla.

REGLAS DE ORO respetadas: NUNCA precio ni cifras de dinero en el hook; "2X1" / "ENVÍO GRATIS" /
"PAGAS AL RECIBIR" sí son texto permitido.
"""
from __future__ import annotations

import json
import os
import re

_BLUEPRINT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blueprint_ganador.json")
_CACHE: dict | None = None

# Hook de reserva (sin Gemini): curiosidad genérica, sin precio ni cifras de dinero.
_HOOK_FALLBACK = "MIRA POR QUÉ TODOS LO ESTÁN COMPRANDO"

# Cifras de dinero prohibidas en pantalla (regla de oro). "2x1" NO es dinero (se permite).
_MONEY = re.compile(r"(\$|cop|usd|pesos?|€|\d+\s*%|\bprecio\b|\d[\d.,]*\s*(mil|k|millon))", re.I)


def load_blueprint() -> dict:
    """Carga blueprint_ganador.json una sola vez (cacheado). Devuelve {} si no existe/rompe."""
    global _CACHE
    if _CACHE is None:
        try:
            with open(_BLUEPRINT_PATH, "r", encoding="utf-8") as f:
                _CACHE = json.load(f)
        except Exception:  # noqa: BLE001
            _CACHE = {}
    return _CACHE


def _hooks_texto(bp: dict) -> list[str]:
    """Aplana la librería de hooks a frases de TEXTO (excluye las notas 'shock_visual' que son
    instrucciones de cámara, no texto de banner, y la 'regla_de_oro')."""
    lib = (bp.get("libreria_hooks") or {})
    out: list[str] = []
    for cat, vals in lib.items():
        if cat in ("regla_de_oro", "shock_visual"):
            continue
        if isinstance(vals, list):
            out += [v for v in vals if isinstance(v, str)]
    return out


def _limpiar_hook(texto: str) -> str:
    """Deja UNA línea, en MAYÚSCULAS, sin comillas ni prefijos, sin cifras de dinero."""
    t = (texto or "").strip().splitlines()[0] if (texto or "").strip() else ""
    t = t.strip().strip('"').strip("'").strip("-•* ").strip()
    # quita prefijos tipo "Hook:" o "Respuesta:"
    t = re.sub(r"^\s*(hook|respuesta|opcion|opción)\s*[:\-]\s*", "", t, flags=re.I).strip()
    if not t:
        return ""
    if _MONEY.search(t):          # regla de oro: nunca cifras de dinero en el banner
        return ""
    return t.upper()


def elegir_hook(product_desc: str, gemini_key: str | None = None, angulo: str = "") -> str:
    """Elige/adapta el HOOK del banner superior a partir de product_desc + blueprint.libreria_hooks.

    1 llamada a Gemini flash (barata, thinkingBudget=0). Si no hay key o falla → hook de reserva
    del blueprint. SIEMPRE devuelve una línea en MAYÚSCULAS sin precio.
    """
    bp = load_blueprint()
    candidatos = _hooks_texto(bp)
    fallback = _limpiar_hook(candidatos[0]) if candidatos else "" or _HOOK_FALLBACK
    fallback = fallback or _HOOK_FALLBACK

    key = gemini_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    prod = (product_desc or "").strip()
    if not key or not prod:
        return fallback

    try:
        from . import gemini_fast
        lista = "\n".join(f"- {h}" for h in candidatos)
        ang = f"\nÁngulo del anuncio: {angulo}." if angulo else ""
        prompt = (
            "Eres experto en creativos de dropshipping que VENDEN (pago contra entrega, Colombia). "
            "Voy a poner un HOOK como banner ARRIBA del video, visible TODO el anuncio.\n"
            f"PRODUCTO: {prod}.{ang}\n\n"
            "Estos son los hooks GANADORES probados (elige el que mejor pegue y ADÁPTALO al producto, "
            "o crea uno del mismo estilo):\n"
            f"{lista}\n\n"
            "REGLAS ESTRICTAS:\n"
            "- Devuelve SOLO el hook, UNA sola línea, en MAYÚSCULAS.\n"
            "- Corto y contundente (máx ~9 palabras). Debe frenar el scroll en 1 segundo.\n"
            "- PROHIBIDO mencionar precio, cifras de dinero, %, ni descuentos con número.\n"
            "- Puedes usar pregunta de autoridad, problema directo o curiosidad.\n"
            "- Nada de comillas, ni prefijos, ni explicación. SOLO la frase."
        )
        texto = gemini_fast.generate(key, [prompt])
        hook = _limpiar_hook(texto or "")
        if hook and 2 <= len(hook.split()) <= 14:
            return hook
    except Exception:  # noqa: BLE001
        pass
    return fallback
