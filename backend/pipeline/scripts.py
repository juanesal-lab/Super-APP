"""Generacion de guiones de voz en off con Gemini (varios angulos de venta)."""
from __future__ import annotations

import json
import os
import re

import cv2

from .analyze import Segment

_MODEL = "gemini-2.5-flash"

# CTA OBLIGATORIO: el cierre DURO de contraentrega. Antes iba en TODOS los guiones; ahora es
# EXCLUSIVO de BOFU (caliente). TOFU cierra SUAVE y MOFU con CTA medio (embudo TOFU/MOFU/BOFU,
# asset funnel-tofu-mofu-bofu-2026.md). La cadena EXACTA de BOFU no cambia (pedido del dueño).
CTA_OBLIGATORIO = ("por tu compra hoy te regalamos el envío, y para tu seguridad ante estafas "
                   "pagas al recibir")

# CTAs por etapa (cta_mode): "hard" = BOFU (frase exacta de arriba), "medium" = MOFU, "soft" = TOFU.
_CTA_SUAVE = "te dejo el link, míralo"                 # TOFU: nada de contraentrega dura
_CTA_MEDIO = "mira las reseñas y decídelo tú"          # MOFU: CTA medio

# Palabras clave para NO duplicar el cierre si el modelo ya escribió uno de la etapa.
_CTA_KEYS = {
    "soft": ("link", "búscalo", "buscalo", "míralo", "miralo", "búscala", "buscala", "perfil"),
    "medium": ("reseña", "resena", "decídelo", "decidelo", "reviews", "míralas", "miralas",
               "opiniones"),
}


def _cta_text(cta_mode: str) -> str:
    if cta_mode == "soft":
        return _CTA_SUAVE
    if cta_mode == "medium":
        return _CTA_MEDIO
    return CTA_OBLIGATORIO


def _cta_words(cta_mode: str) -> int:
    """Cuántas palabras reserva el CTA de esta etapa (para el presupuesto de recorte)."""
    return len(_cta_text(cta_mode).split())


def _con_cta(texto: str, cta_mode: str = "hard") -> str:
    """Garantiza que el copy CIERRE con el CTA de su etapa (lo añade si el modelo no lo puso).

    `cta_mode`: "hard" (BOFU, frase exacta de contraentrega), "medium" (MOFU), "soft" (TOFU).
    Por defecto "hard" → comportamiento idéntico al de antes (retrocompatible)."""
    t = (texto or "").strip()
    if cta_mode == "hard":
        if CTA_OBLIGATORIO.lower() in t.lower():
            return t
        sep = "" if (not t or t.endswith((".", "!", "?"))) else "."
        return (t + sep + " " + CTA_OBLIGATORIO.capitalize() + ".").strip()
    # soft / medium: NO se fuerza el CTA duro de contraentrega. Si el guion ya trae un cierre
    # de su etapa, se deja; si no, se agrega uno corto (no ampută el cuerpo como el de 17 palabras).
    low = t.lower()
    if any(k in low for k in _CTA_KEYS.get(cta_mode, ())):
        return t
    cta = _cta_text(cta_mode)
    sep = "" if (not t or t.endswith((".", "!", "?"))) else "."
    return (t + sep + " " + cta.capitalize() + ".").strip()


def _ajustar_largo(texto: str, max_words: int, cta_mode: str = "hard") -> str:
    """Recorte DURO al presupuesto de palabras. Gemini a veces ignora el 'MÁXIMO N palabras'
    (salieron guiones de 140 palabras para un video de 15s → 30s de video congelado al final,
    bug real del 2026-07-03). Se corta por FRASES desde el inicio reservando el CTA obligatorio,
    y se cierra con el CTA exacto. Si ya cabe, no toca nada."""
    t = (texto or "").strip()
    # tolerancia AMPLIA: un 35% de desborde solo alarga el video unos segundos (la voz manda y el
    # montaje la sigue). El recorte duro es SOLO para desbordes catastróficos (Gemini 140 palabras
    # para 15s) porque corta desde el final y se puede comer el momento del producto.
    tope = int(max_words * 1.35)
    if len(t.split()) <= tope:
        return _con_cta(t, cta_mode)
    if cta_mode == "hard":               # solo BOFU trae el CTA duro que hay que quitar y re-agregar
        idx = t.lower().find(CTA_OBLIGATORIO.lower()[:30])
        if idx > 0:
            t = t[:idx].rstrip(" ,.;:¡¿")
    frases = re.split(r"(?<=[.!?…])\s+", t)
    presupuesto = max(10, int(max_words * 1.05) - _cta_words(cta_mode))
    out, cuenta = [], 0
    for fr in frases:
        nw = len(fr.split())
        if out and cuenta + nw > presupuesto:
            break
        out.append(fr)
        cuenta += nw
    return _con_cta(" ".join(out), cta_mode)


