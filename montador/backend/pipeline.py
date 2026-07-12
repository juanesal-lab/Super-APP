"""
Montador — pipeline de montaje automático.
Flujo: transcribir voz → catalogar clips (Claude ve frames) → plan de montaje (Claude) →
ensamblar con efectos (ffmpeg zoompan) → karaoke (Pillow) → entregables.
"""
import os, io, json, base64, subprocess, threading, re, unicodedata, traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PROJECTS = BASE / "projects"

# ---------------------------------------------------------------- estado
_LOCKS = {}
def _lock(pid):
    return _LOCKS.setdefault(pid, threading.Lock())

# Semáforo GLOBAL de render: máximo N procesar()/otra_version() a la vez (default 1).
# Los demás quedan "en cola" (y así se ven en la UI) hasta que se libere el turno.
# Subirlo: MONTADOR_RENDERS=2 en el .env (ojo: 2 ffmpeg a la vez exigen bastante CPU).
_RENDER_SEM = threading.Semaphore(max(1, int(os.environ.get("MONTADOR_RENDERS", "1"))))

def _estado_path(pid):
    return PROJECTS / pid / "estado.json"

def leer_estado(pid):
    p = _estado_path(pid)
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)

def _guardar(pid, estado):
    p = _estado_path(pid)
    if not p.parent.exists():
        return  # el proyecto fue eliminado (p.ej. mientras esperaba en cola)
    with open(p, "w") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)

def log(pid, msg, fase=None, progreso=None):
    with _lock(pid):
        e = leer_estado(pid) or {}
        e.setdefault("log", []).append(msg)
        if fase: e["fase"] = fase
        if progreso is not None: e["progreso"] = progreso
        _guardar(pid, e)
    print(f"[{pid}] {msg}", flush=True)

# ---------------------------------------------------------------- utils
def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def ffprobe_info(path):
    r = run(["ffprobe","-v","error","-select_streams","v:0",
             "-show_entries","stream=width,height","-show_entries","format=duration",
             "-of","json",str(path)])
    try:
        d = json.loads(r.stdout)
        st = (d.get("streams") or [{}])[0]
        return {"w": st.get("width",0), "h": st.get("height",0),
                "dur": float(d.get("format",{}).get("duration",0))}
    except Exception:
        return {"w":0,"h":0,"dur":0}

def audio_dur(path):
    r = run(["ffprobe","-v","error","-show_entries","format=duration",
             "-of","default=noprint_wrappers=1:nokey=1",str(path)])
    try: return float(r.stdout.strip())
    except Exception: return 0.0

def slug(s, maxlen=40):
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+","-",s).strip("-").lower()
    return s[:maxlen] or "proyecto"

# ---------------------------------------------------------------- whisper
_WHISPER = None
_WLOCK = threading.Lock()
def _whisper():
    global _WHISPER
    with _WLOCK:
        if _WHISPER is None:
            from faster_whisper import WhisperModel
            _WHISPER = WhisperModel("small", device="cpu", compute_type="int8")
    return _WHISPER

def transcribir(pid, audio_path, workdir):
    wav = workdir / "voz.wav"
    run(["ffmpeg","-y","-loglevel","error","-i",str(audio_path),"-ar","16000","-ac","1",str(wav)])
    model = _whisper()
    segments, info = model.transcribe(str(wav), language="es", word_timestamps=True, beam_size=5)
    segs, words = [], []
    for s in segments:
        segs.append({"start":round(s.start,3),"end":round(s.end,3),"text":s.text.strip()})
        for w in (s.words or []):
            words.append({"w":w.word.strip(),"start":round(w.start,3),"end":round(w.end,3)})
    data = {"duration": round(audio_dur(audio_path),3), "segments":segs, "words":words,
            "texto":" ".join(x["text"] for x in segs)}
    with open(workdir/"transcript.json","w") as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
    return data

# ---------------------------------------------------------------- beats
def _partir_segmento_largo(seg, words, tope=6.0):
    """Un beat >6s = un solo plano eterno (la regla destilada dice frase máx ~4.8s).
    Se parte en la frontera de palabra más cercana al centro, recursivo."""
    dur = seg["end"] - seg["start"]
    if dur <= tope:
        return [seg]
    dentro = [w for w in words if seg["start"] + 0.4 < w["start"] < seg["end"] - 0.4]
    if len(dentro) < 2:
        return [seg]
    medio = (seg["start"] + seg["end"]) / 2
    corte = min(dentro, key=lambda w: abs(w["start"] - medio))
    palabras = seg["text"].split()
    # repartir el texto proporcional al tiempo del corte
    frac = (corte["start"] - seg["start"]) / dur
    k = max(1, min(len(palabras) - 1, round(len(palabras) * frac)))
    a = {"start": seg["start"], "end": corte["start"], "text": " ".join(palabras[:k])}
    b = {"start": corte["start"], "end": seg["end"], "text": " ".join(palabras[k:])}
    return _partir_segmento_largo(a, words, tope) + _partir_segmento_largo(b, words, tope)

def construir_beats(transcript):
    """Cortes = inicios de segmento (primer corte en 0). Segmentos <0.7s se funden con el
    anterior; segmentos >6s se PARTEN en frontera de palabra (ritmo + clips cortos)."""
    segs = [s for s in transcript["segments"] if s["text"].strip()]
    merged = []
    for s in segs:
        if merged and (s["end"]-s["start"]) < 0.7:
            merged[-1] = {**merged[-1], "end":s["end"],
                          "text":merged[-1]["text"]+" "+s["text"]}
        else:
            merged.append(dict(s))
    words = transcript.get("words", [])
    partidos = []
    for s in merged:
        partidos.extend(_partir_segmento_largo(dict(s), words))
    merged = partidos
    total = transcript["duration"]
    beats = []
    for i,s in enumerate(merged):
        t0 = 0.0 if i==0 else merged[i]["start"]
        t1 = merged[i+1]["start"] if i+1 < len(merged) else total
        if t1 - t0 < 0.35:  # seguridad
            t1 = min(total, t0+0.35)
        beats.append({"n":i+1,"t0":round(t0,3),"t1":round(t1,3),
                      "dur":round(t1-t0,3),
                      "seg_start":s["start"],"seg_end":s["end"],"texto":s["text"]})
    return beats

# ---------------------------------------------------------------- frames + Claude
def extraer_frames(clip_path, dur, outdir, cid, tiempos=None):
    """tiempos: lista opcional de segundos exactos (agente momentos); si no, fracciones fijas."""
    if tiempos:
        marcas = [max(0.1, min(t, dur - 0.2)) for t in tiempos]
    else:
        fracs = [0.15,0.45,0.80] if dur <= 60 else [0.08,0.28,0.50,0.72,0.92]
        marcas = [max(0.1, dur*fr) for fr in fracs]
    paths = []
    for i,t in enumerate(marcas):
        p = outdir / f"{cid}_{i}.jpg"
        run(["ffmpeg","-y","-loglevel","error","-ss",str(t),"-i",str(clip_path),
             "-frames:v","1","-vf","scale=320:568:force_original_aspect_ratio=increase,crop=320:568",str(p)])
        if p.exists():
            paths.append((round(t,1), p))
    return paths

def _b64(p):
    with open(p,"rb") as f:
        return base64.standard_b64encode(f.read()).decode()

def _claude():
    import anthropic
    return anthropic.Anthropic()

def _model():
    return os.environ.get("MONTADOR_MODEL","claude-sonnet-5")

def _texto_respuesta(r):
    """Une los bloques de texto (ignora thinking/tool blocks)."""
    partes = [b.text for b in r.content if getattr(b, "type", "") == "text"]
    return "\n".join(partes)

def _parse_json(texto):
    m = re.search(r"```(?:json)?\s*(.*?)```", texto, re.S)
    if m: texto = m.group(1)
    i = min([x for x in [texto.find("["), texto.find("{")] if x >= 0], default=0)
    j = max(texto.rfind("]"), texto.rfind("}"))
    return json.loads(texto[i:j+1])

