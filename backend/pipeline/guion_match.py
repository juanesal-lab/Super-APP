"""Montaje GUIADO POR EL GUION — "primero se crea el guion y después se edita" (Juan, 2026-07-03).

El sistema mira TODOS los clips (ya clasificados por fase visual con phase_classify) y el guion
frase a frase (tiempos por palabra de ElevenLabs): para cada FRASE de la voz elige el clip que
mejor ILUSTRA lo que se está diciendo en ese momento, y el corte cae en el límite de frase.
Es la regla #18 de las referencias ganadoras (assets/edicion-pro-reglas.md): el montaje lo
gobierna la VOZ, no la música ni el azar.

Salida compatible con assemble.build_variations: (orden de índices, tope de duración por slot).
Si algo falla (sin timings, sin fases), el caller cae al plan clásico — nunca rompe.
"""
from __future__ import annotations

import json
import re
from typing import Sequence

from .phase_classify import FASES

# Pausa entre palabras que corta frase aunque no haya puntuación (respiro del locutor)
_PAUSA_FRASE = 0.35
# Una frase muy larga se parte (el plano aguantaría >2 slots y el ritmo se muere)
_FRASE_MAX_S = 4.8
_SLOT_MIN = 0.45          # ningún plano útil por debajo (regla de las referencias)

# Si no hay clip de la fase pedida, se acepta la más cercana en SIGNIFICADO (en este orden)
_PREFERENCIA: dict[str, list[str]] = {
    "problema": ["problema", "resultado", "solucion", "funcionamiento", "producto", "caracteristicas"],
    "solucion": ["solucion", "funcionamiento", "producto", "resultado", "caracteristicas", "problema"],
    "funcionamiento": ["funcionamiento", "solucion", "caracteristicas", "producto", "resultado", "problema"],
    "producto": ["producto", "caracteristicas", "solucion", "funcionamiento", "resultado", "problema"],
    "caracteristicas": ["caracteristicas", "producto", "funcionamiento", "solucion", "resultado", "problema"],
    "resultado": ["resultado", "solucion", "producto", "funcionamiento", "caracteristicas", "problema"],
    # CTA: se ve el producto en uso, calmado (el "payoff" de las referencias)
    "cta": ["solucion", "producto", "resultado", "funcionamiento", "caracteristicas", "problema"],
}

_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("cta", ("pide", "pídelo", "ordena", "escríbe", "contraentrega", "contra entrega", "envío",
             "envio", "paga al recibir", "toca", "aprovecha", "oferta", "promoción", "promocion",
             "unidades", "hoy mismo", "link", "enlace")),
    ("problema", ("dolor", "duele", "cansad", "sufr", "molest", "problema", "hart", "aburrid",
                  "frustra", "gastar", "sin ver", "difícil", "dificil", "inflam", "hinchad",
                  "vergüenza", "verguenza", "miedo", "preocup", "nada funciona", "intentado")),
    ("solucion", ("solución", "solucion", "llegó", "llego", "conoce", "descubr", "adiós", "adios",
                  "olvídate", "olvidate", "elimina", "acaba", "combate", "por fin", "existe",
                  "secreto", "cambia eso", "la respuesta")),
    ("funcionamiento", ("solo aplica", "aplícal", "aplical", "usa", "úsal", "usal", "pon", "coloca",
                        "presiona", "enciende", "minutos al día", "minutos", "así de fácil",
                        "asi de facil", "pasos", "funciona", "cómo", "como se usa")),
    ("caracteristicas", ("incluye", "trae", "material", "resistente", "batería", "bateria",
                         "recargable", "lavable", "tamaño", "tamano", "diseño", "diseno",
                         "calidad", "tecnología", "tecnologia", "portátil", "portatil")),
    ("resultado", ("resultado", "verás", "veras", "sentirás", "sentiras", "notarás", "notaras",
                   "desde el primer", "en pocos días", "en pocos dias", "feliz", "segura",
                   "confianza", "transform", "renovad", "como nunca", "sin dolor", "libre de")),
    ("producto", ("este", "producto", "dispositivo", "diseñado", "disenado", "creado", "único",
                  "unico", "original", "certificad")),
]


