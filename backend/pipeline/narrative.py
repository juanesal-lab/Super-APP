"""Análisis de la ESTRUCTURA NARRATIVA de un video publicitario con Gemini.

A diferencia de:
  - `analyze.py`   -> mide CALIDAD técnica (nitidez/luz/movimiento), sin IA.
  - `gemini_rank.py` -> rankea clips sueltos según si se ve el PRODUCTO.

este módulo entiende el video como un ANUNCIO con una estructura en el TIEMPO y
etiqueta cada tramo según su función narrativa:

    HOOK  ·  DOLOR  ·  SOLUCIÓN  ·  DESEO/RESULTADO  ·  CTA

Por cada tramo devuelve qué se VE (Gemini visión) y qué se DICE (Gemini transcribe
el audio del mismo video, sin Whisper: es multimodal), más una razón corta de por
qué le puso esa etiqueta (para poder auditar si la IA entendió la narrativa).

El JSON resultante es la base para que las siguientes estaciones (guion, música,
efectos, subtítulos) cuadren con cada momento del video.

Respeta la regla del proyecto: usa SOLO Gemini (no Anthropic). Reutiliza `probe`
de ffmpeg_utils y `_parse_array` de gemini_rank (mismo patrón que el resto).
"""
from __future__ import annotations

import os
import time
from typing import Callable

from .ffmpeg_utils import probe
from .gemini_rank import _parse_array  # reutilizado: extrae el array JSON de la respuesta

# Mismo modelo multimodal que usa el resto del pipeline
_MODEL = "gemini-2.5-flash"

# Las 5 etiquetas oficiales (en orden narrativo típico de un ad)
ETIQUETAS = ["HOOK", "DOLOR", "SOLUCIÓN", "DESEO/RESULTADO", "CTA"]

# Variantes que puede escupir el modelo -> etiqueta canónica
_ALIAS = {
    "HOOK": "HOOK", "GANCHO": "HOOK",
    "DOLOR": "DOLOR", "PROBLEMA": "DOLOR", "PAIN": "DOLOR",
    "SOLUCION": "SOLUCIÓN", "SOLUCIÓN": "SOLUCIÓN", "PRODUCTO": "SOLUCIÓN", "SOLUTION": "SOLUCIÓN",
    "DESEO": "DESEO/RESULTADO", "RESULTADO": "DESEO/RESULTADO",
    "DESEO/RESULTADO": "DESEO/RESULTADO", "TRANSFORMACION": "DESEO/RESULTADO",
    "TRANSFORMACIÓN": "DESEO/RESULTADO", "RESULT": "DESEO/RESULTADO",
    "CTA": "CTA", "CIERRE": "CTA", "LLAMADO": "CTA", "CALL TO ACTION": "CTA",
}

_UPLOAD_TIMEOUT = 120   # s máx esperando a que Gemini procese el video subido
_POLL_EVERY = 2         # s entre consultas de estado


# --- Helpers de timestamps (para que el orchestrator corte con FFmpeg) ---------

def mmss_to_seconds(ts) -> float:
    """Convierte un timestamp de texto a SEGUNDOS en float.

    Acepta "mm:ss" y también "hh:mm:ss" (por si aparecen videos de más de 1 hora),
    o solo segundos ("7"). Admite fracciones de segundo ("00:03.5" -> 3.5).

    Ejemplos:
        mmss_to_seconds("01:23")    -> 83.0
        mmss_to_seconds("00:05")    -> 5.0
        mmss_to_seconds("1:02:30")  -> 3750.0
        mmss_to_seconds("7")        -> 7.0
        mmss_to_seconds(12.5)       -> 12.5     (si ya es número, lo respeta)
        mmss_to_seconds("basura")   -> 0.0      (robusto: NO lanza excepción)

    Devuelve 0.0 ante cualquier formato inválido, para no tumbar el pipeline.
    """
    if ts is None:
        return 0.0
    # Si ya viene como número, lo devolvemos tal cual
    if isinstance(ts, (int, float)):
        return float(ts)

    partes = str(ts).strip().split(":")
    # mm:ss = 2 partes, hh:mm:ss = 3, solo segundos = 1. Más de 3 = formato raro.
    if not partes or len(partes) > 3:
        return 0.0
    try:
        total = 0.0
        # De derecha a izquierda: segundos (60^0), minutos (60^1), horas (60^2)
        for i, parte in enumerate(reversed(partes)):
            total += float(parte) * (60 ** i)
        return round(total, 3)
    except (ValueError, TypeError):
        return 0.0


