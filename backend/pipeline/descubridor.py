"""🧭 Descubridor de productos GANADORES — vista segmentada sobre el Radar.

Descubrimiento de productos NUEVOS que ganan en OTROS mercados (el usuario NO sube foto).
Se apoya 100% en los datos que YA calcula el Radar (radar_api._candidatos_completos):
ganadores de la Meta Ad Library por país + sourcing (Dropi/importación/maquila) +
saturación en Colombia. Aquí NO se escanea nada ni se gastan créditos de ScrapeCreators.

Flujo (descubrir):
  1. Lee los candidatos del último escaneo. Si no hay escaneo → error HONESTO (sin_datos),
     nunca inventa productos.
  2. Filtra por VERTICAL (gadgets|nutra): solo nichos y países de esa vertical + regla
     del ganador (>= min_dias activos en Meta, default 20). Prioridad de países y respaldo.
  3. Descarta los SATURADOS en Colombia (a una lista `quemados` aparte, el solucionador
     los muestra como "parece ganador pero está quemado en CO").
  4. Agrupa en SEGMENTOS por sourcing (dropi / importacion / maquila) según la vertical.
  5. UN agente Gemini (estudio + solucionador) da veredicto fresco/entrando/quemado y,
     para nutra, un "vehículo" alterno (misma necesidad, otro formato). Si Gemini falla o
     no hay key → heurística simple + aviso honesto.
  6. Garantiza min_por_segmento (5): si hay menos, marca `pocos` con nota honesta.

Best-effort: JAMÁS lanza al caller. Cualquier fallo del Radar → error honesto.
"""
from __future__ import annotations

import json
import os
import re

from . import gemini_fast
from .ia_errors import error_amigable

_MODEL = "gemini-2.5-flash"
_CLAUDE = "claude-opus-4-8"

# Etiquetas amables por acción (el front las pinta; duplicadas allá, aquí solo de referencia).
_ACCIONES = ("testear_ya", "importar", "fabricar_marca", "vigilar", "descartar_quemado")

# Rutas: este archivo vive en backend/pipeline/ ; la raíz del repo está 2 niveles arriba.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RADAR_CONFIG = os.path.join(_ROOT, "radar", "config.json")
_PATRON_MD = os.path.join(_ROOT, "assets", "patron-ganador-validado.md")

# Etiquetas visibles por segmento y vertical (las pinta el front tal cual).
_LABELS = {
    "gadgets": {
        "dropi": "🟦 Catálogo público (Dropi) — vender ya",
        "importacion": "🟧 Importación — traerlo",
    },
    "nutra": {
        "dropi": "🟦 En Dropi — listos para testear",
        "maquila": "🟪 Marca propia / fabricar",
    },
}
# Segmento por defecto cuando el candidato aún no tiene etiqueta de sourcing.
_DEFAULT_SEG = {"gadgets": "importacion", "nutra": "maquila"}


