"""🤖 Asistente de la app — responde SIEMPRE con el estado REAL del backend, nunca "revisá vos".

Queja real de Jack (2026-07-10): le preguntó a una IA si su búsqueda de creativos tenía
resultados y la IA le contestó "no puedo confirmarte desde mi lado... revisá vos la sección".
INACEPTABLE: el asistente vive EN el mismo proceso que los trabajos → antes de responder,
este módulo junta EVIDENCIA real (jobs en memoria, bitácora de eventos en disco, estado de
las API keys) y con eso responde. Reglas duras:

1. PROHIBIDO responder "no puedo confirmar" o "revisá vos" — la evidencia se mira acá.
2. Si un trabajo FALLÓ → decir QUÉ falló (el error concreto: 429 de Foreplay, key de Gemini
   vencida, timeout...) y qué hacer.
3. Si sigue corriendo → cuánto lleva y cuánto suele tardar (tabla de típicos abajo).
4. Si terminó bien → qué produjo y dónde verlo.
5. Si algo lo excede (key vencida, bug, decisión de negocio) → anota la duda en el puente
   con Claude (`/Users/jaca/Vidaria/data/dudas-superapp.jsonl`) y se lo dice a Jack.
6. Si Gemini mismo está caído, la respuesta determinística (sin IA) IGUAL entrega el estado
   real — el asistente nunca queda mudo ni tira la pelota.

Motor: Gemini flash (el de la app). 100% aditivo: nada del pipeline existente cambia.
"""
from __future__ import annotations

import json
import os
import time

from .ia_errors import error_amigable

# ── puente con Claude (el orquestador del negocio, en la terminal) ───────────────────────
VIDARIA_DIR = "/Users/jaca/Vidaria"
DUDAS_PATH = os.path.join(VIDARIA_DIR, "data", "dudas-superapp.jsonl")
_VIDARIA_ENV = os.path.join(VIDARIA_DIR, ".env")

# ── bitácora de eventos (jobs y búsquedas) que el asistente lee como evidencia ───────────
_EVENTOS = "_eventos.jsonl"          # vive en work/_eventos.jsonl
_EVENTOS_MAX_BYTES = 400_000         # rotación simple: si crece mucho, se quedan las últimas líneas
_EVENTOS_KEEP = 500

# Cuánto SUELE tardar cada tipo de trabajo (minutos, rangos honestos medidos en uso real).
DURACION_TIPICA_MIN = {
    "cortar_clips": (2, 10), "mas_versiones": (2, 8), "render_versiones": (3, 12),
    "guiones": (1, 3), "crear_creativo": (4, 15), "clonar_ganador": (4, 15),
    "reemplazar_producto": (3, 10), "doblaje": (3, 10), "doblaje_traduccion": (1, 3),
    "doblaje_voz": (2, 8), "descargar_videos": (1, 5), "regenerar_version": (1, 5),
    "producto_clips": (2, 8), "foreplay_producto": (2, 6), "foreplay_clips": (3, 12),
    "ads_imagen": (1, 5), "variar_imagen": (1, 4), "variar_hook": (3, 10),
}

TIPO_LEGIBLE = {
    "cortar_clips": "Cortar clips", "mas_versiones": "Más versiones",
    "render_versiones": "Render de versiones (voz/subtítulos)", "guiones": "Guiones",
    "crear_creativo": "Crear creativo (auto)", "clonar_ganador": "Clon con mi producto",
    "reemplazar_producto": "Reemplazar producto", "doblaje": "Doblaje",
    "doblaje_traduccion": "Doblar · paso 1 (traducir)", "doblaje_voz": "Doblar · paso 2 (voz)",
    "descargar_videos": "Descargar videos", "regenerar_version": "Regenerar versión",
    "producto_clips": "Mi producto → clips", "foreplay_producto": "Foreplay: buscar mi producto",
    "foreplay_clips": "Foreplay → clips", "ads_imagen": "Ads de imagen",
    "variar_imagen": "Variar imagen", "variar_hook": "Variar hook",
}