def _parse_json_tolerante(texto):
    """Rescata los objetos {...} válidos de un JSON roto/truncado (comillas sin escapar,
    corte a mitad de array). Los beats que se pierdan los rellena la validación del plan."""
    objs = []
    for m in re.finditer(r"\{(?:[^{}]|\{[^{}]*\})*\}", texto):
        try:
            objs.append(json.loads(m.group(0)))
        except Exception:
            continue
    return objs

def _es_transitorio(ex):
    """¿Error temporal de la API (saturación/red)? → se reintenta con espera."""
    status = getattr(ex, "status_code", None)
    if status in (429, 500, 502, 503, 504, 529):
        return True
    txt = str(ex).lower()
    return any(s in txt for s in ("overloaded", "rate_limit", "rate limit",
                                  "connection", "timeout", "timed out", "server error"))

def _crear_msg(client, system, msgs, max_tokens, sin_pensar=False, pid=None):
    """Crea el mensaje EN STREAMING (con max_tokens grandes el SDK exige streaming).
    Con sin_pensar=True intenta desactivar el thinking (en prompts gigantes el modelo
    puede gastar TODO el presupuesto pensando y devolver texto VACÍO). Y ante errores
    TRANSITORIOS de la API (Overloaded/529, rate limit, red) reintenta solo con
    backoff 5→15→30→60s en vez de tumbar el proyecto."""
    import random as _rnd, time as _t
    kw = dict(model=_model(), max_tokens=max_tokens, system=system, messages=msgs)
    INTENTOS = 5
    for i in range(INTENTOS):
        try:
            if sin_pensar:
                try:
                    with client.messages.stream(thinking={"type": "disabled"}, **kw) as s:
                        return s.get_final_message()
                except Exception as ex_sp:
                    if _es_transitorio(ex_sp):
                        raise      # que lo maneje el backoff de afuera
                    # el param thinking no existe u otro error de request → sin él
            with client.messages.stream(**kw) as s:
                return s.get_final_message()
        except Exception as ex:
            if not _es_transitorio(ex) or i == INTENTOS - 1:
                raise
            espera = min(60, 5 * (2 ** i)) + _rnd.uniform(0, 3)
            msg = f"⏳ API de Claude saturada (Overloaded); reintento {i+1}/{INTENTOS-1} en {espera:.0f}s…"
            if pid:
                log(pid, msg)
            else:
                print(msg, flush=True)
            _t.sleep(espera)

def _pedir_json(client, system, content, max_tokens=8000, debug_path=None, pid=None):
    """Llama a Claude y parsea JSON con capas: parse estricto → rescate tolerante →
    reintento SIN thinking y con presupuesto grande. (Con 30+ beats el JSON puede llegar
    truncado, con comillas rotas, o directamente vacío si el thinking se comió los tokens.)"""
    def _dbg(texto, intento):
        if debug_path:
            try:
                with open(debug_path, "a") as f:
                    f.write(f"\n===== intento {intento} =====\n{texto}\n")
            except Exception:
                pass
    AVISO = ("\nIMPORTANTE: responde ÚNICAMENTE el array JSON completo, sin explicación ni "
             "markdown. 'razon' de MÁXIMO 6 palabras, sin saltos de línea dentro de strings, "
             "escapa toda comilla doble interna.")
    intentos = [
        {"sin_pensar": False, "max_tokens": max_tokens, "aviso": False},
        {"sin_pensar": True, "max_tokens": max(max_tokens, 24000), "aviso": True},
    ]
    ultimo = ""
    for k, it in enumerate(intentos, 1):
        cont = content
        if it["aviso"]:
            if isinstance(cont, str):
                cont = cont + AVISO
            else:  # contenido multimodal (catálogo): añadir bloque de texto
                cont = list(cont) + [{"type": "text", "text": AVISO}]
        r = _crear_msg(client, system, [{"role": "user", "content": cont}],
                       it["max_tokens"], it["sin_pensar"], pid=pid)
        texto = _texto_respuesta(r)
        _dbg(texto, k)
        ultimo = texto
        try:
            return _parse_json(texto)
        except Exception:
            pass
        objs = _parse_json_tolerante(texto)
        if len(objs) >= 3:   # rescate útil (si salvó casi nada, mejor reintentar)
            return objs
    raise RuntimeError(f"Claude no devolvió JSON usable. Inicio de la respuesta: {ultimo[:200]!r}")

CATALOGO_SYS = (
"Eres director de arte de ads de dropshipping (Meta/TikTok, español LATAM). "
"Te muestro frames de varios clips crudos. Para CADA clip devuelve JSON:\n"
'[{"id":"01","desc":"qué se ve (1 frase)","tipo":"gancho|producto|textura|demo|persona|ambiente|tienda|otro",'
'"momentos":[{"t":seg,"que":"qué pasa ahí"}],"texto_en_pantalla":"texto quemado visible o \'\'",'
'"conflicto":"si el texto quemado incluye precios/medidas/teléfonos/marcas que podrían chocar con un ad, dilo; si no \'\'",'
'"sujeto":"protagonista del clip: perro|gato|bebé|persona|producto|otro (sé específico con la especie del animal)",'
'"producto_visible":true/false (si se ve el producto que se está vendiendo o su empaque),'
'"watermark":"handle o marca de agua visible (@usuario, logo) o \'\'",'
'"calidad":"alta|media|baja"}]\n'
"Los 'momentos' son los timestamps de los frames que te doy (te los indico). SOLO responde el JSON."
)

def catalogar_clips(pid, clips, framesdir, usar_momentos=False):
    """clips: [{id, path, dur, w, h}] -> catálogo con descripciones de Claude.
    usar_momentos: 🤖 agente momentos — detecta los mejores instantes de cada clip
    (movimiento/contenido) y saca los frames AHÍ en vez de en fracciones fijas."""
    mod_mom = None
    if usar_momentos:
        from backend.agentes import cargar
        mod_mom = cargar("momentos")
        if mod_mom is None:
            log(pid, "🤖 Agente momentos marcado pero el módulo no está — uso fracciones fijas")
        else:
            log(pid, "🤖 Agente momentos: buscando los mejores instantes de cada clip…")
    client = _claude()
    catalogo = []
    BATCH = 8
    for bi in range(0, len(clips), BATCH):
        batch = clips[bi:bi+BATCH]
        content = []
        for c in batch:
            tiempos = None
            if mod_mom is not None:
                try:
                    tiempos = mod_mom.candidatos(c["path"], c["dur"])
                except Exception:
                    tiempos = None
            frames = extraer_frames(c["path"], c["dur"], framesdir, c["id"], tiempos=tiempos)
            tlist = ", ".join(f"{t}s" for t,_ in frames)
            content.append({"type":"text","text":
                f"CLIP {c['id']} — dur {c['dur']:.1f}s, {c['w']}x{c['h']}. Frames en: {tlist}"})
            for t,p in frames:
                content.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":_b64(p)}})
        content.append({"type":"text","text":"Devuelve el JSON del catálogo para estos clips."})
        parte = _pedir_json(client, CATALOGO_SYS, content, max_tokens=8000, pid=pid)
        catalogo.extend(parte)
        log(pid, f"👁️  Clips analizados: {min(bi+BATCH,len(clips))}/{len(clips)}")
    return catalogo

