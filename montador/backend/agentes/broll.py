"""broll.py — Agente 🤖: buscador de B-ROLLS de stock (Pexels/Pixabay).

La voz en off a veces menciona conceptos VISUALES que el usuario no tiene en sus clips
(metáforas: "inflamada como un hipopótamo" → un hipopótamo; menciones: "las cucarachas se
meten a tu casa" → cucarachas en una cocina). Este agente:
  1. detectar_necesidades() → UNA llamada a Claude que lee todos los beats y propone
     b-rolls SOLO para esos conceptos ajenos al producto (el producto SIEMPRE se muestra
     con las tomas del usuario — regla de Jack).
  2. buscar_y_bajar()      → CADENA DE FUENTES por cada necesidad:
       (a) Pexels si hay key   → limpio, va primero
       (b) Pixabay si hay key  → respaldo limpio
       (c) TikTok vía tikwm     → GRATIS, SIN KEY, SIEMPRE disponible (fallback que garantiza
           b-roll aunque Jack no tenga ninguna key). OJO: TikTok devuelve mucha basura
           (memes/comedia/ads), así que cada clip bajado se VERIFICA con Claude frame a
           frame ("¿este frame muestra CLARAMENTE un hipopótamo real?") y SOLO se usa si
           el juez dice muestra=true. Si nada BUENO en ninguna fuente → se salta (mejor el
           clip principal que un b-roll malo — regla de Jack).
  3. integrar()            → mete los bajados a clips_map/catálogo con ids "B1","B2"…
     para que el plan de montaje los vea (y los use SOLO en su beat sugerido).

La lógica de parseo de las dos APIs está portada de backend/pipeline/stock_broll.py de
la Super-APP (la resolvió Juan) — autocontenida aquí, sin importar del repo padre.

Keys: PEXELS_API_KEY / PIXABAY_API_KEY del entorno (el run.sh del Montador carga su .env);
si no están, se rescatan del .env del repo padre (la key pegada en 🔑 Claves de la
Super-APP sirve para ambos). Ambas APIs son GRATIS (key instantánea). Si NO hay ninguna
key, TikTok (tikwm) entra como fuente sin key — por eso el b-roll SIEMPRE tiene una opción.

El juez Claude para verificar los clips de TikTok se INYECTA como parámetro (claude, model)
desde pipeline.py (usa su _claude()/_model()) — así este agente no se acopla al SDK ni a la
config del Montador. Sin juez (claude=None) o si el juez falla/timeout → no se aprueba ningún
TikTok (best-effort: mejor sin b-roll que meter basura sin verificar).

Contrato de agentes: nada de aquí debe tumbar el pipeline — el llamador envuelve todo
en try/except y sigue sin b-rolls si algo truena.
"""
import base64
import json
import os
import re
import subprocess
import threading
import time
import unicodedata
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]        # …/montador
_PEXELS = "https://api.pexels.com/videos/search"
_PIXABAY = "https://pixabay.com/api/videos/"
_TIKWM = "https://tikwm.com/api/feed/search"        # búsqueda de TikTok GRATIS, sin key ni login
_UA = {"User-Agent": "Mozilla/5.0"}
_MARGEN = 0.8      # s extra sobre la dur del beat: que el editor corte cómodo (in + dur <= clip - 0.5)
_MIN_BYTES = 10_000  # una descarga más chica que esto es un error disfrazado, no un video
_TIK_MAX_CAND = 5    # cuántos candidatos de TikTok bajar+verificar por necesidad (tope de costo/tiempo)


# ---------------------------------------------------------------- utils locales
def _slug(s, maxlen=24):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen] or "broll"


