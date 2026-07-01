"""Servidor web local del Cortador de Clips."""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import sys
sys.path.insert(0, os.path.dirname(__file__))
from pipeline.orchestrator import process_job, analyze_select, render_versions
from pipeline.assemble import export_resolution, list_sfx
from pipeline.scripts import generate_scripts, suggest_sfx, suggest_music
from pipeline.voiceover import (synthesize, synthesize_with_timestamps, sound_effect,
                                music as gen_music, VOICES)
from pipeline.hook_gen import fetch_page_text
from pipeline.product_swap import detect_product_ranges, find_new_clips, swap_product
from pipeline.dubbing import dub_video, LANGS as DUB_LANGS
from pipeline.auto_studio import generar_creativo_auto
from pipeline.narrative import analyze_narrative

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE, "uploads")
WORK_DIR = os.path.join(BASE, "work")
FRONTEND = os.path.join(BASE, "frontend")
ENV_FILE = os.path.join(BASE, ".env")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Baja el modelo EAST (~92 MB) la primera vez, en segundo plano para no
    # frenar el arranque del servidor. Así el usuario no hace nada manual.
    from pipeline.text_detect import ensure_model
    threading.Thread(target=ensure_model, daemon=True).start()
    yield


app = FastAPI(title="Cortador de Clips", lifespan=lifespan)


# Estado de trabajos en memoria
JOBS: dict[str, dict] = {}

# Ancho de descarga (la altura se ajusta sola segun el formato 1:1 / 9:16 / 4:5)
RES_MAP = {"2160": 2160, "1440": 1440, "1080": 1080, "720": 720, "480": 480}


def _load_key(name: str) -> str | None:
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(name)


def _load_env_key() -> str | None:
    return _load_key("GEMINI_API_KEY")


def _load_eleven_key() -> str | None:
    return _load_key("ELEVENLABS_API_KEY")


def _load_anthropic_key() -> str | None:
    return _load_key("ANTHROPIC_API_KEY")


def _run_job(job_id: str, paths: list[str], settings: dict):
    job = JOBS[job_id]

    def progress(msg: str, pct: int):
        job["message"] = msg
        job["progress"] = pct

    try:
        result = process_job(
            paths,
            os.path.join(WORK_DIR, job_id),
            target_seconds=settings["target_seconds"],
            max_clip_seconds=settings["max_clip_seconds"],
            use_gemini=settings["use_gemini"],
            product_desc=settings["product_desc"],
            aspect=settings["aspect"],
            hook_text=settings["hook_text"],
            hook_pos=settings["hook_pos"],
            auto_hook=settings["auto_hook"],
            page_url=settings["page_url"],
            enhance=settings["enhance"],
            effects=settings.get("effects", False),
            blur_captions=settings.get("blur_captions", False),
            text_mode=settings.get("text_mode", "tapar"),
            caption_pos=settings.get("caption_pos", "abajo"),
            gemini_key=_load_env_key(),
            progress=progress,
        )
        job["result"] = result
        job["status"] = "done" if result.get("ok") else "error"
        if not result.get("ok"):
            job["message"] = result.get("error", "Error desconocido")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


