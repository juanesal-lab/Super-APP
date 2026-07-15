"""QA TÉCNICO automático de cada versión FINAL — el chequeo BARATO que ve Jack antes que nadie.

`video_ok()` (ffmpeg_utils) solo mira que el mp4 exista/pese/dure > 0.1s. Eso NO detecta los
defectos feos que igual matan un ad: frames negros a mitad, un clip congelado, silencios largos,
audio reventado (clipping) o casi mudo, o una duración que se fue de madre. Este módulo los caza
en UNA sola pasada de ffmpeg (blackdetect + freezedetect + silencedetect + volumedetect encadenados)
más un ffprobe para la salud de streams. Objetivo: < 3s por versión de 30s.

Filosofía (regla de oro de Jack): HONESTO y NO BLOQUEANTE. Si algo raro pasa con ffmpeg, se devuelve
ok=True (best-effort, nunca rompe el job). Los defectos se muestran como aviso, no frenan la entrega.
"""
from __future__ import annotations

import os
import re
import subprocess


# ── Umbrales (todo en un sitio para poder afinarlos sin cazar por el código) ──────────────
BLACK_MIN = 0.4        # frames negros: segmento >0.4s = defecto
FREEZE_MIN = 1.5       # congelado: >1.5s = defecto
FREEZE_ENDCARD_EXENTO = 1.8  # exime el último ~1.8s (ahí vive la end-card estática, congelada a propósito)
SILENCE_MIN = 2.0      # silencio en medio >2s = defecto (el arranque 0-0.3s es normal y ni se reporta)
SILENCE_ARRANQUE = 0.3
CLIP_MAX_DB = -0.1     # max_volume > -0.1 dB = clipping
MUDO_MEAN_DB = -35.0   # mean_volume < -35 dB = casi mudo
DUR_TOLERANCIA = 0.15  # desvío de duración > 15% respecto a la esperada
FPS_MIN, FPS_MAX = 10.0, 121.0


