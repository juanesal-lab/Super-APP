"""QA AUTOMÁTICO de creativos — hace cumplir SOLO las reglas del dueño (CLAUDE.md §7 de Vidaria)
sin depender de que alguien se acuerde. Es el "portero" al final de los pipelines de video.

Verifica lo MEDIBLE por código (barato, determinista, $0):
  (a) FORMATO: resolución/aspecto EXACTO 9:16 (1080×1920, tolerancia mínima). Nada de 1:1 ni 4:5.
  (b) ZONAS SEGURAS: si el caller pasa coordenadas de texto (banners/subtítulos que puso el
      pipeline), valida que caigan en la franja segura — márgenes ≥64px, banner ≥90px del borde
      superior, subtítulos entre 55-78% de altura (nunca bajo y=1500), zona muerta inferior ~420px
      y derecha ~130px, tamaños mínimos (subtítulo ≥48px, banner ≥44px).
  (c) VISUAL (opcional, con Gemini visión): revisa 2-3 frames clave (arranque, medio, final) con un
      prompt-checklist de las reglas del dueño, simulando la UI de TikTok/Reels encima. Detecta lo
      que el código NO puede: texto cortado por el borde/caja de blur, texto ilegible, texto tapado
      por la UI. Máx 3 frames por video (control de costo). Si no hay key → se omite (no rompe).

Devuelve un dict con veredicto APROBADO/RECHAZADO + motivos. Los pipelines lo enganchan al final:
si RECHAZA, el job termina en estado "rechazado por QA" con los motivos (no se reporta "listo OK").

Uso rápido:
    from .qa_creativos import qa_video
    r = qa_video(ruta_mp4, gemini_key=key)          # con visión si hay key
    if not r["aprobado"]:
        # el pipeline marca el job como rechazado y muestra r["motivos"]
"""
from __future__ import annotations

import os
import subprocess

from .ffmpeg_utils import probe

# ── Constantes de zonas seguras (referencia 9:16 = 1080×1920), regla dura del dueño ──
# Reusan el mismo contrato que text_overlay.py (única fuente de verdad de las zonas).
try:
    from .text_overlay import (SAFE_REF_W, SAFE_REF_H, SAFE_SIDE_PX, SAFE_TOP_PX,
                               SAFE_TOP_ZONE, SAFE_BOTTOM_DEAD, SAFE_SUB_ZONE,
                               SAFE_MIN_SUB_PX, SAFE_MIN_BANNER_PX)
except Exception:  # noqa: BLE001 — fallback si cambia el import (mismos números)
    SAFE_REF_W, SAFE_REF_H = 1080, 1920
    SAFE_SIDE_PX, SAFE_TOP_PX = 64, 90
    SAFE_TOP_ZONE, SAFE_BOTTOM_DEAD = 0.12, 0.78125
    SAFE_SUB_ZONE = (0.55, 0.78125)
    SAFE_MIN_SUB_PX, SAFE_MIN_BANNER_PX = 48, 44

SAFE_RIGHT_DEAD_PX = 130       # columna de botones (like/compartir) tapa los últimos ~130px derecha
ASPECT_916 = 9 / 16            # 0.5625
ASPECT_TOL = 0.02              # tolerancia de aspecto (|w/h − 9/16| ≤ 0.02)


# ══════════════════════════════════ (a) FORMATO 9:16 ══════════════════════════════════

def check_formato(width: int, height: int) -> tuple[bool, list[str]]:
    """9:16 vertical EXACTO. Devuelve (ok, motivos)."""
    motivos: list[str] = []
    if not width or not height:
        return False, ["No pude leer la resolución del video."]
    ar = width / height
    if height <= width:
        motivos.append(f"El video NO es vertical ({width}×{height}). Regla: SOLO 9:16 vertical.")
    elif abs(ar - ASPECT_916) > ASPECT_TOL:
        cual = "1:1 (cuadrado)" if abs(ar - 1.0) < 0.05 else (
            "4:5" if abs(ar - 0.8) < 0.03 else f"{ar:.3f}")
        motivos.append(f"El aspecto es {cual}, no 9:16. Regla del dueño: todos, toditos, 9:16.")
    return (not motivos), motivos


# ══════════════════════════════ (b) ZONAS SEGURAS por coords ══════════════════════════════