def _parse_json(texto):
    """Parse robusto: pela el fence markdown, recorta al primer [/{ … último ]/} y si
    aun así truena, rescata los objetos {...} válidos uno a uno (JSON truncado)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", texto, re.S)
    if m:
        texto = m.group(1)
    try:
        i = min([x for x in [texto.find("["), texto.find("{")] if x >= 0], default=0)
        j = max(texto.rfind("]"), texto.rfind("}"))
        return json.loads(texto[i:j + 1])
    except Exception:
        objs = []
        for mm in re.finditer(r"\{(?:[^{}]|\{[^{}]*\})*\}", texto):
            try:
                objs.append(json.loads(mm.group(0)))
            except Exception:
                continue
        return objs


def _ffprobe(path):
    """Medidas reales del archivo bajado (no confiamos en lo que declara la API)."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height",
                            "-show_entries", "format=duration",
                            "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=15)
        d = json.loads(r.stdout or "{}")
        st = (d.get("streams") or [{}])[0]
        return {"w": int(st.get("width") or 0), "h": int(st.get("height") or 0),
                "dur": float((d.get("format") or {}).get("duration") or 0)}
    except Exception:
        return {"w": 0, "h": 0, "dur": 0.0}


def _leer_env_padre(nombre):
    """Rescata una key del .env del repo padre (Super-APP): la key pegada en la pestaña
    🔑 Claves de la Super-APP sirve también para el Montador."""
    try:
        for linea in (BASE.parent / ".env").read_text().splitlines():
            linea = linea.strip()
            if linea.startswith(nombre + "="):
                return linea.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _keys():
    px = os.environ.get("PEXELS_API_KEY", "").strip() or _leer_env_padre("PEXELS_API_KEY")
    pb = os.environ.get("PIXABAY_API_KEY", "").strip() or _leer_env_padre("PIXABAY_API_KEY")
    return px, pb


# ---------------------------------------------------------------- 1) detección (Claude)
DETECTAR_SYS = (
    "Eres director de arte de video ads de dropshipping (español LATAM). Te doy los BEATS "
    "de una voz en off y la descripción del PRODUCTO que vende el ad. Detecta qué beats "
    "mencionan un CONCEPTO VISUAL CONCRETO ajeno al producto que se ilustraría mejor con un "
    "b-roll de banco de video (metáforas: «inflamada como un hipopótamo» → hipopótamo; "
    "menciones: «las cucarachas se meten a tu casa» → cucarachas en una cocina).\n"
    "REGLAS DURAS:\n"
    "- JAMÁS propongas b-roll para beats que hablan del PRODUCTO, de su uso o de sus "
    "beneficios directos: el producto SIEMPRE se muestra con las tomas del usuario.\n"
    "- Máximo 1 b-roll por beat y como MÁXIMO 1 por cada 3 beats del total (el ad no puede "
    "volverse un collage de stock). Elige solo los conceptos MÁS potentes.\n"
    "- 'query_en': la búsqueda para el banco, en INGLÉS, de 1 a 3 palabras (los bancos "
    "indexan mejor en inglés). Concreta y filmable ('hippopotamus', 'cockroach kitchen').\n"
    "- Solo conceptos FILMABLES (animal, objeto, escena real). Nada abstracto ('confianza').\n"
    "- Si ningún beat lo amerita, devuelve [].\n"
    "Devuelve SOLO JSON:\n"
    '[{"beat_n":3,"concepto":"hipopótamo","query_en":"hippopotamus","motivo":"metáfora de hinchazón"}]'
)