def _probe(path: str) -> dict:
    """ffprobe → dict con duración, dims, fps y si hay audio. Best-effort ({} si algo falla)."""
    try:
        import json
        cmd = ["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", path]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(out.stdout or "{}")
    except Exception:  # noqa: BLE001
        return {}
    v = None
    has_audio = False
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and v is None:
            v = s
        if s.get("codec_type") == "audio":
            has_audio = True
    dur = 0.0
    try:
        dur = float(data.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        dur = 0.0
    fps = 0.0
    w = h = 0
    if v is not None:
        raw = v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1"
        try:
            num, den = raw.split("/")
            fps = float(num) / float(den) if float(den) else 0.0
        except (ValueError, ZeroDivisionError):
            fps = 0.0
        try:
            w = int(v.get("width", 0)); h = int(v.get("height", 0))
        except (TypeError, ValueError):
            w = h = 0
        if dur <= 0:
            try:
                dur = float(v.get("duration", 0) or 0)
            except (TypeError, ValueError):
                pass
    return {"duration": dur, "width": w, "height": h, "fps": fps,
            "has_audio": has_audio, "has_video": v is not None}


def _num(m):
    """Convierte a float con cuidado (los grupos de regex pueden venir None)."""
    try:
        return float(m)
    except (TypeError, ValueError):
        return None


def revisar_version(path: str, dur_esperada: float | None = None) -> dict:
    """QA técnico de UNA versión final. Devuelve:
        {ok: bool, defectos: [{tipo, detalle, severidad}], metrica: {...}}
    ok=True cuando no hay defectos. NUNCA lanza: cualquier problema con ffmpeg → ok=True honesto
    (mejor no avisar que dar un falso defecto que asuste a Jack sin motivo)."""
    defectos: list[dict] = []
    metrica: dict = {}

    # Guarda mínima: si el archivo no existe/está vacío no hay nada que revisar (video_ok ya lo pilla).
    try:
        if not path or not os.path.exists(path) or os.path.getsize(path) < 1000:
            return {"ok": True, "defectos": [], "metrica": {"nota": "sin archivo"}}
    except Exception:  # noqa: BLE001
        return {"ok": True, "defectos": [], "metrica": {}}

    info = _probe(path)
    dur = float(info.get("duration") or 0.0)
    metrica.update({k: info.get(k) for k in
                    ("duration", "width", "height", "fps", "has_audio", "has_video")})

    # ── Salud de streams ──────────────────────────────────────────────────────────────────
    if info:
        if not info.get("has_video"):
            defectos.append({"tipo": "sin_video", "detalle": "no hay stream de video",
                             "severidad": "alta"})
        if not info.get("has_audio"):
            defectos.append({"tipo": "sin_audio", "detalle": "el video no tiene audio",
                             "severidad": "alta"})
        w, h = int(info.get("width") or 0), int(info.get("height") or 0)
        if w and h and (w % 2 or h % 2):
            defectos.append({"tipo": "dims_impares",
                             "detalle": f"dimensiones impares {w}x{h} (algunos players fallan)",
                             "severidad": "baja"})
        fps = float(info.get("fps") or 0.0)
        if fps and not (FPS_MIN <= fps <= FPS_MAX):
            defectos.append({"tipo": "fps_raro", "detalle": f"fps fuera de rango: {fps:.1f}",
                             "severidad": "baja"})

    # ── Duración esperada ─────────────────────────────────────────────────────────────────
    if dur_esperada and dur_esperada > 0 and dur > 0:
        desvio = abs(dur - dur_esperada) / dur_esperada
        if desvio > DUR_TOLERANCIA:
            defectos.append({
                "tipo": "duracion",
                "detalle": f"dura {dur:.1f}s y se esperaban ~{dur_esperada:.1f}s "
                           f"({desvio*100:.0f}% de desvío)",
                "severidad": "media"})

    # ── UNA pasada de ffmpeg: negros + congelado (video) + silencio + volumen (audio) ─────
    # Se escala a 320px de ancho SOLO para el análisis (más rápido; no afecta la detección).
    vf = (f"scale=320:-2,blackdetect=d={BLACK_MIN}:pix_th=0.10,"
          f"freezedetect=n=-60dB:d={FREEZE_MIN}")
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:v:0",
           "-vf", vf]
    has_audio = bool(info.get("has_audio"))
    if has_audio:
        af = f"silencedetect=n=-40dB:d={SILENCE_MIN},volumedetect"
        cmd += ["-map", "0:a:0", "-af", af]
    cmd += ["-f", "null", "-"]

    stderr = ""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        stderr = proc.stderr or ""
    except Exception:  # noqa: BLE001
        # ffmpeg raro/timeout → devolvemos lo que tengamos de probe, sin inventar defectos de A/V
        return {"ok": len(defectos) == 0, "defectos": defectos,
                "metrica": {**metrica, "nota": "análisis A/V no disponible"}}

    # Frames negros (blackdetect): "black_start:X black_end:Y black_duration:Z"
    negros = re.findall(r"black_start:([\d.]+)[^\n]*?black_duration:([\d.]+)", stderr)
    peor_negro = 0.0
    for _st, d in negros:
        d = _num(d) or 0.0
        peor_negro = max(peor_negro, d)
    metrica["n_negros"] = len(negros)
    if peor_negro >= BLACK_MIN:
        defectos.append({"tipo": "frames_negros",
                         "detalle": f"frames negros {peor_negro:.1f}s",
                         "severidad": "alta"})

    # Congelado (freezedetect): freeze_start / freeze_duration por bloques.
    starts = [_num(x) for x in re.findall(r"freeze_start:\s*([\d.]+)", stderr)]
    fdurs = [_num(x) for x in re.findall(r"freeze_duration:\s*([\d.]+)", stderr)]
    peor_freeze = 0.0
    n_freeze_real = 0
    for i, st in enumerate(starts):
        if st is None:
            continue
        d = fdurs[i] if i < len(fdurs) and fdurs[i] is not None else FREEZE_MIN
        # Exime la end-card: si el congelado ARRANCA dentro del último ~1.8s, es estática a propósito.
        if dur > 0 and st >= (dur - FREEZE_ENDCARD_EXENTO):
            continue
        n_freeze_real += 1
        peor_freeze = max(peor_freeze, d)
    metrica["n_congelados"] = n_freeze_real
    if peor_freeze >= FREEZE_MIN:
        defectos.append({"tipo": "congelado",
                         "detalle": f"imagen congelada {peor_freeze:.1f}s",
                         "severidad": "media"})

    # Silencio (silencedetect): "silence_start: X" ... "silence_end: Y | silence_duration: Z"
    if has_audio:
        sil = re.findall(r"silence_start:\s*(-?[\d.]+)", stderr)
        sil_dur = re.findall(r"silence_duration:\s*([\d.]+)", stderr)
        peor_sil = 0.0
        n_sil_real = 0
        for i, st in enumerate(sil):
            st_f = _num(st)
            d = _num(sil_dur[i]) if i < len(sil_dur) else None
            if d is None:
                d = SILENCE_MIN
            # el arranque (silencio que empieza en 0-0.3s) es normal; el resto en medio es defecto
            if st_f is not None and st_f <= SILENCE_ARRANQUE:
                continue
            if d >= SILENCE_MIN:
                n_sil_real += 1
                peor_sil = max(peor_sil, d)
        metrica["n_silencios"] = n_sil_real
        if peor_sil >= SILENCE_MIN:
            defectos.append({"tipo": "silencio",
                             "detalle": f"silencio de {peor_sil:.1f}s en medio",
                             "severidad": "media"})

        # Volumen (volumedetect): "max_volume: X dB" / "mean_volume: Y dB"
        mmax = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", stderr)
        mmean = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", stderr)
        max_db = _num(mmax.group(1)) if mmax else None
        mean_db = _num(mmean.group(1)) if mmean else None
        metrica["max_volume_db"] = max_db
        metrica["mean_volume_db"] = mean_db
        if max_db is not None and max_db > CLIP_MAX_DB:
            defectos.append({"tipo": "clipping",
                             "detalle": f"audio saturado (pico {max_db:.1f} dB)",
                             "severidad": "media"})
        if mean_db is not None and mean_db < MUDO_MEAN_DB:
            defectos.append({"tipo": "audio_bajo",
                             "detalle": f"audio casi mudo (promedio {mean_db:.1f} dB)",
                             "severidad": "alta"})

    return {"ok": len(defectos) == 0, "defectos": defectos, "metrica": metrica}


def resumen_defectos(qa: dict, max_items: int = 3) -> str:
    """Frase corta para el badge del front, ej. 'frames negros 2.1s · silencio de 3.0s'."""
    if not qa or qa.get("ok"):
        return ""
    partes = [d.get("detalle", d.get("tipo", "")) for d in (qa.get("defectos") or [])]
    partes = [p for p in partes if p]
    txt = " · ".join(partes[:max_items])
    if len(partes) > max_items:
        txt += f" (+{len(partes) - max_items})"
    return txt