def check_zonas_texto(width: int, height: int, textos: list[dict]) -> tuple[bool, list[str]]:
    """Valida cajas de texto que el pipeline colocó. Cada item:
        {"tipo": "banner"|"subtitulo"|"texto", "x":px, "y":px, "w":px, "h":px, "font_px": px}
    (x,y) = esquina sup-izq de la caja en píxeles reales del video. font_px opcional.
    Devuelve (ok, motivos). Lista vacía → no hay coords que validar → ok=True.
    """
    motivos: list[str] = []
    if not textos:
        return True, []
    side = round(SAFE_SIDE_PX * width / SAFE_REF_W)          # margen lateral en px reales
    top_min = round(SAFE_TOP_PX * height / SAFE_REF_H)       # y mínima del banner superior
    bottom_limit = int(height * SAFE_BOTTOM_DEAD)            # y máxima de texto clave
    right_dead = round(SAFE_RIGHT_DEAD_PX * width / SAFE_REF_W)
    right_limit = width - right_dead
    sub_lo, sub_hi = SAFE_SUB_ZONE
    for i, t in enumerate(textos):
        tipo = str(t.get("tipo", "texto"))
        x, y = int(t.get("x", 0)), int(t.get("y", 0))
        w, h = int(t.get("w", 0)), int(t.get("h", 0))
        x1, y1 = x + w, y + h
        etq = f"{tipo}#{i}"
        # márgenes laterales: ninguna letra toca el borde (≥64px)
        if x < side:
            motivos.append(f"{etq}: se sale por la IZQUIERDA (x={x}px < {side}px de margen seguro).")
        if x1 > width - side:
            motivos.append(f"{etq}: se sale por la DERECHA (x2={x1}px > {width - side}px).")
        # zona muerta derecha (botones de la plataforma)
        if tipo != "banner" and x1 > right_limit:
            motivos.append(f"{etq}: entra en la zona de botones derecha (x2={x1}px > {right_limit}px).")
        # tamaño mínimo legible
        fpx = int(t.get("font_px", 0) or 0)
        if fpx:
            piso = (SAFE_MIN_BANNER_PX if tipo == "banner" else SAFE_MIN_SUB_PX)
            piso_px = round(piso * height / SAFE_REF_H)
            if fpx < piso_px:
                motivos.append(f"{etq}: fuente {fpx}px demasiado chica (mín {piso_px}px legible).")
        # ubicación vertical por tipo
        if tipo == "banner":
            if y < top_min:
                motivos.append(f"{etq}: el banner arranca a y={y}px, muy pegado arriba "
                               f"(mín {top_min}px, la UI/reloj lo taparía).")
            if y1 > int(height * (SAFE_TOP_ZONE + 0.06)):   # margen para 2 líneas
                motivos.append(f"{etq}: el banner baja demasiado (y2={y1}px, debe vivir arriba).")
        elif tipo == "subtitulo":
            if y1 > bottom_limit:
                motivos.append(f"{etq}: subtítulo bajo la zona muerta inferior "
                               f"(y2={y1}px > {bottom_limit}px ≈ y=1500). La UI lo taparía.")
            if y < int(height * sub_lo) - 2:
                motivos.append(f"{etq}: subtítulo demasiado ALTO (y={y}px < {int(height*sub_lo)}px "
                               f"de la franja segura {int(sub_lo*100)}-{int(sub_hi*100)}%).")
        else:   # texto/clave genérico
            if y1 > bottom_limit:
                motivos.append(f"{etq}: texto clave en la zona muerta inferior (y2={y1}px > "
                               f"{bottom_limit}px).")
    return (not motivos), motivos


# ══════════════════════════════ (c) REVISIÓN VISUAL con Gemini ══════════════════════════════

_MODEL = "gemini-2.5-flash"
_MAX_FRAMES = 3   # tope DURO de frames por video enviados a visión (control de costo)

_PROMPT_QA = (
    "Eres un revisor de QA de creativos verticales (TikTok/Reels) para dropshipping. Te paso "
    "hasta 3 frames de UN video 9:16 (arranque, medio y final). Imagina la INTERFAZ de TikTok/Reels "
    "ENCIMA: caption y botones tapan los últimos ~22% de ABAJO, y una columna de botones tapa los "
    "~130px de la DERECHA; el reloj/UI ocupa arriba del todo.\n"
    "Revisa SOLO estas reglas del dueño y sé estricto:\n"
    "1) ¿Todo el TEXTO (banner de arriba, subtítulos, precios, CTA) se ve COMPLETO, sin cortarse "
    "por el borde de la imagen ni por la caja de desenfoque (blur)?\n"
    "2) ¿Ninguna palabra queda tapada por la UI de abajo o de la derecha?\n"
    "3) ¿El texto es LEGIBLE (tamaño suficiente, buen contraste)?\n"
    "4) Si hay una zona tapada con blur: ¿el texto viejo quedó 100% tapado y el blur se ve SUAVE "
    "(no cuadriculado/pixelado)?\n"
    "Responde SOLO un JSON: {\"aprobado\": true|false, \"motivos\": [\"...\"]}. "
    "Si todo cumple, aprobado=true y motivos=[]. Si algo falla, aprobado=false y explica corto "
    "cada falla en español."
)