def _cargar_config_vertical(vertical: str) -> dict | None:
    """Bloque `verticales[vertical]` de radar/config.json (+ max_competidores_co)."""
    try:
        with open(_RADAR_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    v = (cfg.get("verticales") or {}).get(vertical)
    if not isinstance(v, dict):
        return None
    return {
        "nichos": list(v.get("nichos") or []),
        "paises_prioridad": list(v.get("paises_prioridad") or []),
        "paises_respaldo": list(v.get("paises_respaldo") or []),
        "max_competidores_co": int(cfg.get("max_competidores_co", 2) or 2),
    }


def _brief_patron() -> str:
    """Resumen corto del patrón ganador para aterrizar el veredicto de la IA."""
    try:
        txt = open(_PATRON_MD, encoding="utf-8").read()
        # Nos quedamos con la definición operativa del ganador (primeras líneas útiles).
        return txt.strip()[:900]
    except Exception:  # noqa: BLE001
        return ("Un producto GANADOR lleva 20-30+ días activo en la Meta Ad Library y ESCALA "
                "variaciones del creativo (varias versiones del mismo anuncio corriendo a la vez). "
                "Si lleva mucho tiempo Y muchas variaciones, ya está maduro (entrando/quemado).")


def _segmento_de(c: dict, vertical: str) -> tuple[str, bool]:
    """(segmento, sourcing_pendiente) para un candidato según su etiqueta de sourcing."""
    etiqueta = (c.get("sourcing") or "").strip().lower()
    validos = set(_LABELS.get(vertical, {}).keys())
    if etiqueta in validos:
        return etiqueta, False
    # Sin etiqueta (o etiqueta que no aplica a esta vertical) → default sensato + flag.
    return _DEFAULT_SEG.get(vertical, "importacion"), True


def _competidores_co(c: dict) -> int:
    try:
        return int(c.get("competidores") or 0)
    except (TypeError, ValueError):
        return 0


def _esta_quemado(c: dict, max_comp: int) -> bool:
    """Saturado en Colombia = estado 'saturado' O más competidores CO que el tope."""
    if (c.get("comp_estado") or "").strip().lower() == "saturado":
        return True
    return _competidores_co(c) > max_comp


def _item_base(c: dict, vertical: str) -> dict:
    """ITEM de salida (campos estables para el front) a partir de un candidato del Radar."""
    seg, pendiente = _segmento_de(c, vertical)
    item = {
        "clave": c.get("clave"),
        "nombre": c.get("pagina") or "(sin nombre)",
        "pais": c.get("pais") or "",
        "nicho": c.get("nicho") or "",
        "dias": int(c.get("dias") or 0),
        "variaciones": int(c.get("variaciones") or 0),
        "score": int(c.get("score") or 0),
        "segmento": seg,
        "competidores_co": _competidores_co(c),
        "estado_co": (c.get("comp_estado") or "").strip().lower(),
        "veredicto": "",
        "por_que": "",
        # El solucionador (Claude) rellena estos dos; sin anthropic_key quedan vacíos (compatibilidad).
        "accion": "",
        "nota": "",
        # calcular_candidatos expone la media como img/video (no media_img/media_video):
        "media_img": c.get("img") or c.get("media_img") or "",
        "media_video": c.get("video") or c.get("media_video") or "",
        "link": c.get("link") or c.get("ad_library") or "",
    }
    if pendiente:
        item["sourcing_pendiente"] = True
    return item


def _prompt_estudio(items: list[dict], vertical: str) -> str:
    """UNA llamada: veredicto por producto (+ vehículo alterno solo en nutra)."""
    lineas = []
    for i, it in enumerate(items):
        lineas.append(
            f"{i}. \"{it['nombre']}\" | nicho {it['nicho']} | país {it['pais']} | "
            f"{it['dias']} días activo | {it['variaciones']} variaciones del creativo | "
            f"{it['competidores_co']} competidores en Colombia")
    extra_nutra = ""
    if vertical == "nutra":
        extra_nutra = (
            '  - "vehiculo": para CADA producto, la MISMA necesidad resuelta en OTRO formato/vehículo '
            "más fácil de vender o fabricar (ej. colágeno en cápsulas → colágeno en café; magnesio en "
            "pastilla → en gomitas). 4-10 palabras. Es una sugerencia de marca propia.\n")
    return (
        "Eres un cazador de productos ganadores para dropshipping COD en Colombia. Analiza esta lista "
        "de productos que YA están corriendo anuncios en la Meta Ad Library de otros mercados.\n\n"
        "QUÉ ES UN GANADOR (guíate por esto):\n" + _brief_patron() + "\n\n"
        f"PRODUCTOS (vertical: {vertical}):\n" + "\n".join(lineas) + "\n\n"
        "Para CADA producto (por su número) decide:\n"
        '  - "veredicto": "fresco" (ganador joven, hay ventana para entrar), "entrando" (madurando, '
        'aún se puede pero apúrate) o "quemado" (muy maduro/saturado, riesgo alto).\n'
        '  - "por_que": 1 frase corta y concreta (por qué ese veredicto, en español).\n'
        + extra_nutra +
        "Reglas: 20-30 días con variaciones subiendo = fresco/entrando; 45+ días y muchas variaciones = "
        "entrando/quemado; muchos competidores en Colombia = más cerca de quemado.\n"
        "Responde SOLO un JSON array, un objeto por producto EN ORDEN:\n"
        '[{"i":0,"veredicto":"fresco","por_que":"..."'
        + (',"vehiculo":"..."' if vertical == "nutra" else "") + "}]"
    )


def _heuristica(it: dict) -> str:
    """Veredicto sin IA: mucho tiempo + muchas variaciones = maduro/riesgo."""
    if it["dias"] >= 45 and it["variaciones"] >= 3:
        return "entrando"
    if it["dias"] >= 60:
        return "quemado"
    return "fresco"


def _aplicar_ia(items: list[dict], vertical: str, gemini_key: str | None) -> str | None:
    """Rellena veredicto/por_que/vehiculo en `items` (in-place). Devuelve un aviso si falló la IA."""
    if not items:
        return None
    if not gemini_key:
        for it in items:
            it["veredicto"] = _heuristica(it)
            it["por_que"] = "Estimado por longevidad y variaciones (sin IA: falta la key de Gemini)."
        return "Sin key de Gemini: los veredictos son un estimado por días activos y variaciones."
    texto = gemini_fast.generate(gemini_key, [_prompt_estudio(items, vertical)], model=_MODEL)
    if not texto:
        motivo = gemini_fast.ultimo_error
        for it in items:
            it["veredicto"] = _heuristica(it)
            it["por_que"] = "Estimado por longevidad y variaciones (la IA no respondió)."
        return error_amigable(motivo, "Gemini")
    try:
        m = re.search(r"\[.*\]", texto, re.DOTALL)
        data = json.loads(m.group(0)) if m else []
    except Exception:  # noqa: BLE001
        data = []
    por_idx = {}
    if isinstance(data, list):
        for j, d in enumerate(data):
            if isinstance(d, dict):
                idx = d.get("i", j)
                try:
                    idx = int(idx)
                except (TypeError, ValueError):
                    idx = j
                por_idx[idx] = d
    for i, it in enumerate(items):
        d = por_idx.get(i, {})
        ver = str(d.get("veredicto", "")).strip().lower()
        it["veredicto"] = ver if ver in ("fresco", "entrando", "quemado") else _heuristica(it)
        it["por_que"] = str(d.get("por_que", "")).strip()[:200] or "—"
        if vertical == "nutra":
            veh = str(d.get("vehiculo", "")).strip()[:120]
            if veh:
                it["vehiculo"] = veh
    return None


_SOLUCIONADOR_TOOL = {
    "name": "resolver",
    "description": "Decisión final de sourcing/acción para cada producto descubierto (mercado Colombia).",
    "input_schema": {
        "type": "object",
        "properties": {
            "productos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "i": {"type": "integer", "description": "índice del producto en la lista"},
                        "accion": {"type": "string",
                                   "enum": list(_ACCIONES),
                                   "description": "qué hacer con el producto"},
                        "nota": {"type": "string",
                                 "description": "1 frase accionable en español (por qué esa acción)"},
                        "es_falso_ganador": {"type": "boolean",
                                             "description": "true si PARECE ganador pero en realidad está quemado/saturado en Colombia o es un espejismo (muchos competidores CO, muy viejo con señales cayendo, o marca grande)"},
                    },
                    "required": ["i", "accion", "nota", "es_falso_ganador"],
                },
            },
        },
        "required": ["productos"],
    },
}


