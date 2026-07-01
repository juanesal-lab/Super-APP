"""Efectos y música GUIADOS POR LA NARRATIVA (Fase 2 del blueprint).

Toma el blueprint que produce `narrative.py` (las fases HOOK/DOLOR/SOLUCIÓN/
DESEO-RESULTADO/CTA de un anuncio de REFERENCIA) y arma un PLAN de qué efecto
visual, qué sonido (SFX) y qué música va en cada fase del anuncio final.

Es el "cerebro": decide QUÉ va dónde. NO aplica los efectos ni toca `assemble.py`;
solo devuelve el plan para que el cableado (en `add_voiceover_and_sfx`, terreno de
Juan) lo use. Así queda auto-contenido y sin riesgo de chocar con su código.

⚠️ Clave (aviso de Juan): los tiempos del blueprint son del ad de REFERENCIA
(otra duración). El ad final de Juan tiene OTRO largo. Por eso NO usamos los mm:ss
crudos: normalizamos cada fase como FRACCIÓN de la duración del referente y la
multiplicamos por el `target_seconds` del ad final (ver `rescale_phases`).

Reutiliza `mmss_to_seconds` de narrative.py.
"""
from __future__ import annotations

import os
from typing import Callable

from .narrative import mmss_to_seconds

# Etiquetas canónicas (mismas que narrative.py + la estructura madre del blueprint)
_ETIQUETAS = ["HOOK", "DOLOR", "SOLUCIÓN", "PRUEBA", "DESEO/RESULTADO", "CTA"]

# Config por fase: efecto visual + sonido preferido + música + razón (para auditar).
# 'sfx_prefer' es una palabra que se busca en el nombre del archivo de SFX disponible.
_PHASE_CFG: dict[str, dict] = {
    "HOOK": {
        "efecto": {"zoom": "in_fuerte", "intensidad": "alta"},
        "sfx_prefer": "whoosh",
        "musica": {"estilo": "enganchante, energía media-alta, que frene el scroll", "energia": 0.7},
        "por_que": "HOOK: entra con impacto (whoosh + zoom de entrada) y música enganchante "
                   "para frenar el scroll en los primeros segundos.",
    },
    "DOLOR": {
        "efecto": {"zoom": "ninguno", "intensidad": "baja"},
        "sfx_prefer": None,   # sin golpe: el dolor no se celebra
        "musica": {"estilo": "baja y tensa, incómoda", "energia": 0.3},
        "por_que": "DOLOR: sin efectos agresivos; música baja y tensa para que se sienta el problema.",
    },
    "SOLUCIÓN": {
        "efecto": {"zoom": "punch_in", "intensidad": "alta"},
        "sfx_prefer": "impact",
        "musica": {"estilo": "que sube, esperanzadora (llega el producto)", "energia": 0.75},
        "por_que": "SOLUCIÓN: momento del producto → impacto (golpe + punch-in) y música que sube "
                   "para marcar que aparece la solución.",
    },
    "PRUEBA": {
        "efecto": {"zoom": "in_suave", "intensidad": "media"},
        "sfx_prefer": "swoosh",
        "musica": {"estilo": "creíble y positiva, que da confianza (reseñas/evidencia)", "energia": 0.6},
        "por_que": "PRUEBA: evidencia/reseñas → zoom suave para enfocar la prueba y música creíble "
                   "que refuerza la confianza, sin exagerar.",
    },
    "DESEO/RESULTADO": {
        "efecto": {"zoom": "in_suave", "intensidad": "media"},
        "sfx_prefer": "swoosh",
        "musica": {"estilo": "en clímax, positiva y aspiracional", "energia": 0.9},
        "por_que": "DESEO/RESULTADO: la transformación → zoom suave y música en clímax para vender "
                   "el resultado deseado.",
    },
    "CTA": {
        "efecto": {"zoom": "ninguno", "intensidad": "media"},
        "sfx_prefer": "whoosh",
        "musica": {"estilo": "cierre resolutivo con un toque de urgencia", "energia": 0.6},
        "por_que": "CTA: whoosh de cierre y música resolutiva que acompaña el llamado a la acción.",
    },
}

# Config de respaldo si llega una etiqueta rara (no debería, narrative.py ya normaliza)
_DEFAULT_CFG = {
    "efecto": {"zoom": "in_suave", "intensidad": "media"},
    "sfx_prefer": "whoosh",
    "musica": {"estilo": "neutra, media", "energia": 0.5},
    "por_que": "Etiqueta no reconocida: efecto y música neutros por defecto.",
}


def _reference_duration(blueprint: dict) -> float:
    """Duración del ad de referencia: usa 'duration' si viene; si no, el 'fin' del último tramo."""
    dur = float(blueprint.get("duration", 0) or 0)
    if dur > 0:
        return dur
    segs = blueprint.get("segments", [])
    if segs:
        return mmss_to_seconds(segs[-1].get("fin", "0"))
    return 0.0


