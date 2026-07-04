"""Mezcla de audio PRO — reglas destiladas de 4 ads ganadores reales (2026-07-03).

Un agente midió (ebur128/RMS/onsets) y escuchó (Gemini 2.5 Pro) las referencias de Juan:
- Master a −18 LUFS (no −14): la sensación "pro" viene del RANGO dinámico, no del volumen.
- Música: UNA cama upbeat plana ~120BPM, SIN drops/risers, 12-15dB bajo la voz + ducking
  dinámico de 3-5dB cuando la voz habla; arranca al 100% en 0.0s y hace fade-out final 1.5s.
- SFX: presupuesto ~1 cada 1.8s (NO en cada corte: 40-60% de las transiciones), el 80-90%
  SUTILES (pico ~−8dBFS, se SIENTEN no se OYEN) y solo 1-2 "protagonistas" (+9-12dB) en los
  momentos de negocio (producto/oferta). El whoosh arranca ~150ms ANTES del corte para que
  su pico aterrice EN el corte. Nunca el mismo sample dos veces seguidas; jitter de ±1.5dB.

Este módulo SOLO arma el plan y la mezcla; el cableado vive en assemble/auto_studio.
"""
from __future__ import annotations

import os
import random
import subprocess

from .ffmpeg_utils import run

# --- Constantes de mezcla (números medidos en las referencias) ---------------------
LOUDNORM = "loudnorm=I=-18:TP=-1.5:LRA=8"     # regla 1: −18 LUFS, TP −1.5, LRA 7-9
MUSICA_VOL = 0.22          # ~−13dB bajo la voz (antes del ducking)
MUSICA_VOL_SIN_VOZ = 0.30  # sin voz en off la cama puede vivir un pelín más arriba
DUCK = "sidechaincompress=threshold=0.02:ratio=4:attack=25:release=400"  # −3..−5dB al hablar
SFX_DB_SUTIL = -14.0       # gain de un SFX normal respecto a la voz (se siente, no se oye)
SFX_DB_MEDIO = -9.0        # transiciones importantes
SFX_DB_PROTA = -2.0        # 1-2 por video: producto/oferta (el acento fuerte)
WHOOSH_PRE_MS = 150        # el whoosh arranca 150ms ANTES del corte
FADE_OUT_MUSICA = 1.5      # s de fade-out de la cama al final


def _dur_audio(path: str) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", path], capture_output=True, text=True, timeout=15)
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0


def _familia(nombre: str) -> str:
    n = os.path.basename(nombre).lower()
    if any(k in n for k in ("whoosh", "swoosh")):
        return "whoosh"
    if any(k in n for k in ("ding", "sparkle", "chime")):
        return "brillo"
    if any(k in n for k in ("boom", "impact", "bass")):
        return "golpe"
    if any(k in n for k in ("pop", "click")):
        return "pop"
    if "riser" in n:
        return "riser"
    return "otro"