def frases_de_vo(words: Sequence[dict], dur_total: float) -> list[dict]:
    """Agrupa los tiempos por palabra [{'word','start','end'}] en FRASES.

    Corta por puntuación fuerte (.!?…) o por pausa > _PAUSA_FRASE; una frase que pase de
    _FRASE_MAX_S se parte en la coma/pausa más cercana al medio. La última frase se estira
    hasta el final de la voz (el CTA cubre el cierre). Devuelve [{'texto','inicio','fin'}]."""
    words = [w for w in (words or []) if str(w.get("word", "")).strip()]
    if len(words) < 4:
        return []
    frases: list[dict] = []
    cur: list[dict] = []

    def _cerrar(fin: float):
        if not cur:
            return
        frases.append({"texto": " ".join(str(w["word"]).strip() for w in cur),
                       "inicio": float(cur[0]["start"]), "fin": float(fin)})
        cur.clear()

    for k, w in enumerate(words):
        cur.append(w)
        texto = str(w.get("word", ""))
        fin_puntuacion = bool(re.search(r"[.!?…]$", texto.strip()))
        gap = (float(words[k + 1]["start"]) - float(w["end"])) if k + 1 < len(words) else 99.0
        dur_frase = float(w["end"]) - float(cur[0]["start"])
        if fin_puntuacion or gap >= _PAUSA_FRASE or dur_frase >= _FRASE_MAX_S:
            # el silencio hasta la próxima palabra pertenece a ESTA frase (el plano lo sostiene)
            fin = float(words[k + 1]["start"]) if k + 1 < len(words) else float(w["end"])
            _cerrar(fin)
    _cerrar(float(words[-1]["end"]))
    if frases and dur_total > frases[-1]["fin"]:
        frases[-1]["fin"] = float(dur_total)          # la voz manda hasta el último segundo
    # micro-frases (<0.6s) se funden con la anterior (un plano de 0.3s no ilustra nada)
    depuradas: list[dict] = []
    for f in frases:
        if depuradas and (f["fin"] - f["inicio"]) < 0.6:
            depuradas[-1]["fin"] = f["fin"]
            depuradas[-1]["texto"] += " " + f["texto"]
        else:
            depuradas.append(f)
    return depuradas


def _heuristica(texto: str, rel: float) -> str:
    """Fase por palabras clave; si nada pega, por posición en el arco del anuncio."""
    t = f" {texto.lower()} "
    for fase, claves in _KEYWORDS:
        if any(k in t for k in claves):
            return fase
    if rel < 0.20:
        return "problema"
    if rel < 0.40:
        return "solucion"
    if rel < 0.55:
        return "funcionamiento"
    if rel < 0.72:
        return "producto"
    if rel < 0.88:
        return "resultado"
    return "cta"


def etiquetar_frases(frases_por_version: list[list[dict]], gemini_key: str | None,
                     product_desc: str = "") -> None:
    """Pone `fase` a cada frase (in-place). UNA llamada Gemini para TODAS las versiones;
    si falla o no hay key, heurística por palabras clave + posición (nunca lanza)."""
    todas = [f for frases in frases_por_version for f in frases]
    if not todas:
        return
    if gemini_key:
        try:
            from google import genai
            listado = "\n".join(f'{i}: "{f["texto"]}"' for i, f in enumerate(todas))
            prompt = (
                f"Frases de guiones de anuncios de UN producto ({product_desc or 'producto'}). "
                "Clasifica CADA frase, por número, en UNA fase según lo que debería VERSE en "
                "pantalla mientras se dice:\n"
                "- problema: se nombra el dolor/situación molesta\n"
                "- solucion: se anuncia que existe la solución / el producto en acción\n"
                "- funcionamiento: cómo se usa / pasos / cuánto tarda\n"
                "- producto: qué es, presentación del producto\n"
                "- caracteristicas: materiales, partes, especificaciones\n"
                "- resultado: el después, cómo te sentirás/verás\n"
                "- cta: llamado a comprar (oferta, envío, paga al recibir)\n"
                f"Responde SOLO un JSON array [{{\"i\":0,\"fase\":\"problema\"}},...] con TODAS "
                f"las frases (0..{len(todas) - 1}).\n\n{listado}")
            cl = genai.Client(api_key=gemini_key)
            resp = cl.models.generate_content(model="gemini-2.5-flash", contents=[prompt])
            m = re.search(r"\[.*\]", resp.text or "", re.DOTALL)
            if m:
                validas = set(FASES) | {"cta"}
                for item in json.loads(m.group(0)):
                    i = int(item.get("i", -1))
                    fase = str(item.get("fase", "")).strip().lower()
                    if 0 <= i < len(todas) and fase in validas:
                        todas[i]["fase"] = fase
        except Exception:  # noqa: BLE001
            pass
    for frases in frases_por_version:          # relleno heurístico de lo que falte
        dur = max(0.1, frases[-1]["fin"]) if frases else 1.0
        for f in frases:
            if not f.get("fase"):
                f["fase"] = _heuristica(f["texto"], f["inicio"] / dur)