def _extraer_frames(video_path: str, work_dir: str, n: int = _MAX_FRAMES) -> list[bytes]:
    """Saca n frames (arranque ~0.5s, medio, ~final) escalados chico (barato). Máx _MAX_FRAMES."""
    n = max(1, min(n, _MAX_FRAMES))
    try:
        dur = probe(video_path).duration or 0
    except Exception:  # noqa: BLE001
        dur = 0
    if dur <= 0:
        puntos = [0.5]
    elif n == 1:
        puntos = [dur / 2]
    else:
        # arranque, medio, casi-final (evita el negro del último frame)
        puntos = [min(0.5, dur * 0.05), dur * 0.5, max(0.0, dur - 0.4)][:n]
    frames: list[bytes] = []
    for k, t in enumerate(puntos):
        fj = os.path.join(work_dir, f"_qaframe_{k}.jpg")
        try:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", video_path,
                            "-frames:v", "1", "-vf", "scale=540:-2", fj],
                           capture_output=True, timeout=30)
            if os.path.exists(fj):
                with open(fj, "rb") as fh:
                    frames.append(fh.read())
        except Exception:  # noqa: BLE001
            pass
    return frames


def check_visual(video_path: str, gemini_key: str | None, work_dir: str | None = None
                 ) -> tuple[bool, list[str], bool]:
    """Revisión visual con Gemini de 2-3 frames. Devuelve (aprobado, motivos, corrió).
    `corrió`=False si no había key o no se pudo (entonces el veredicto visual NO cuenta)."""
    gemini_key = gemini_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not gemini_key:
        return True, [], False
    import tempfile
    wd = work_dir or tempfile.mkdtemp(prefix="qa_")
    os.makedirs(wd, exist_ok=True)
    frames = _extraer_frames(video_path, wd)
    if not frames:
        return True, [], False
    texto = ""
    try:
        from . import gemini_fast
        texto = gemini_fast.generate(
            gemini_key, [_PROMPT_QA] + [(fb, "image/jpeg") for fb in frames]) or ""
    except Exception:  # noqa: BLE001
        texto = ""
    if not texto:
        try:
            from google import genai
            from google.genai import types
            partes = [_PROMPT_QA] + [types.Part.from_bytes(data=fb, mime_type="image/jpeg")
                                     for fb in frames]
            resp = genai.Client(api_key=gemini_key).models.generate_content(
                model=_MODEL, contents=partes)
            texto = resp.text or ""
        except Exception:  # noqa: BLE001
            return True, [], False       # la IA no respondió → no bloqueamos por visión
    import json
    import re
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        return True, [], False
    try:
        data = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return True, [], False
    aprobado = bool(data.get("aprobado", True))
    motivos = [str(x) for x in (data.get("motivos") or []) if str(x).strip()]
    return aprobado, (motivos if not aprobado else []), True


# ══════════════════════════════════ ORQUESTADOR ══════════════════════════════════

def qa_video(video_path: str, *, textos: list[dict] | None = None,
             gemini_key: str | None = None, work_dir: str | None = None,
             con_vision: bool = True) -> dict:
    """QA completo de UN video. Devuelve:
        {"aprobado": bool, "motivos": [str], "checks": {formato, zonas, visual}, "resolucion": "WxH"}

    - `textos`: cajas de texto que el pipeline colocó (opcional) para validar zonas por coords.
    - `con_vision`: si False o sin key, se omite la revisión visual (solo formato + zonas).
    El veredicto final es APROBADO solo si TODOS los checks que corrieron aprueban.
    """
    motivos: list[str] = []
    checks: dict = {}
    if not video_path or not os.path.exists(video_path):
        return {"aprobado": False, "motivos": ["No encuentro el video para hacer QA."],
                "checks": {}, "resolucion": ""}

    # (a) formato
    try:
        info = probe(video_path)
        w, h = info.width, info.height
    except Exception as e:  # noqa: BLE001
        return {"aprobado": False, "motivos": [f"El video no se puede leer (¿corrupto?): {e}"],
                "checks": {"formato": False}, "resolucion": ""}
    ok_fmt, m_fmt = check_formato(w, h)
    checks["formato"] = ok_fmt
    motivos += m_fmt

    # (b) zonas seguras por coordenadas (si el caller las pasó)
    ok_zonas, m_zonas = check_zonas_texto(w, h, textos or [])
    checks["zonas"] = ok_zonas
    motivos += m_zonas

    # (c) visual (opcional)
    if con_vision:
        ok_vis, m_vis, corrio = check_visual(video_path, gemini_key, work_dir)
        checks["visual"] = (ok_vis if corrio else None)   # None = no corrió (sin key)
        if corrio:
            motivos += m_vis
    else:
        checks["visual"] = None

    aprobado = not motivos
    return {"aprobado": aprobado, "motivos": motivos, "checks": checks,
            "resolucion": f"{w}x{h}"}


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("Uso: python -m backend.pipeline.qa_creativos <video.mp4> [--sin-vision]")
        raise SystemExit(1)
    con_vis = "--sin-vision" not in sys.argv
    r = qa_video(sys.argv[1], con_vision=con_vis)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    raise SystemExit(0 if r["aprobado"] else 2)