def seconds_to_mmss(seconds, *, force_hours: bool = False) -> str:
    """Convierte SEGUNDOS (float/int) a un timestamp de texto (función inversa).

    Devuelve "mm:ss" normalmente, o "hh:mm:ss" si pasa de una hora (o si se fuerza
    con force_hours=True).

    Ejemplos:
        seconds_to_mmss(83)     -> "01:23"
        seconds_to_mmss(5)      -> "00:05"
        seconds_to_mmss(3750)   -> "01:02:30"
        seconds_to_mmss(-3)     -> "00:00"      (robusto: negativos/basura -> 00:00)

    Devuelve "00:00" ante cualquier valor inválido, para no tumbar el pipeline.
    """
    try:
        total = int(round(float(seconds)))
    except (ValueError, TypeError):
        return "00:00"
    if total < 0:
        total = 0
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h or force_hours:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _prompt(product_desc: str, duration: float) -> str:
    prod = product_desc.strip()
    contexto = (
        f'El producto anunciado es: "{prod}". ' if prod
        else "Identifica el producto principal que se anuncia. "
    )
    dur = f"{int(duration // 60):02d}:{int(duration % 60):02d}"
    return (
        "Eres un director creativo experto en anuncios de e-commerce (dropshipping). "
        + contexto +
        f"Te doy un video-anuncio que dura {dur} (mm:ss). Analízalo como una historia de venta "
        "y divídelo en TRAMOS CONSECUTIVOS (sin huecos ni solapamientos) que cubran TODO el video "
        "de principio a fin. A cada tramo asígnale UNA función narrativa, eligiendo SOLO entre "
        "estas etiquetas exactas:\n"
        "- HOOK: el gancho inicial, lo que frena el scroll en los primeros segundos.\n"
        "- DOLOR: se muestra o menciona el problema/la molestia que sufre la persona.\n"
        "- SOLUCIÓN: aparece el PRODUCTO resolviendo o entrando en acción.\n"
        "- DESEO/RESULTADO: la transformación, el resultado logrado, la persona feliz/satisfecha.\n"
        "- CTA: el llamado a la acción o cierre (comprar, pedir, oferta, urgencia).\n\n"
        "Devuelve SOLO un JSON válido (un array), sin texto extra, con esta forma EXACTA:\n"
        '[{"inicio":"00:00","fin":"00:03","etiqueta":"HOOK",'
        '"que_se_ve":"descripción visual de lo que se ve en pantalla",'
        '"que_se_dice":"transcripción literal de lo que se escucha en ese tramo",'
        '"por_que":"razón corta de por qué es esa etiqueta"}, ...]\n\n'
        "Reglas:\n"
        "- inicio y fin en formato mm:ss; el primer inicio es 00:00 y el último fin = la duración total.\n"
        "- que_se_dice: transcribe el audio REAL de ese tramo (en su idioma). Si no hay voz, pon \"\".\n"
        "- por_que: una frase breve, para poder revisar si entendiste bien la narrativa.\n"
        "- Puede repetirse una etiqueta si la narrativa la retoma, pero respeta el orden temporal."
    )


def _normalize_label(raw: str) -> str:
    """Lleva lo que devuelva el modelo a una de las 5 etiquetas canónicas."""
    key = (raw or "").strip().upper()
    if key in _ALIAS:
        return _ALIAS[key]
    # match parcial (por si viene con texto extra)
    for alias, canon in _ALIAS.items():
        if alias in key:
            return canon
    return key or "HOOK"