PLAN_SYS = (
"Eres editor senior de ads de respuesta directa (dropshipping LATAM, formato 9:16). "
"Recibes: (1) los BEATS de una voz en off (tiempos fijos, no los cambies) y (2) un CATÁLOGO de clips. "
"Asigna a cada beat el clip que mejor ilustre lo que dice la voz EXACTAMENTE en ese momento.\n"
"REGLAS DURAS:\n"
"- JAMÁS repitas un clip en dos beats (regla del cliente). Si hay MÁS beats que clips, "
"reusa primero los clips largos variando MUCHO el 'in' (otra escena del mismo clip, nunca la misma toma).\n"
"- Evita clips cuyo 'conflicto' choque con el ad (precios/medidas/teléfonos ajenos).\n"
"- COHERENCIA DE ESPECIE: identifica de qué especie/sujeto trata el ad por la voz; TODOS los clips "
"de animales deben ser de ESA especie (jamás un gato en un ad de perros), salvo que la voz mencione "
"explícitamente a otro animal en ese beat.\n"
"- NO SPOILEES el producto: los clips con 'producto_visible' SOLO pueden ir en el beat de la "
"revelación (primera fase 'solucion') o después. Antes de eso, jamás se ve el producto.\n"
"- Evita clips con 'watermark' visible si existe alternativa equivalente.\n"
"- Prefiere calidad alta y resolución 1080x1920.\n"
"- El beat 1 es el gancho: el visual más fuerte.\n"
"- Busca matches literales (dice 'lavable' → clip lavando; 'no resbala' → respaldo antideslizante).\n"
"- 'in' es el segundo DENTRO del clip donde empieza el corte; usa los 'momentos' del catálogo; "
"cuida que in + dur_beat <= dur_clip - 0.5.\n"
"- 'fase': la fase narrativa del beat: hook|dolor|solucion|prueba|deseo|precio|cta "
"(el motor de edición decide movimiento y SFX según la fase).\n"
"- 'punch': true SOLO en 1-2 beats de máximo impacto (revelación de producto u oferta). El beat 1 ya lleva punch_hook automático.\n"
"- 'caption': el texto del beat corregido para subtítulo (arregla errores de transcripción, números como $139.900, tildes).\n"
"- 'razon': MÁXIMO 6 palabras. Sin saltos de línea dentro de strings; escapa comillas internas.\n"
"Devuelve SOLO JSON:\n"
'[{"beat":1,"clip":"07","in":16.5,"fase":"hook","punch":false,"caption":"...","razon":"por qué"}]'
)

FASES = {"hook","dolor","solucion","prueba","deseo","precio","cta"}

def plan_montaje(pid, beats, catalogo, clips_info, instrucciones=None, plan_anterior=None,
                 con_emojis=False):
    client = _claude()
    dur_map = {c["id"]: c["dur"] for c in clips_info}
    user = {"beats":[{"n":b["n"],"t0":b["t0"],"t1":b["t1"],"dur":b["dur"],"dice":b["texto"]} for b in beats],
            "catalogo":catalogo,
            "duraciones_clips":dur_map}
    sistema = PLAN_SYS
    if con_emojis:
        sistema += (
            "\n- 'emoji': UN emoji por beat que refuerce el caption (o \"\" si no aporta). "
            "SOLO de esta lista blanca (los demás se ven rotos): "
            "😱 😴 🔥 ✨ 💤 ✅ ❌ ⚠️ 💰 🚚 🛒 ❤️ 😍 🤯 👇 🎁 🧸 🏠 🌙 ⭐"
        )
    extra = ""
    if instrucciones:
        # plan anterior COMPACTO (sin 'razon'): menos entrada = menos thinking = menos
        # riesgo de respuesta vacía/truncada en ajustes de proyectos largos
        prev = [{k: p.get(k) for k in ("beat","clip","in","fase","punch","caption","emoji")}
                for p in (plan_anterior or [])]
        extra = ("\nAJUSTE PEDIDO POR EL CLIENTE (prioridad máxima): " + instrucciones +
                 "\nPLAN ANTERIOR (modifica solo lo necesario): " + json.dumps(prev, ensure_ascii=False))
    plan = _pedir_json(client, sistema,
                       json.dumps(user, ensure_ascii=False) + extra, max_tokens=16000,
                       debug_path=PROJECTS / pid / "work" / "debug_plan.txt", pid=pid)

    # ---- validación dura en código ----
    # Regla del cliente: JAMÁS la misma toma dos veces. Si hay más beats que clips,
    # se reusa el clip MENOS usado y con una ventana de tiempo que no pise las anteriores.
    disponibles = [c["id"] for c in clips_info]
    ventanas = {cid: [] for cid in disponibles}   # cid -> [(in, out)] ya usados
    limpio = []

    # ANTI-SPOILER determinista: clips que muestran el producto NO pueden ir antes de la
    # revelación (primer beat cuya fase ya no es hook/dolor). No depende del modelo.
    producto_clips = {str(c.get("id","")).zfill(2) for c in catalogo if c.get("producto_visible")}
    fases_crudas = {p.get("beat"): str(p.get("fase","")).lower() for p in plan}
    primer_reveal = next((b["n"] for b in beats
                          if fases_crudas.get(b["n"]) not in ("hook","dolor")), None)

    def _sin_pisar(cid, inp, dur):
        """Devuelve un in-point que no solape ventanas previas del clip (o None)."""
        dmax = dur_map.get(cid, 10.0)
        tope = max(0.0, dmax - dur - 0.3)
        candidatos = [max(0.0, min(inp, tope))] + [round(x*0.5,2) for x in range(0, int(tope*2)+1)]
        for c in candidatos:
            if all(c + dur <= a or c >= b_ for a, b_ in ventanas[cid]):
                return c
        return None

    for b in beats:
        item = next((p for p in plan if p.get("beat")==b["n"]), None) or {}
        cid = str(item.get("clip","")).zfill(2)
        inp_sug = float(item.get("in", 0.5))
        if cid not in disponibles:
            cid = None
        # preferir clips vírgenes; si el sugerido ya se usó y hay libres, cambiar
        libres = [x for x in disponibles if not ventanas[x]]
        if cid is None or (ventanas[cid] and libres):
            cid = cid if (cid in libres) else (libres[0] if libres else
                  min(disponibles, key=lambda x: len(ventanas[x])))
        # anti-spoiler: antes de la revelación, jamás un clip con el producto visible
        pre_reveal = primer_reveal is not None and b["n"] < primer_reveal
        if pre_reveal and cid in producto_clips:
            alt = next((x for x in disponibles if x not in producto_clips and not ventanas[x]),
                       None) or next((x for x in disponibles if x not in producto_clips), None)
            if alt:
                cid = alt
        inp = _sin_pisar(cid, inp_sug, b["dur"])
        if inp is None:  # clip lleno: usar el menos usado con espacio
            for alt in sorted(disponibles, key=lambda x: len(ventanas[x])):
                inp = _sin_pisar(alt, 0.5, b["dur"])
                if inp is not None:
                    cid = alt; break
        if inp is None:  # último recurso: aceptar solape
            inp = max(0.0, min(inp_sug, max(0.0, dur_map.get(cid,10.0) - b["dur"] - 0.3)))
        ventanas[cid].append((inp, inp + b["dur"]))
        fase = str(item.get("fase","")).lower()
        if fase not in FASES: fase = "solucion"
        limpio.append({"beat":b["n"],"clip":cid,"in":round(inp,2),"fase":fase,
                       "punch":bool(item.get("punch")),
                       "caption":item.get("caption", b["texto"]).strip(),
                       "emoji":str(item.get("emoji","") or "").strip(),
                       "razon":item.get("razon","")})
    return limpio

# ---------------------------------------------------------------- ensamble
# El ensamble, karaoke y mezcla de audio viven en editor.py (motor PRO v2):
# dissolves 0.17s + cortes casi-duros, ciclo Ken Burns, color grade, loudnorm −18,
# SFX por fase y karaoke por grupos con tiempos reales.
from backend import editor  # noqa: E402