# ══ Bitácora de eventos ═══════════════════════════════════════════════════════════════════

def log_evento(work_dir: str, evento: str, **datos) -> None:
    """Anota un evento (inicio/fin de job, búsqueda con sus conteos, error) en
    work/_eventos.jsonl. Best-effort TOTAL: jamás rompe el flujo que lo llama.
    Ojo: `evento` es el nombre del evento; el tipo de JOB va como kwarg `tipo=`."""
    try:
        path = os.path.join(work_dir, _EVENTOS)
        linea = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "evento": evento}
        for k, v in datos.items():
            if v is not None and v != "":
                linea[k] = v
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")
        # rotación simple para que no crezca sin límite
        if os.path.getsize(path) > _EVENTOS_MAX_BYTES:
            with open(path, encoding="utf-8") as f:
                lineas = f.readlines()
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lineas[-_EVENTOS_KEEP:])
    except Exception:  # noqa: BLE001
        pass


def leer_eventos(work_dir: str, n: int = 40) -> list[dict]:
    """Los últimos n eventos anotados (búsquedas con conteos, jobs iniciados/terminados)."""
    try:
        with open(os.path.join(work_dir, _EVENTOS), encoding="utf-8") as f:
            lineas = f.readlines()[-n:]
        out = []
        for ln in lineas:
            try:
                out.append(json.loads(ln))
            except Exception:  # noqa: BLE001
                pass
        return out
    except Exception:  # noqa: BLE001
        return []


# ══ Snapshot de los trabajos (la evidencia principal) ═════════════════════════════════════

def _resumen_result(result) -> str:
    """Qué produjo un job terminado, contado en criollo ('6 versiones', '3 creativos ok')."""
    if not isinstance(result, dict):
        return ""
    partes = []
    if isinstance(result.get("versions"), list) and result["versions"]:
        partes.append(f"{len(result['versions'])} versiones de video")
    if isinstance(result.get("creativos"), list) and result["creativos"]:
        ok = sum(1 for c in result["creativos"] if isinstance(c, dict) and c.get("ok"))
        partes.append(f"{ok}/{len(result['creativos'])} creativos ok")
    if isinstance(result.get("variantes"), list) and result["variantes"]:
        con_img = sum(1 for v in result["variantes"]
                      if isinstance(v, dict) and (v.get("image") or v.get("path")))
        partes.append(f"{len(result['variantes'])} conceptos" +
                      (f" ({con_img} con imagen)" if con_img else ""))
    for k, nombre in (("clips", "clips"), ("paths", "archivos"), ("items", "items"),
                      ("links", "links"), ("ads", "ads"), ("scripts", "guiones"),
                      ("imagenes", "imágenes"), ("videos", "videos")):
        v = result.get(k)
        if isinstance(v, list) and v:
            partes.append(f"{len(v)} {nombre}")
    if result.get("video"):
        partes.append("1 video final")
    if result.get("resumen"):
        partes.append(str(result["resumen"])[:80])
    if not result.get("ok") and result.get("error"):
        partes.append(f"error: {str(result['error'])[:120]}")
    return " · ".join(dict.fromkeys(partes))     # dedup conservando orden