@app.get("/", response_class=HTMLResponse)
def index():
    # Sin cache: el navegador siempre carga la version mas reciente de la app
    return FileResponse(
        os.path.join(FRONTEND, "index.html"),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/config")
def get_config():
    return {
        "has_gemini_key": bool(_load_env_key()),
        "has_eleven_key": bool(_load_eleven_key()),
        "has_anthropic_key": bool(_load_anthropic_key()),
        "voices": [{"key": k, "label": v["label"]} for k, v in VOICES.items()],
        "dub_langs": [{"code": c, "label": n} for c, n in DUB_LANGS.items()],
    }


_KEY_ENV = {"gemini": "GEMINI_API_KEY", "eleven": "ELEVENLABS_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY"}
# Prefijos esperados por proveedor: evita pegar el key equivocado en el campo equivocado
# (fue lo que pasó: un key de Anthropic terminó en GEMINI_API_KEY y rompió todo lo de Gemini).
_KEY_PREFIX = {"gemini": ("AIza", "AQ."), "eleven": ("sk_",), "anthropic": ("sk-ant-",)}
_KEY_LABEL = {"gemini": "Gemini (empieza con AIza o AQ.)",
              "eleven": "ElevenLabs (empieza con sk_)",
              "anthropic": "Claude/Anthropic (empieza con sk-ant-)"}


@app.post("/api/save-key")
def save_key(key: str = Form(...), provider: str = Form("gemini")):
    key = key.strip()
    env_name = _KEY_ENV.get(provider, "GEMINI_API_KEY")
    if not key:
        raise HTTPException(400, "Key vacia")
    pref = _KEY_PREFIX.get(provider)
    if pref and not key.startswith(pref):
        raise HTTPException(400, f"Esa key no parece de {_KEY_LABEL[provider]}. "
                                 "¿La pegaste en el campo correcto?")
    # Conservar otras lineas del .env
    lines = []
    if os.path.exists(ENV_FILE):
        lines = [l for l in open(ENV_FILE) if not l.startswith(env_name + "=")]
    lines.append(f"{env_name}={key}\n")
    with open(ENV_FILE, "w") as f:
        f.writelines(lines)
    os.environ[env_name] = key
    return {"ok": True}


@app.post("/api/process")
async def process(
    files: list[UploadFile] = File(...),
    target_seconds: float = Form(15.0),
    max_clip: float = Form(2.5),
    use_gemini: bool = Form(True),
    product_desc: str = Form(""),
    aspect: str = Form("1:1"),
    hook_text: str = Form(""),
    hook_pos: str = Form("arriba"),
    auto_hook: bool = Form(False),
    page_url: str = Form(""),
    enhance: bool = Form(False),
    effects: bool = Form(False),
    blur_captions: bool = Form(False),
    text_mode: str = Form("tapar"),
    caption_pos: str = Form("abajo"),
):
    if not files:
        raise HTTPException(400, "Sube al menos un video")

    job_id = uuid.uuid4().hex[:12]
    job_upload = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_upload, exist_ok=True)

    paths = []
    for f in files:
        dest = os.path.join(job_upload, os.path.basename(f.filename or f"v_{len(paths)}.mp4"))
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        paths.append(dest)

    JOBS[job_id] = {
        "status": "running", "progress": 0,
        "message": "Iniciando...", "result": None,
        "created": time.time(),
    }
    settings = {
        "target_seconds": float(target_seconds),
        "max_clip_seconds": min(5.0, max(1.0, float(max_clip))),
        "use_gemini": bool(use_gemini),
        "product_desc": product_desc.strip(),
        "aspect": aspect if aspect in ("1:1", "9:16", "4:5", "16:9") else "1:1",
        "hook_text": hook_text.strip(),
        "hook_pos": hook_pos if hook_pos in ("arriba", "centro", "abajo") else "arriba",
        "auto_hook": bool(auto_hook),
        "page_url": page_url.strip(),
        "enhance": bool(enhance),
        "effects": bool(effects),
        "blur_captions": bool(blur_captions),
        "text_mode": text_mode if text_mode in ("tapar", "traducir") else "tapar",
        "caption_pos": caption_pos if caption_pos in ("abajo", "arriba", "ambos") else "abajo",
    }
    threading.Thread(target=_run_job, args=(job_id, paths, settings), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    return {
        "status": job["status"], "progress": job["progress"],
        "message": job["message"], "result": job.get("result"),
    }


# ---- MODO AUTOMÁTICO: un video ganador -> creativo terminado (cadena completa) ----

def _run_auto_job(job_id: str, video_path: str, settings: dict):
    job = JOBS[job_id]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = pct

    try:
        result = generar_creativo_auto(
            video_path,
            gemini_key=_load_env_key(),
            eleven_key=_load_eleven_key(),
            anthropic_key=_load_anthropic_key(),
            product_desc=settings.get("product_desc", ""),
            voz=settings.get("voz", "juan_carlos"),
            oferta_2x1=settings.get("oferta_2x1", False),
            verticalizar=settings.get("verticalizar", True),
            work_dir=os.path.join(WORK_DIR, job_id),
            progress=progress,
        )
        job["result"] = result
        job["status"] = "done" if result.get("ok") else "error"
        if not result.get("ok"):
            job["message"] = result.get("error", "Error desconocido")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


@app.post("/api/auto")
async def auto(
    file: UploadFile = File(...),
    product_desc: str = Form(""),
    voz: str = Form("juan_carlos"),
    oferta_2x1: bool = Form(False),
    verticalizar: bool = Form(True),
):
    if not file:
        raise HTTPException(400, "Sube un video ganador")
    job_id, paths = _save_uploads([file])
    JOBS[job_id] = {"status": "running", "progress": 0,
                    "message": "Iniciando...", "result": None, "created": time.time()}
    settings = {
        "product_desc": product_desc.strip(),
        "voz": voz if voz in ("kate", "juan_carlos") else "juan_carlos",
        "oferta_2x1": bool(oferta_2x1),
        "verticalizar": bool(verticalizar),
    }
    threading.Thread(target=_run_auto_job, args=(job_id, paths[0], settings), daemon=True).start()
    return {"job_id": job_id}


# ---- Proceso por pasos para VOZ EN OFF ----

def _save_uploads(files: list[UploadFile]) -> tuple[str, list[str]]:
    job_id = uuid.uuid4().hex[:12]
    job_upload = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_upload, exist_ok=True)
    paths = []
    for f in files:
        dest = os.path.join(job_upload, os.path.basename(f.filename or f"v_{len(paths)}.mp4"))
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        paths.append(dest)
    return job_id, paths