# ---------------------------------------------------------------- guion
def escribir_guion(beats, plan, catalogo, clips_map, outdir, nombre):
    cat = {c["id"]:c for c in catalogo}
    movs = editor.asignar_movimiento(plan)
    rows=[]
    avisos=[]
    for (b,p,m) in zip(beats,plan,movs):
        c = cat.get(p["clip"],{})
        fn = Path(clips_map[p["clip"]]).name
        rows.append(f"| {b['t0']:.2f}–{b['t1']:.2f} | {p['caption']} | {p['clip']} · `{fn}` "
                    f"| {p['in']:.1f}→{p['in']+b['dur']:.1f} | {p['fase']} | {m} | {c.get('desc','')} — {p['razon']} |")
        if c.get("texto_en_pantalla"):
            avisos.append(f"- **{b['t0']:.1f}s (corte {b['n']}):** el clip trae texto quemado: “{c['texto_en_pantalla']}” → tápalo en CapCut si molesta.")
        if c.get("watermark"):
            avisos.append(f"- **{b['t0']:.1f}s (corte {b['n']}):** marca de agua visible: “{c['watermark']}”.")
    md = (f"# 🎬 Guion de montaje — {nombre}\n\n"
          "Motor PRO v2: dissolves 0.17s + cortes casi-duros (1/5), Ken Burns por plano, "
          "color grade, voz −18 LUFS, SFX por fase, karaoke Poppins por grupos.\n\n"
          "| Tiempo | Voz/Subtítulo | Clip | in→out | Fase | Movimiento | Qué se ve · por qué |\n|--|--|--|--|--|--|--|\n"
          + "\n".join(rows) + "\n")
    if avisos:
        md += "\n## ⚠️ Textos ajenos detectados\n" + "\n".join(avisos) + "\n"
    with open(outdir/"guion-montaje.md","w") as f:
        f.write(md)

# ---------------------------------------------------------------- guion visual
def generar_thumbs(pid, beats, pdir):
    """Extrae 1 miniatura (160px de ancho) por beat desde el video final → work/thumbs/."""
    video = pdir / "resultado" / "corte-base.mp4"
    tdir = pdir / "work" / "thumbs"; tdir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for b in beats:
        # mitad del beat: ya pasó la transición de entrada, todavía no empieza la de salida
        t = editor.VOICE_LEAD + (b["t0"] + b["t1"]) / 2.0
        p = tdir / f"beat_{b['n']:02d}.jpg"
        run(["ffmpeg","-y","-loglevel","error","-ss",f"{t:.3f}","-i",str(video),
             "-frames:v","1","-vf","scale=160:-2",str(p)])
        ok += 1 if p.exists() else 0
    log(pid, f"🖼️  Guion visual: {ok}/{len(beats)} miniaturas extraídas")

# ---------------------------------------------------------------- orquestador
def _turno_render(pid):
    """Toma el turno del semáforo global; si está ocupado, marca el proyecto 'en cola'."""
    if not _RENDER_SEM.acquire(blocking=False):
        log(pid, "⏳ Hay otro render en curso; este proyecto queda en cola…", fase="en cola")
        _RENDER_SEM.acquire()

def procesar(pid, instrucciones=None):
    """Corre el pipeline completo (o re-plan si hay instrucciones y caches).
    Respeta el semáforo global: máximo 1 render a la vez."""
    _turno_render(pid)
    try:
        _procesar(pid, instrucciones)
    finally:
        _RENDER_SEM.release()

def _procesar(pid, instrucciones=None):
    pdir = PROJECTS / pid
    if not pdir.exists():
        print(f"[{pid}] proyecto eliminado mientras esperaba en cola; no se procesa", flush=True)
        return
    workdir = pdir / "work"; workdir.mkdir(exist_ok=True)
    framesdir = workdir / "frames"; framesdir.mkdir(exist_ok=True)
    outdir = pdir / "resultado"; outdir.mkdir(exist_ok=True)
    try:
        e = leer_estado(pid)
        nombre = e.get("nombre", pid)
        audio_path = pdir / e["audio"]
        clips_info = []
        clips_map = {}
        for i, fn in enumerate(sorted(e["clips"]), 1):
            cid = f"{i:02d}"
            p = pdir / "clips" / fn
            info = ffprobe_info(p)
            clips_info.append({"id":cid,"path":p,"dur":info["dur"],"w":info["w"],"h":info["h"]})
            clips_map[cid] = p

        # 1. transcripción (cache)
        tpath = workdir/"transcript.json"
        if tpath.exists():
            transcript = json.load(open(tpath))
        else:
            log(pid,"🎙️  Transcribiendo la voz…", fase="transcribiendo", progreso=10)
            transcript = transcribir(pid, audio_path, workdir)
        log(pid, f"📝 Guion detectado: “{transcript['texto'][:110]}…”", progreso=20)

        beats = construir_beats(transcript)
        log(pid, f"🥁 {len(beats)} beats construidos sobre {transcript['duration']:.1f}s de voz", progreso=25)

        agentes = e.get("agentes") or {}

        # 2. catálogo visual (cache propio, o heredado de un hermano del grupo:
        #    mismos clips → mismo catálogo; la llamada cara a Claude se hace UNA vez).
        #    Con renders SIMULTÁNEOS (MONTADOR_RENDERS>1) el candado del grupo hace que
        #    el segundo hermano ESPERE el catálogo del primero en vez de pagarlo doble.
        cpath = workdir/"catalogo.json"
        _gl = _lock("grupo-" + e["grupo"]) if e.get("grupo") else None
        if _gl: _gl.acquire()
        try:
            # 📦 cache de catálogo por PAQUETE de la biblioteca: mismos clips → mismo
            # catálogo, aunque sea otro proyecto/día (cambiar solo el guion sale casi gratis)
            _pkg = e.get("paquete")
            if not cpath.exists() and _pkg:
                pk_cat = BASE / "biblioteca" / _pkg / "catalogo.json"
                pk_clips = sorted(f.name for f in (BASE/"biblioteca"/_pkg/"clips").glob("*")) \
                           if (BASE/"biblioteca"/_pkg/"clips").exists() else []
                if pk_cat.exists() and set(pk_clips) == set(e.get("clips", [])):
                    import shutil as _sh
                    _sh.copy2(pk_cat, cpath)
                    log(pid, f"📦 Catálogo del paquete “{_pkg}” reusado — 0 llamadas extra")
            if not cpath.exists() and e.get("grupo"):
                for otro in PROJECTS.iterdir():
                    if otro.name == pid or not otro.is_dir():
                        continue
                    eo = leer_estado(otro.name)
                    if eo and eo.get("grupo") == e["grupo"] and set(eo.get("clips",[])) == set(e["clips"]):
                        cjson = otro / "work" / "catalogo.json"
                        if cjson.exists():
                            import shutil as _sh
                            _sh.copy2(cjson, cpath)
                            log(pid, f"📚 Catálogo heredado del grupo (lo calculó “{eo.get('nombre','')}” — 0 llamadas extra)")
                            break
            if not cpath.exists():
                log(pid,"👁️  Analizando tus clips (Claude está viendo los frames)…", fase="analizando", progreso=30)
                catalogo = catalogar_clips(pid, clips_info, framesdir,
                                           usar_momentos=agentes.get("momentos", False))
                with open(cpath,"w") as f: json.dump(catalogo,f,ensure_ascii=False,indent=2)
                # guardarlo también en el paquete (si el set de clips coincide exacto)
                if _pkg:
                    pk_dir = BASE / "biblioteca" / _pkg
                    pk_clips = sorted(f.name for f in (pk_dir/"clips").glob("*")) if (pk_dir/"clips").exists() else []
                    if pk_clips and set(pk_clips) == set(e.get("clips", [])):
                        import shutil as _sh
                        _sh.copy2(cpath, pk_dir / "catalogo.json")
                        log(pid, f"📦 Catálogo guardado en el paquete “{_pkg}” (los próximos proyectos con estos clips no lo pagan)")
        finally:
            if _gl: _gl.release()
        catalogo = json.load(open(cpath))
        log(pid, f"📚 Catálogo listo: {len(catalogo)} clips entendidos", progreso=55)

        # 3. plan
        plan_prev = e.get("plan")
        log(pid,"🧠 Armando el plan de montaje…", fase="planeando", progreso=60)
        plan = plan_montaje(pid, beats, catalogo, clips_info,
                            instrucciones=instrucciones, plan_anterior=plan_prev,
                            con_emojis=agentes.get("emojis", False))
        with _lock(pid):
            e2 = leer_estado(pid); e2["plan"] = plan; e2["beats"] = beats; _guardar(pid, e2)

        # 4. ensamble + karaoke + audio (motor PRO v2 + agentes opcionales)
        log(pid,"🎬 Renderizando con el motor PRO v2…", fase="renderizando", progreso=65)
        musica_path = (pdir / e["musica"]) if e.get("musica") else None
        editor.build(outdir, workdir, audio_path, beats, plan, clips_map,
                     transcript.get("words", []), log=lambda m: log(pid, m),
                     musica_path=musica_path,
                     estilo_subs=e.get("estilo_subs", "karaoke"),
                     plataforma=e.get("plataforma", "meta"),
                     opts=agentes)

        # 5. guion visual (miniaturas por beat para la UI)
        generar_thumbs(pid, beats, pdir)

        # 6. guion
        escribir_guion(beats, plan, catalogo, clips_map, outdir, nombre)

        with _lock(pid):
            e3 = leer_estado(pid)
            e3.update({"fase":"listo","progreso":100,"done":True,"error":None,
                       "resultados":["corte-base.mp4","corte-base-SUBS.mp4","guion-montaje.md","subtitulos.srt"]})
            _guardar(pid, e3)
        log(pid,"✅ ¡Listo! Video montado, karaoke y guion generados.")
        # Envío a Telegram (si hay llaves). Nunca rompe el render si falla.
        try:
            from backend import notify
            log(pid, "📤 Enviando el video a Telegram…")
            envios = ["corte-base-SUBS.mp4"]
            # 🤖 agente telegram: comprime a <48MB para que quepa por el bot
            from backend.agentes import cargar
            mod_tg = cargar("telegram_compress")
            if mod_tg is not None:
                try:
                    envios = mod_tg.preparar(pdir, envios, log=lambda m: log(pid, m))
                except Exception as _tex:  # noqa: BLE001
                    log(pid, f"🤖 Agente telegram falló ({_tex}) — mando el original")
            notify.enviar_resultado(pdir, nombre, envios)
        except Exception as _ex:  # noqa: BLE001
            log(pid, f"(Telegram no enviado: {_ex})")
    except Exception as ex:
        traceback.print_exc()
        with _lock(pid):
            e = leer_estado(pid) or {}
            e.update({"fase":"error","done":False,"error":str(ex)})
            _guardar(pid, e)
        log(pid, f"❌ Error: {ex}")