def snapshot_jobs(jobs: dict, n: int = 15) -> list[dict]:
    """Foto REAL de los últimos n trabajos (los corriendo SIEMPRE incluidos):
    id, tipo, estado, progreso, hace cuánto arrancó, típico, y qué produjo o qué error dio."""
    ahora = time.time()
    items = sorted(jobs.items(), key=lambda kv: kv[1].get("created", 0), reverse=True)
    corriendo = [(k, v) for k, v in items if v.get("status") == "running"]
    resto = [(k, v) for k, v in items if v.get("status") != "running"]
    out = []
    for jid, j in (corriendo + resto)[:n]:
        tipo = j.get("tipo", "")
        d = {
            "job": jid,
            "tipo": TIPO_LEGIBLE.get(tipo, tipo or "trabajo"),
            "estado": j.get("status", ""),
            "progreso_pct": j.get("progress", 0),
            "mensaje": str(j.get("message", ""))[:200],
        }
        creado = j.get("created")
        if creado:
            mins = (ahora - float(creado)) / 60.0
            d["arranco_hace_min"] = round(mins, 1)
            tip = DURACION_TIPICA_MIN.get(tipo)
            if tip and j.get("status") == "running":
                d["suele_tardar_min"] = f"{tip[0]}-{tip[1]}"
                if mins > tip[1] * 2:
                    d["alerta"] = "lleva MÁS del doble de lo típico — puede estar colgado"
        if j.get("status") == "done":
            d["produjo"] = _resumen_result(j.get("result"))
        if j.get("status") == "error":
            d["error"] = str(j.get("message", ""))[:250]
        out.append(d)
    return out


# ══ Puente con Claude (terminal) + aviso urgente por Telegram ═════════════════════════════