def _solucionador_claude(items: list[dict], vertical: str, anthropic_key: str | None) -> dict:
    """SEGUNDO agente (Claude Opus, más fuerte): revisa TODO el lote con todas sus señales y da la
    decisión final por producto: `accion` ∈ _ACCIONES, `nota` accionable y `es_falso_ganador` (parece
    ganador pero está quemado/saturado o es un espejismo).

    UNA sola llamada sobre todo el lote (forced tool-use, mismo patrón que tiktok_search._verificar_claude).
    Devuelve {index: {accion, nota, es_falso_ganador}}. Ante CUALQUIER fallo o sin key → {} (nunca lanza)."""
    if not (items and anthropic_key):
        return {}
    try:
        lineas = []
        for i, it in enumerate(items):
            veh = f" | vehículo alterno sugerido: {it['vehiculo']}" if it.get("vehiculo") else ""
            lineas.append(
                f"{i}. \"{it.get('nombre', '')}\" | segmento sourcing: {it.get('segmento', '')} | "
                f"nicho {it.get('nicho', '')} | país origen {it.get('pais', '')} | "
                f"{it.get('dias', 0)} días activo en Meta | {it.get('variaciones', 0)} variaciones del creativo | "
                f"{it.get('competidores_co', 0)} competidores en Colombia | "
                f"estado Colombia: {it.get('estado_co', '') or 'sin dato'} | "
                f"veredicto previo (Gemini): {it.get('veredicto', '') or 'sin dato'}{veh}")
        prompt = (
            "Eres un analista EXPERTO en sourcing de productos para dropshipping COD en el mercado de "
            "COLOMBIA. Tienes enfrente una lista de productos que YA corren anuncios en la Meta Ad Library "
            "de otros mercados, con TODAS sus señales. Tu trabajo es el de un revisor DURO que le pone "
            "precio a cada decisión: detectar el que PARECE ganador pero en realidad está quemado/saturado "
            "en Colombia (muchos competidores CO, o muy viejo con señales cayendo, o una marca grande "
            "difícil de pelear) y decir claro qué hacer con cada uno.\n\n"
            f"PRODUCTOS (vertical: {vertical}):\n" + "\n".join(lineas) + "\n\n"
            "Para CADA producto (por su número) decide:\n"
            '  - "accion": una de: "testear_ya" (ganador fresco, hay ventana, lánzalo ya), '
            '"importar" (vale la pena pero toca traerlo de importación), "fabricar_marca" (mejor marca '
            'propia / maquila para diferenciarte), "vigilar" (aún no, obsérvalo) o "descartar_quemado" '
            "(quemado/saturado, no entres).\n"
            '  - "nota": 1 frase corta, concreta y ACCIONABLE en español (el porqué de la acción).\n'
            '  - "es_falso_ganador": true si PARECE ganador pero realmente está quemado/saturado en '
            "Colombia o es un espejismo (muchos competidores CO, o muy viejo con señales cayendo, o marca "
            "grande); false si es una oportunidad real.\n"
            "Devuelve TODOS los productos, en orden, por la herramienta."
        )
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=2000,
            tools=[_SOLUCIONADOR_TOOL], tool_choice={"type": "tool", "name": "resolver"},
            messages=[{"role": "user", "content": prompt}])
        out: dict[int, dict] = {}
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use" and b.name == "resolver":
                for j, d in enumerate((b.input or {}).get("productos") or []):
                    if not isinstance(d, dict):
                        continue
                    try:
                        idx = int(d.get("i", j))
                    except (TypeError, ValueError):
                        idx = j
                    accion = str(d.get("accion", "")).strip().lower()
                    if accion not in _ACCIONES:
                        accion = "vigilar"
                    out[idx] = {
                        "accion": accion,
                        "nota": str(d.get("nota", "")).strip()[:200],
                        "es_falso_ganador": bool(d.get("es_falso_ganador")),
                    }
        return out
    except Exception:  # noqa: BLE001 — nunca romper el descubridor por el solucionador
        return {}