# ---------------------------------------------------------------- otra versión
def otra_version(pid):
    """Re-corre SOLO editor.build con otra semilla (beats/plan cacheados en estado.json,
    SIN llamar a Claude) y guarda los mp4 en resultado/version-N/. Respeta el semáforo."""
    _turno_render(pid)
    try:
        _otra_version(pid)
    finally:
        _RENDER_SEM.release()

def _otra_version(pid):
    pdir = PROJECTS / pid
    if not pdir.exists():
        print(f"[{pid}] proyecto eliminado mientras esperaba en cola; no se procesa", flush=True)
        return
    try:
        e = leer_estado(pid)
        if not e or not e.get("beats") or not e.get("plan"):
            raise RuntimeError("No hay beats/plan cacheados; corre el proyecto completo primero")
        n = max([v["n"] for v in e.get("versiones", [])] or [1]) + 1
        seed = n - 1
        with _lock(pid):
            e2 = leer_estado(pid)
            e2.update({"fase": f"renderizando v{n}", "done": False, "error": None, "progreso": 30})
            _guardar(pid, e2)
        log(pid, f"🎲 Otra versión (v{n}, semilla {seed}): mismo plan, nuevo ritmo de cortes…")
        transcript = json.load(open(pdir / "work" / "transcript.json"))
        clips_map = {f"{i:02d}": pdir / "clips" / fn
                     for i, fn in enumerate(sorted(e["clips"]), 1)}
        outdir = pdir / "resultado" / f"version-{n}"
        workdir = pdir / "work" / f"version-{n}"
        musica_path = (pdir / e["musica"]) if e.get("musica") else None
        editor.build(outdir, workdir, pdir / e["audio"], e["beats"], e["plan"], clips_map,
                     transcript.get("words", []), log=lambda m: log(pid, m), seed=seed,
                     musica_path=musica_path,
                     estilo_subs=e.get("estilo_subs", "karaoke"),
                     plataforma=e.get("plataforma", "meta"),
                     opts=e.get("agentes") or {})
        with _lock(pid):
            e3 = leer_estado(pid)
            e3.setdefault("versiones", []).append(
                {"n": n, "carpeta": f"version-{n}", "semilla": seed,
                 "archivos": ["corte-base.mp4", "corte-base-SUBS.mp4"]})
            e3.update({"fase": "listo", "progreso": 100, "done": True, "error": None})
            _guardar(pid, e3)
        log(pid, f"✅ Versión v{n} lista (resultado/version-{n}/).")
        try:
            from backend import notify
            log(pid, "📤 Enviando la versión a Telegram…")
            envios = [f"version-{n}/corte-base-SUBS.mp4"]
            from backend.agentes import cargar
            mod_tg = cargar("telegram_compress")
            if mod_tg is not None:
                try:
                    envios = mod_tg.preparar(pdir, envios, log=lambda m: log(pid, m))
                except Exception as _tex:  # noqa: BLE001
                    log(pid, f"🤖 Agente telegram falló ({_tex}) — mando el original")
            notify.enviar_resultado(pdir, f"{e.get('nombre', pid)} v{n}", envios)
        except Exception as _ex:  # noqa: BLE001
            log(pid, f"(Telegram no enviado: {_ex})")
    except Exception as ex:
        traceback.print_exc()
        # la versión falló pero el resultado base sigue intacto: no marcamos error global
        with _lock(pid):
            e = leer_estado(pid) or {}
            e.update({"fase": "listo", "done": True, "progreso": 100})
            _guardar(pid, e)
        log(pid, f"❌ La versión alternativa falló: {ex}")

# ================================================================ clonar ganador
import shutil as _shutil

VOCES_11LABS = {"kate": "qWWAqFomnJ99VwQLREfT", "juan_carlos": "G4IAP30yc6c1gK0csDfu"}
_FRAMEWORK_GUIONES = Path.home() / "cortador-clips" / "assets" / "guion-framework.md"

def tts_elevenlabs(texto, voice_key="kate", destino=None):
    """TTS con el patrón de voiceover.py de cortador-clips. Lanza RuntimeError con
    mensaje claro si no hay créditos (quota_exceeded) o la key falla."""
    import requests
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("Falta ELEVENLABS_API_KEY en el .env")
    vid = VOCES_11LABS.get(voice_key, voice_key)
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        json={"text": texto, "model_id": "eleven_multilingual_v2",
              "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.25}},
        timeout=120)
    if r.status_code != 200:
        msg = r.text[:250]
        if "quota_exceeded" in msg:
            raise RuntimeError("ElevenLabs sin créditos — recarga tu plan y dale Reintentar (los guiones ya quedaron guardados)")
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {msg}")
    destino = Path(destino)
    destino.write_bytes(r.content)
    if audio_dur(destino) < 1.0:
        raise RuntimeError("ElevenLabs devolvió un audio inválido")
    return destino

