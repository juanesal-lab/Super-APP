"""Agentes opcionales del Montador.

Cada agente es un módulo independiente que se activa con su checkbox en la UI:
  emoji.py             → emojis en los subtítulos karaoke (lista blanca Apple Color Emoji)
  endcard.py           → end-card CTA en los últimos 1.8s (precio + botón)
  hookbanner.py        → pill amarilla de beneficio sobre el hook
  momentos.py          → detector de mejores in-points antes de que Claude decida
  broll.py             → busca y baja b-rolls de stock (Pexels/Pixabay) para metáforas de la voz
  telegram_compress.py → comprime el video a <48MB para que quepa por el bot

Contrato: si un módulo no existe o truena al importar, el pipeline sigue como si
el agente estuviera apagado (se loguea y ya). Cargar SIEMPRE con cargar().
"""
import importlib

def cargar(nombre):
    """Devuelve el módulo del agente o None (jamás lanza excepción)."""
    try:
        return importlib.import_module(f"backend.agentes.{nombre}")
    except Exception:
        return None
