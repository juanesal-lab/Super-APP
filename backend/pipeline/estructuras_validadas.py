"""🎯 Avatares + estructuras VALIDADAS para el lote de guiones de Cortar clips.

El problema real (Jack, 2026-07): las 8 versiones salían como "8 sabores del mismo helado" —
misma duración, mismo arco, solo cambiaba el ángulo del copy. Meta (Andromeda) agrupa los
anuncios parecidos, así que el lote NO diversificaba de verdad y los creativos no vendían.

Este módulo asigna a CADA versión del lote un par (AVATAR, ESTRUCTURA) distinto:
  - La biblioteca vive en `assets/estructuras-validadas.json`: 9 estructuras destiladas del
    research REAL del repo (patron-ganador-validado, playbook-por-nicho, guion-framework v3,
    funnel-tofu-mofu-bofu, blueprint-creativos-ganadores…), cada una con su PROPIA duración
    (el research manda: hogar 20-30s · mecanismo 45-60s · reveal visual 12-18s…).
  - `asignar_estructuras()` usa Gemini flash (1 sola llamada) para detectar el nicho y generar
    4-8 AVATARES reales del producto (ej. rodillera: deportista lesionado / abuela con artrosis /
    hijo que compra para su papá) y asigna pares (avatar, estructura) coherentes y DISTINTOS.
  - Sin key o si Gemini falla → asignación por defecto rotando la biblioteca (best-effort,
    JAMÁS lanza excepción: el flujo de guiones sigue como siempre).

REGLAS DE ORO respetadas: sin precios/cifras en nada de lo que se genera aquí; nada de claims
médicos (la biblioteca ya dice "ayuda a / apoya"); el CTA obligatorio de scripts.py no se toca.
"""
from __future__ import annotations

import json
import os
import re

_MODEL = "gemini-2.5-flash"

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets")
_LIB_PATH = os.path.join(_ASSETS, "estructuras-validadas.json")
_LIB_CACHE: list[dict] | None = None

# Campos que TODA estructura de la biblioteca debe traer (los valida cargar_biblioteca).
CAMPOS_ESTRUCTURA = ("id", "nombre", "fuente", "duracion_s", "fases", "tipo_hook",
                     "funnel", "avatares_sugeridos")

# Avatares de reserva (sin Gemini): arquetipos de comprador que aplican a casi cualquier
# producto COD — mejor un avatar genérico útil que ninguno.
_AVATARES_FALLBACK = [
    {"nombre": "el que ya probó de todo y desconfía",
     "dolor": "perdió plata en soluciones que no sirvieron", "objecion": "¿y este sí funciona o es otro cuento?", "momento": "cuando ve otro anuncio más del mismo tipo"},
    {"nombre": "mamá práctica que compra para la casa",
     "dolor": "el problema le daña la rutina de todos en casa", "objecion": "¿me va a durar o se daña a la semana?", "momento": "en la noche, cuando por fin se sienta"},
    {"nombre": "hijo/a que lo compra para su papá o mamá",
     "dolor": "ve a su papá/mamá aguantándose el problema sin quejarse", "objecion": "¿será fácil de usar para una persona mayor?", "momento": "después de la visita del domingo"},
    {"nombre": "trabajador que lo necesita a diario",
     "dolor": "el problema le pega justo cuando más rinde el día", "objecion": "¿aguanta el uso duro de todos los días?", "momento": "a media jornada, cuando el cuerpo pasa factura"},
    {"nombre": "el escéptico que pide pruebas en cámara",
     "dolor": "lo han tumbado con fotos que no eran el producto", "objecion": "muéstremelo funcionando de verdad, sin cortes", "momento": "cuando compara antes de decidir"},
    {"nombre": "quien recién descubre que esto existe",
     "dolor": "vivía resignado creyendo que no había solución", "objecion": "¿por qué nadie me lo había mostrado antes?", "momento": "scrolleando de noche"},
    {"nombre": "el que está comparando opciones ahora mismo",
     "dolor": "hay mil versiones y no sabe cuál pedir", "objecion": "¿qué tiene este que no tenga el otro?", "momento": "con tres pestañas abiertas"},
    {"nombre": "quien lo quiere para regalar y quedar bien",
     "dolor": "los regalos de siempre ya no sorprenden a nadie", "objecion": "¿de verdad lo va a usar o queda guardado?", "momento": "cuando se acerca la fecha y no tiene nada"},
]

# Etapa del embudo → funnel de estructura preferido (para cuando el lote viene con mix TOFU/MOFU/BOFU).
_FUNNEL_DE_STAGE = {"TOFU": "tofu", "MOFU": "mofu", "BOFU": "bofu"}