def _run_scripts_job(job_id: str, paths: list[str], settings: dict):
    job = JOBS[job_id]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = pct

    try:
        a = analyze_select(
            paths, target_seconds=settings["target_seconds"],
            max_clip_seconds=settings["max_clip_seconds"], use_gemini=settings["use_gemini"],
            product_desc=settings["product_desc"], gemini_key=_load_env_key(), progress=progress)
        if not a["ok"]:
            job["status"] = "error"; job["message"] = a.get("error", "Error"); return
        selected = a["selected"]
        sample = max(selected, key=lambda s: (s.shows_use, s.score)) if selected else None
        page_text = fetch_page_text(settings["page_url"]) if settings["page_url"] else ""
        wd = os.path.join(WORK_DIR, job_id)

        # Anuncio de referencia (opcional): la IA lee su estructura narrativa (narrative.py) y
        # los guiones COPIAN ese arco ganador (HOOK→DOLOR→SOLUCIÓN→DESEO→CTA) con su ritmo.
        blueprint = None
        ref = settings.get("reference_ad")
        if ref and os.path.exists(ref):
            progress("Analizando la estructura del anuncio de referencia (IA)...", 62)
            try:
                bp = analyze_narrative(ref, api_key=_load_env_key(),
                                       product_desc=settings["product_desc"], progress=progress)
                if bp.get("ok"):
                    blueprint = bp
                    os.makedirs(wd, exist_ok=True)
                    import json as _json
                    with open(os.path.join(wd, "blueprint.json"), "w", encoding="utf-8") as bf:
                        _json.dump(bp, bf, ensure_ascii=False, indent=2)
            except Exception:  # noqa: BLE001
                blueprint = None

        progress("Generando 10 guiones de voz en off...", 70)
        scripts = generate_scripts(_load_env_key(), settings["product_desc"], page_text,
                                   settings["target_seconds"], sample, blueprint=blueprint)
        # Guardar estado para la fase 2 (renderizado con voz)
        job.update({
            "selected": selected, "has_audio_by_src": a["has_audio_by_src"],
            "used_gemini": a["used_gemini"], "n_sources": a["n_sources"],
            "settings": settings, "work_dir": wd,
        })
        job["result"] = {"ok": True, "scripts": scripts, "blueprint": blueprint}
        job["status"] = "done"; job["message"] = "Guiones listos"; job["progress"] = 100
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"; job["message"] = f"Error: {e}"