def _clean_segments(data: list[dict]) -> list[dict]:
    """Valida y ordena los segmentos que devolvió Gemini a nuestro formato final."""
    out: list[dict] = []
    for d in data:
        if not isinstance(d, dict):
            continue
        out.append({
            "inicio": str(d.get("inicio", "")).strip(),
            "fin": str(d.get("fin", "")).strip(),
            "etiqueta": _normalize_label(str(d.get("etiqueta", ""))),
            "que_se_ve": str(d.get("que_se_ve", "")).strip(),
            "que_se_dice": str(d.get("que_se_dice", "")).strip(),
            "por_que": str(d.get("por_que", "")).strip(),
        })
    return out


def _wait_active(client, file, progress) -> bool:
    """Espera a que el video subido pase a estado ACTIVE (Gemini lo procesa primero)."""
    waited = 0
    while waited < _UPLOAD_TIMEOUT:
        state = str(getattr(file, "state", "") or "")
        if "ACTIVE" in state:
            return True
        if "FAILED" in state:
            return False
        if progress:
            progress("Gemini está procesando el video...", 30)
        time.sleep(_POLL_EVERY)
        waited += _POLL_EVERY
        file = client.files.get(name=file.name)
    return "ACTIVE" in str(getattr(file, "state", "") or "")


def analyze_narrative(
    video_path: str,
    *,
    api_key: str | None = None,
    product_desc: str = "",
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Analiza un video-anuncio y devuelve sus tramos etiquetados por función narrativa.

    Retorna:
      {"ok": True, "duration": <s>, "segments": [ {inicio, fin, etiqueta,
        que_se_ve, que_se_dice, por_que}, ... ]}
      o  {"ok": False, "error": "..."} si algo falla (sin romper el resto del pipeline).
    """
    def report(msg, pct):
        if progress:
            progress(msg, pct)

    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {"ok": False, "error": "Falta la API key de Gemini (GEMINI_API_KEY)."}

    # Duración real del video (para acotar los timestamps en el prompt)
    try:
        info = probe(video_path)
        duration = info.duration
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"No se pudo leer el video: {e}"}

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"No se pudo iniciar Gemini: {e}"}

    uploaded = None
    try:
        # 1) Subir el video (el mismo archivo aporta imagen Y audio a Gemini)
        report("Subiendo el video a Gemini...", 10)
        uploaded = client.files.upload(file=video_path)

        # 2) Esperar a que Gemini termine de procesarlo
        if not _wait_active(client, uploaded, progress):
            return {"ok": False, "error": "Gemini no pudo procesar el video (timeout/failed)."}

        # 3) Pedir el análisis narrativo (visión + transcripción en una sola llamada)
        report("Analizando la estructura narrativa (visión + audio)...", 55)
        current = client.files.get(name=uploaded.name)  # con uri/estado ya ACTIVE
        resp = client.models.generate_content(
            model=_MODEL,
            contents=[current, _prompt(product_desc, duration)],
        )

        data = _parse_array(resp.text or "")
        if not data:
            return {"ok": False, "error": "Gemini no devolvió un JSON válido.",
                    "raw": (resp.text or "")[:500]}

        segments = _clean_segments(data)
        report("Listo", 100)
        return {"ok": True, "duration": round(duration, 2), "segments": segments}

    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Error analizando la narrativa: {e}"}
    finally:
        # Limpieza: borrar el archivo subido para no acumular en la cuenta
        if uploaded is not None:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass


# --- CLI de prueba: python -m backend.pipeline.narrative <video> [descripcion] ---
if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m backend.pipeline.narrative <video.mp4> [descripcion del producto]")
        raise SystemExit(1)

    video = sys.argv[1]
    desc = sys.argv[2] if len(sys.argv) > 2 else ""

    def _p(msg, pct):
        print(f"[{pct:3d}%] {msg}", file=sys.stderr)

    result = analyze_narrative(video, product_desc=desc, progress=_p)
    print(json.dumps(result, ensure_ascii=False, indent=2))