def rescale_phases(blueprint: dict, target_seconds: float) -> list[dict]:
    """Reescala las fases del referente a la timeline del ad final (el paso que faltaba).

    Devuelve una lista de fases FUSIONADAS por etiqueta (tramos consecutivos con la
    misma etiqueta se unen), cada una con inicio/fin YA en segundos del ad final:
        [{"etiqueta": "HOOK", "inicio_s": 0.0, "fin_s": 1.43,
          "frac_inicio": 0.0, "frac_fin": 0.072}, ...]
    """
    ref = _reference_duration(blueprint)
    segs = blueprint.get("segments", [])
    if ref <= 0 or not segs or target_seconds <= 0:
        return []

    # 1) Fusionar tramos consecutivos con la misma etiqueta (una "fase" por beat narrativo)
    merged: list[dict] = []
    for s in segs:
        etq = str(s.get("etiqueta", "")).strip().upper()
        ini = mmss_to_seconds(s.get("inicio", "0"))
        fin = mmss_to_seconds(s.get("fin", "0"))
        if merged and merged[-1]["etiqueta"] == etq:
            merged[-1]["fin"] = fin           # extiende la fase anterior
        else:
            merged.append({"etiqueta": etq, "inicio": ini, "fin": fin})

    # 2) Convertir a fracción del referente y multiplicar por la duración del ad final
    phases: list[dict] = []
    for m in merged:
        frac_i = max(0.0, min(1.0, m["inicio"] / ref))
        frac_f = max(0.0, min(1.0, m["fin"] / ref))
        phases.append({
            "etiqueta": m["etiqueta"],
            "inicio_s": round(frac_i * target_seconds, 2),
            "fin_s": round(frac_f * target_seconds, 2),
            "frac_inicio": round(frac_i, 3),
            "frac_fin": round(frac_f, 3),
        })
    return phases


def _pick_sfx(sfx_paths: list[str], prefer: str | None) -> str | None:
    """Elige el SFX cuyo nombre contenga 'prefer'.

    Si 'prefer' es None -> la fase NO lleva SFX a propósito (ej. DOLOR, no se celebra).
    Si se pide un 'prefer' pero no hay match exacto -> cae al primero disponible.
    """
    if not sfx_paths or prefer is None:
        return None
    for p in sfx_paths:
        if prefer.lower() in os.path.basename(p).lower():
            return p
    return sfx_paths[0]


def phase_effect_plan(
    blueprint: dict,
    target_seconds: float,
    sfx_paths: list[str] | None = None,
    *,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Arma el PLAN de efectos + música por fase para el ad final.

    Entrada:
      - blueprint: dict que devuelve narrative.analyze_narrative (con 'segments' y 'duration').
      - target_seconds: duración del ad final de Juan (para reescalar los tiempos).
      - sfx_paths: lista de rutas de SFX disponibles (ej. assets/sfx/*.wav).

    Salida (dict):
      {"ok": True, "target_seconds": 20.0, "phases": [
          {"etiqueta","inicio_s","fin_s","efecto","sfx","musica","por_que"}, ...]}
      o {"ok": False, "error": "..."} si el blueprint no sirve (nunca lanza).
    """
    if progress:
        progress("Armando plan de efectos y música por fase...", 10)

    sfx_paths = [p for p in (sfx_paths or []) if p and os.path.exists(p)]
    phases = rescale_phases(blueprint, target_seconds)
    if not phases:
        return {"ok": False, "error": "Blueprint inválido o sin fases (revisa 'segments'/'duration')."}

    plan: list[dict] = []
    for ph in phases:
        cfg = _PHASE_CFG.get(ph["etiqueta"], _DEFAULT_CFG)
        plan.append({
            "etiqueta": ph["etiqueta"],
            "inicio_s": ph["inicio_s"],
            "fin_s": ph["fin_s"],
            "efecto": dict(cfg["efecto"]),                     # {zoom, intensidad}
            "sfx": _pick_sfx(sfx_paths, cfg["sfx_prefer"]),    # ruta del sonido (o None)
            "musica": dict(cfg["musica"]),                     # {estilo, energia}
            "por_que": cfg["por_que"],                         # para auditar congruencia
        })

    if progress:
        progress("Plan listo", 100)
    return {"ok": True, "target_seconds": round(float(target_seconds), 2), "phases": plan}


def phase_cut_times(plan: dict) -> list[float]:
    """Helper para el cableado: tiempos (s) donde arranca cada fase, para poner el SFX ahí.

    Directamente utilizable como `cut_times` de `assemble.add_voiceover_and_sfx`
    (esa función ya ignora los tiempos <= 0.2 s, así que el 0.0 del HOOK no molesta).
    """
    if not plan.get("ok"):
        return []
    return [p["inicio_s"] for p in plan["phases"]]


# --- CLI de prueba (sin gastar API): usa un blueprint de ejemplo embebido ----------
if __name__ == "__main__":
    import json

    # Blueprint de ejemplo (como el que sacó narrative.py de un ad real de 41.9s)
    ejemplo = {
        "ok": True,
        "duration": 41.9,
        "segments": [
            {"inicio": "00:00", "fin": "00:03", "etiqueta": "HOOK"},
            {"inicio": "00:03", "fin": "00:09", "etiqueta": "DOLOR"},
            {"inicio": "00:09", "fin": "00:15", "etiqueta": "SOLUCIÓN"},
            {"inicio": "00:15", "fin": "00:24", "etiqueta": "SOLUCIÓN"},   # consecutiva: se fusiona
            {"inicio": "00:24", "fin": "00:31", "etiqueta": "DESEO/RESULTADO"},
            {"inicio": "00:31", "fin": "00:39", "etiqueta": "DESEO/RESULTADO"},
            {"inicio": "00:39", "fin": "00:41", "etiqueta": "CTA"},
        ],
    }
    sfx = ["assets/sfx/whoosh.wav", "assets/sfx/impact.wav", "assets/sfx/swoosh.wav"]

    print("### Ad final de 20s (referente de 41.9s reescalado) ###")
    plan = phase_effect_plan(ejemplo, target_seconds=20.0, sfx_paths=sfx)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print("\ncut_times para add_voiceover_and_sfx:", phase_cut_times(plan))