@app.post("/api/scripts")
async def scripts(
    files: list[UploadFile] = File(...),
    target_seconds: float = Form(15.0),
    max_clip: float = Form(2.5),
    use_gemini: bool = Form(True),
    product_desc: str = Form(""),
    aspect: str = Form("9:16"),
    hook_text: str = Form(""),
    hook_pos: str = Form("arriba"),
    auto_hook: bool = Form(False),
    page_url: str = Form(""),
    enhance: bool = Form(False),
    effects: bool = Form(False),
    blur_captions: bool = Form(False),
    text_mode: str = Form("tapar"),
    caption_pos: str = Form("abajo"),
    use_music: bool = Form(False),
    use_captions: bool = Form(False),
    reference_ad: UploadFile | None = File(None),
):
    if not files:
        raise HTTPException(400, "Sube al menos un video")
    job_id, paths = _save_uploads(files)
    # Anuncio de referencia (opcional) para clonar su estructura narrativa
    ref_path = None
    if reference_ad is not None and reference_ad.filename:
        ref_path = os.path.join(UPLOAD_DIR, job_id,
                                "reference_" + os.path.basename(reference_ad.filename))
        with open(ref_path, "wb") as rf:
            shutil.copyfileobj(reference_ad.file, rf)
    JOBS[job_id] = {"status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time()}
    settings = {
        "target_seconds": float(target_seconds),
        "max_clip_seconds": min(5.0, max(1.0, float(max_clip))),
        "use_gemini": bool(use_gemini), "product_desc": product_desc.strip(),
        "aspect": aspect if aspect in ("1:1", "9:16", "4:5", "16:9") else "9:16",
        "hook_text": hook_text.strip(),
        "hook_pos": hook_pos if hook_pos in ("arriba", "centro", "abajo") else "arriba",
        "auto_hook": bool(auto_hook), "page_url": page_url.strip(), "enhance": bool(enhance),
        "effects": bool(effects), "blur_captions": bool(blur_captions),
        "text_mode": text_mode if text_mode in ("tapar", "traducir") else "tapar",
        "caption_pos": caption_pos if caption_pos in ("abajo", "arriba", "ambos") else "abajo",
        "use_music": bool(use_music), "captions": bool(use_captions),
        "reference_ad": ref_path,
    }
    threading.Thread(target=_run_scripts_job, args=(job_id, paths, settings), daemon=True).start()
    return {"job_id": job_id}


N_VERSIONS = 6


def _run_render_job(job_id: str, scripts: list[str], voice_key: str):
    job = JOBS[job_id]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = pct

    try:
        s = job["settings"]
        wd = job["work_dir"]
        os.makedirs(wd, exist_ok=True)
        key = _load_eleven_key()
        # Una voz/guion DISTINTO por version (si hay menos guiones, se ciclan)
        chosen = [(scripts * (N_VERSIONS // max(1, len(scripts)) + 1))[i] for i in range(N_VERSIONS)]
        version_vos = []
        for i, txt in enumerate(chosen):
            progress(f"Generando voz {i + 1}/{N_VERSIONS} con ElevenLabs...", 12 + i * 4)
            vp = os.path.join(wd, f"vo_{i}.mp3")
            if s.get("captions"):
                wt = synthesize_with_timestamps(key, txt, voice_key, vp)
            else:
                synthesize(key, txt, voice_key, vp); wt = None
            version_vos.append((vp, wt))
        # Efectos de transicion: samples REALES (los del usuario en assets/sfx/ o los del set)
        sfx_paths = list_sfx() if s.get("effects") else []
        # Musica de fondo (opcional): ElevenLabs Music, segun el nicho del producto
        music_path, music_warning = None, None
        if s.get("use_music"):
            try:
                progress("Generando la música de fondo según el nicho...", 40)
                mdesc = suggest_music(_load_env_key(), s["product_desc"])
                music_path = os.path.join(wd, "music.mp3")
                gen_music(_load_eleven_key(), mdesc, music_path,
                          length_ms=int((s["target_seconds"] + 4) * 1000))
            except Exception as e:  # noqa: BLE001
                music_path = None
                if "music_generation" in str(e):
                    music_warning = ("La música no se agregó: tu API key de ElevenLabs no tiene el "
                                     "permiso 'Music Generation'. Actívalo en elevenlabs.io → API Keys.")
                else:
                    music_warning = "La música no se pudo generar."
        manifest = render_versions(
            job["selected"], job["has_audio_by_src"], wd,
            aspect=s["aspect"], enhance=s["enhance"], hook_text=s["hook_text"],
            hook_pos=s["hook_pos"], auto_hook=s["auto_hook"], page_url=s["page_url"],
            product_desc=s["product_desc"], gemini_key=_load_env_key(),
            version_vos=version_vos, effects=s.get("effects", False), sfx_paths=sfx_paths,
            music_path=music_path,
            blur_captions=s.get("blur_captions", False), text_mode=s.get("text_mode", "tapar"),
            caption_pos=s.get("caption_pos", "abajo"),
            captions=s.get("captions", False),
            used_gemini=job["used_gemini"], n_sources=job["n_sources"],
            target_seconds=s["target_seconds"], max_clip_seconds=s["max_clip_seconds"],
            progress=progress)
        if music_warning and isinstance(manifest, dict):
            manifest["music_warning"] = music_warning
        job["result"] = manifest
        job["status"] = "done" if manifest.get("ok") else "error"
        if not manifest.get("ok"):
            job["message"] = manifest.get("error", "Error")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"; job["message"] = f"Error: {e}"


_PREVIEW_DIR = os.path.join(WORK_DIR, "_previews")


@app.post("/api/preview-voice")
def preview_voice(text: str = Form(...), voice: str = Form("kate")):
    """Genera (y cachea) un audio de un guion para escucharlo antes de elegir."""
    text = text.strip()
    if not text:
        raise HTTPException(400, "Texto vacío")
    key = _load_eleven_key()
    if not key:
        raise HTTPException(400, "Falta la API key de ElevenLabs")
    os.makedirs(_PREVIEW_DIR, exist_ok=True)
    h = hashlib.md5((voice + "|" + text).encode("utf-8")).hexdigest()[:16]
    out = os.path.join(_PREVIEW_DIR, f"{h}.mp3")
    if not os.path.exists(out):
        try:
            synthesize(key, text, voice, out)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"ElevenLabs: {e}")
    return FileResponse(out, media_type="audio/mpeg")


@app.post("/api/render")
def render(job_id: str = Form(...), voice: str = Form("kate"),
           scripts_json: str = Form(""), script_text: str = Form("")):
    job = JOBS.get(job_id)
    if not job or "selected" not in job:
        raise HTTPException(404, "Sesión no encontrada (vuelve a generar los guiones)")
    import json as _json
    scripts: list[str] = []
    if scripts_json.strip():
        try:
            scripts = [str(x).strip() for x in _json.loads(scripts_json) if str(x).strip()]
        except Exception:
            scripts = []
    if not scripts and script_text.strip():
        scripts = [script_text.strip()]
    if not scripts:
        raise HTTPException(400, "No hay guiones seleccionados")
    job["status"] = "running"; job["progress"] = 0; job["message"] = "Iniciando..."; job["result"] = None
    threading.Thread(target=_run_render_job, args=(job_id, scripts, voice), daemon=True).start()
    return {"job_id": job_id}


def _resolve_desc(desc: str) -> str:
    """Si es un link, lee la página y saca la descripción del producto; si no, texto tal cual."""
    desc = (desc or "").strip()
    if desc.startswith(("http://", "https://")):
        txt = fetch_page_text(desc)
        return txt[:400] if txt else desc
    return desc


def _run_swap_job(job_id: str, old_path: str, new_paths: list[str],
                  old_desc: str, new_desc: str):
    job = JOBS[job_id]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = pct

    try:
        wd = os.path.join(WORK_DIR, job_id)
        os.makedirs(wd, exist_ok=True)
        old_desc, new_desc = _resolve_desc(old_desc), _resolve_desc(new_desc)
        progress("Detectando dónde aparece el producto VIEJO (IA)...", 20)
        ranges = detect_product_ranges(_load_env_key(), old_path, old_desc)
        if not ranges:
            job["status"] = "error"
            job["message"] = ("No detecté el producto viejo en el video. "
                              "Prueba describirlo mejor (ej. 'frasco negro de suero').")
            return
        progress("Analizando tus videos del producto NUEVO...", 45)
        new_clips = find_new_clips(_load_env_key(), new_paths, new_desc)
        progress(f"Reemplazando {len(ranges)} tomas con tu producto nuevo...", 60)
        out = os.path.join(wd, "swapped.mp4")
        swap_product(old_path, new_clips, ranges, out, wd)
        job["result"] = {
            "ok": True, "path": out, "filename": "reemplazado.mp4",
            "n_ranges": len(ranges),
            "ranges": [[round(a, 1), round(b, 1)] for a, b in ranges],
        }
        job["status"] = "done"; job["progress"] = 100; job["message"] = "Listo"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"; job["message"] = f"Error: {e}"


@app.post("/api/swap")
async def swap(old: UploadFile = File(...), new_files: list[UploadFile] = File(...),
               product_desc: str = Form(""), new_desc: str = Form("")):
    if not old or not new_files:
        raise HTTPException(400, "Sube el video viejo y al menos un video del producto nuevo")
    job_id = uuid.uuid4().hex[:12]
    up = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(up, exist_ok=True)
    old_path = os.path.join(up, "old_" + os.path.basename(old.filename or "old.mp4"))
    with open(old_path, "wb") as f:
        shutil.copyfileobj(old.file, f)
    new_paths = []
    for nf in new_files:
        dest = os.path.join(up, "new_" + os.path.basename(nf.filename or f"n{len(new_paths)}.mp4"))
        with open(dest, "wb") as f:
            shutil.copyfileobj(nf.file, f)
        new_paths.append(dest)
    JOBS[job_id] = {"status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_swap_job,
                     args=(job_id, old_path, new_paths, product_desc.strip(), new_desc.strip()),
                     daemon=True).start()
    return {"job_id": job_id}


def _run_dub_job(job_id: str, video_path: str, target_lang: str, source_lang: str):
    job = JOBS[job_id]

    def progress(msg, pct=None):
        job["message"] = msg
        if pct is not None:
            job["progress"] = pct

    try:
        wd = os.path.join(WORK_DIR, job_id)
        os.makedirs(wd, exist_ok=True)
        job["progress"] = 15
        progress("Enviando el video a ElevenLabs para doblarlo...", 15)
        out = os.path.join(wd, f"dubbed_{target_lang}.mp4")
        dub_video(_load_eleven_key(), video_path, target_lang, out,
                  source_lang=source_lang, progress=lambda m: progress(m))
        job["result"] = {"ok": True, "path": out, "target_lang": target_lang}
        job["status"] = "done"; job["progress"] = 100; job["message"] = "Listo"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        msg = str(e)
        if "dubbing_write" in msg:
            msg = ("Tu API key de ElevenLabs no tiene el permiso 'Dubbing'. "
                   "Actívalo en elevenlabs.io → API Keys (Dubbing → Write).")
        job["message"] = msg


@app.post("/api/dub")
async def dub(video: UploadFile = File(...), target_lang: str = Form("en"),
              source_lang: str = Form("auto")):
    if not video:
        raise HTTPException(400, "Sube un video")
    job_id = uuid.uuid4().hex[:12]
    up = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(up, exist_ok=True)
    vpath = os.path.join(up, "dub_" + os.path.basename(video.filename or "video.mp4"))
    with open(vpath, "wb") as f:
        shutil.copyfileobj(video.file, f)
    JOBS[job_id] = {"status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_dub_job, args=(job_id, vpath, target_lang, source_lang),
                     daemon=True).start()
    return {"job_id": job_id}


def _safe_path(path: str) -> str:
    """Solo permite servir archivos dentro de WORK_DIR."""
    full = os.path.abspath(path)
    if not full.startswith(os.path.abspath(WORK_DIR)):
        raise HTTPException(403, "Ruta no permitida")
    if not os.path.exists(full):
        raise HTTPException(404, "Archivo no existe")
    return full


@app.get("/api/file")
def serve_file(path: str):
    """Sirve un clip/version para previsualizar en el navegador."""
    full = _safe_path(path)
    return FileResponse(full, media_type="video/mp4")


@app.get("/api/download")
def download(path: str, res: str = "1080", name: str = "clip"):
    """Descarga una version re-escalada al ancho pedido, conservando el formato."""
    full = _safe_path(path)
    width = RES_MAP.get(res, 1080)
    out_dir = os.path.join(os.path.dirname(full), "downloads")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{name}_{width}w.mp4")
    if not os.path.exists(out_path):
        export_resolution(full, out_path, width)
    return FileResponse(out_path, media_type="video/mp4",
                        filename=f"{name}_{width}w.mp4")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8420)