def descubrir(vertical: str, segmento: str | None = None, *, gemini_key: str | None = None,
              anthropic_key: str | None = None, min_dias: int = 20, min_por_segmento: int = 5,
              progress=None) -> dict:
    """Descubre productos ganadores segmentados sobre los datos del Radar.

    vertical: "gadgets" | "nutra". segmento: opcional, devuelve solo ese segmento.
    Devuelve dict con ok/segmentos/quemados/aviso o un error honesto (nunca lanza)."""
    try:
        vertical = (vertical or "gadgets").strip().lower()
        if vertical not in _LABELS:
            return {"ok": False, "error": f"Vertical desconocida: {vertical}. Usá 'gadgets' o 'nutra'."}
        try:
            min_dias = int(min_dias)
        except (TypeError, ValueError):
            min_dias = 20

        conf = _cargar_config_vertical(vertical)
        if not conf:
            return {"ok": False, "error": "No pude leer la configuración de verticales del Radar "
                    "(radar/config.json). Revisá que exista el bloque 'verticales'."}
        max_comp = conf["max_competidores_co"]

        # 1) Candidatos del Radar (reutiliza toda la infra: sourcing + competencia ya fusionados).
        try:
            import radar_api
            if not radar_api._hay_datos():
                return _sin_datos()
            fecha, cands = radar_api._candidatos_completos()
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "No pude leer los datos del Radar. Andá a 📡 Radar y corré "
                    "'Escanear ahora', o revisá que el módulo del Radar esté instalado.",
                    "sin_datos": True}
        if not cands:
            return _sin_datos()

        # 2) Filtro por vertical: nicho + país + regla de los 20 días.
        nichos = set(conf["nichos"])
        prioridad = conf["paises_prioridad"]
        respaldo = conf["paises_respaldo"]
        paises_ok = set(prioridad) | set(respaldo)

        def _dias(c):
            try:
                return int(c.get("dias") or 0)
            except (TypeError, ValueError):
                return 0

        base = [c for c in cands
                if (c.get("nicho") in nichos)
                and (c.get("pais") in paises_ok)
                and _dias(c) >= min_dias]

        # Preferir países de prioridad; si esos no alcanzan, sumar los de respaldo.
        de_prioridad = [c for c in base if c.get("pais") in set(prioridad)]
        candidatos = de_prioridad if len(de_prioridad) >= min_por_segmento else base

        # 3) Separar quemados en Colombia.
        frescos = [c for c in candidatos if not _esta_quemado(c, max_comp)]
        quemados_raw = [c for c in candidatos if _esta_quemado(c, max_comp)]

        # 4) Agrupar por segmento (según sourcing/etiqueta).
        segs_vertical = list(_LABELS[vertical].keys())
        if segmento:
            segmento = segmento.strip().lower()
            if segmento not in segs_vertical:
                return {"ok": False, "error": f"Segmento '{segmento}' no aplica a la vertical {vertical}."}
            segs_vertical = [segmento]

        por_seg: dict[str, list[dict]] = {s: [] for s in segs_vertical}
        todos_items: list[dict] = []
        for c in frescos:
            it = _item_base(c, vertical)
            if it["segmento"] in por_seg:
                por_seg[it["segmento"]].append(it)
                todos_items.append(it)
        quemados_items = [_item_base(c, vertical) for c in quemados_raw]
        # Ordenar cada segmento por score (mejor primero).
        for s in por_seg:
            por_seg[s].sort(key=lambda x: -x["score"])
        quemados_items.sort(key=lambda x: -x["score"])

        # 5) Agentes de IA — SOLO sobre los MEJORES por score (tope de costo/tiempo): con 40-50
        #    candidatos, mandar todos a Gemini+Claude tardaba 2-3 min y el server se reiniciaba en
        #    medio. El resto recibe el veredicto HEURÍSTICO (rápido, sin API). Los top-N sí llevan el
        #    veredicto de IA + la acción del solucionador.
        _MAX_IA = 18
        if progress:
            progress("Analizando los ganadores con IA...", 45)
        orden_ia = sorted(todos_items + quemados_items, key=lambda x: -x["score"])
        ia_batch, resto = orden_ia[:_MAX_IA], orden_ia[_MAX_IA:]
        aviso = _aplicar_ia(ia_batch, vertical, gemini_key)     # Gemini (veredicto + vehículo) sobre el top-N
        if resto:
            _aplicar_ia(resto, vertical, None)                  # heurística rápida (gemini_key=None) para el resto

        # 5b) SEGUNDO agente (Claude Opus, opcional/key-gated): revisor/solucionador fuerte sobre el
        #     top-N — da la acción final y detecta "falsos ganadores". Aditivo: sin key, todo igual.
        if anthropic_key and ia_batch:
            if progress:
                progress("Revisor final (Claude): acción y falsos ganadores...", 72)
            sol = _solucionador_claude(ia_batch, vertical, anthropic_key)
            if sol:
                todos_ids = {id(x) for x in todos_items}
                falsos_ganadores = []
                for i, it in enumerate(ia_batch):
                    d = sol.get(i)
                    if not d:
                        continue
                    it["accion"] = d["accion"]
                    it["nota"] = d["nota"]
                    # Falso ganador que aún está en un segmento → moverlo a quemados (con su accion/nota).
                    if d["es_falso_ganador"] and id(it) in todos_ids:
                        falsos_ganadores.append(it)
                if falsos_ganadores:
                    fg_ids = {id(x) for x in falsos_ganadores}
                    for s in por_seg:
                        por_seg[s] = [x for x in por_seg[s] if id(x) not in fg_ids]
                    quemados_items.extend(falsos_ganadores)
                    quemados_items.sort(key=lambda x: -x["score"])

        # 6) Armar segmentos con la garantía de min_por_segmento.
        segmentos = {}
        for s in segs_vertical:
            items = por_seg.get(s, [])
            pocos = len(items) < min_por_segmento
            segmentos[s] = {
                "label": _LABELS[vertical][s],
                "items": items,
                "pocos": pocos,
            }
            if pocos:
                segmentos[s]["mensaje"] = (
                    f"Solo {len(items)} producto(s) pasaron el filtro de {min_dias}+ días activos en "
                    "este segmento. No inventamos: corré el Radar seguido para acumular más ganadores.")

        return {
            "ok": True,
            "vertical": vertical,
            "fecha": fecha,
            "segmentos": segmentos,
            "quemados": quemados_items,
            "aviso": aviso,
        }
    except Exception as e:  # noqa: BLE001 — pase lo que pase, error honesto, nunca romper el endpoint
        return {"ok": False, "error": f"No pude descubrir productos ahora: {str(e)[:160]}"}


def _sin_datos() -> dict:
    return {"ok": False, "sin_datos": True,
            "error": "Todavía no hay escaneo del Radar. Andá a 📡 Radar y dale 'Escanear ahora' "
                     "(2-5 min), o corré el escaneo nocturno."}
