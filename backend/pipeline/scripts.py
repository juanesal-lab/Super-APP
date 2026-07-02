"""Generacion de guiones de voz en off con Gemini (varios angulos de venta)."""
from __future__ import annotations

import json
import os
import re

import cv2

from .analyze import Segment

_MODEL = "gemini-2.5-flash"

# CTA OBLIGATORIO: TODOS los copies/guiones deben CERRAR con esta frase EXACTA (pedido del dueño).
CTA_OBLIGATORIO = ("por tu compra hoy te regalamos el envío, y para tu seguridad ante estafas "
                   "pagas al recibir")


def _con_cta(texto: str) -> str:
    """Garantiza que el copy termine con el CTA EXACTO (lo añade si el modelo no lo puso igual)."""
    t = (texto or "").strip()
    if CTA_OBLIGATORIO.lower() in t.lower():
        return t
    sep = "" if (not t or t.endswith((".", "!", "?"))) else "."
    return (t + sep + " " + CTA_OBLIGATORIO.capitalize() + ".").strip()

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets")

# Fallback condensado (si no está el framework real de Juan en assets/)
_FRAMEWORK_FALLBACK = """METODOLOGIA: el hook (0-3s) frena el scroll; el producto aparece DESPUES
del gancho. Estructura: HOOK -> PROBLEMA -> MECANISMO (por que funciona) -> DEMO cruda ->
PRUEBA (ancla de precio) -> CTA con COD/escasez. Voz colombiana de pana real, no de vendedor.
Nunca des el precio solo: compáralo con algo más caro. CTA: "paga al recibir, antes de que se agote"."""


def _load_framework() -> str:
    """Carga el framework REAL de guiones de Juan (copiado de su skill viral-creative-coach)."""
    for name in ("guion-framework.md", "swipe-file-juan.md"):
        path = os.path.join(_ASSETS, name)
        if os.path.exists(path):
            try:
                return open(path, encoding="utf-8").read()
            except Exception:
                pass
    return _FRAMEWORK_FALLBACK


def _blueprint_text(blueprint: dict | None) -> str:
    """Formatea el arco narrativo de un ad de referencia (de narrative.py) para el prompt.

    Devuelve "" si no hay blueprint válido -> el guion se genera igual que siempre.
    """
    if not blueprint or not blueprint.get("ok") or not blueprint.get("segments"):
        return ""
    lines = []
    for s in blueprint["segments"]:
        et = s.get("etiqueta", "")
        ini, fin = s.get("inicio", ""), s.get("fin", "")
        dice = (s.get("que_se_dice") or "").strip()
        ve = (s.get("que_se_ve") or "").strip()
        parte = f"- [{et}] {ini}-{fin}"
        if dice:
            parte += f' · dice: "{dice[:160]}"'
        elif ve:
            parte += f" · se ve: {ve[:120]}"
        lines.append(parte)
    try:
        dur = int(float(blueprint.get("duration", 0)))
    except Exception:
        dur = 0
    return (
        "\n=== ESTRUCTURA DE UN ANUNCIO GANADOR DE REFERENCIA (CLÓNALA) ===\n"
        f"Este anuncio de ~{dur}s ya funciona. Copia su MISMO arco narrativo, el ORDEN de sus "
        "fases y su RITMO (cuánto dura cada fase). Adapta el mensaje al producto de Juan y usa "
        "SU voz, pero respeta esta estructura y estos tiempos:\n" + "\n".join(lines) +
        "\n=== FIN DE LA REFERENCIA ===\n"
    )


