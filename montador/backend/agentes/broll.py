"""broll.py — Agente 🤖: buscador de B-ROLLS de stock (Pexels/Pixabay).

La voz en off a veces menciona conceptos VISUALES que el usuario no tiene en sus clips
(metáforas: "inflamada como un hipopótamo" → un hipopótamo; menciones: "las cucarachas se
meten a tu casa" → cucarachas en una cocina). Este agente:
  1. detectar_necesidades() → UNA llamada a Claude que lee todos los beats y propone
     b-rolls SOLO para esos conceptos ajenos al producto (el producto SIEMPRE se muestra
     con las tomas del usuario — regla de Jack).
  2. buscar_y_bajar()      → busca en Pexels Videos (y Pixabay de respaldo) y baja el
     mejor candidato: vertical (o el más cercano), duración >= la del beat, archivo
     más liviano que cumpla >=720p. Si nada BUENO → se salta (mejor el clip principal
     que un b-roll malo).
  3. integrar()            → mete los bajados a clips_map/catálogo con ids "B1","B2"…
     para que el plan de montaje los vea (y los use SOLO en su beat sugerido).

La lógica de parseo de las dos APIs está portada de backend/pipeline/stock_broll.py de
la Super-APP (la resolvió Juan) — autocontenida aquí, sin importar del repo padre.

Keys: PEXELS_API_KEY / PIXABAY_API_KEY del entorno (el run.sh del Montador carga su .env);
si no están, se rescatan del .env del repo padre (la key pegada en 🔑 Claves de la
Super-APP sirve para ambos). Ambas APIs son GRATIS (key instantánea).

Contrato de agentes: nada de aquí debe tumbar el pipeline — el llamador envuelve todo
en try/except y sigue sin b-rolls si algo truena.
"""
import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]        # …/montador
_PEXELS = "https://api.pexels.com/videos/search"
_PIXABAY = "https://pixabay.com/api/videos/"
_UA = {"User-Agent": "Mozilla/5.0"}
_MARGEN = 0.8      # s extra sobre la dur del beat: que el editor corte cómodo (in + dur <= clip - 0.5)
_MIN_BYTES = 10_000  # una descarga más chica que esto es un error disfrazado, no un video


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


def buscar_y_bajar(necesidades, workdir, log=print):
    """Para cada necesidad busca en Pexels → Pixabay y baja el mejor candidato a
    workdir/brolls/broll_<beat>_<slug>.mp4. Devuelve {beat_n: {concepto,query,fuente,file,…}}.
    Sin keys → {} con aviso claro. Si una búsqueda no da nada BUENO → se salta
    (regla de Jack: mejor el clip principal que un b-roll malo). Lo ya bajado se reusa."""
    out = {}
    if not necesidades:
        return out
    px, pb = _keys()
    if not (px or pb):
        log("🎞️ Agente B-roll: falta PEXELS_API_KEY (gratis en pexels.com/api) "
            "o PIXABAY_API_KEY — sigo sin b-rolls")
        return out
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

        cand, fuente = None, ""
        if px:
            cand, fuente = _buscar_pexels(q, px, dur_min), "pexels"
        if cand is None and pb:
            cand, fuente = _buscar_pixabay(q, pb, dur_min), "pixabay"
        if cand is None:
            log(f"🎞️ B-roll «{q}» (beat {beat}): nada BUENO en los bancos "
                "— mejor tu clip principal que un b-roll malo, lo salto")
            continue
        try:
            if not _bajar(cand["url"], destino):
                destino.unlink(missing_ok=True)
                log(f"🎞️ B-roll «{q}» (beat {beat}): la descarga llegó vacía — lo salto")
                continue
        except Exception as ex:  # noqa: BLE001
            destino.unlink(missing_ok=True)
            log(f"🎞️ B-roll «{q}» (beat {beat}): la descarga falló ({ex}) — lo salto")
            continue
        info = {"concepto": str(nec.get("concepto") or q), "query": q, "fuente": fuente,
                "w": cand["w"], "h": cand["h"], "dur": cand["dur"]}
        meta[str(beat)] = info
        out[beat] = {**info, "file": str(destino)}
        log(f"🎞️ B-roll bajado: «{info['concepto']}» para el beat {beat} "
            f"({fuente}, {cand['w']}x{cand['h']}, {cand['dur']:.0f}s)")
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