def detectar_tramos_ganador(video, dur):
    """Tramos visuales del ganador por detección de escenas; fallback cortes de 2s; cap 14."""
    r = run(["ffmpeg", "-i", str(video), "-vf", "select='gt(scene,0.25)',showinfo", "-f", "null", "-"])
    ts = sorted(float(m) for m in re.findall(r"pts_time:\s*([0-9.]+)", r.stderr))
    cortes = [0.0]
    for t in ts:
        if 0.4 < t < dur - 0.3 and t - cortes[-1] >= 0.6:
            cortes.append(round(t, 2))
    cortes.append(round(dur, 2))
    tramos = [(a, b) for a, b in zip(cortes[:-1], cortes[1:]) if b - a > 0.15]
    if len(tramos) < 3:  # video sin cortes detectables → tramos uniformes de 2s
        paso = 2.0
        tramos = [(round(i * paso, 2), round(min(dur, (i + 1) * paso), 2))
                  for i in range(int(dur // paso) + 1) if i * paso < dur - 0.2]
    while len(tramos) > 14:  # fusionar el tramo más corto con su vecino
        i = min(range(len(tramos)), key=lambda k: tramos[k][1] - tramos[k][0])
        if i == 0:
            tramos[0] = (tramos[0][0], tramos[1][1]); del tramos[1]
        else:
            tramos[i - 1] = (tramos[i - 1][0], tramos[i][1]); del tramos[i]
    return tramos

ADN_SYS = (
"Eres estratega creativo de ads de dropshipping (español LATAM). Te doy la TRANSCRIPCIÓN "
"con tiempos de un AD GANADOR y un frame de cada tramo visual. Devuelve SOLO JSON:\n"
'{"tramos":[{"i":1,"t0":0.0,"t1":2.4,"que_se_ve":"...","texto_pantalla":"texto/caption visible en pantalla o \'\'",'
'"fase":"hook|dolor|solucion|prueba|deseo|precio|cta"}],'
'"global":{"angulo":"...","producto":"qué producto vende","elementos":["cta_cod","urgencia","precio","social_proof",...],'
'"ritmo":"cortes por segundo aprox y estilo (UGC crudo / pulido)","por_que_gana":"1-2 frases",'
'"recomendacion_audio":"voz|musica — ¿este ad vive de su narración (voz) o de la música + textos en pantalla (musica)? '
'Si no tiene narración real, SIEMPRE musica"}}\n'
"Alinea cada tramo con lo que la voz dice en ese rango. Sé concreto en 'que_se_ve'."
)

def analizar_ganador(pid, video, transcript, workdir):
    """ADN del ganador: tramos visuales (frames→Claude) alineados con su transcript."""
    dur = transcript["duration"]
    tramos = detectar_tramos_ganador(video, dur)
    fdir = workdir / "frames_ganador"; fdir.mkdir(exist_ok=True)
    content = [{"type": "text", "text":
        "TRANSCRIPCIÓN DEL GANADOR (con tiempos):\n" +
        "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in transcript["segments"]) +
        f"\n\nTRAMOS VISUALES ({len(tramos)}): te doy un frame del centro de cada uno, en orden."}]
    for i, (a, b) in enumerate(tramos, 1):
        p = fdir / f"tramo_{i:02d}.jpg"
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str((a + b) / 2), "-i", str(video),
             "-frames:v", "1", "-vf",
             "scale=320:568:force_original_aspect_ratio=increase,crop=320:568", str(p)])
        if p.exists():
            content.append({"type": "text", "text": f"TRAMO {i}: {a:.1f}s → {b:.1f}s"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(p)}})
    content.append({"type": "text", "text": "Devuelve el JSON del ADN."})
    client = _claude()
    data = _pedir_json(client, ADN_SYS, content, max_tokens=8000, pid=pid)
    if isinstance(data, list):  # el parser tolerante puede devolver fragmentos
        data = next((d for d in data if isinstance(d, dict) and "tramos" in d), {"tramos": data, "global": {}})
    data.setdefault("tramos", []); data.setdefault("global", {})
    return data

def _leer_framework():
    try:
        return _FRAMEWORK_GUIONES.read_text()[:30000]
    except Exception:
        return ("Reglas mínimas: hook sin mostrar el producto, arranque en caliente (jamás 'Hola'), "
                "anti-baneo (nada de atacar atributos personales, ni curas absolutas, ni promesas con cifras), "
                "PROHIBIDO decir precios con cifras salvo que el ganador lo haga, números concretos, "
                "CTA único con contra entrega (COD Colombia), máximo 1 modismo colombiano por guion.")

GUIONES_SYS = (
"Eres el copywriter de Juan (dropshipping COD Colombia). Te doy el ADN de un ad GANADOR "
"(estructura por tramos con tiempos, transcripción literal) y su ángulo. Escribe VARIACIONES "
"del guion: FIELES BEAT A BEAT (misma estructura, mismas duraciones por fase ±15%, mismo ángulo) "
"pero con palabras NUEVAS (jamás copies frases literales del ganador). Español colombiano neutro, "
"listo para TTS (sin acotaciones, sin emojis, puntuación natural).\n"
"Sigue SIEMPRE el framework de Juan que va abajo (anti-baneo, hook, CTA COD).\n"
"Devuelve SOLO JSON: [{\"titulo\":\"corto\",\"guion\":\"texto completo para locución\"}]"
)

def _es_musica(transcript):
    """¿El 'transcript' es una alucinación de whisper sobre música? Multi-señal,
    calibrado con casos reales (música: densidad 1.4 w/s, únicas .43, trigrama x3,
    cobertura .57 — voz real: 3.0-3.3 w/s, únicas .74+, trigrama x1, cobertura .83+):"""
    from collections import Counter
    words = [w["w"].lower().strip(".,!?¿¡") for w in transcript.get("words", []) if w.get("w")]
    if len(words) < 8:
        return True
    dur = transcript.get("duration", 0) or 1
    densidad = len(words) / dur                      # voz en off real ≈ 2.5-3.5 palabras/s
    if densidad < 1.8:
        return True
    unicas = len(set(words)) / len(words)
    if unicas < 0.5:                                 # letra en loop
        return True
    tri = [" ".join(words[i:i+3]) for i in range(len(words) - 2)]
    if tri and max(Counter(tri).values()) >= 3:      # misma frase 3+ veces
        return True
    hablado = sum(s["end"] - s["start"] for s in transcript.get("segments", []))
    return (hablado / dur) < 0.4                     # la "voz" cubre poco del video

def generar_guiones_variacion(pid, adn, transcript, n, modo_musica=False, debug_path=None):
    client = _claude()
    dur = transcript["duration"]
    if modo_musica:
        palabras_obj = max(40, int(dur * 2.6))   # ritmo de locución es-CO ≈ 2.6 palabras/s
        user = ("ADN DEL GANADOR (este ganador NO tiene narración: es SOLO MÚSICA con visuales; "
                "su fuerza está en la estructura visual):\n" + json.dumps(adn, ensure_ascii=False) +
                f"\n\nEscribe {n} guiones de VOZ EN OFF que sigan su estructura visual tramo a tramo "
                f"(mismas fases y proporciones de tiempo). Duración total hablada ≈ {dur:.0f}s "
                f"(~{palabras_obj} palabras cada guion ±15%).\n\n=== FRAMEWORK DE JUAN ===\n" + _leer_framework())
    else:
        user = ("ADN DEL GANADOR:\n" + json.dumps(adn, ensure_ascii=False) +
                "\n\nTRANSCRIPCIÓN LITERAL DEL GANADOR (duración total " +
                f"{dur:.1f}s):\n{transcript['texto']}" +
                f"\n\nEscribe {n} variaciones. La duración hablada de cada una debe quedar MUY cerca de "
                f"{dur:.0f}s (mismo conteo aproximado de palabras que el original: "
                f"{len(transcript['texto'].split())} palabras ±15%).\n\n=== FRAMEWORK DE JUAN ===\n" + _leer_framework())
    guiones = _pedir_json(client, GUIONES_SYS, user, max_tokens=8000, pid=pid, debug_path=debug_path)
    limpio = []
    for g in guiones if isinstance(guiones, list) else []:
        texto = str(g.get("guion", "")).strip()
        if len(texto.split()) >= 20:
            limpio.append({"titulo": str(g.get("titulo", f"variación {len(limpio)+1}"))[:60], "guion": texto})
    if not limpio:
        raise RuntimeError("Claude no devolvió guiones utilizables")
    return limpio[:n]