def detectar_necesidades(beats, product_desc, claude, model):
    """UNA llamada a Claude sobre TODOS los beats → [{beat_n, concepto, query_en, motivo, dur}].
    Lista vacía si nada amerita b-roll. El tope de ~1 por cada 3 beats se refuerza en código."""
    user = ("PRODUCTO DEL AD (jamás propongas b-roll para esto): " + str(product_desc)[:400] +
            "\n\nBEATS DE LA VOZ:\n" +
            json.dumps([{"n": b["n"], "dur": b["dur"], "dice": b["texto"]} for b in beats],
                       ensure_ascii=False))
    r = claude.messages.create(model=model, max_tokens=1500, system=DETECTAR_SYS,
                               messages=[{"role": "user", "content": user}])
    texto = "\n".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    data = _parse_json(texto)

    # refuerzo en código de las reglas duras (por si el modelo se emociona)
    dur_by_n = {b["n"]: b["dur"] for b in beats}
    # ~1 b-roll por cada 3 beats (que no se vuelva un collage); piso de 2 para
    # ads cortos donde 2 conceptos potentes sí caben (ej. hipopótamo + cucarachas)
    tope = max(2, len(beats) // 3)
    limpio, vistos = [], set()
    for item in (data if isinstance(data, list) else []):
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("beat_n"))
        except (TypeError, ValueError):
            continue
        q = " ".join(str(item.get("query_en", "")).strip().split()[:3])  # 1-3 palabras
        if n not in dur_by_n or n in vistos or not q:
            continue
        limpio.append({"beat_n": n,
                       "concepto": str(item.get("concepto") or q).strip()[:60],
                       "query_en": q,
                       "motivo": str(item.get("motivo", "")).strip()[:100],
                       "dur": dur_by_n[n]})
        vistos.add(n)
        if len(limpio) >= tope:
            break
    return limpio


# ---------------------------------------------------------------- 2) bancos de stock
def _elegir_pexels(videos, dur_min):
    """Mejor candidato de Pexels: duración >= dur_min (obligatorio — si es más largo no
    importa, el editor corta), VERTICAL primero (o el más cercano por ratio h/w), y entre
    los archivos del video el más liviano que cumpla >=720p (si lo hay)."""
    mejor, mejor_orden = None, None
    for v in videos or []:
        dur = float(v.get("duration") or 0)
        if dur < dur_min:
            continue
        vfs = [vf for vf in (v.get("video_files") or [])
               if vf.get("link") and "mp4" in (vf.get("file_type") or "video/mp4")]
        if not vfs:
            continue
        vw, vh = int(v.get("width") or 0), int(v.get("height") or 0)
        ratio = (vh / vw) if vw else 0.0
        # vertical gana; entre iguales, el más cercano a vertical; luego el más corto (descarga liviana)
        orden = (1 if vh > vw else 0, ratio, -dur)
        if mejor_orden is not None and orden <= mejor_orden:
            continue

        def _rank_vf(vf):
            w, h = int(vf.get("width") or 0), int(vf.get("height") or 0)
            hd = min(w, h) >= 720
            # HD gana; entre HD el de MENOR área (más liviano); sin HD, el de mayor área
            return (1, -(w * h)) if hd else (0, w * h)

        vf = max(vfs, key=_rank_vf)
        mejor = {"url": vf["link"], "w": int(vf.get("width") or 0),
                 "h": int(vf.get("height") or 0), "dur": dur}
        mejor_orden = orden
    return mejor


def _buscar_pexels(query, key, dur_min):
    """Pexels Videos API (parseo portado de stock_broll.py de Juan). None si nada bueno."""
    try:
        r = requests.get(_PEXELS, headers={"Authorization": key, **_UA},
                         params={"query": query, "orientation": "portrait", "per_page": 5},
                         timeout=20)
        if r.status_code != 200:
            return None
        return _elegir_pexels(r.json().get("videos") or [], dur_min)
    except Exception:  # noqa: BLE001 — red caída = sin candidato, no error
        return None