def _frame_bytes(seg: Segment) -> bytes | None:
    cap = cv2.VideoCapture(seg.video)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, (seg.start + seg.end) / 2.0 * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    h, w = frame.shape[:2]
    if max(h, w) > 640:
        sc = 640.0 / max(h, w)
        frame = cv2.resize(frame, (int(w * sc), int(h * sc)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None


def generate_scripts(api_key: str | None, product_desc: str = "", page_text: str = "",
                     target_seconds: float = 15.0, sample_seg: Segment | None = None,
                     n: int = 10, blueprint: dict | None = None,
                     oferta_2x1: bool = False) -> list[dict]:
    """Devuelve hasta n guiones: [{'angulo': str, 'texto': str}]. [] si falla.

    `blueprint`: opcional, el análisis narrativo (narrative.py) de un ANUNCIO GANADOR de
    referencia. Si viene, los guiones copian su arco (HOOK→DOLOR→SOLUCIÓN→DESEO→CTA) y ritmo.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return []
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
    except Exception:
        return []

    # ~2.3 palabras/seg en espanol a ritmo de ad
    max_words = max(12, int(target_seconds * 2.3))

    info = ""
    if product_desc.strip():
        info += f"\nProducto: {product_desc.strip()}"
    if page_text.strip():
        info += f"\nInfo de la pagina de venta: {page_text.strip()[:2500]}"

    framework = _load_framework()
    bp = _blueprint_text(blueprint)
    arco = ("Cada guion debe SEGUIR el arco narrativo del anuncio de referencia de arriba "
            "(mismas fases, mismo orden, ritmo parecido). " if bp else "")
    prompt = (
        "Eres el copywriter de Juan para ads de dropshipping (Colombia, COD). Escribes guiones "
        "de VOZ EN OFF que NO suenan a anuncio, usando SU voz real y SUS fórmulas ganadoras.\n\n"
        "=== BANCO REAL DE HOOKS, FÓRMULAS Y VOZ DE JUAN (úsalo, no inventes genérico) ===\n"
        + framework[:13000] +
        "\n=== FIN DEL BANCO ===\n"
        + bp +
        "\n"
        f"TAREA: escribe {n} guiones DISTINTOS para la voz en off de un video de TikTok/Reels de "
        f"~{int(target_seconds)} segundos. " + arco + "Cada uno usando una FÓRMULA o tipo de HOOK "
        "distinto del banco de arriba. OBLIGATORIO: pasa el test anti-anuncio (la 1ra frase es opinión/mala "
        "noticia/pregunta incómoda, NO el producto; el producto aparece DESPUÉS del gancho); usa la "
        "voz colombiana real de Juan (modismos: 'Y señores', 'Oiga', '¡Ojo!', 'Le tengo malas "
        "noticias', 'es físico y ya', 'No te voy a mentir', 'es extrañamente satisfactorio'); ancla "
        "de precio comparativa. "
        + ("OFERTA 2x1: integra de forma natural que al pedir uno se lleva OTRO GRATIS (2x1). "
           if oferta_2x1 else "")
        + f"OBLIGATORIO: TERMINA cada guion con esta frase EXACTA como cierre (cópiala igual, sin "
        f"cambiar ni una palabra): \"{CTA_OBLIGATORIO}\".\n"
        f"Cada guion: SOLO el VOICEOVER hablado completo y fluido, MÁXIMO {max_words} palabras, sin "
        "emojis, sin overlays ni acotaciones de escena, listo para narrar de corrido.\n"
        "Devuelve SOLO un JSON válido (array) con esta forma exacta:\n"
        '[{"angulo":"Fórmula sketch + ASMR","texto":"el voiceover hablado completo"}, ...]' + info
    )

    contents = [prompt]
    if sample_seg is not None:
        fb = _frame_bytes(sample_seg)
        if fb:
            contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))

    try:
        resp = client.models.generate_content(model=_MODEL, contents=contents)
        m = re.search(r"\[.*\]", resp.text or "", re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group(0))
    except Exception:
        return []

    out = []
    for d in data if isinstance(data, list) else []:
        if isinstance(d, dict) and d.get("texto"):
            out.append({"angulo": str(d.get("angulo", ""))[:40],
                        "texto": _con_cta(str(d["texto"]).strip()[:600])})  # cierre con CTA EXACTO
    return out[:n]


_DEFAULT_SFX = "cinematic transition whoosh with deep impact boom, punchy, professional sound design"


def suggest_sfx(api_key: str | None, product_desc: str = "") -> str:
    """La IA decide el sonido de transicion que encaja con el producto (en ingles, para ElevenLabs)."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key or not product_desc.strip():
        return _DEFAULT_SFX
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            f"Producto: {product_desc.strip()}. Para un video de ads (TikTok/Reels), describe "
            "UN efecto de sonido de TRANSICION entre cortes que suene PROFESIONAL y con cuerpo "
            "(no plano ni simple): un whoosh cinematografico con impacto/boom grave, punchy. "
            "Si encaja con el producto, incorpora su sonido (ej. agua a presion). "
            "Responde SOLO la descripcion en INGLES para un generador de SFX (8-15 palabras). "
            "Ej: 'cinematic water whoosh transition with deep bass impact, punchy and crisp'. Nada mas."
        )
        resp = client.models.generate_content(model=_MODEL, contents=prompt)
        txt = (resp.text or "").strip().strip('"').splitlines()[0][:120]
        return txt or _DEFAULT_SFX
    except Exception:
        return _DEFAULT_SFX


_DEFAULT_MUSIC = "upbeat modern background music for a product ad, light energetic beat, no vocals"


def suggest_music(api_key: str | None, product_desc: str = "") -> str:
    """La IA decide el estilo de musica de fondo para el ad (en ingles, para ElevenLabs Music)."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key or not product_desc.strip():
        return _DEFAULT_MUSIC
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            f"Producto: {product_desc.strip()}. Primero identifica el NICHO (ej. herramientas, "
            "salud/belleza, hogar, fitness, mascotas, cocina) y elige una musica de fondo que "
            "ENCAJE con ese nicho (herramientas->energica/industrial; salud-belleza->suave/inspiradora; "
            "fitness->electronica con fuerza; hogar->calida y limpia). "
            "Para un ad de TikTok/Reels: energica pero sutil, que NO tape la voz, SIN voces "
            "(instrumental). Responde SOLO la descripcion en INGLES (8-15 palabras) para un "
            "generador de musica. Termina con 'instrumental, no vocals'."
        )
        resp = client.models.generate_content(model=_MODEL, contents=prompt)
        txt = (resp.text or "").strip().strip('"').splitlines()[0][:140]
        return txt or _DEFAULT_MUSIC
    except Exception:
        return _DEFAULT_MUSIC