def plan_sfx(cut_times: list[float], dur: float, sfx_paths: list[str],
             phases: list[dict] | None = None) -> list[dict]:
    """Arma el plan de SFX según las reglas destiladas. Devuelve [{t, path, db, pre_ms}].

    - Solo ~50% de los cortes llevan whoosh (alternados), sutiles, arrancando 150ms antes.
    - 1 SFX protagonista de "brillo" en el momento del producto (fase SOLUCIÓN si hay plan;
      si no, al ~35% de la duración) — el acento de negocio.
    - Un pop sutil al primer texto (0.2s) para el hot-start.
    - Presupuesto duro: ~1 SFX cada 1.8s (máx). En DOLOR no se celebra nada (sin SFX).
    """
    sfx_paths = [p for p in (sfx_paths or []) if p and os.path.exists(p)]
    if not sfx_paths or dur <= 1.0:
        return []
    por_familia: dict[str, list[str]] = {}
    for p in sfx_paths:
        por_familia.setdefault(_familia(p), []).append(p)
    whooshes = por_familia.get("whoosh") or sfx_paths
    brillos = por_familia.get("brillo") or por_familia.get("pop") or sfx_paths
    pops = por_familia.get("pop") or brillos

    presupuesto = max(3, int(dur / 1.8))
    eventos: list[dict] = []
    ultimo_sample = [None]

    def _pick(pool: list[str]) -> str:
        opciones = [p for p in pool if p != ultimo_sample[0]] or pool
        s = random.choice(opciones)
        ultimo_sample[0] = s
        return s

    def _jitter(db: float) -> float:
        return db + random.uniform(-1.5, 1.5)

    # rangos de DOLOR (ahí no se celebra: sin SFX) y momento del producto (SOLUCIÓN)
    dolor: list[tuple[float, float]] = []
    t_producto = dur * 0.35
    if phases:
        for ph in phases:
            etq = str(ph.get("etiqueta", "")).upper()
            if "DOLOR" in etq:
                dolor.append((float(ph.get("inicio_s", 0)), float(ph.get("fin_s", 0))))
            if "SOLUC" in etq:
                t_producto = float(ph.get("inicio_s", dur * 0.35))

    def _en_dolor(t: float) -> bool:
        return any(a <= t <= b for a, b in dolor)

    # 1) hot-start: pop/brillo sutil con el primer texto (regla 5)
    eventos.append({"t": 0.20, "path": _pick(pops), "db": _jitter(SFX_DB_SUTIL), "pre_ms": 0})

    # 2) protagonista: brillo en el momento del producto (regla 8)
    if 1.0 < t_producto < dur - 1.5:
        eventos.append({"t": t_producto, "path": _pick(brillos), "db": SFX_DB_PROTA, "pre_ms": 0})

    # 3) whooshes en ~la mitad de los cortes, sutiles/medios alternados, 150ms antes (reglas 6/9)
    cortes = [t for t in sorted(cut_times or []) if 0.6 < t < dur - 0.6 and not _en_dolor(t)]
    usar = cortes[::2] if len(cortes) > 3 else cortes          # ~50% de las transiciones
    for k, t in enumerate(usar):
        if abs(t - t_producto) < 0.7:                          # el protagonista ya cubre ese corte
            continue
        db = SFX_DB_MEDIO if (k % 3 == 0) else SFX_DB_SUTIL    # mayoría sutiles, algunos medios
        eventos.append({"t": t, "path": _pick(whooshes), "db": _jitter(db), "pre_ms": WHOOSH_PRE_MS})

    # 4) presupuesto duro (mediana real: 13 SFX en 23s): recorta lo menos importante
    eventos.sort(key=lambda e: e["t"])
    if len(eventos) > presupuesto:
        protas = [e for e in eventos if e["db"] >= SFX_DB_PROTA - 0.1]
        resto = [e for e in eventos if e not in protas]
        paso = max(1, len(resto) // max(1, presupuesto - len(protas)))
        eventos = sorted(protas + resto[::paso], key=lambda e: e["t"])[:presupuesto]
    return eventos


def filtros_mezcla(*, vo_label: str | None, clip_label: str | None, music_index: int | None,
                   sfx_eventos: list[dict], input_offset: int, dur_total: float,
                   con_voz: bool) -> tuple[list[str], list[str], list[str]]:
    """Construye los filtros FFmpeg de la mezcla pro. Devuelve (extra_inputs, filter_chains, mix_labels).

    - vo_label/clip_label: etiquetas ya declaradas por el llamador (ej. "[vo]", "[clip]").
    - music_index: índice de input de la música (ya agregado por el llamador) o None.
    - sfx_eventos: plan de plan_sfx(). Los inputs de SFX se agregan aquí (desde input_offset).
    - La música se agacha con sidechaincompress usando la voz (o el audio del clip) como llave.
    """
    extra_inputs: list[str] = []
    fc: list[str] = []
    mix: list[str] = []
    idx = input_offset

    llave = vo_label if con_voz else clip_label     # quién manda: la voz (o el audio del clip)
    if llave and music_index is not None:
        # split: una copia va a la mezcla, otra es la llave del ducking de la música
        base = llave.strip("[]")
        fc.append(f"{llave}asplit=2[{base}_mix][{base}_key]")
        mix.append(f"[{base}_mix]")
    elif llave:
        mix.append(llave)               # sin música no hay ducking: la llave va directo a la mezcla

    if music_index is not None:
        vol = MUSICA_VOL if con_voz else MUSICA_VOL_SIN_VOZ
        fade_st = max(0.0, dur_total - FADE_OUT_MUSICA)
        cadena = (f"[{music_index}:a]aloop=loop=-1:size=2000000000,volume={vol},"
                  f"afade=t=out:st={fade_st:.2f}:d={FADE_OUT_MUSICA}")
        if llave:
            base = llave.strip("[]")
            fc.append(cadena + "[mus0]")
            fc.append(f"[mus0][{base}_key]{DUCK}[mus]")         # la cama se agacha al hablar
        else:
            fc.append(cadena + "[mus]")
        mix.append("[mus]")

    for k, ev in enumerate(sfx_eventos):
        extra_inputs += ["-i", ev["path"]]
        ms = max(0, int(ev["t"] * 1000) - int(ev.get("pre_ms", 0)))
        fc.append(f"[{idx}:a]adelay={ms}|{ms},volume={ev['db']:.1f}dB[sfx{k}]")
        mix.append(f"[sfx{k}]")
        idx += 1

    return extra_inputs, fc, mix


def cadena_final(mix_labels: list[str]) -> str:
    """amix + loudnorm de una pasada → master −18 LUFS con la voz al frente."""
    return ("".join(mix_labels)
            + f"amix=inputs={len(mix_labels)}:normalize=0:duration=first,{LOUDNORM}[a]")