def plan_montaje(selected, fases_por_idx: dict[int, str], frases: list[dict],
                 usage: dict[int, int]) -> tuple[list[int], list[float]] | None:
    """Elige los clips para UNA versión siguiendo el guion. Devuelve (orden, topes por slot).

    - Cada frase se llena con el mejor clip de SU fase (fallback: fases vecinas en significado);
      si el clip no alcanza, se encadena otro dentro de la misma frase.
    - JAMÁS se repite un clip dentro de la versión (regla dura de Juan); `usage` balancea
      entre versiones (se prefiere el clip menos usado por las demás).
    - Primera frase (hook): planos cortos (ritmo de ráfaga). Última: planos calmados.
    """
    if not frases or not fases_por_idx:
        return None
    usados: set[int] = set()
    orden: list[int] = []
    caps: list[float] = []

    def _mejor(fase: str, tope: float) -> int | None:
        for f in _PREFERENCIA.get(fase, list(FASES)):
            pool = [i for i, ff in fases_por_idx.items() if ff == f and i not in usados]
            if not pool:
                continue
            # menos usado por otras versiones primero; luego mejor score; y que RINDA el slot
            pool.sort(key=lambda i: (usage.get(i, 0),
                                     -min(selected[i].duration(), tope),
                                     -selected[i].score))
            return pool[0]
        sobrantes = [i for i in fases_por_idx if i not in usados]
        if sobrantes:
            sobrantes.sort(key=lambda i: (usage.get(i, 0), -selected[i].score))
            return sobrantes[0]
        return None

    n_frases = len(frases)
    for fi, fr in enumerate(frases):
        restante = float(fr["fin"]) - float(fr["inicio"])
        primera, ultima = fi == 0, fi >= n_frases - 1
        while restante >= _SLOT_MIN:
            tope_slot = 1.2 if (primera and len(orden) < 3) else (2.2 if ultima or fi >= n_frases - 2 else 1.7)
            i = _mejor(str(fr.get("fase", "producto")), tope_slot)
            if i is None:
                break                        # pool agotado: el tpad sostiene el último frame
            nat = selected[i].duration()
            dur = min(nat, tope_slot, restante)
            # que no quede una colita imposible de llenar (<_SLOT_MIN): mejor absorberla ya
            if _SLOT_MIN < restante - dur < _SLOT_MIN * 1.4:
                dur = min(nat, restante) if nat >= restante else dur
            if dur < _SLOT_MIN:
                dur = min(nat, max(_SLOT_MIN, restante))
            usados.add(i)
            usage[i] = usage.get(i, 0) + 1
            orden.append(i)
            caps.append(round(dur, 3))
            restante -= dur
        # colita (<_SLOT_MIN) sin cubrir: se estira el último plano de la frase si el clip da
        if 0.02 < restante and orden:
            nat_ult = selected[orden[-1]].duration()
            extra = min(restante, max(0.0, nat_ult - caps[-1]))
            if extra > 0.02:
                caps[-1] = round(caps[-1] + extra, 3)
    return (orden, caps) if orden else None