def _ajustar_por_fases(d: dict, max_words: int, cta_mode: str = "hard") -> str | None:
    """Recorte INTELIGENTE usando el desglose por fases que entrega el modelo: si el guion se
    pasa del presupuesto, se sacrifican fases en orden de importancia (prueba → problema → giro)
    pero JAMÁS el hook, el producto ni el CTA. (El recorte ciego por frases amputaba desde el
    final y se comía el momento del producto — bug real del 2026-07-04.)"""
    f = d.get("fases")
    if not isinstance(f, dict):
        return None
    orden = ["hook", "problema", "giro", "producto", "prueba"]
    partes = {k: str(f.get(k, "") or "").strip().rstrip(".") for k in orden}
    if not partes["hook"] or not partes["producto"]:
        return None                        # sin hook o sin producto el desglose no sirve
    tope = int(max_words * 1.2)
    sacrificables = ["prueba", "problema", "giro"]
    omitidas: set[str] = set()

    def _arma() -> str:
        trozos = [partes[k] for k in orden if k not in omitidas and partes[k]]
        cuerpo = " ".join(p if p.endswith(("?", "!", "…")) else p + "." for p in trozos)
        return _con_cta(cuerpo, cta_mode)

    texto = _arma()
    for k in sacrificables:
        if len(texto.split()) <= tope:
            break
        omitidas.add(k)
        texto = _arma()
    return texto


# ── EMBUDO TOFU / MOFU / BOFU (asset funnel-tofu-mofu-bofu-2026.md) ──────────────────────────
# Cada etapa cambia el ARCO, las familias de hook, la dureza del CTA y el largo objetivo. Meta
# (Andromeda) agrupa anuncios parecidos → dar temperaturas DISTINTAS es el eje de diversificación.
_STAGES_META = {
    "TOFU": {
        "temp": "frío", "emoji": "🧊", "cta_mode": "soft", "seconds": (15, 25),
        "arco": ("HOOK → PROBLEMA/agitación (~60% del guion, detalle cotidiano) → GIRO + primer "
                 "vistazo del producto (se nombra TARDE, UNA vez) → cierre SUAVE"),
        "hooks": ("pattern-interrupt / dolor relatable / claim audaz / curiosidad / POV "
                  "'esto no es un anuncio'"),
        "cta": ("SUAVE — 'te dejo el link', 'búscalo', 'míralo'. PROHIBIDO aquí el cierre de "
                "contraentrega / 'pagas al recibir' / oferta dura (eso espanta al público frío)"),
        "pantalla": "curiosidad o problema (ej. 'NADIE TE DICE ESTO')",
    },
    "MOFU": {
        "temp": "tibio", "emoji": "🌤️", "cta_mode": "medium", "seconds": (20, 40),
        "arco": ("HOOK → MECANISMO/DEMO (por qué funciona) → PRUEBA (reseñas / antes-después / "
                 "comparación) → CTA MEDIO"),
        "hooks": ("'probé N y solo una…' / 'por qué no te ha funcionado' / objeción / "
                  "número específico"),
        "cta": ("MEDIO — 'mira las reseñas', 'decídelo tú'. Se puede INSINUAR el pago al recibir, "
                "pero SIN la frase dura completa ni oferta 2x1"),
        "pantalla": "prueba / mecanismo (ej. 'MIRA LA DIFERENCIA', '4.8★ 12.000 RESEÑAS')",
    },
    "BOFU": {
        "temp": "caliente", "emoji": "🔥", "cta_mode": "hard", "seconds": (8, 20),
        "arco": ("RECORDATORIO/objeción directa → OFERTA + reversión de riesgo (contraentrega, "
                 "envío, garantía) → CTA DURO con urgencia"),
        "hooks": ("objeción directa / oferta / escasez / '¿lo pensaste y no lo pediste?'"),
        "cta": ("DURO — TERMINA con la frase EXACTA de contraentrega + urgencia ('antes de que "
                "se agote')"),
        "pantalla": "oferta / urgencia (ej. '2X1 SOLO HOY', 'PAGA AL RECIBIR')",
    },
}
_STAGE_ORDER = ("TOFU", "MOFU", "BOFU")