def anotar_duda(tema: str, duda: str, contexto: str = "", urgencia: str = "normal") -> bool:
    """Deja una duda/problema anotado para Claude (el orquestador del negocio la lee en sus
    sesiones de terminal y la resuelve). Una línea JSON por duda. True si quedó escrita."""
    try:
        os.makedirs(os.path.dirname(DUDAS_PATH), exist_ok=True)
        linea = {
            "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tema": str(tema or "")[:120],
            "duda": str(duda or "")[:600],
            "contexto": str(contexto or "")[:600],
            "urgencia": urgencia if urgencia in ("baja", "normal", "alta") else "normal",
            "origen": "superapp-asistente",
        }
        with open(DUDAS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001
        return False


def _leer_env_vidaria(nombre: str) -> str:
    try:
        if os.path.exists(_VIDARIA_ENV):
            for line in open(_VIDARIA_ENV):
                if line.startswith(nombre + "="):
                    return line.split("=", 1)[1].strip()
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get(nombre, "")


def notificar_telegram(texto: str) -> bool:
    """Aviso al Telegram del dueño (mismo bot del negocio, @Jacabuenashopbot) para URGENCIAS.
    Best-effort: sin token/chat configurados devuelve False y no pasa nada."""
    try:
        import requests
        token = _leer_env_vidaria("TELEGRAM_BOT_TOKEN")
        chat = _leer_env_vidaria("TELEGRAM_OWNER_IDS").split(",")[0].strip()
        if not (token and chat):
            return False
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": texto[:3500]}, timeout=8)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


# ══ El cerebro: responder con evidencia ═══════════════════════════════════════════════════

_SYS = """Sos el ASISTENTE de CreativeMaxing, la app de creativos de Vidaria (dropshipping COD en LatAm). Hablás con Jack, el dueño. Jack NO es técnico: hablale en criollo, directo, corto y sin jerga.

Abajo te paso la EVIDENCIA REAL del backend, recién mirada: los trabajos (jobs) con su estado/progreso/errores, la bitácora de búsquedas y eventos recientes, y el estado de las API keys. VOS tenés el backend al lado — la evidencia ya está mirada.

REGLAS DURAS (no se negocian):
1. PROHIBIDO decir "revisá vos", "no puedo confirmar desde mi lado", "andá a la sección X a ver". La evidencia la tenés acá abajo: respondé con ella, citando lo concreto (tipo de trabajo, hace cuánto, error exacto).
2. Si un trabajo FALLÓ: decí QUÉ falló con el error concreto de la evidencia (ej: "Foreplay quedó sin créditos (429)", "la key de Gemini está vencida") y qué hacer: si es reintentable (429, timeout, red) decile que le dé de nuevo al botón y listo; si es de key, que la cambie en 🔑 Claves.
3. Si un trabajo SIGUE corriendo: decí cuánto lleva ("arranco_hace_min") y cuánto suele tardar ("suele_tardar_min"). Si tiene "alerta", avisale.
4. Si terminó BIEN: decí qué produjo ("produjo": cuántas versiones/creativos/imágenes) y que los ve en la misma pestaña donde lo lanzó (los videos también quedan en la carpeta work del proyecto).
5. Si el dato que pide NO está en la evidencia (ni en jobs ni en eventos): decí exactamente qué falta y por qué (ej: "esa búsqueda fue antes de que empezáramos a anotar la bitácora" o "el server se reinició y eso no quedó guardado"), y anotá una DUDA para Claude — el orquestador del negocio que corre en la terminal — para que lo resuelva. NUNCA respondas un simple "no sé".
6. Si detectás un problema que te excede (key vencida, bug repetido, decisión de plata): también va como DUDA para Claude, y si es grave marcala urgencia "alta".
7. NADA de inventar números, resultados ni estados. Evidencia o duda anotada. Y nunca muestres API keys.

FORMATO DE SALIDA — devolvé SOLO un JSON (sin backticks):
{"respuesta": "lo que le decís a Jack, en criollo", "duda": null}
o, si hay que escalarle algo a Claude:
{"respuesta": "...", "duda": {"tema": "corto", "duda": "qué hay que resolver", "contexto": "datos útiles", "urgencia": "baja|normal|alta"}}"""


def _extraer_json(texto: str) -> dict | None:
    """Saca el primer objeto JSON válido de la respuesta del modelo (tolera ```json ...```)."""
    if not texto:
        return None
    t = texto.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t.strip("`")
        if t.startswith("json"):
            t = t[4:]
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(t[a:b + 1])
    except Exception:  # noqa: BLE001
        return None


def respuesta_deterministica(evidencia: dict, motivo_ia: str = "") -> str:
    """Respuesta SIN IA con el estado real — para cuando Gemini mismo está caído.
    Aun sin motor, el asistente entrega evidencia: jamás 'no puedo confirmar'."""
    lineas = []
    if motivo_ia:
        lineas.append(f"⚠️ Mi motor de IA no respondió ({motivo_ia}), pero igual te muestro "
                      "el estado REAL que acabo de mirar en el backend:")
    jobs = evidencia.get("jobs") or []
    corriendo = [j for j in jobs if j.get("estado") == "running"]
    if corriendo:
        lineas.append("▶️ Corriendo AHORA:")
        for j in corriendo:
            tip = f" (suele tardar {j['suele_tardar_min']} min)" if j.get("suele_tardar_min") else ""
            lineas.append(f"  • {j['tipo']} — {j.get('progreso_pct', 0)}%, lleva "
                          f"{j.get('arranco_hace_min', '?')} min{tip} — {j.get('mensaje', '')}")
    ultimos = [j for j in jobs if j.get("estado") in ("done", "error")][:5]
    if ultimos:
        lineas.append("🗂 Últimos trabajos:")
        for j in ultimos:
            if j.get("estado") == "done":
                lineas.append(f"  • ✅ {j['tipo']}: {j.get('produjo') or 'terminó bien'}")
            else:
                lineas.append(f"  • ❌ {j['tipo']}: {j.get('error') or j.get('mensaje', 'error')}")
    evs = [e for e in (evidencia.get("eventos_recientes") or []) if e.get("evento") == "busqueda"][-3:]
    if evs:
        lineas.append("🔍 Búsquedas recientes:")
        for e in evs:
            res = []
            if "tiktok" in e:
                res.append(f"{e['tiktok']} de TikTok")
            if "foreplay" in e:
                res.append(f"{e['foreplay']} de Foreplay")
            estado = "ok" if e.get("ok") else f"falló ({e.get('error', 'sin detalle')})"
            lineas.append(f"  • {e.get('t', '')} «{e.get('producto', '')}» → "
                          f"{' + '.join(res) or 'sin resultados'} — {estado}")
    if not (corriendo or ultimos or evs):
        lineas.append("Ahora mismo no hay trabajos corriendo ni terminados en esta sesión, y la "
                      "bitácora no tiene búsquedas recientes. Si lanzaste algo y no aparece, lo más "
                      "probable es que el server se haya reiniciado en el medio: lanzalo de nuevo y "
                      "esta vez queda anotado.")
    ks = evidencia.get("keys") or {}
    problemas = []
    if ks.get("gemini") not in ("ok", None, "desconocido"):
        problemas.append(f"Gemini: {ks['gemini']}")
    fpu = ks.get("foreplay_creditos")
    if isinstance(fpu, dict) and fpu.get("ok") is False:
        problemas.append(f"Foreplay: {fpu.get('error', 'con problemas')}")
    if problemas:
        lineas.append("🔑 Ojo con las llaves: " + " · ".join(problemas) + " (pestaña 🔑 Claves).")
    return "\n".join(lineas)


def responder(mensaje: str, historial: list, evidencia: dict,
              gemini_key: str | None) -> dict:
    """Responde el mensaje de Jack CON la evidencia. Devuelve {respuesta, duda, motor}.
    Si Gemini falla, cae a la respuesta determinística (evidencia igual) y deja la duda
    del motor anotable por el caller."""
    ev_json = json.dumps(evidencia, ensure_ascii=False, default=str)
    hist_txt = ""
    for h in (historial or [])[-10:]:
        if isinstance(h, dict) and h.get("texto"):
            quien = "JACK" if str(h.get("rol", "")).lower() in ("vos", "user", "jack") else "ASISTENTE"
            hist_txt += f"{quien}: {str(h['texto'])[:400]}\n"
    prompt = (f"{_SYS}\n\n══ EVIDENCIA REAL DEL BACKEND (recién consultada) ══\n{ev_json}\n\n"
              + (f"══ CONVERSACIÓN PREVIA ══\n{hist_txt}\n" if hist_txt else "")
              + f"══ MENSAJE DE JACK ══\n{mensaje}\n\nTu JSON:")

    if not gemini_key:
        det = respuesta_deterministica(evidencia, "no hay key de Gemini configurada")
        return {"respuesta": det, "motor": "sin_ia",
                "duda": {"tema": "Key de Gemini faltante",
                         "duda": "El asistente de la SuperApp no tiene key de Gemini para responder con IA.",
                         "contexto": "Pestaña 🔑 Claves sin GEMINI_API_KEY.", "urgencia": "normal"}}

    texto, err = None, None
    # 1) REST rápido (thinkingBudget=0, ~2-5s); 2) SDK como fallback (mismo patrón del resto de la app)
    try:
        from . import gemini_fast
        texto = gemini_fast.generate(gemini_key, [prompt], timeout=45)
    except Exception as e:  # noqa: BLE001
        err = e
    if not texto:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            r = client.models.generate_content(model="gemini-2.5-flash", contents=[prompt])
            texto = r.text
        except Exception as e:  # noqa: BLE001
            err = e
    if not texto:
        motivo = error_amigable(err, "Gemini")
        det = respuesta_deterministica(evidencia, motivo)
        duda = None
        low = str(err or "").lower()
        if any(k in low for k in ("401", "403", "api key", "quota", "429", "exhausted", "spend")):
            duda = {"tema": "Gemini caído en la SuperApp",
                    "duda": f"El asistente no pudo usar Gemini: {motivo}",
                    "contexto": f"Error crudo: {str(err)[:200]}", "urgencia": "alta"}
        return {"respuesta": det, "motor": "sin_ia", "duda": duda}

    data = _extraer_json(texto)
    if not isinstance(data, dict) or not data.get("respuesta"):
        # el modelo no respetó el JSON → su texto igual sirve como respuesta
        return {"respuesta": texto.strip()[:2500], "motor": "gemini", "duda": None}
    duda = data.get("duda")
    if not (isinstance(duda, dict) and str(duda.get("duda", "")).strip()):
        duda = None
    return {"respuesta": str(data["respuesta"])[:2500], "motor": "gemini", "duda": duda}