def _elegir_pixabay(hits, dur_min):
    """Mejor candidato de Pixabay: mismo criterio que Pexels. Cada hit trae variantes
    tiny/small/medium/large (todas el mismo encuadre): la más liviana que cumpla >=720p."""
    mejor, mejor_orden = None, None
    for hit in hits or []:
        dur = float(hit.get("duration") or 0)
        if dur < dur_min:
            continue
        cands = [v for v in (hit.get("videos") or {}).values() if v.get("url")]
        if not cands:
            continue

        def _rank_var(v):
            w, h = int(v.get("width") or 0), int(v.get("height") or 0)
            hd = min(w, h) >= 720
            peso = int(v.get("size") or (w * h))
            return (1, -peso) if hd else (0, peso)

        v = max(cands, key=_rank_var)
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        ratio = (h / w) if w else 0.0
        orden = (1 if h > w else 0, ratio, -dur)
        if mejor_orden is None or orden > mejor_orden:
            mejor = {"url": v["url"], "w": w, "h": h, "dur": dur}
            mejor_orden = orden
    return mejor


def _buscar_pixabay(query, key, dur_min):
    """Pixabay Videos API (respaldo cuando Pexels no da nada bueno). None si nada bueno."""
    try:
        r = requests.get(_PIXABAY, headers=_UA,
                         params={"key": key, "q": query, "per_page": 5, "safesearch": "true"},
                         timeout=20)
        if r.status_code != 200:
            return None
        return _elegir_pixabay(r.json().get("hits") or [], dur_min)
    except Exception:  # noqa: BLE001
        return None


def _bajar(url, destino):
    """Descarga en streaming. True solo si quedó un archivo con pinta de video."""
    with requests.get(url, headers=_UA, stream=True, timeout=90) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return destino.exists() and destino.stat().st_size > _MIN_BYTES


# ---------------------------------------------------------------- 2b) TikTok (tikwm, GRATIS)
# Pacer GLOBAL portado de backend/pipeline/tiktok_search.py de Juan: tikwm gratis aguanta
# ~1 request/segundo; si se llama en paralelo devuelve code=-1 "Free Api Limit" (que el código
# viejo confundía con "0 resultados"). Este lock serializa TODAS las llamadas a ~1/s y reintenta
# con backoff si igual rebota. Aquí el b-roll llama en serie, pero el pacer lo deja a prueba de balas.
_TK_LOCK = threading.Lock()
_TK_INTERVALO = 1.05          # segundos entre requests a tikwm (el límite gratis es 1/s)
_tk_ultimo = 0.0


def _tk_get(params, timeout=25, reintentos=2):
    """GET a tikwm RESPETANDO su límite gratis (1 req/s global) + retry con backoff.
    Devuelve el JSON con code=0, o {} si tras los reintentos sigue fallando."""
    global _tk_ultimo
    for intento in range(reintentos + 1):
        with _TK_LOCK:                       # pausa global: nadie dispara antes de tiempo
            espera = _tk_ultimo + _TK_INTERVALO - time.time()
            if espera > 0:
                time.sleep(espera)
            _tk_ultimo = time.time()
        try:
            r = requests.get(_TIKWM, params=params, headers=_UA, timeout=timeout)
            j = r.json() or {}
        except Exception:  # noqa: BLE001 — timeout / red / JSON roto → reintento
            j = None
        if j is not None and j.get("code") == 0:
            return j
        if intento < reintentos:             # rate-limit (code=-1) o error → backoff y otra vez
            time.sleep(1.2 * (intento + 1))
    return {}


def _variantes_tik(query):
    """Variantes de búsqueda para TikTok (el inglés corto rinde más): la query tal cual y,
    si tiene ≥2 palabras, su 1ª palabra sola (más amplia, más candidatos)."""
    q = " ".join(str(query).split())
    pal = q.split()
    out = [q]
    if len(pal) >= 2 and pal[0].lower() not in {x.lower() for x in out}:
        out.append(pal[0])
    return out[:2]


