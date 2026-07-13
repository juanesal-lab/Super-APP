"""Montador — server FastAPI. Sube 1 audio + N videos (y música opcional) y la IA monta el ad."""
import os, re, json, time, shutil, zipfile, threading, unicodedata
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

from backend import pipeline  # noqa: E402  (necesita el .env cargado)

app = FastAPI(title="Montador")
PROJECTS = BASE / "projects"
PROJECTS.mkdir(exist_ok=True)

VIDEO_EXT = {".mp4",".mov",".mkv",".webm",".m4v"}
AUDIO_EXT = {".mp3",".wav",".m4a",".aac",".flac",".ogg"}

def _safe(name):
    """Sanitiza filenames al subir: comas, espacios y símbolos raros → '_' (gotcha ffmpeg)."""
    name = unicodedata.normalize("NFKD", name)
    return re.sub(r"[^\w.\-()]", "_", name)

def _pid_seguro(pid):
    if not re.fullmatch(r"[\w.\-]+", pid) or ".." in pid:
        raise HTTPException(400, "ID de proyecto inválido")
    return PROJECTS / pid

def _validar_media(path, tipo, nombre_original):
    """Blindaje: verifica con ffprobe que el archivo subido abre bien; si no, error claro."""
    if tipo == "video":
        info = pipeline.ffprobe_info(path)
        if info["dur"] <= 0 or info["w"] <= 0 or info["h"] <= 0:
            return f"El video “{nombre_original}” está dañado o no se puede leer (ffprobe no lo abre). Súbelo de nuevo o expórtalo otra vez."
    else:
        if pipeline.audio_dur(path) <= 0:
            return f"El audio “{nombre_original}” está dañado o no se puede leer (ffprobe no lo abre). Súbelo de nuevo o expórtalo otra vez."
    return None

@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "frontend" / "index.html").read_text()

@app.get("/api/salud")
def salud():
    key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return {"ok": True, "api_key": key, "modelo": os.environ.get("MONTADOR_MODEL","claude-sonnet-5")}

@app.get("/api/proyectos")
def listar():
    out = []
    for d in sorted(PROJECTS.iterdir(), reverse=True):
        e = pipeline.leer_estado(d.name)
        if e:
            out.append({"id": d.name, "nombre": e.get("nombre"), "fase": e.get("fase"),
                        "progreso": e.get("progreso", 0), "done": e.get("done", False),
                        "error": e.get("error"), "creado": e.get("creado")})
    return out

