"""Errores de IA (Gemini/Claude) traducidos a mensajes HONESTOS y accionables.

Auditoría 2026-07-06: cuando la IA falla (429/cuota, key mala, bloqueo), varios flujos
tragaban el error y entregaban basura como "listo", o culpaban al usuario ("describe mejor
tu producto") cuando el problema era la cuota. Patrón copiado de
disruptive_images._error_amigable, compartido para todo el pipeline: siempre que un flujo
reporte un fallo de IA, debe decir QUÉ falló y QUÉ hacer, nombrando el MOTOR REAL.
"""
from __future__ import annotations

_CUOTA = ("429", "resource_exhausted", "resource exhausted", "quota", "exceeded",
          "rate limit", "rate_limit", "overloaded", "spend")
_KEY = ("api key", "api_key", "x-api-key", "unauthorized", "permission denied",
        "401", "403", "authentication", "invalid key")


def es_cuota(err) -> bool:
    """¿El error crudo es de cuota/créditos agotados? (NO es culpa del usuario ni del video)."""
    m = str(err or "").lower()
    return any(k in m for k in _CUOTA)


def error_amigable(err, motor: str = "Gemini") -> str:
    """Traduce el error crudo a algo accionable, nombrando el motor que falló de verdad."""
    m = str(err or "").lower()
    if motor == "Gemini" and ("spend" in m or "spending cap" in m):
        return "Se agotó el TOPE DE GASTO mensual de Google. Súbelo en ai.studio/spend y reintenta."
    if es_cuota(m):
        return f"{motor} está sin cuota/créditos ahora (429). Revisa la cuenta o reintenta más tarde."
    if any(k in m for k in _KEY):
        return f"Problema con la API key de {motor} (revísala en 🔑 Claves)."
    if "safety" in m or "blocked" in m or "prohibited" in m:
        return f"{motor} bloqueó el contenido por políticas. Ajusta el texto/producto y reintenta."
    if "timeout" in m or "timed out" in m or "deadline" in m:
        return f"{motor} tardó demasiado (timeout). Reintenta."
    base = str(err or "").strip()
    return f"{motor} falló: {base[:160]}" if base else f"{motor} no respondió (reintenta)."