def _tiktok_candidatos(query, dur_min):
    """Candidatos de b-roll desde tikwm (gratis). Filtra Colombia (regla de Jack) y sin mp4.
    Ordena: los que cumplen la duración del beat primero, luego los de más views."""
    cands, vistos = [], set()
    for q in _variantes_tik(query):
        j = _tk_get({"keywords": q, "count": 20, "cursor": 0})
        for v in (j.get("data") or {}).get("videos") or []:
            vid = str(v.get("video_id") or "")
            play = v.get("play") or ""            # mp4 directo (para bajar y verificar)
            if not (vid and play) or vid in vistos:
                continue
            if (v.get("region") or "").upper() == "CO":
                continue
            vistos.add(vid)
            cands.append({"url": play, "dur": float(v.get("duration") or 0),
                          "plays": int(v.get("play_count") or 0),
                          "title": (v.get("title") or "")[:120]})
        if len(cands) >= 14:
            break
    # dur >= la del beat primero (si no, el editor no tiene de dónde cortar), luego más virales
    cands.sort(key=lambda c: (0 if c["dur"] >= dur_min else 1, -c["plays"]))
    return cands


def _frames_b64(video_path, fracs=(0.35, 0.7)):
    """Extrae 1-2 frames del video (a esas fracciones) como JPG base64 para el juez visual.
    Usa el mismo patrón que pipeline.extraer_frames (ffmpeg directo). Lista vacía si no se pudo."""
    med = _ffprobe(video_path)
    dur = med["dur"] or 0.0
    out = []
    for k, fr in enumerate(fracs):
        t = max(0.1, dur * fr) if dur > 0 else 0.5
        tmp = Path(video_path).parent / f".vf_{k}.jpg"
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
                            "-i", str(video_path), "-frames:v", "1",
                            "-vf", "scale=480:-2", str(tmp)],
                           capture_output=True, timeout=20)
            if tmp.exists() and tmp.stat().st_size > 0:
                out.append(base64.standard_b64encode(tmp.read_bytes()).decode())
        except Exception:  # noqa: BLE001
            pass
        finally:
            tmp.unlink(missing_ok=True)
    return out


VERIF_SYS = (
    "Eres un verificador VISUAL MUY estricto de b-roll para video ads de dropshipping. Te doy "
    "1-2 frames sacados de un video de TikTok y un CONCEPTO. Di si el video MUESTRA CLARAMENTE "
    "ese concepto REAL en escena — no un meme, no un dibujo/animación, no un montaje de texto, "
    "no una persona hablando a cámara SOBRE el tema, no un producto distinto. "
    "Ej: concepto «hipopótamo» → muestra=true SOLO si se ve un hipopótamo real; concepto "
    "«cucarachas en la cocina» → true SOLO si se ven cucarachas reales. "
    "Ante CUALQUIER duda → muestra=false (mejor descartar un bueno que colar basura). "
    'Responde SOLO JSON: {"muestra":true/false,"motivo":"máx 6 palabras"}'
)


def _verificar_concepto(frames_b64, concepto, claude, model):
    """Juez Claude: ¿los frames muestran CLARAMENTE el concepto? Devuelve {muestra,motivo} o
    None si no se pudo verificar (sin juez, sin frames, error o timeout) → el caller NO aprueba."""
    if not (frames_b64 and claude and model):
        return None
    try:
        content = [{"type": "text",
                    "text": f"CONCEPTO a verificar: «{concepto}». ¿Los frames lo muestran CLARAMENTE?"}]
        for b in frames_b64:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": b}})
        r = claude.messages.create(model=model, max_tokens=200, system=VERIF_SYS,
                                   messages=[{"role": "user", "content": content}],
                                   timeout=25.0)   # tope duro: jamás cuelga el montaje
        texto = "\n".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        d = _parse_json(texto)
        if isinstance(d, list):
            d = d[0] if d else {}
        if not isinstance(d, dict):
            return None
        return {"muestra": bool(d.get("muestra")), "motivo": str(d.get("motivo", ""))[:80]}
    except Exception:  # noqa: BLE001 — API caída/timeout → best-effort, no se aprueba
        return None