@app.post("/api/proyectos")
async def crear(nombre: str = Form("mi ad"),
                audio: list[UploadFile] = File(...),
                videos: list[UploadFile] = File(None),
                paquete: str = Form(""),
                guardar_paquete: str = Form(""),
                musica: UploadFile = File(None),
                estilo_subs: str = Form("karaoke"),
                plataforma: str = Form("meta"),
                ag_encuadre: bool = Form(True),
                ag_emojis: bool = Form(False),
                ag_endcard: bool = Form(False),
                ag_hookbanner: bool = Form(False),
                ag_hookbanner_texto: str = Form(""),
                ag_momentos: bool = Form(False),
                usar_broll: bool = Form(True)):
    """Acepta VARIAS voces en off: se crea un proyecto por voz (mismo paquete de clips,
    enlazado en disco sin duplicar) y se montan en cola. El catálogo visual se calcula
    una sola vez y los hermanos del grupo lo heredan."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "Falta ANTHROPIC_API_KEY en el .env")
    audios = [a for a in audio if a and a.filename]
    if not audios:
        raise HTTPException(400, "Sube al menos 1 audio (voz en off)")
    if len(audios) > 10:
        raise HTTPException(400, "Máximo 10 voces por tanda")
    for a in audios:
        if Path(a.filename).suffix.lower() not in AUDIO_EXT:
            raise HTTPException(400, f"“{a.filename}”: el audio debe ser {', '.join(sorted(AUDIO_EXT))}")
    vids = [v for v in (videos or []) if Path(v.filename or "").suffix.lower() in VIDEO_EXT]
    paquete = paquete.strip(); guardar_paquete = guardar_paquete.strip()
    pkg_clips_n = len(_pkg_clips(_pkg_dir(paquete)[0])) if paquete else 0
    if len(vids) + pkg_clips_n < 2:
        raise HTTPException(400, "Sube al menos 2 clips o elige un 📦 paquete guardado")
    if estilo_subs not in ("karaoke", "caja", "minimal"):
        estilo_subs = "karaoke"
    if plataforma not in ("meta", "tiktok"):
        plataforma = "meta"
    mext = None
    if musica and musica.filename:
        mext = Path(musica.filename).suffix.lower()
        if mext not in AUDIO_EXT:
            raise HTTPException(400, f"La música debe ser {', '.join(sorted(AUDIO_EXT))}")

    ts = time.strftime("%Y%m%d-%H%M%S")
    # sufijo único: varias pestañas pueden enviar en el MISMO segundo con el mismo
    # nombre → sin esto chocarían los IDs de proyecto
    import uuid
    grupo = ts + "-" + pipeline.slug(nombre) + "-" + uuid.uuid4().hex[:4]
    agentes = {"encuadre": ag_encuadre, "emojis": ag_emojis, "endcard": ag_endcard,
               "hookbanner": ag_hookbanner, "hookbanner_texto": ag_hookbanner_texto.strip()[:60],
               "momentos": ag_momentos}

    def _enlazar(origen, destino):
        """Enlace duro (mismo disco, cero espacio extra); si no se puede, copia."""
        try:
            os.link(origen, destino)
        except OSError:
            shutil.copy2(origen, destino)

    ids, base_dir, clip_names, musica_name = [], None, [], None
    try:
        for i, a in enumerate(audios, 1):
            pid = grupo if len(audios) == 1 else f"{grupo}-voz{i}"
            pdir = PROJECTS / pid
            (pdir / "clips").mkdir(parents=True)
            ids.append(pid)          # desde ya, para que el cleanup lo cubra si algo falla
            aext = Path(a.filename).suffix.lower()
            audio_name = "voz" + aext
            with open(pdir / audio_name, "wb") as f:
                f.write(await a.read())
            err = _validar_media(pdir / audio_name, "audio", a.filename)
            if err:
                raise HTTPException(400, err)

            if base_dir is None:
                # primer proyecto del grupo: recibe los archivos reales
                if paquete:   # 📦 clips guardados: enlace duro, cero re-subida
                    pk_names, _pk = _materializar_paquete(paquete, pdir / "clips")
                    clip_names.extend(pk_names)
                for v in vids:
                    fn = _safe(Path(v.filename).name)
                    if fn in clip_names:
                        fn = "up_" + fn
                    with open(pdir / "clips" / fn, "wb") as f:
                        f.write(await v.read())
                    clip_names.append(fn)
                if guardar_paquete and vids:   # guardar los subidos en la biblioteca
                    gp_dir, gp_slug = _pkg_dir(guardar_paquete)
                    (gp_dir / "clips").mkdir(parents=True, exist_ok=True)
                    for fn in clip_names:
                        destino = gp_dir / "clips" / fn
                        if not destino.exists():
                            try:
                                os.link(pdir / "clips" / fn, destino)
                            except OSError:
                                shutil.copy2(pdir / "clips" / fn, destino)
                    (gp_dir / "catalogo.json").unlink(missing_ok=True)
                if mext:
                    musica_name = "musica" + mext
                    with open(pdir / musica_name, "wb") as f:
                        f.write(await musica.read())
                errores = []
                if musica_name:
                    e2 = _validar_media(pdir / musica_name, "audio", musica.filename)
                    if e2: errores.append(e2)
                for v, fn in zip(vids, clip_names):
                    e2 = _validar_media(pdir / "clips" / fn, "video", v.filename or fn)
                    if e2: errores.append(e2)
                if errores:
                    raise HTTPException(400, " · ".join(errores))
                base_dir = pdir
            else:
                # hermanos: clips y música ENLAZADOS del primero (sin duplicar disco)
                for fn in clip_names:
                    _enlazar(base_dir / "clips" / fn, pdir / "clips" / fn)
                if musica_name:
                    _enlazar(base_dir / musica_name, pdir / musica_name)

            voz_nombre = Path(a.filename).stem[:40]
            nombre_pieza = nombre if len(audios) == 1 else f"{nombre} · voz {i} ({voz_nombre})"
            pkg_puro = ""
            if paquete and not vids:
                pkg_puro = _pkg_dir(paquete)[1]
            elif guardar_paquete and vids:
                pkg_puro = _pkg_dir(guardar_paquete)[1]
            estado = {"id": pid, "nombre": nombre_pieza, "creado": time.strftime("%Y-%m-%d %H:%M"),
                      "grupo": grupo, "voz": a.filename, "paquete": pkg_puro,
                      "audio": audio_name, "clips": clip_names, "musica": musica_name,
                      "estilo_subs": estilo_subs, "plataforma": plataforma, "versiones": [],
                      "agentes": agentes, "usar_broll": usar_broll,
                      "fase": "en cola", "progreso": 0, "done": False, "error": None, "log": []}
            with open(pdir / "estado.json", "w") as f:
                json.dump(estado, f, ensure_ascii=False, indent=2)
    except HTTPException:
        for pid in ids:                      # todo-o-nada: limpiar lo creado a medias
            shutil.rmtree(PROJECTS / pid, ignore_errors=True)
        raise

    for pid in ids:
        threading.Thread(target=pipeline.procesar, args=(pid,), daemon=True).start()
    return {"id": ids[0], "ids": ids}

@app.get("/api/proyectos/{pid}")
def estado(pid: str):
    e = pipeline.leer_estado(pid)
    if not e:
        raise HTTPException(404, "No existe")
    return e

@app.post("/api/proyectos/{pid}/reintentar")
async def reintentar(pid: str):
    e = pipeline.leer_estado(pid)
    if not e:
        raise HTTPException(404, "No existe")
    es_ganador = e.get("tipo") == "ganador"
    # un 🏆 ganador SIEMPRE se puede reintentar (es idempotente: reusa transcript/ADN/
    # guiones cacheados y solo genera lo que falte — p.ej. voces tras recargar ElevenLabs)
    if not es_ganador and (e.get("done") or (e.get("fase") not in ("error",) and e.get("error") is None)):
        raise HTTPException(400, "Solo se reintenta un proyecto en error")
    with pipeline._lock(pid):
        e["fase"] = "reintentando"; e["error"] = None
        if es_ganador:
            e["done"] = False
        e.setdefault("log", []).append("🔁 Reintentando…")
        pipeline._guardar(pid, e)
    objetivo = pipeline.procesar_ganador if es_ganador else pipeline.procesar
    threading.Thread(target=objetivo, args=(pid,), daemon=True).start()
    return {"ok": True}

@app.post("/api/proyectos/{pid}/ajustar")
async def ajustar(pid: str, instrucciones: str = Form(...)):
    e = pipeline.leer_estado(pid)
    if not e:
        raise HTTPException(404, "No existe")
    if not e.get("done"):
        raise HTTPException(400, "Espera a que termine el proyecto")
    with pipeline._lock(pid):
        e["fase"] = "re-planeando"; e["done"] = False; e["progreso"] = 55
        e.setdefault("log", []).append(f"🔁 Ajuste pedido: {instrucciones}")
        pipeline._guardar(pid, e)
    threading.Thread(target=pipeline.procesar, args=(pid, instrucciones), daemon=True).start()
    return {"ok": True}

@app.get("/api/proyectos/{pid}/archivo/{nombre}")
def archivo(pid: str, nombre: str, dl: bool = False):
    if "/" in nombre or ".." in nombre:
        raise HTTPException(400, "Nombre inválido")
    p = PROJECTS / pid / "resultado" / nombre
    if not p.exists():
        raise HTTPException(404, "No existe")
    media = "video/mp4" if p.suffix == ".mp4" else "text/plain; charset=utf-8"
    # inline por defecto (los <video> no reproducen bien con Content-Disposition: attachment
    # y algunas extensiones de Chrome secuestran las descargas de media); ?dl=1 para descargar
    if dl:
        return FileResponse(p, media_type=media, filename=nombre)
    return FileResponse(p, media_type=media)

# ---------------------------------------------------------------- otra versión
@app.post("/api/proyectos/{pid}/version")
async def otra_version(pid: str):
    _pid_seguro(pid)
    e = pipeline.leer_estado(pid)
    if not e:
        raise HTTPException(404, "No existe")
    if not e.get("done"):
        raise HTTPException(400, "Espera a que termine el proyecto")
    if not (e.get("beats") and e.get("plan")):
        raise HTTPException(400, "No hay plan cacheado; corre el proyecto completo primero")
    with pipeline._lock(pid):
        e["done"] = False; e["fase"] = "en cola (otra versión)"
        e.setdefault("log", []).append("🎲 Pedida otra versión…")
        pipeline._guardar(pid, e)
    threading.Thread(target=pipeline.otra_version, args=(pid,), daemon=True).start()
    return {"ok": True}

@app.get("/api/proyectos/{pid}/version/{n}/{nombre}")
def archivo_version(pid: str, n: int, nombre: str, dl: bool = False):
    if "/" in nombre or ".." in nombre:
        raise HTTPException(400, "Nombre inválido")
    p = _pid_seguro(pid) / "resultado" / f"version-{n}" / nombre
    if not p.exists():
        raise HTTPException(404, "No existe")
    media = "video/mp4" if p.suffix == ".mp4" else "text/plain; charset=utf-8"
    if dl:
        return FileResponse(p, media_type=media, filename=f"v{n}-{nombre}")
    return FileResponse(p, media_type=media)

# ---------------------------------------------------------------- guion visual
@app.get("/api/proyectos/{pid}/thumb/{n}")
def thumb(pid: str, n: int):
    p = _pid_seguro(pid) / "work" / "thumbs" / f"beat_{n:02d}.jpg"
    if not p.exists():
        raise HTTPException(404, "No existe")
    return FileResponse(p, media_type="image/jpeg")

# ---------------------------------------------------------------- zip y eliminar
@app.get("/api/proyectos/{pid}/zip")
def zip_resultado(pid: str):
    pdir = _pid_seguro(pid)
    res = pdir / "resultado"
    if not res.exists():
        raise HTTPException(404, "Aún no hay resultado")
    (pdir / "work").mkdir(exist_ok=True)
    zpath = pdir / "work" / "resultado.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for f in sorted(res.rglob("*")):
            if f.is_file():
                # los mp4 ya vienen comprimidos: STORED (rápido); el resto DEFLATED
                comp = zipfile.ZIP_STORED if f.suffix == ".mp4" else zipfile.ZIP_DEFLATED
                z.write(f, f.relative_to(res), compress_type=comp)
    return FileResponse(zpath, media_type="application/zip", filename=f"{pid}-resultado.zip")

@app.delete("/api/proyectos/{pid}")
def eliminar(pid: str):
    pdir = _pid_seguro(pid)
    if not pdir.exists():
        raise HTTPException(404, "No existe")
    e = pipeline.leer_estado(pid)
    fase = (e or {}).get("fase") or ""
    ocupado = e and not e.get("done") and not e.get("error") and not fase.startswith("en cola")
    if ocupado:
        raise HTTPException(409, "El proyecto se está procesando; espera a que termine (o falle) para eliminarlo")
    shutil.rmtree(pdir)
    return {"ok": True}

# ---------------------------------------------------------------- clonar ganador
@app.post("/api/ganador")
async def clonar_ganador(nombre: str = Form("ganador"),
                         ganador: UploadFile = File(...),
                         videos: list[UploadFile] = File(None),
                         paquete: str = Form(""),
                         guardar_paquete: str = Form(""),
                         musica: UploadFile = File(None),
                         n_variaciones: int = Form(3),
                         incluir_original: bool = Form(True),
                         voz: str = Form("kate"),
                         modo_audio: str = Form("auto"),
                         estilo_subs: str = Form("karaoke"),
                         plataforma: str = Form("meta"),
                         ag_encuadre: bool = Form(True),
                         ag_emojis: bool = Form(False),
                         ag_endcard: bool = Form(False),
                         ag_hookbanner: bool = Form(False),
                         ag_hookbanner_texto: str = Form(""),
                         ag_momentos: bool = Form(False),
                         usar_broll: bool = Form(True)):
    """🏆 Sube un ad GANADOR + tus clips → la app lo analiza y genera variaciones
    (guiones nuevos beat a beat + voz ElevenLabs + una versión con el audio original)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "Falta ANTHROPIC_API_KEY en el .env")
    if modo_audio not in ("auto", "voz", "musica"):
        modo_audio = "auto"
    if modo_audio == "voz" and not os.environ.get("ELEVENLABS_API_KEY"):
        raise HTTPException(400, "Falta ELEVENLABS_API_KEY en el .env (necesaria para el modo voz)")
    gext = Path(ganador.filename or "").suffix.lower()
    if gext not in VIDEO_EXT:
        raise HTTPException(400, f"El ganador debe ser video ({', '.join(sorted(VIDEO_EXT))})")
    vids = [v for v in (videos or []) if Path(v.filename or "").suffix.lower() in VIDEO_EXT]
    paquete = paquete.strip(); guardar_paquete = guardar_paquete.strip()
    pkg_clips_n = len(_pkg_clips(_pkg_dir(paquete)[0])) if paquete else 0
    if len(vids) + pkg_clips_n < 2:
        raise HTTPException(400, "Sube al menos 2 clips o elige un 📦 paquete guardado")
    n_variaciones = max(2, min(5, int(n_variaciones)))
    if voz not in pipeline.VOCES_11LABS:
        voz = "kate"
    if estilo_subs not in ("karaoke", "caja", "minimal"):
        estilo_subs = "karaoke"
    if plataforma not in ("meta", "tiktok"):
        plataforma = "meta"
    mext = None
    if musica and musica.filename:
        mext = Path(musica.filename).suffix.lower()
        if mext not in AUDIO_EXT:
            raise HTTPException(400, "La música debe ser audio")

    import uuid
    ts = time.strftime("%Y%m%d-%H%M%S")
    pid = f"{ts}-{pipeline.slug(nombre)}-{uuid.uuid4().hex[:4]}-gan"
    pdir = PROJECTS / pid
    (pdir / "clips").mkdir(parents=True)
    try:
        ganador_name = "ganador" + gext
        with open(pdir / ganador_name, "wb") as f:
            f.write(await ganador.read())
        err = _validar_media(pdir / ganador_name, "video", ganador.filename)
        if err:
            raise HTTPException(400, err)
        clip_names = []
        if paquete:
            pk_names, _pk = _materializar_paquete(paquete, pdir / "clips")
            clip_names.extend(pk_names)
        for v in vids:
            fn = _safe(Path(v.filename).name)
            if fn in clip_names:
                fn = "up_" + fn
            with open(pdir / "clips" / fn, "wb") as f:
                f.write(await v.read())
            e2 = _validar_media(pdir / "clips" / fn, "video", v.filename or fn)
            if e2:
                raise HTTPException(400, e2)
            clip_names.append(fn)
        if guardar_paquete and vids:
            gp_dir, gp_slug = _pkg_dir(guardar_paquete)
            (gp_dir / "clips").mkdir(parents=True, exist_ok=True)
            for fn in clip_names:
                destino = gp_dir / "clips" / fn
                if not destino.exists():
                    try:
                        os.link(pdir / "clips" / fn, destino)
                    except OSError:
                        shutil.copy2(pdir / "clips" / fn, destino)
            (gp_dir / "catalogo.json").unlink(missing_ok=True)
        musica_name = None
        if mext:
            musica_name = "musica" + mext
            with open(pdir / musica_name, "wb") as f:
                f.write(await musica.read())
            e2 = _validar_media(pdir / musica_name, "audio", musica.filename)
            if e2:
                raise HTTPException(400, e2)
    except HTTPException:
        shutil.rmtree(pdir, ignore_errors=True)
        raise

    agentes = {"encuadre": ag_encuadre, "emojis": ag_emojis, "endcard": ag_endcard,
               "hookbanner": ag_hookbanner, "hookbanner_texto": ag_hookbanner_texto.strip()[:60],
               "momentos": ag_momentos}
    pkg_puro = ""
    if paquete and not vids:
        pkg_puro = _pkg_dir(paquete)[1]
    elif guardar_paquete and vids:
        pkg_puro = _pkg_dir(guardar_paquete)[1]
    estado = {"id": pid, "tipo": "ganador", "nombre": f"🏆 {nombre}",
              "creado": time.strftime("%Y-%m-%d %H:%M"), "grupo": pid, "paquete": pkg_puro,
              "ganador": ganador_name, "clips": clip_names, "musica": musica_name,
              "n_variaciones": n_variaciones, "incluir_original": incluir_original, "voz": voz,
              "modo_audio": modo_audio,
              "estilo_subs": estilo_subs, "plataforma": plataforma, "agentes": agentes,
              "usar_broll": usar_broll,
              "hijos": [], "versiones": [],
              "fase": "en cola", "progreso": 0, "done": False, "error": None, "log": []}
    with open(pdir / "estado.json", "w") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    threading.Thread(target=pipeline.procesar_ganador, args=(pid,), daemon=True).start()
    return {"id": pid}