def _build_stage_list(mix: dict | None) -> list[str]:
    """De {'TOFU':2,'MOFU':2,'BOFU':2} → ['TOFU','TOFU','MOFU','MOFU','BOFU','BOFU'] (orden fijo).

    Ignora etapas desconocidas y cuentas ≤0. Devuelve [] si el mix no pide nada."""
    if not isinstance(mix, dict):
        return []
    out: list[str] = []
    for st in _STAGE_ORDER:
        try:
            c = int(mix.get(st, 0) or 0)
        except (TypeError, ValueError):
            c = 0
        out += [st] * max(0, c)
    return out


def _stage_seconds(stage: str, target_seconds: float) -> float:
    """Segundos objetivo de la etapa: la duración pedida encajada en el rango de la etapa."""
    lo, hi = _STAGES_META[stage]["seconds"]
    return min(float(hi), max(float(lo), float(target_seconds)))


def _stage_max_words(stage: str, target_seconds: float) -> int:
    """Presupuesto de palabras por etapa (~2.55 pal/seg, mismo cálculo que el global)."""
    return max(30, int(_stage_seconds(stage, target_seconds) * 2.55))


def _stage_plan_text(stages: list[str], target_seconds: float) -> str:
    """Bloque de prompt que le dice al modelo, guion por guion, su etapa/arco/hook/CTA/largo."""
    lines = ["=== PLAN DE ETAPAS DEL EMBUDO (OBLIGATORIO: cada guion CUMPLE la etapa que le toca, "
             "y en ESTE MISMO orden) ==="]
    for i, st in enumerate(stages):
        m = _STAGES_META[st]
        lo, hi = m["seconds"]
        secs = int(_stage_seconds(st, target_seconds))
        lines.append(
            f"Guion {i + 1} — ETAPA {st} ({m['temp']}, ~{secs}s; rango {lo}-{hi}s): "
            f"ARCO = {m['arco']}; FAMILIAS DE HOOK = {m['hooks']}; CTA = {m['cta']}; "
            f"TEXTO EN PANTALLA que insinúa = {m['pantalla']}.")
    lines.append(
        "DIVERSIDAD OBLIGATORIA: NINGÚN par de guiones comparte la misma familia de hook ni el "
        "mismo ángulo — cada guion es un CONCEPTO distinto (Meta agrupa los parecidos).")
    lines.append(
        "CTA POR ETAPA (crítico): SOLO los guiones BOFU terminan con la frase EXACTA de "
        f"contraentrega (\"{CTA_OBLIGATORIO}\"). Los TOFU cierran SUAVE ('te dejo el link', "
        "'búscalo') y los MOFU con CTA medio ('mira las reseñas', 'decídelo tú') — a TOFU y MOFU "
        "NO les metas la frase de contraentrega ni el 'pagas al recibir'.")
    lines.append("=== FIN DEL PLAN DE ETAPAS ===")
    return "\n".join(lines) + "\n"


_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets")