CAPTIONS_SYS = (
"Eres editor senior de ads SIN VOZ (solo música + textos en pantalla) para dropshipping LATAM. "
"Te doy el ADN de un ad ganador (tramos con tiempos y fases). Escribe VARIACIONES de la capa de "
"TEXTOS EN PANTALLA: un caption por tramo (respetando t0/t1 del ADN), CORTOS (máx 7 palabras), "
"gancho fuerte en el primero, CTA contra entrega en el último. Sigue el framework de Juan "
"(anti-baneo, sin precios con cifras salvo que el ganador los use, números concretos). "
"Palabras NUEVAS en cada variación (jamás copies los textos del ganador).\n"
"Devuelve SOLO JSON:\n"
'[{"titulo":"corto","captions":[{"t0":0.0,"t1":2.4,"texto":"máx 7 palabras"}]}]'
)

def generar_captions_variacion(pid, adn, dur, n, debug_path=None):
    """Variaciones para ads SOLO MÚSICA: captions por tramo, sin TTS (gratis en ElevenLabs)."""
    client = _claude()
    user = ("ADN DEL GANADOR (ad sin narración: música + textos):\n" +
            json.dumps(adn, ensure_ascii=False) +
            f"\n\nDuración total: {dur:.1f}s. Escribe {n} variaciones de captions." +
            "\n\n=== FRAMEWORK DE JUAN ===\n" + _leer_framework())
    vars_ = _pedir_json(client, CAPTIONS_SYS, user, max_tokens=8000, pid=pid, debug_path=debug_path)
    limpio = []
    for v in vars_ if isinstance(vars_, list) else []:
        caps = [c for c in (v.get("captions") or []) if str(c.get("texto", "")).strip()]
        if len(caps) >= 3:
            limpio.append({"titulo": str(v.get("titulo", f"música {len(limpio)+1}"))[:60],
                           "captions": caps})
    if not limpio:
        raise RuntimeError("Claude no devolvió captions utilizables")
    return limpio[:n]

def _transcript_sintetico(captions, dur):
    """'Transcript' para un ad sin voz: los captions hacen de segmentos (beats) y el
    karaoke reparte los tiempos por palabra uniformemente (fallback ya probado)."""
    segs = []
    for c in captions:
        t0 = max(0.0, min(float(c.get("t0", 0)), dur - 0.4))
        t1 = max(t0 + 0.4, min(float(c.get("t1", t0 + 2)), dur))
        txt = str(c.get("texto", "")).strip()
        if txt:
            segs.append({"start": round(t0, 3), "end": round(t1, 3), "text": txt})
    segs.sort(key=lambda s: s["start"])
    # sin solapes (cada beat arranca donde el anterior termina si se pisan)
    for i in range(1, len(segs)):
        if segs[i]["start"] < segs[i-1]["end"]:
            segs[i]["start"] = segs[i-1]["end"]
            segs[i]["end"] = max(segs[i]["end"], segs[i]["start"] + 0.4)
    return {"duration": round(dur, 3), "segments": segs, "words": [],
            "texto": " ".join(s["text"] for s in segs)}

def escribir_adn_md(outdir, transcript, adn, guiones):
    g = adn.get("global", {})
    md = ["# 🏆 ADN del ganador\n",
          f"**Ángulo:** {g.get('angulo','?')}  \n**Producto:** {g.get('producto','?')}  \n"
          f"**Ritmo:** {g.get('ritmo','?')}  \n**Elementos:** {', '.join(g.get('elementos',[]) or [])}  \n"
          f"**Por qué gana:** {g.get('por_que_gana','?')}\n",
          "## Estructura por tramos\n",
          "| Tramo | Tiempo | Fase | Qué se ve |\n|--|--|--|--|"]
    for t in adn.get("tramos", []):
        md.append(f"| {t.get('i','?')} | {t.get('t0',0):.1f}–{t.get('t1',0):.1f}s | {t.get('fase','?')} | {t.get('que_se_ve','')} |")
    md.append("\n## Transcripción del ganador\n")
    for s in transcript["segments"]:
        md.append(f"- `[{s['start']:.1f}s]` {s['text']}")
    md.append("\n## Guiones variación\n")
    for i, gg in enumerate(guiones, 1):
        md.append(f"### {i}. {gg['titulo']}\n\n{gg['guion']}\n")
    with open(Path(outdir) / "adn-ganador.md", "w") as f:
        f.write("\n".join(md))

def _guia_adn(adn, transcript):
    """Instrucciones compactas para el plan de los hijos: imitar la lógica visual del ganador."""
    lineas = []
    segs = transcript["segments"]
    for t in adn.get("tramos", [])[:14]:
        dice = " ".join(s["text"] for s in segs if s["start"] < t.get("t1", 0) and s["end"] > t.get("t0", 0))[:80]
        lineas.append(f"[{t.get('fase','?')}] cuando dice «{dice}» el ganador muestra: {t.get('que_se_ve','')[:90]}")
    guia = ("ADN DEL AD GANADOR QUE ESTAMOS CLONANDO — imita su lógica visual beat a beat con los clips disponibles:\n"
            + "\n".join(lineas))
    return guia[:1800]

def crear_hijo(padre, pid_hijo, nombre, audio_src, transcript_src=None):
    """Proyecto hijo del ganador: clips hardlink del padre, mismo grupo (hereda catálogo)."""
    pdir = PROJECTS / pid_hijo
    (pdir / "clips").mkdir(parents=True, exist_ok=True)
    padre_dir = PROJECTS / padre["id"]
    for fn in padre["clips"]:
        destino = pdir / "clips" / fn
        if not destino.exists():
            try:
                os.link(padre_dir / "clips" / fn, destino)
            except OSError:
                _shutil.copy2(padre_dir / "clips" / fn, destino)
    audio_name = "voz" + Path(audio_src).suffix.lower()
    _shutil.copy2(audio_src, pdir / audio_name)
    musica_name = padre.get("musica")
    if musica_name and not (pdir / musica_name).exists():
        try:
            os.link(padre_dir / musica_name, pdir / musica_name)
        except OSError:
            _shutil.copy2(padre_dir / musica_name, pdir / musica_name)
    if transcript_src and Path(transcript_src).exists():
        (pdir / "work").mkdir(exist_ok=True)
        _shutil.copy2(transcript_src, pdir / "work" / "transcript.json")
    import time as _time
    estado = {"id": pid_hijo, "nombre": nombre, "creado": _time.strftime("%Y-%m-%d %H:%M"),
              "grupo": padre.get("grupo") or padre["id"], "padre": padre["id"],
              "paquete": padre.get("paquete", ""),
              "audio": audio_name, "clips": padre["clips"], "musica": musica_name,
              "estilo_subs": padre.get("estilo_subs", "karaoke"),
              "plataforma": padre.get("plataforma", "meta"), "versiones": [],
              "agentes": padre.get("agentes") or {},
              "fase": "en cola", "progreso": 0, "done": False, "error": None, "log": []}
    with open(pdir / "estado.json", "w") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    return pid_hijo

def procesar_ganador(pid):
    with _RENDER_SEM:
        _procesar_ganador(pid)