# ---------------------------------------------------------------- 📦 biblioteca de clips
BIBLIOTECA = BASE / "biblioteca"
BIBLIOTECA.mkdir(exist_ok=True)

def _pkg_dir(nombre):
    slug = pipeline.slug(nombre, 50)
    if not slug:
        raise HTTPException(400, "Nombre de paquete inválido")
    return BIBLIOTECA / slug, slug

def _pkg_clips(pdir):
    cdir = pdir / "clips"
    return sorted(f.name for f in cdir.glob("*") if f.suffix.lower() in VIDEO_EXT) if cdir.exists() else []

@app.get("/api/paquetes")
def paquetes():
    out = []
    for d in sorted(BIBLIOTECA.iterdir()):
        if d.is_dir():
            clips = _pkg_clips(d)
            if clips:
                mb = sum((d / "clips" / c).stat().st_size for c in clips) / 1_000_000
                out.append({"nombre": d.name, "clips": len(clips), "mb": round(mb),
                            "catalogo": (d / "catalogo.json").exists()})
    return out

@app.post("/api/paquetes")
async def crear_paquete(nombre: str = Form(...), videos: list[UploadFile] = File(...)):
    pdir, slug_ = _pkg_dir(nombre)
    (pdir / "clips").mkdir(parents=True, exist_ok=True)
    nuevos = 0
    for v in videos:
        if Path(v.filename or "").suffix.lower() not in VIDEO_EXT:
            continue
        fn = _safe(Path(v.filename).name)
        destino = pdir / "clips" / fn
        with open(destino, "wb") as f:
            f.write(await v.read())
        err = _validar_media(destino, "video", v.filename)
        if err:
            destino.unlink(missing_ok=True)
            raise HTTPException(400, err)
        nuevos += 1
    if nuevos:  # el set de clips cambió → el catálogo guardado ya no vale
        (pdir / "catalogo.json").unlink(missing_ok=True)
    return {"ok": True, "paquete": slug_, "clips": len(_pkg_clips(pdir))}

@app.delete("/api/paquetes/{nombre}")
def borrar_paquete(nombre: str):
    pdir, _ = _pkg_dir(nombre)
    if not pdir.exists():
        raise HTTPException(404, "No existe")
    shutil.rmtree(pdir, ignore_errors=True)
    return {"ok": True}

def _materializar_paquete(paquete, destino_clips):
    """Enlaza (hardlink) los clips del paquete al proyecto. Devuelve la lista de nombres."""
    pdir, slug_ = _pkg_dir(paquete)
    clips = _pkg_clips(pdir)
    if not clips:
        raise HTTPException(400, f"El paquete “{paquete}” no existe o está vacío")
    nombres = []
    for fn in clips:
        d = destino_clips / fn
        if not d.exists():
            try:
                os.link(pdir / "clips" / fn, d)
            except OSError:
                shutil.copy2(pdir / "clips" / fn, d)
        nombres.append(fn)
    return nombres, slug_