def _tiktok_broll_verificado(concepto, query, dur_min, destino, claude, model, log, beat):
    """FALLBACK GRATIS (sin key): busca en TikTok, baja hasta _TIK_MAX_CAND candidatos y los
    VERIFICA con Claude frame a frame. Se queda con el PRIMERO que de verdad muestra el concepto
    (lo deja en `destino` y devuelve {w,h,dur}). None si ninguno pasa (→ no se mete b-roll)."""
    if not (claude and model):
        log(f"🎞️ B-roll «{query}» (beat {beat}): sin juez Claude no verifico TikTok — lo salto")
        return None
    cands = _tiktok_candidatos(query, dur_min)
    if not cands:
        log(f"🎞️ B-roll «{query}» (beat {beat}): TikTok no devolvió candidatos — lo salto")
        return None
    bajados = 0
    for c in cands[:_TIK_MAX_CAND]:
        try:
            if not _bajar(c["url"], destino):
                destino.unlink(missing_ok=True)
                continue
        except Exception:  # noqa: BLE001 — descarga fallida → siguiente candidato
            destino.unlink(missing_ok=True)
            continue
        bajados += 1
        med = _ffprobe(destino)
        if med["dur"] <= 0:                       # descarga corrupta
            destino.unlink(missing_ok=True)
            continue
        veredicto = _verificar_concepto(_frames_b64(destino), concepto, claude, model)
        if veredicto and veredicto["muestra"]:
            log(f"🎞️ B-roll: busqué «{concepto}» en TikTok → {bajados} bajado(s), 1 verificado ✅ "
                f"({veredicto.get('motivo', '')})")
            return {"w": med["w"], "h": med["h"], "dur": med["dur"]}
        destino.unlink(missing_ok=True)           # no muestra el concepto → fuera, probar el siguiente
    log(f"🎞️ B-roll: «{concepto}» — bajé {bajados} de TikTok, ninguno mostró el concepto, "
        "dejo el clip del producto")
    destino.unlink(missing_ok=True)
    return None