def _procesar_ganador(pid):
    """Analiza el ganador → guiones variación → TTS → hijos. Idempotente: con Reintentar
    reusa transcript/ADN/guiones cacheados y solo genera lo que falte (p.ej. TTS sin créditos)."""
    pdir = PROJECTS / pid
    if not pdir.exists():
        return
    workdir = pdir / "work"; workdir.mkdir(exist_ok=True)
    outdir = pdir / "resultado"; outdir.mkdir(exist_ok=True)
    try:
        e = leer_estado(pid)
        ganador = pdir / e["ganador"]

        # 1. audio del ganador → mp3 (cache)
        voz_g = workdir / "ganador_voz.mp3"
        if not voz_g.exists():
            log(pid, "🏆 Extrayendo el audio del ganador…", fase="analizando ganador", progreso=8)
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ganador), "-vn",
                 "-ar", "44100", "-b:a", "192k", str(voz_g)])
        if audio_dur(voz_g) < 3.0:
            raise RuntimeError("El video ganador no tiene audio utilizable")

        # 2. transcript (cache)
        tpath = workdir / "transcript.json"
        if tpath.exists():
            transcript = json.load(open(tpath))
        else:
            log(pid, "🎙️  Transcribiendo la narración del ganador…", progreso=15)
            transcript = transcribir(pid, voz_g, workdir)
        modo_musica = _es_musica(transcript)
        if modo_musica:
            log(pid, "🎵 Este ganador NO tiene narración (es música + visuales) — modo MÚSICA: "
                     "el ADN sale de su estructura visual y los guiones se escriben desde cero", progreso=22)
        else:
            log(pid, f"📝 Guion del ganador: “{transcript['texto'][:100]}…”", progreso=22)

        # 3. ADN (cache)
        apath = workdir / "adn.json"
        if apath.exists():
            adn = json.load(open(apath))
        else:
            log(pid, "🧬 Analizando la estructura visual del ganador (Claude viendo tramos)…", progreso=30)
            adn = analizar_ganador(pid, ganador, transcript, workdir)
            with open(apath, "w") as f:
                json.dump(adn, f, ensure_ascii=False, indent=2)
        g = adn.get("global", {})
        log(pid, f"🧬 ADN: {len(adn.get('tramos',[]))} tramos · ángulo: {str(g.get('angulo','?'))[:70]}", progreso=40)

        # 4. resolver el MODO DE AUDIO: auto → los agentes deciden con el ADN
        n = int(e.get("n_variaciones", 3))
        modo_audio = (e.get("modo_audio") or "auto").lower()
        rec = str(adn.get("global", {}).get("recomendacion_audio", "")).lower()
        if modo_audio == "auto":
            modo_res = "musica" if (modo_musica or rec == "musica") else "voz"
            log(pid, f"🤖 Modo AUTO → los agentes eligieron: {'🎵 solo música' if modo_res=='musica' else '🗣️ voz en off'}"
                     + (f" (ADN recomienda: {rec})" if rec else ""), progreso=45)
        else:
            modo_res = "musica" if modo_audio == "musica" else "voz"

        fallos_tts = []
        e = leer_estado(pid)
        hijos = list(e.get("hijos", []))
        base_nombre = e.get("nombre", "ganador").replace("🏆", "").strip()

        if modo_res == "musica":
            # ---- variaciones SOLO MÚSICA (sin TTS: no gasta ElevenLabs) ----
            if e.get("musica"):
                pista = pdir / e["musica"]
            elif modo_musica:
                pista = voz_g          # la música ES el audio del ganador
            else:
                pista = voz_g
                log(pid, "⚠️ Elegiste solo música pero el ganador HABLA y no subiste pista musical: "
                         "uso su audio tal cual (trae la voz) — para música limpia, sube una en el campo 🎵 y Reintentar")
            dur_pista = audio_dur(pista)
            caps_vars = e.get("captions_vars")
            if not caps_vars:
                log(pid, f"✍️  Escribiendo {n} variaciones de captions (ad sin voz, framework de Juan)…", progreso=50)
                caps_vars = generar_captions_variacion(pid, adn, dur_pista, n,
                                                       debug_path=workdir / "debug_guiones.txt")
                with _lock(pid):
                    e2 = leer_estado(pid); e2["captions_vars"] = caps_vars; _guardar(pid, e2)
            guiones_md = [{"titulo": v["titulo"],
                           "guion": "\n".join(f"[{float(c.get('t0',0)):.1f}-{float(c.get('t1',0)):.1f}s] {c['texto']}"
                                              for c in v["captions"])} for v in caps_vars]
            escribir_adn_md(outdir, transcript, adn, guiones_md)
            for i, v in enumerate(caps_vars, 1):
                pid_h = f"{pid}-mus{i}"
                if pid_h in hijos:
                    continue
                crear_hijo(e, pid_h, f"{base_nombre} · música {i}: {v['titulo']}", pista)
                wdir_h = PROJECTS / pid_h / "work"; wdir_h.mkdir(exist_ok=True)
                with open(wdir_h / "transcript.json", "w") as f:
                    json.dump(_transcript_sintetico(v["captions"], dur_pista), f, ensure_ascii=False, indent=2)
                hijos.append(pid_h)
                log(pid, f"👶 Variación música {i} creada: “{v['titulo']}”")
        else:
            # ---- variaciones con VOZ (guiones + TTS ElevenLabs) ----
            guiones = e.get("guiones")
            if not guiones:
                log(pid, f"✍️  Escribiendo {n} guiones variación (framework de Juan)…", progreso=48)
                guiones = generar_guiones_variacion(pid, adn, transcript, n,
                                                    modo_musica=modo_musica,
                                                    debug_path=workdir / "debug_guiones.txt")
                with _lock(pid):
                    e2 = leer_estado(pid); e2["guiones"] = guiones; _guardar(pid, e2)
            escribir_adn_md(outdir, transcript, adn, guiones)

            voz_key = e.get("voz", "kate")
            mp3s = []
            for i, gg in enumerate(guiones, 1):
                destino = workdir / f"voz_var{i}.mp3"
                if destino.exists() and audio_dur(destino) > 1.0:
                    mp3s.append((i, gg, destino)); continue
                try:
                    log(pid, f"🗣️  Voz {voz_key} para “{gg['titulo']}” ({i}/{len(guiones)})…", progreso=48 + i * 6)
                    tts_elevenlabs(gg["guion"], voz_key, destino)
                    mp3s.append((i, gg, destino))
                except Exception as ex:
                    fallos_tts.append(str(ex))
                    log(pid, f"⚠️ TTS falló para la variación {i}: {ex}")

            e = leer_estado(pid)
            hijos = list(e.get("hijos", []))
            if e.get("incluir_original", True) and not modo_musica:
                pid_h = f"{pid}-original"
                if pid_h not in hijos:
                    crear_hijo(e, pid_h, f"{base_nombre} · audio ORIGINAL del ganador", voz_g,
                               transcript_src=tpath)
                    hijos.append(pid_h)
                    log(pid, "👶 Variación con el audio original creada")
            for i, gg, mp3 in mp3s:
                pid_h = f"{pid}-var{i}"
                if pid_h not in hijos:
                    crear_hijo(e, pid_h, f"{base_nombre} · var {i}: {gg['titulo']}", mp3)
                    hijos.append(pid_h)
                    log(pid, f"👶 Variación {i} creada: “{gg['titulo']}”")
        with _lock(pid):
            e3 = leer_estado(pid); e3["hijos"] = hijos; _guardar(pid, e3)

        # 7. lanzar los hijos (pasan por la cola normal) con la guía del ADN
        guia = _guia_adn(adn, transcript)
        for h in hijos:
            eh = leer_estado(h)
            if eh and not eh.get("done") and not eh.get("error") and eh.get("fase") == "en cola":
                threading.Thread(target=procesar, args=(h, guia), daemon=True).start()

        with _lock(pid):
            e4 = leer_estado(pid)
            e4.update({"fase": "listo", "progreso": 100, "done": True, "error": None,
                       "resultados": ["adn-ganador.md"]})
            _guardar(pid, e4)
        cierre = f"✅ Ganador clonado: {len(hijos)} variaciones en cola."
        if fallos_tts:
            cierre += f" ⚠️ {len(fallos_tts)} voces fallaron ({fallos_tts[0][:80]}) — recarga ElevenLabs y dale Reintentar: solo generará lo que falta."
        log(pid, cierre)
    except Exception as ex:
        traceback.print_exc()
        with _lock(pid):
            e = leer_estado(pid) or {}
            e.update({"fase": "error", "done": False, "error": str(ex)})
            _guardar(pid, e)
        log(pid, f"❌ Error: {ex}")