def _anthropic_key() -> str | None:
    """Key de Claude (mejor copywriter para los guiones): env o .env del repo."""
    k = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if k:
        return k
    try:
        env = os.path.join(os.path.dirname(_ASSETS), ".env")
        for ln in open(env):
            if ln.startswith("ANTHROPIC_API_KEY="):
                v = ln.split("=", 1)[1].strip().strip('"').strip("'")
                return v or None
    except Exception:  # noqa: BLE001
        pass
    return None

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
                     oferta_2x1: bool = False, mix: dict | None = None) -> list[dict]:
    """Devuelve hasta n guiones: [{'angulo': str, 'texto': str}].

    Si la IA NO PUDO correr (sin keys, cuota 429, respuesta ilegible) levanta RuntimeError
    con mensaje amigable que nombra el motor real (Claude 1º, Gemini respaldo) — antes
    devolvía [] y el job terminaba "Guiones listos" con 0 guiones culpando a Gemini.

    `blueprint`: opcional, el análisis narrativo (narrative.py) de un ANUNCIO GANADOR de
    referencia. Si viene, los guiones copian su arco (HOOK→DOLOR→SOLUCIÓN→DESEO→CTA) y ritmo.

    `mix`: opcional, embudo TOFU/MOFU/BOFU (ej. {"TOFU":2,"MOFU":2,"BOFU":2}). Si viene, se
    asigna una ETAPA por índice, se inyecta un bloque por etapa (arco + familias de hook + dureza
    de CTA + largo) y cada guion sale etiquetado con `stage`/`temp`. n = sum(mix.values()). Si es
    None, comportamiento idéntico al de antes (n guiones sin etapa, CTA duro en todos).
    """
    from .ia_errors import error_amigable
    # ── Embudo: lista de etapas por índice (o None = flujo clásico sin etapas) ──
    stages = _build_stage_list(mix)
    if stages:
        n = len(stages)
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ak = _anthropic_key()          # Claude escribe mejor copy: es la 1ª opción; Gemini respaldo
    if not api_key and not ak:
        raise RuntimeError("No hay API key de IA para escribir los guiones — configura "
                           "Gemini o Anthropic en 🔑 Claves.")
    client = None
    if api_key:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)
        except Exception:  # noqa: BLE001
            client = None
    if client is None and not ak:
        raise RuntimeError("No pude iniciar Gemini para escribir los guiones — "
                           "revisa la key en 🔑 Claves.")

    # ~2.55 palabras/seg: ElevenLabs es-CO medido (2.4) x la aceleración 1.12 del Manual §6.
    # El presupuesto INCLUYE el CTA obligatorio (17 palabras): a 15s el cuerpo queda muy corto
    # → el sweet spot para tráfico frío es 20-25s (Manual §10.1).
    max_words = max(30, int(target_seconds * 2.55))

    info = ""
    if product_desc.strip():
        info += f"\nProducto: {product_desc.strip()}"
    if page_text.strip():
        info += f"\nInfo de la pagina de venta: {page_text.strip()[:2500]}"

    framework = _load_framework()
    bp = _blueprint_text(blueprint)
    arco = ("Cada guion debe SEGUIR el arco narrativo del anuncio de referencia de arriba "
            "(mismas fases, mismo orden, ritmo parecido). " if bp else "")
    # Embudo activo: el plan por etapa se inyecta y el bloque CTA/presupuesto se vuelve por-etapa.
    stage_plan = _stage_plan_text(stages, target_seconds) + "\n" if stages else ""
    if stages:
        # Con etapas el CTA duro NO va en todos: cada guion cierra según su etapa (ver PLAN).
        cta_budget_block = (
            "CTA POR ETAPA (ya definido arriba en el PLAN DE ETAPAS, respétalo): SOLO los guiones "
            f"BOFU terminan con la frase EXACTA \"{CTA_OBLIGATORIO}\"; los TOFU cierran SUAVE "
            "('te dejo el link', 'búscalo') y los MOFU con CTA medio ('mira las reseñas', "
            "'decídelo tú') — a TOFU y MOFU NO les metas la contraentrega ni el 'pagas al recibir'.\n"
            "Cada guion: SOLO el VOICEOVER hablado completo y fluido, con el LARGO que su etapa pide "
            "en el plan (~2.5 palabras por segundo). El BOFU gasta ~17 palabras en su CTA duro, así "
            "que su cuerpo va más apretado; TOFU y MOFU tienen más aire porque su cierre es corto. "
            "Reparte cada guion así — hook ≤12, problema/mecanismo ≤14, giro+producto/demo ≤16, "
            "prueba ≤10 — y si un beat no cabe, FUSIÓNALO o elimínalo TÚ conscientemente (mejor 3 "
            "momentos bien desarrollados que 6 telegramas). Sin emojis, sin overlays ni acotaciones "
            "de escena, listo para narrar de corrido.\n")
    else:
        cta_budget_block = (
            f"OBLIGATORIO: TERMINA cada guion con esta frase EXACTA como cierre (cópiala igual, sin "
            f"cambiar ni una palabra): \"{CTA_OBLIGATORIO}\".\n"
            f"Cada guion: SOLO el VOICEOVER hablado completo y fluido, de ENTRE {max(20, max_words - 12)} "
            f"y {max_words} palabras TOTALES (CTA incluido — cuéntalas: {max_words} ≈ "
            f"{int(target_seconds)}s hablados). El CTA fijo ya gasta 17 de esas palabras: reparte el "
            f"CUERPO restante (~{max(20, max_words - 17)} palabras) así — hook ≤12, problema ≤12, "
            "giro+producto ≤16, prueba ≤8. Si un beat no cabe en ese presupuesto, FUSIÓNALO o elimínalo "
            "TÚ conscientemente (mejor 3 momentos bien desarrollados que 6 telegramas). Si te pasas, el "
            "guion se AMPUTA por el final y pierde el momento del producto — inaceptable. Sin emojis, "
            "sin overlays ni acotaciones de escena, listo para narrar de corrido.\n")
    prompt = (
        "Eres el copywriter de Juan para ads de dropshipping (Colombia, COD). Escribes guiones "
        "de VOZ EN OFF que NO suenan a anuncio, usando SU voz real y SUS fórmulas ganadoras.\n\n"
        # EL PRODUCTO VA PRIMERO (bug real: iba al final del prompt y Gemini lo ignoraba —
        # guiones genéricos que no nombraban el producto ni usaban sus datos)
        + (f"=== EL PRODUCTO QUE VENDES (la materia prima de CADA guion) ==={info}\n"
           "=== FIN DEL PRODUCTO ===\n\n" if info.strip() else "")
        + "=== BANCO REAL DE HOOKS, FÓRMULAS Y VOZ DE JUAN + FRAMEWORKS DE ADS GANADORES (úsalo, no inventes genérico). "
          "OJO: donde el FRAMEWORK v3 contradiga al v2 o a las fórmulas viejas (staccato, anclas con cifras, "
          "'Hasta que probé…'), MANDA EL v3 y las reglas de esta TAREA ===\n"
        + framework[:30000] +
        "\n=== FIN DEL BANCO ===\n"
        + bp
        + stage_plan +
        "\n"
        f"TAREA: escribe {n} guiones DISTINTOS para la voz en off de un video de TikTok/Reels de "
        f"~{int(target_seconds)} segundos. " + arco + "PRIMERO elige las 2-3 FAMILIAS de hook del "
        "FRAMEWORK v3 que mejor CALZAN con esta categoría de producto (nunca fuerces un hook que no "
        "le calza a la categoría) y reparte los guiones SOLO entre esas familias, variando además el "
        "NIVEL DE CONSCIENCIA del avatar (no sabe que existe solución / ya probó otras cosas y "
        "desconfía / está comparando opciones). Arco: HOOK → PROBLEMA/agitación (detalle cotidiano) → "
        "GIRO+PRODUCTO → PRUEBA → CTA. "
        f"OJO con el tiempo: a ~{int(target_seconds)}s NO recites las fases a la carrera — FUSIONA "
        "(hook+problema juntos, giro+producto juntos) y desarrolla BIEN 3-4 momentos en vez de 7 "
        "telegramas. Prioriza: hook potente, dolor con detalle, giro+producto, cierre. "
        "DINAMISMO CON FLUIDEZ (clave): el guion debe sonar a una persona CONTÁNDOLE algo a un amigo, "
        "no a titulares sueltos. Alterna frases conversacionales COMPLETAS (como los ganadores: 'No "
        "hablo de ser el más lindo de la sala, hablo del tipo que entra y sin decir nada ya se nota') "
        "con golpes cortos SOLO en la ráfaga del problema o del producto ('No aprieta. No mancha. "
        "Funciona.'). PROHIBIDO el telegrama continuo tipo 'Rollito molesto. Ropa no luce.' — eso está "
        "MAL. Un PERO/Ahora que gira, números concretos, social proof conversacional. "
        "ESPECIFICIDAD OBLIGATORIA (lo que separa un ganador de un guion plano): PROHIBIDAS las frases "
        "de catálogo ('moldea y tonifica', 'sin esfuerzo', 'resultados increíbles', 'pura clase'). Cada "
        "fase lleva UN detalle CONCRETO y cotidiano — dónde, cuándo, qué se siente: 'ese rollito que se "
        "asoma cuando te sientas', 'el jean que ya no cierra a las 6pm', 'te lo pones en 20 segundos "
        "antes de dormir'. El HOOK copia la mecánica exacta del banco (ej. autoridad-revelación lleva su "
        "giro: '…y no, no es la dieta'). "
        "OBLIGATORIO: pasa el test anti-anuncio (la 1ra frase es opinión/mala "
        "noticia/pregunta incómoda, NO el producto; el producto aparece DESPUÉS del gancho); usa la "
        "voz colombiana real de Juan — pero la voz es RITMO y ACTITUD de parcero, no muletillas: "
        "MÁXIMO UN modismo por guion y solo si calza natural ('Oiga', '¡Ojo!', 'Le tengo malas "
        "noticias', 'Y señores'). 'No te voy a mentir' en MÁXIMO 1 guion de TODO el lote, y siempre "
        "concediendo algo negativo REAL primero ('no hace milagros de un día para otro'). "
        "'Es físico y ya' SOLO si el producto es mecánico. "
        "ARRANQUE EN CALIENTE (Manual Maestro): la primera línea entra A MITAD DE PENSAMIENTO, como "
        "si la conversación ya hubiera empezado — JAMÁS 'Hola', 'Hoy te presento' ni saludos. "
        "RE-ENGANCHE: la 2ª fuga de audiencia es en los segundos 5-10 y pasa cuando el guion pivotea "
        "del hook a una LISTA DE FEATURES — después del hook viene dolor con detalle o historia, jamás "
        "ficha técnica. Solo si el video dura 30s o más, mete UN micro-gancho a mitad (pregunta o "
        "giro); bajo 30s NO hay presupuesto para más: un solo gancho y desarrollo fluido. "
        "🛡️ POLÍTICAS Meta/TikTok (OBLIGATORIO): usa el DICCIONARIO ANTI-BANEO del framework — NUNCA "
        "ataques el atributo personal del que ve ('estás gordo/viejo/enfermo'); di lo MISMO con metáfora "
        "o situación ('te levantas sintiéndote como un hipopótamo', 'tu amiguito ya no responde como "
        "antes', 'tu cara dice algo diferente'). Nada de curas absolutas ni % médicos (usa 'ayuda a / "
        "apoya'), nada de promesas de resultado con plazo garantizado (repórtalo: 'muchos lo notan en "
        "pocas semanas'), nada de antes/después corporal explícito. "
        "🏷️ NOMBRA EL PRODUCTO (OBLIGATORIO): cada guion dice el producto UNA vez en el momento "
        "del GIRO/PRODUCTO — jamás en el hook (el hook engancha, no vende). Si la info del "
        "producto trae NOMBRE o MARCA, úsalo EXACTO; si no, el tipo de producto con su atributo "
        "('el aceite de ricino puro', 'el corrector de postura de neopreno'). Y usa 2-3 DETALLES "
        "REALES tomados de la info del producto (ingrediente, beneficio concreto, cómo se usa, para "
        "quién). PROHIBIDO INVENTAR specs, números o mecanismos que NO estén en la info del producto "
        "(inventar '7 minutos al día' o 'luz azul' = queja o baneo): si la info no trae specs, la "
        "especificidad va del lado del DOLOR, que nunca es falsa ('la uña que escondes en la piscina', "
        "'el jean que ya no cierra a las 6pm'), NUNCA del lado del producto. Un guion que podría ser "
        "de CUALQUIER producto del nicho está MAL y se rechaza. "
        "PROHIBIDO mencionar PRECIO, cifras de dinero, pesos, '$' o descuentos con número. Pero el "
        "cierre SÍ puede llevar un ANCLA DE VALOR SIN CIFRAS justo antes del CTA — 'menos de lo que "
        "ya gastaste en cremas que no pasan de la superficie', 'una fracción de lo que vale una sola "
        "cita del especialista' — el ancla comparativa es el cierre que nunca falla en el banco de "
        "Juan; lo prohibido es la CIFRA, no la comparación de valor. "
        + (("🎁 OFERTA 2x1 (OBLIGATORIO EN TODOS LOS GUIONES, no es opcional): justo ANTES del CTA "
            "final, TODOS los guiones dicen la oferta de forma natural y clara — que al pedir uno se "
            "lleva OTRO completamente GRATIS ('y hoy por pedir uno te llevas el segundo gratis', 'están "
            "de 2x1: pides uno y llegan dos'). SIN decir precio ni cifras. Un guion sin la mención del "
            "2x1 se rechaza. " if not stages else
            "🎁 OFERTA 2x1 (SOLO en los guiones BOFU, es una oferta dura de cierre): en los guiones "
            "BOFU, justo ANTES del CTA final, menciona que al pedir uno se lleva OTRO GRATIS ('y hoy "
            "por pedir uno te llevas el segundo gratis'). En TOFU y MOFU NO va la oferta 2x1 (romperían "
            "su temperatura). SIN decir precio ni cifras. ")
           if oferta_2x1 else "")
        + cta_budget_block
        + "LISTA NEGRA DE TICS DE IA (si aparece UNO, ese guion se rechaza): 'Hasta que probé/llegó/"
        "descubrí…', '¿Te imaginas…?', 'Dile adiós a…', 'Es hora de…', 'Olvídate de…', el 'no es X, "
        "es Y' encadenado, y el paralelismo triple ('sin A, sin B, sin C') más de una vez en el lote.\n"
        "ESCRIBE EL VOICEOVER CORRIDO PRIMERO, como se narra en una sola respiración, y SOLO DESPUÉS "
        "pártelo en fases para el campo 'fases' — JAMÁS escribas fase por fase y las pegues (queda "
        "telegráfico).\n"
        "EJEMPLO DE GUION PERFECTO a 25s (63 palabras exactas — copia su NIVEL y su fluidez, NO su "
        "contenido):\n"
        '{"angulo":"regalo a mamá","fases":{"hook":"Le compré este tapete a mi mamá y ya no me lo '
        'devuelve.","problema":"Vivía trapeando el charco de la ducha a diario.","giro":"Resulta que '
        'es piedra diatomita:","producto":"lo pisas empapado y la huella desaparece en segundos.",'
        '"prueba":"Ella ahora lo pisa solo por verlo secarse. Extrañamente satisfactorio.",'
        '"cta":"Por tu compra hoy te regalamos el envío, y para tu seguridad ante estafas pagas al '
        'recibir."},"texto":"Le compré este tapete a mi mamá y ya no me lo devuelve. Vivía trapeando '
        'el charco de la ducha a diario. Resulta que es piedra diatomita: lo pisas empapado y la '
        'huella desaparece en segundos. Ella ahora lo pisa solo por verlo secarse. Extrañamente '
        'satisfactorio. Por tu compra hoy te regalamos el envío, y para tu seguridad ante estafas '
        'pagas al recibir."}\n'
        "Por qué es perfecto: hook de familiar (patrón récord del dataset +1M: 15% likes/plays), cero "
        "specs inventadas ('piedra diatomita' sale de la info del producto), UN solo toque de la voz "
        "de Juan, fluye de corrido y el CTA entra sin latigazo.\n"
        "Devuelve SOLO un JSON válido (array) con esta forma exacta (fases = el MISMO texto partido por "
        "fase del arco, para que el editor sepa qué es cada parte):\n"
        '[{"angulo":"nombre del hook usado",'
        '"fases":{"hook":"...","problema":"...","giro":"...","producto":"...","prueba":"...","cta":"..."},'
        '"texto":"el voiceover hablado completo de corrido"}, ...]'
    )

    # LISTÓN DE CALIDAD (queja de Juan: "los guiones no me convencen, les falta atracción"):
    prompt += (
        "\n🔥 LISTÓN FINAL antes de entregar cada guion: (1) el HOOK debe provocar '¿QUÉ? a ver...' "
        "en 1 segundo — si es tibio, reescríbelo con más riesgo (mala noticia más dura, pregunta "
        "más incómoda, dato más impactante); (2) cada guion lleva UN momento MEMORABLE que se pueda "
        "citar de memoria (metáfora visual extrema, número hiperespecífico, giro inesperado — como "
        "'te levantas sintiéndote como un hipopótamo' o 'con 50 mil pesos le clonan la señal'); "
        "(3) léelo en voz alta mentalmente: si suena a locutor y no a un parcero contándote un "
        "chisme bueno, reescríbelo. Prefiere lo ARRIESGADO a lo correcto.")

    # 1º Claude (el mejor copywriter disponible — mismo cerebro de los ads de imagen);
    # si no hay key o falla → Gemini (comportamiento anterior).
    data = None
    claude_err = None
    if ak:
        try:
            from anthropic import Anthropic
            tool = {
                "name": "entregar_guiones",
                "description": "Entrega los guiones de voz en off.",
                "input_schema": {
                    "type": "object",
                    "properties": {"guiones": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "angulo": {"type": "string"},
                            "fases": {"type": "object"},
                            "texto": {"type": "string"},
                        },
                        "required": ["angulo", "texto"],
                    }}},
                    "required": ["guiones"],
                },
            }
            resp = Anthropic(api_key=ak).messages.create(
                model="claude-opus-4-8", max_tokens=8000,
                tools=[tool], tool_choice={"type": "tool", "name": "entregar_guiones"},
                messages=[{"role": "user", "content": prompt}])
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use" and block.name == "entregar_guiones":
                    data = list(block.input.get("guiones", []))
                    break
        except Exception as e:  # noqa: BLE001
            claude_err = e
            data = None

    if data is None:
        if client is None:
            # Claude era el ÚNICO motor disponible y falló: error explícito con el motor REAL
            # (antes: [] silencioso y el front culpaba a Gemini).
            raise RuntimeError("Claude no pudo escribir los guiones — "
                               + error_amigable(claude_err, "Claude"))
        contents = [prompt]
        if sample_seg is not None:
            fb = _frame_bytes(sample_seg)
            if fb:
                contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))
        try:
            resp = client.models.generate_content(model=_MODEL, contents=contents)
            m = re.search(r"\[.*\]", resp.text or "", re.DOTALL)
            if not m:
                raise RuntimeError("Gemini respondió sin guiones válidos (reintenta).")
            data = json.loads(m.group(0))
        except RuntimeError:
            raise
        except Exception as e:
            quien = ("Claude y Gemini fallaron escribiendo los guiones — "
                     if claude_err is not None else "Gemini no pudo escribir los guiones — ")
            raise RuntimeError(quien + error_amigable(e))

    out = []
    lst = data if isinstance(data, list) else []
    for i, d in enumerate(lst):
        if isinstance(d, dict) and d.get("texto"):
            # ETAPA de este guion (por índice del PLAN); sin embudo → None y CTA duro como siempre.
            stage = stages[i] if (stages and i < len(stages)) else None
            cta_mode = _STAGES_META[stage]["cta_mode"] if stage else "hard"
            mw = _stage_max_words(stage, target_seconds) if stage else max_words
            # recorte por FASES primero (respeta hook/producto/CTA); si no hay desglose,
            # recorte ciego por frases + CTA de la etapa
            crudo = str(d["texto"]).strip()[:900]
            texto = None
            if len(crudo.split()) > int(mw * 1.35):
                texto = _ajustar_por_fases(d, mw, cta_mode)
            item = {"angulo": str(d.get("angulo", ""))[:40],
                    "texto": texto or _ajustar_largo(crudo, mw, cta_mode)}
            if stage:
                item["stage"] = stage
                item["temp"] = _STAGES_META[stage]["temp"]
            f = d.get("fases")
            if isinstance(f, dict):   # desglose por fase (hook/problema/giro/producto/prueba/cta)
                item["fases"] = {k: str(v)[:220] for k, v in f.items() if isinstance(v, str) and v.strip()}
            out.append(item)
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