def cargar_biblioteca() -> list[dict]:
    """Carga y valida `assets/estructuras-validadas.json` una vez (cacheada).

    Solo entran estructuras con TODOS los campos obligatorios y fases bien formadas.
    Si el archivo no existe o está roto devuelve [] (el caller hace fallback)."""
    global _LIB_CACHE
    if _LIB_CACHE is not None:
        return _LIB_CACHE
    out: list[dict] = []
    try:
        with open(_LIB_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for e in data.get("estructuras", []):
            if not isinstance(e, dict) or not all(k in e for k in CAMPOS_ESTRUCTURA):
                continue
            dur = e.get("duracion_s")
            if not (isinstance(dur, list) and len(dur) == 2 and all(
                    isinstance(x, (int, float)) for x in dur)):
                continue
            fases = e.get("fases")
            if not (isinstance(fases, list) and fases and all(
                    isinstance(f, dict) and f.get("fase") for f in fases)):
                continue
            out.append(e)
    except Exception:  # noqa: BLE001 — biblioteca rota = [] y el caller sobrevive
        out = []
    _LIB_CACHE = out
    return out


def _dur_media(est: dict) -> int:
    """Duración objetivo de una estructura: el punto medio de su rango [min,max]."""
    lo, hi = est["duracion_s"]
    return int(round((float(lo) + float(hi)) / 2.0))


def _resumen_estructura(est: dict) -> str:
    """Etiqueta corta para UI/manifest: 'Mecanismo/autoridad · ~52s'."""
    return f"{est['nombre']} · ~{_dur_media(est)}s"


def _rotacion_por_funnel(lib: list[dict], n: int, funnel_seq: list[str] | None) -> list[dict]:
    """Elige n estructuras rotando la biblioteca sin repetir hasta agotarla.

    Si viene `funnel_seq` (una etapa TOFU/MOFU/BOFU por versión, del embudo), cada slot
    prefiere una estructura de SU temperatura (rotando dentro de esa familia)."""
    if not lib:
        return []
    por_funnel: dict[str, list[dict]] = {}
    for e in lib:
        por_funnel.setdefault(str(e.get("funnel", "")).lower(), []).append(e)
    cursores: dict[str, int] = {}
    out: list[dict] = []
    for i in range(n):
        fam = None
        if funnel_seq and i < len(funnel_seq):
            fam = _FUNNEL_DE_STAGE.get(str(funnel_seq[i]).upper())
        pool = por_funnel.get(fam or "", []) or lib
        clave = fam or "_todas"
        c = cursores.get(clave, 0)
        out.append(pool[c % len(pool)])
        cursores[clave] = c + 1
    return out


def _asignacion_fallback(n: int, funnel_seq: list[str] | None = None) -> list[dict]:
    """Asignación SIN IA: rota estructuras de la biblioteca y avatares de reserva con
    desfase, para que ningún par (avatar, estructura) se repita mientras alcance."""
    lib = cargar_biblioteca()
    ests = _rotacion_por_funnel(lib, n, funnel_seq)
    out = []
    for i in range(n):
        av = _AVATARES_FALLBACK[i % len(_AVATARES_FALLBACK)]
        est = ests[i] if i < len(ests) else None
        item = {"avatar": av["nombre"], "dolor": av["dolor"], "objecion": av["objecion"],
                "momento": av["momento"], "nicho": ""}
        if est:
            item.update({"estructura": _resumen_estructura(est), "estructura_id": est["id"],
                         "duracion_s": _dur_media(est), "estructura_def": est})
        out.append(item)
    return out


def _prompt_asignacion(product_desc: str, n: int, lib: list[dict],
                       funnel_seq: list[str] | None) -> str:
    """Prompt de UNA llamada: nicho + avatares reales + par (avatar, estructura) por versión."""
    k = min(8, max(4, n))
    lineas = []
    for e in lib:
        lo, hi = e["duracion_s"]
        lineas.append(f"- {e['id']} — {e['nombre']} ({lo}-{hi}s, hook: {e['tipo_hook']}, "
                      f"temperatura {e['funnel'].upper()}): "
                      + " → ".join(f["fase"] for f in e["fases"])
                      + f". Sirve para: {', '.join(e['avatares_sugeridos'][:2])}.")
    embudo = ""
    if funnel_seq:
        embudo = ("\nEMBUDO OBLIGATORIO: la versión i tiene la temperatura fija de esta lista "
                  f"(elige una estructura de ESA temperatura): {list(funnel_seq)[:n]}.\n")
    return (
        "Eres el estratega de creativos de un dropshipper COD en Colombia. Tu trabajo: que un "
        f"lote de {n} video-ads del MISMO producto ataque COMPRADORES DISTINTOS con ESTRUCTURAS "
        "distintas (Meta agrupa los anuncios parecidos; la diversidad real es avatar + estructura).\n\n"
        f"PRODUCTO: {product_desc.strip()[:600]}\n\n"
        "BIBLIOTECA DE ESTRUCTURAS VALIDADAS (id — nombre — duración — hook — fases):\n"
        + "\n".join(lineas) + "\n" + embudo +
        f"\nTAREA (responde SOLO un JSON):\n"
        "1) Detecta el NICHO del producto (2-4 palabras).\n"
        f"2) Genera {k} AVATARES de comprador REALES y bien DISTINTOS de este producto — personas "
        "concretas, no demografía: quién es (3-7 palabras, ej. 'abuela con artrosis que ya no sale "
        "a caminar'), su dolor #1 dicho en frase cotidiana, su objeción #1 antes de pedir, y el "
        "momento del día/vida en que el problema le pega. Piensa también en el que COMPRA PARA "
        "OTRO (hijo para su papá, esposa para el esposo).\n"
        f"3) Asigna a cada una de las {n} versiones un par (avatar, estructura) — TODOS los pares "
        "DISTINTOS entre sí — y COHERENTE: dolor de salud/cuerpo → estructura con bloque de "
        "mecanismo o transformación; comprador escéptico → objeción derribada; regalo/familiar → "
        "storytime; comprador visual/impulsivo → reveal o demo cruda. Reparte los avatares (no "
        "uses el mismo avatar en más de 2 versiones).\n"
        "PROHIBIDO: precios o cifras de dinero, claims médicos (curas, %), burlarse del avatar.\n"
        'Formato EXACTO: {"nicho":"...","avatares":[{"nombre":"...","dolor":"...","objecion":"...",'
        '"momento":"..."}],"asignaciones":[{"avatar":0,"estructura":"id_de_la_biblioteca"}]}'
        f" — asignaciones debe traer exactamente {n} items, avatar = índice en tu lista de avatares."
    )


def asignar_estructuras(product_desc: str, n: int = 10, gemini_key: str | None = None,
                        funnel_seq: list[str] | None = None) -> list[dict]:
    """Devuelve n asignaciones [{avatar, dolor, objecion, momento, nicho, estructura,
    estructura_id, duracion_s, estructura_def}] — una por versión del lote.

    Con Gemini flash (1 llamada) los avatares salen del PRODUCTO real; sin key o si algo
    falla, rota la biblioteca con avatares de reserva. Best-effort: JAMÁS lanza excepción
    (si hasta la biblioteca falta, devuelve [] y el flujo de guiones sigue como siempre).

    `funnel_seq`: opcional, la etapa TOFU/MOFU/BOFU de cada versión (embudo activo) para que
    la estructura asignada respete la temperatura de su slot."""
    try:
        n = max(1, int(n))
        lib = cargar_biblioteca()
        if not lib:
            return []
        gemini_key = gemini_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not gemini_key or not (product_desc or "").strip():
            return _asignacion_fallback(n, funnel_seq)
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            resp = client.models.generate_content(
                model=_MODEL, contents=_prompt_asignacion(product_desc, n, lib, funnel_seq))
            m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
        except Exception:  # noqa: BLE001 — cuota/red/JSON roto → fallback silencioso
            return _asignacion_fallback(n, funnel_seq)

        nicho = str(data.get("nicho", ""))[:60]
        avatares = [a for a in (data.get("avatares") or [])
                    if isinstance(a, dict) and str(a.get("nombre", "")).strip()]
        asigs = data.get("asignaciones") or []
        if not avatares or not isinstance(asigs, list):
            return _asignacion_fallback(n, funnel_seq)

        por_id = {e["id"]: e for e in lib}
        respaldo_ests = _rotacion_por_funnel(lib, n, funnel_seq)
        out: list[dict] = []
        usados: set[tuple] = set()          # pares (avatar, estructura) ya usados en el lote
        for i in range(n):
            a = asigs[i] if i < len(asigs) and isinstance(asigs[i], dict) else {}
            try:
                av = avatares[int(a.get("avatar", i)) % len(avatares)]
            except (TypeError, ValueError):
                av = avatares[i % len(avatares)]
            est = por_id.get(str(a.get("estructura", "")).strip()) or respaldo_ests[i]
            # embudo activo: si Gemini ignoró la temperatura del slot, se corrige aquí
            if funnel_seq and i < len(funnel_seq):
                fam = _FUNNEL_DE_STAGE.get(str(funnel_seq[i]).upper())
                if fam and str(est.get("funnel", "")).lower() != fam:
                    est = respaldo_ests[i]
            # par repetido → rota la estructura para que la versión no salga clonada
            par = (str(av.get("nombre", "")), est["id"])
            if par in usados:
                for cand in lib:
                    if (str(av.get("nombre", "")), cand["id"]) not in usados and (
                            not funnel_seq or i >= len(funnel_seq)
                            or str(cand.get("funnel", "")).lower()
                            == _FUNNEL_DE_STAGE.get(str(funnel_seq[i]).upper())):
                        est = cand
                        break
            usados.add((str(av.get("nombre", "")), est["id"]))
            out.append({
                "avatar": str(av.get("nombre", ""))[:80],
                "dolor": str(av.get("dolor", ""))[:160],
                "objecion": str(av.get("objecion", ""))[:160],
                "momento": str(av.get("momento", ""))[:120],
                "nicho": nicho,
                "estructura": _resumen_estructura(est),
                "estructura_id": est["id"],
                "duracion_s": _dur_media(est),
                "estructura_def": est,
            })
        return out
    except Exception:  # noqa: BLE001 — pase lo que pase, el flujo de guiones no se cae
        try:
            return _asignacion_fallback(n, funnel_seq)
        except Exception:  # noqa: BLE001
            return []