def buscar_y_bajar(necesidades, workdir, log=print, claude=None, model=None):
    """Para cada necesidad recorre la CADENA DE FUENTES: Pexels (si key) → Pixabay (si key) →
    TikTok vía tikwm (GRATIS, sin key, con verificación dura por Claude), y baja el mejor
    candidato a workdir/brolls/broll_<beat>_<slug>.mp4.
    Devuelve {beat_n: {concepto,query,fuente,file,…}} con fuente ∈ {pexels,pixabay,tiktok}.
    Sin keys de stock → cae directo a TikTok (por eso el b-roll SIEMPRE tiene opción). Si nada
    BUENO en ninguna fuente → se salta (regla de Jack: mejor el clip principal que un b-roll
    malo). `claude`/`model` = juez que verifica los clips de TikTok. Lo ya bajado se reusa."""
    out = {}
    if not necesidades:
        return out
    px, pb = _keys()
    if not (px or pb):
        log("🎞️ Agente B-roll: sin PEXELS_API_KEY/PIXABAY_API_KEY — uso TikTok (gratis) "
            "con verificación por Claude")
    bdir = Path(workdir) / "brolls"
    bdir.mkdir(parents=True, exist_ok=True)
    meta_path = bdir / "bajados.json"
    try:
        meta = json.load(open(meta_path)) if meta_path.exists() else {}
    except Exception:
        meta = {}

    for nec in necesidades:
        try:
            beat = int(nec["beat_n"])
        except (KeyError, TypeError, ValueError):
            continue
        q = str(nec.get("query_en", "")).strip()
        if not q:
            continue
        dur_min = float(nec.get("dur", 2.0)) + _MARGEN
        destino = bdir / f"broll_{beat:02d}_{_slug(q)}.mp4"

        # cache: en ajustes/reintentos no se vuelve a buscar ni a bajar
        prev = meta.get(str(beat))
        if prev and destino.exists() and destino.stat().st_size > _MIN_BYTES:
            out[beat] = {**prev, "file": str(destino)}
            log(f"🎞️ B-roll del beat {beat} ya estaba bajado ({prev.get('fuente', '?')}) — reusado")
            continue

        concepto = str(nec.get("concepto") or q)
        # (a) Pexels y (b) Pixabay PRIMERO cuando hay key (stock limpio y ya relevante).
        cand, fuente = None, ""
        if px:
            cand, fuente = _buscar_pexels(q, px, dur_min), "pexels"
        if cand is None and pb:
            cand, fuente = _buscar_pixabay(q, pb, dur_min), "pixabay"

        if cand is not None:
            # STOCK: bajar el mp4 elegido (no necesita verificación: viene etiquetado por el banco).
            try:
                if not _bajar(cand["url"], destino):
                    destino.unlink(missing_ok=True)
                    log(f"🎞️ B-roll «{q}» (beat {beat}): la descarga de {fuente} llegó vacía — lo salto")
                    continue
            except Exception as ex:  # noqa: BLE001
                destino.unlink(missing_ok=True)
                log(f"🎞️ B-roll «{q}» (beat {beat}): la descarga de {fuente} falló ({ex}) — lo salto")
                continue
            w, h, durc = cand["w"], cand["h"], cand["dur"]
        else:
            # (c) TikTok GRATIS como fallback: baja candidatos y los VERIFICA con Claude; si
            # ninguno muestra de verdad el concepto → devuelve None y no se mete nada.
            tik = _tiktok_broll_verificado(concepto, q, dur_min, destino, claude, model, log, beat)
            if tik is None:
                continue   # ya logueó por qué (mejor el clip del producto que un b-roll malo)
            fuente, w, h, durc = "tiktok", tik["w"], tik["h"], tik["dur"]

        info = {"concepto": concepto, "query": q, "fuente": fuente,
                "w": w, "h": h, "dur": durc}
        meta[str(beat)] = info
        out[beat] = {**info, "file": str(destino)}
        log(f"🎞️ B-roll listo: «{concepto}» para el beat {beat} "
            f"({fuente}, {w}x{h}, {durc:.0f}s)")
    try:
        with open(meta_path, "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- 3) integración
def integrar(beats, clips_map, catalogo, necesidades_bajadas):
    """Mete los b-rolls bajados a clips_map (ids 'B1','B2'…) y al catálogo (entrada que
    dice qué son y para qué beat). Devuelve la lista de b-rolls con medidas REALES
    (ffprobe) para clips_info y estado.json — los corruptos se descartan aquí."""
    btxt = {b["n"]: b["texto"] for b in beats}
    # normalizar keys a int (si vienen de un JSON releído llegan como str)
    bajadas = {int(k): v for k, v in necesidades_bajadas.items()}
    brolls = []
    for beat in sorted(bajadas):
        info = bajadas[beat]
        path = Path(info["file"])
        medidas = _ffprobe(path)
        if medidas["dur"] <= 0:
            continue   # descarga corrupta: fuera (jamás al render)
        bid = f"B{len(brolls) + 1}"
        clips_map[bid] = path
        catalogo.append({
            "id": bid,
            "desc": (f"B-ROLL de apoyo: {info.get('concepto', '')} — SOLO para el beat {beat}, "
                     f"ilustra: «{btxt.get(beat, '')[:90]}»"),
            "tipo": "ambiente", "momentos": [], "texto_en_pantalla": "", "conflicto": "",
            "sujeto": "otro", "producto_visible": False, "watermark": "", "calidad": "alta",
        })
        brolls.append({"id": bid, "beat": int(beat),
                       "concepto": str(info.get("concepto", "")),
                       "query": str(info.get("query", "")),
                       "file": "/".join(path.parts[-3:]),   # work/brolls/… (relativo al proyecto)
                       "fuente": str(info.get("fuente", "")),
                       "path": path,
                       "dur": medidas["dur"], "w": medidas["w"], "h": medidas["h"]})
    return brolls
