"""Servidor web local de CreativeMaxing."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

import sys
sys.path.insert(0, os.path.dirname(__file__))
from pipeline.orchestrator import process_job, analyze_select, render_versions
from pipeline.assemble import export_resolution, list_sfx, concat_clips
from pipeline.ffmpeg_utils import probe as _probe
from pipeline.scripts import generate_scripts, suggest_music
from pipeline.voiceover import (synthesize, synthesize_with_timestamps,
                                music as gen_music, VOICES)
from pipeline.hook_gen import fetch_page_text
from pipeline.product_swap import detect_product_ranges, find_new_clips, swap_product
from pipeline.dubbing import dub_video, LANGS as DUB_LANGS
from pipeline.auto_studio import generar_creativo_auto
from pipeline.narrative import analyze_narrative
from pipeline.downloader import download_urls
from pipeline.producto_clips import producto_a_clips
from pipeline.disruptive_images import (generar_conceptos, generar_ads_fullprompt,
                                        generar_ad_fullprompt, _integrar_producto_ia)
from pipeline import foreplay_search as fp

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


app = FastAPI(title="CreativeMaxing", lifespan=lifespan)


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


def _load_foreplay_key() -> str | None:
    return _load_key("FOREPLAY_API_KEY")


def _agregar_musica_sfx(versions: list[dict], work_dir: str, product_desc: str, progress) -> None:
    """Cortar clips: música de fondo (baja) + SFX variados en los cortes, conservando el audio del clip."""
    from pipeline.assemble import add_music_sfx
    sfx = list_sfx()
    ek = _load_eleven_key()
    music_path = None
    if ek:
        try:
            progress("Poniendo música de fondo...", 95)
            music_path = os.path.join(work_dir, "bed.mp3")
            gen_music(ek, f"música de fondo instrumental moderna y energética para un anuncio de "
                      f"{product_desc or 'producto'}, viral, sin voz", music_path, length_ms=30000)
        except Exception:  # noqa: BLE001
            music_path = None
    for v in versions:
        cuts, acc = [], 0.0
        for sg in (v.get("segments") or [])[:-1]:
            acc += float(sg.get("duration", 0)); cuts.append(acc)
        try:
            out = v["path"][:-4] + "_mx.mp4"
            v["path"] = add_music_sfx(v["path"], out, music_path=music_path, sfx_paths=sfx, cut_times=cuts)
        except Exception:  # noqa: BLE001
            pass


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
        if isinstance(result, dict) and result.get("ok") and result.get("versions") \
                and settings.get("musica", True):
            _agregar_musica_sfx(result["versions"], os.path.join(WORK_DIR, job_id),
                                settings.get("product_desc", ""), progress)
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
        "has_foreplay_key": bool(_load_foreplay_key()),
        "voices": [{"key": k, "label": v["label"]} for k, v in VOICES.items()],
        "dub_langs": [{"code": c, "label": n} for c, n in DUB_LANGS.items()],
    }


_KEY_ENV = {"gemini": "GEMINI_API_KEY", "eleven": "ELEVENLABS_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY", "foreplay": "FOREPLAY_API_KEY"}
# Prefijos esperados por proveedor: evita pegar el key equivocado en el campo equivocado
# (fue lo que pasó: un key de Anthropic terminó en GEMINI_API_KEY y rompió todo lo de Gemini).
_KEY_PREFIX = {"gemini": ("AIza", "AQ."), "eleven": ("sk_",), "anthropic": ("sk-ant-",)}
_KEY_LABEL = {"gemini": "Gemini (empieza con AIza o AQ.)",
              "eleven": "ElevenLabs (empieza con sk_)",
              "anthropic": "Claude/Anthropic (empieza con sk-ant-)"}


@app.post("/api/save-key")
def save_key(key: str = Form(...), provider: str = Form("gemini")):
    key = key.strip()
    env_name = _KEY_ENV.get(provider)
    if not env_name:   # NUNCA caer por defecto en otro proveedor (sobrescribiría la key equivocada)
        raise HTTPException(400, f"Proveedor desconocido: {provider}")
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


def _safe_link_paths(link_paths: list[str]) -> list[str]:
    """Solo acepta rutas de videos ya BAJADOS que estén dentro de UPLOAD_DIR/WORK_DIR y existan (seguridad)."""
    out = []
    for p in link_paths or []:
        ap = os.path.abspath(p)
        if _within(ap, UPLOAD_DIR, WORK_DIR) and os.path.exists(ap):
            out.append(ap)
    return out


@app.post("/api/process")
async def process(
    files: list[UploadFile] = File(None),
    link_paths: list[str] = Form([]),
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
    job_id = uuid.uuid4().hex[:12]
    job_upload = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_upload, exist_ok=True)

    paths = []
    for f in (files or []):
        dest = os.path.join(job_upload, os.path.basename(f.filename or f"v_{len(paths)}.mp4"))
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        paths.append(dest)
    paths += _safe_link_paths(link_paths)      # videos bajados de TikTok (pegados como links)
    if not paths:
        raise HTTPException(400, "Sube al menos un video o baja unos de TikTok")

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


# ---- Cortar clips DESDE LINKS de TikTok (pegar links -> bajar -> cortar) ----

@app.post("/api/fetch-links")
async def fetch_links(links: str = Form("")):
    """Baja videos de TikTok al servidor y devuelve sus rutas (para cortarlos luego con /api/process,
    después de que el usuario configure los ajustes). NO corta nada aquí."""
    urls = [u for u in links.split() if u.startswith("http")]
    if not urls:
        raise HTTPException(400, "Pega al menos un link de TikTok")
    job_id = uuid.uuid4().hex[:12]
    out_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(out_dir, exist_ok=True)
    dl = download_urls(urls, out_dir)
    vids = [{"path": d["path"], "name": d.get("filename") or os.path.basename(d["path"])}
            for d in dl if d.get("ok") and d.get("path")]
    if not vids:
        return {"videos": [], "error": "No se pudo bajar ningún video (revisa los links)"}
    return {"videos": vids}


def _gc_jobs(keep: int = 80):
    """Evita que JOBS crezca sin límite (fuga de RAM en sesiones largas): si hay muchos, borra los MÁS
    VIEJOS que YA terminaron (nunca toca los que están 'running')."""
    if len(JOBS) <= keep:
        return
    terminados = sorted((kv for kv in list(JOBS.items()) if kv[1].get("status") != "running"),
                        key=lambda kv: kv[1].get("created", 0))
    for jid, _ in terminados[:len(JOBS) - keep]:
        JOBS.pop(jid, None)


@app.get("/api/status/{job_id}")
def status(job_id: str):
    _gc_jobs()   # limpieza oportunista de trabajos viejos ya terminados
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    return {
        "status": job.get("status", "running"), "progress": job.get("progress", 0),
        "message": job.get("message", ""), "result": job.get("result"),
    }


# ---- MODO AUTOMÁTICO: un video ganador -> creativo terminado (cadena completa) ----

def _run_auto_job(job_id: str, video_paths: list[str], settings: dict):
    """Procesa VARIOS videos: un creativo terminado por cada uno (en lote)."""
    job = JOBS[job_id]
    n = max(1, len(video_paths))

    try:
        creativos = []
        for i, vp in enumerate(video_paths):
            def progress(msg, pct, _i=i):
                job["message"] = f"Creativo {_i + 1}/{n}: {msg}"
                job["progress"] = int((_i * 100 + pct) / n)   # progreso global del lote

            r = generar_creativo_auto(
                vp,
                gemini_key=_load_env_key(),
                eleven_key=_load_eleven_key(),
                anthropic_key=_load_anthropic_key(),
                product_desc=settings.get("product_desc", ""),
                voz=settings.get("voz", "juan_carlos"),
                oferta_2x1=settings.get("oferta_2x1", False),
                verticalizar=settings.get("verticalizar", True),
                caption_style=settings.get("caption_style", "bold_outline"),
                oferta=settings.get("oferta", ""),
                work_dir=os.path.join(WORK_DIR, job_id, f"c{i}"),
                progress=progress,
            )
            r["nombre"] = os.path.basename(vp)
            creativos.append(r)

        ok_n = sum(1 for c in creativos if c.get("ok") and c.get("video"))
        job["result"] = {"ok": True, "creativos": creativos,
                         "resumen": f"{ok_n}/{n} creativo(s) listo(s)"}
        job["status"] = "done"
        job["progress"] = 100
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


@app.post("/api/auto")
async def auto(
    files: list[UploadFile] = File(...),
    product_desc: str = Form(""),
    voz: str = Form("juan_carlos"),
    oferta_2x1: bool = Form(False),
    verticalizar: bool = Form(True),
    caption_style: str = Form("bold_outline"),
    oferta: str = Form(""),
):
    if not files:
        raise HTTPException(400, "Sube al menos un video ganador")
    job_id, paths = _save_uploads(files)
    JOBS[job_id] = {"status": "running", "progress": 0,
                    "message": "Iniciando...", "result": None, "created": time.time()}
    settings = {
        "product_desc": product_desc.strip(),
        "voz": voz if voz in ("kate", "juan_carlos") else "juan_carlos",
        "oferta_2x1": bool(oferta_2x1),
        "verticalizar": bool(verticalizar),
        "caption_style": caption_style,
        "oferta": oferta.strip(),
    }
    threading.Thread(target=_run_auto_job, args=(job_id, paths, settings), daemon=True).start()
    return {"job_id": job_id}


# ---- BUSCAR CREATIVOS EN TIKTOK (foto + nombre -> links reales) ----

@app.post("/api/tiktok-search")
async def tiktok_search(nombre: str = Form(""), count: int = Form(20),
                        foto: UploadFile = File(None)):
    from pipeline.tiktok_search import buscar
    img_path = None
    if foto is not None and foto.filename:
        d = os.path.join(UPLOAD_DIR, "tksearch")
        os.makedirs(d, exist_ok=True)
        img_path = os.path.join(d, os.path.basename(foto.filename))
        with open(img_path, "wb") as o:
            shutil.copyfileobj(foto.file, o)
    if not (nombre.strip() or img_path):
        raise HTTPException(400, "Dame el nombre del producto o una foto")
    return buscar(image_path=img_path, nombre=nombre.strip(),
                  api_key=_load_env_key(), count=int(count))


# ---- CLON GANADOR CON MI PRODUCTO (reemplazo inteligente por movimiento) ----

def _run_clone_job(job_id: str, winner: str, photos: list, videos: list, settings: dict):
    from pipeline.winner_clone import clonar_ganador
    job = JOBS[job_id]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = pct

    try:
        result = clonar_ganador(
            winner, our_photos=photos, our_videos=videos,
            product_desc=settings.get("product_desc", ""),
            old_desc=settings.get("old_desc", ""),
            doblar=settings.get("doblar", False),
            voz=settings.get("voz", "juan_carlos"),
            verticalizar=settings.get("verticalizar", True),
            gemini_key=_load_env_key(), eleven_key=_load_eleven_key(),
            work_dir=os.path.join(WORK_DIR, job_id), progress=progress,
        )
        job["result"] = result
        job["status"] = "done" if result.get("ok") else "error"
        if not result.get("ok"):
            job["message"] = result.get("error", "Error")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"; job["message"] = f"Error: {e}"


@app.post("/api/clone")
async def clone(
    winner: UploadFile = File(...),
    photos: list[UploadFile] = File([]),
    videos: list[UploadFile] = File([]),
    product_desc: str = Form(""),
    old_desc: str = Form(""),
    doblar: bool = Form(False),
    voz: str = Form("juan_carlos"),
    verticalizar: bool = Form(True),
):
    if not winner:
        raise HTTPException(400, "Sube el creativo ganador")
    job_id = uuid.uuid4().hex[:12]
    up = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(up, exist_ok=True)

    def _save(f, sub):
        d = os.path.join(up, sub); os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, os.path.basename(f.filename or "f"))
        with open(dest, "wb") as o:
            shutil.copyfileobj(f.file, o)
        return dest

    winner_path = _save(winner, "winner")
    photo_paths = [_save(f, "photos") for f in (photos or []) if f and f.filename]
    video_paths = [_save(f, "videos") for f in (videos or []) if f and f.filename]

    JOBS[job_id] = {"status": "running", "progress": 0,
                    "message": "Iniciando...", "result": None, "created": time.time()}
    settings = {
        "product_desc": product_desc.strip(), "old_desc": old_desc.strip(),
        "doblar": bool(doblar), "voz": voz if voz in ("kate", "juan_carlos") else "juan_carlos",
        "verticalizar": bool(verticalizar),
    }
    threading.Thread(target=_run_clone_job,
                     args=(job_id, winner_path, photo_paths, video_paths, settings),
                     daemon=True).start()
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
                                   settings["target_seconds"], sample, blueprint=blueprint,
                                   oferta_2x1=settings.get("oferta_2x1", False))
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
    files: list[UploadFile] = File(None),
    link_paths: list[str] = Form([]),
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
    oferta_2x1: bool = Form(False),
    reference_ad: UploadFile | None = File(None),
):
    job_id, paths = _save_uploads(files or [])
    paths += _safe_link_paths(link_paths)      # videos bajados de TikTok
    if not paths:
        raise HTTPException(400, "Sube al menos un video o baja unos de TikTok")
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
        "oferta_2x1": bool(oferta_2x1),
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
            captions=s.get("captions", False), caption_style=s.get("caption_style", "hormozi"),
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


def _run_dub_job(job_id: str, video_path: str, target_lang: str, source_lang: str,
                 oferta_2x1: bool = False, product_desc: str = ""):
    job = JOBS[job_id]

    def progress(msg, pct=None):
        job["message"] = msg
        if pct is not None:
            job["progress"] = pct

    try:
        wd = os.path.join(WORK_DIR, job_id)
        os.makedirs(wd, exist_ok=True)
        # Oferta 2x1: NO se traduce verbatim; se usa la voz COLOMBIANA que reescribe el guion
        # (español colombiano) y MENCIONA el 2x1 en el audio.
        if oferta_2x1:
            from pipeline.dub_colombia import generar_dub
            progress("Doblando a español colombiano (con oferta 2x1)...", 15)
            d = generar_dub(video_path, api_key=_load_env_key(), eleven_key=_load_eleven_key(),
                            product_desc=product_desc, voz="juan_carlos", oferta_2x1=True,
                            generar_video=True, work_dir=wd,
                            progress=lambda m, p=None: progress(m, p if p is not None else 50))
            if d.get("ok") and d.get("video"):
                job["result"] = {"ok": True, "path": d["video"], "target_lang": "es-CO · 2x1"}
                job["status"] = "done"; job["progress"] = 100
                job["message"] = "Listo (voz colombiana · menciona el 2x1)"
            else:
                job["status"] = "error"
                job["message"] = d.get("error", "Error en el doblaje colombiano")
            return
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
async def dub(video: UploadFile = File(None), target_lang: str = Form("en"),
              source_lang: str = Form("auto"), oferta_2x1: bool = Form(False),
              product_desc: str = Form(""), video_url: str = Form("")):
    job_id = uuid.uuid4().hex[:12]
    up = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(up, exist_ok=True)
    vpath = os.path.join(up, "dub_video.mp4")
    if video_url.strip():
        # Doblar un creativo de Foreplay: bajarlo primero (solo su CDN por seguridad)
        from urllib.parse import urlparse
        host = (urlparse(video_url).hostname or "").lower()
        if not (host == "foreplay.co" or host.endswith(".foreplay.co")):
            raise HTTPException(400, "URL de video no permitida")
        if not fp.descargar_video(video_url.strip(), vpath):
            raise HTTPException(502, "No se pudo bajar el creativo de Foreplay")
    elif video is not None and video.filename:
        vpath = os.path.join(up, "dub_" + os.path.basename(video.filename))
        with open(vpath, "wb") as f:
            shutil.copyfileobj(video.file, f)
    else:
        raise HTTPException(400, "Sube un video o pasa un creativo de Foreplay")
    JOBS[job_id] = {"status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_dub_job,
                     args=(job_id, vpath, target_lang, source_lang, bool(oferta_2x1),
                           product_desc.strip()),
                     daemon=True).start()
    return {"job_id": job_id}


def _run_download_job(job_id: str, urls: list[str]):
    """Baja videos con yt-dlp a WORK_DIR/job_id (servibles via /api/file)."""
    job = JOBS[job_id]
    try:
        out_dir = os.path.join(WORK_DIR, job_id)

        def progress(msg, pct):
            job["message"] = msg
            job["progress"] = pct

        results = download_urls(urls, out_dir, progress=progress)
        ok = [r for r in results if r["ok"]]
        job["result"] = {"videos": results, "n_ok": len(ok), "n_total": len(results)}
        job["status"] = "done"
        job["progress"] = 100
        job["message"] = f"Listo: {len(ok)}/{len(results)} videos descargados"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


@app.post("/api/download-videos")
async def download_videos(urls: str = Form(...)):
    """Baja videos desde una lista de links (uno por línea) con yt-dlp."""
    links = [u.strip() for u in urls.replace(",", "\n").splitlines() if u.strip()]
    if not links:
        raise HTTPException(400, "Pega al menos un link")
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_download_job, args=(job_id, links), daemon=True).start()
    return {"job_id": job_id}


def _run_producto_job(job_id: str, winner_urls: list[str], product_url: str,
                      image_path: str | None, product_desc: str, settings: dict):
    """Producto → Clips: descarga ganadores → entiende el producto → crea clips."""
    job = JOBS[job_id]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = pct

    try:
        result = producto_a_clips(
            winner_urls, os.path.join(WORK_DIR, job_id),
            product_url=product_url, image_path=image_path,
            product_desc=product_desc, settings=settings,
            gemini_key=_load_env_key(), eleven_key=_load_eleven_key(), progress=progress,
        )
        job["result"] = result
        job["status"] = "done" if result.get("ok") else "error"
        if not result.get("ok"):
            job["message"] = result.get("error", "Error desconocido")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


@app.post("/api/producto-clips")
async def producto_clips(
    winner_urls: str = Form(...),
    product_url: str = Form(""),
    product_desc: str = Form(""),
    product_image: UploadFile | None = File(None),
    aspect: str = Form("9:16"),
    target_seconds: float = Form(15.0),
    max_clip: float = Form(3.0),
    blur_captions: bool = Form(True),
    text_mode: str = Form("tapar"),
    musica: bool = Form(True),
    bajar_volumen: bool = Form(True),
):
    """Semi-auto: pega links de ganadores + tu producto → descarga + clips en una pasada."""
    links = [u.strip() for u in winner_urls.replace(",", "\n").splitlines() if u.strip()]
    if not links:
        raise HTTPException(400, "Pega al menos un link de un creativo ganador")

    job_id = uuid.uuid4().hex[:12]
    image_path = None
    if product_image and product_image.filename:
        up = os.path.join(UPLOAD_DIR, job_id)
        os.makedirs(up, exist_ok=True)
        image_path = os.path.join(up, "producto_" + os.path.basename(product_image.filename))
        with open(image_path, "wb") as f:
            shutil.copyfileobj(product_image.file, f)

    settings = {
        "aspect": aspect,
        "target_seconds": float(target_seconds),
        "max_clip": min(5.0, max(1.0, float(max_clip))),
        "blur_captions": bool(blur_captions),
        "text_mode": text_mode,
        "use_gemini": True,
        "musica": bool(musica),
        "bajar_volumen": bool(bajar_volumen),
    }
    JOBS[job_id] = {"status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_producto_job,
                     args=(job_id, links, product_url.strip(), image_path,
                           product_desc.strip(), settings), daemon=True).start()
    return {"job_id": job_id}


# ─────────────────────────  FOREPLAY (biblioteca de ads ganadores)  ─────────────────────────
@app.get("/api/foreplay-usage")
def foreplay_usage():
    """Créditos disponibles de Foreplay (para mostrar en la pestaña)."""
    return fp.usage(_load_foreplay_key() or "")


@app.get("/api/foreplay-thumb")
def foreplay_thumb(url: str):
    """Proxy de miniaturas de Foreplay (su CDN bloquea el hotlink desde el navegador)."""
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if not (host == "foreplay.co" or host.endswith(".foreplay.co")):
        raise HTTPException(400, "URL no permitida")
    try:
        import requests as _rq
        r = _rq.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20, allow_redirects=False)
        if r.status_code != 200:
            raise HTTPException(502, "No se pudo cargar la miniatura")
        return Response(content=r.content, media_type=r.headers.get("Content-Type", "image/jpeg"),
                        headers={"Cache-Control": "public, max-age=86400"})
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "Error cargando miniatura")


@app.get("/api/foreplay-video")
def foreplay_video(url: str, dl: int = 0):
    """Proxy del MP4 de Foreplay (para reproducir y descargar sin bloqueo de CORS del CDN)."""
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if not (host == "foreplay.co" or host.endswith(".foreplay.co")):
        raise HTTPException(400, "URL no permitida")
    try:
        import requests as _rq
        r = _rq.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=90,
                    stream=True, allow_redirects=False)   # stream: no cargar el MP4 entero en RAM
        if r.status_code != 200:
            raise HTTPException(502, "No se pudo cargar el video")
        headers = {"Cache-Control": "public, max-age=3600"}
        if r.headers.get("Content-Length"):
            headers["Content-Length"] = r.headers["Content-Length"]
        if dl:
            headers["Content-Disposition"] = 'attachment; filename="creativo.mp4"'
        return StreamingResponse(r.iter_content(chunk_size=1 << 16),
                                 media_type=r.headers.get("Content-Type", "video/mp4"), headers=headers)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "Error cargando el video")


@app.post("/api/foreplay-search")
def foreplay_search(query: str = Form(""), live: bool = Form(True),
                    languages: str = Form(""), niches: str = Form(""),
                    video_only: bool = Form(True), running_min_days: int = Form(0),
                    video_max_seconds: int = Form(0), cursor: str = Form("")):
    """Busca ads ganadores en Foreplay (+100M) por keyword/idioma/nicho."""
    key = _load_foreplay_key()
    if not key:
        raise HTTPException(400, "Falta la API key de Foreplay (ponla en 🔑 Claves)")
    r = fp.buscar_ads(query, api_key=key, live=live, languages=languages, niches=niches,
                      video_only=video_only,
                      running_min_days=running_min_days or None,
                      video_max_seconds=video_max_seconds or None, cursor=cursor)
    if not r.get("ok"):
        raise HTTPException(502, r.get("error", "No se pudo buscar en Foreplay"))
    return r


def _run_foreplay_clips_job(job_id: str, videos: list[dict], settings: dict):
    """Descarga los videos elegidos de Foreplay → los corta en clips (pipeline normal)."""
    job = JOBS[job_id]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = pct

    try:
        out_dir = os.path.join(WORK_DIR, job_id)
        progress("Descargando videos de Foreplay...", 4)
        paths = fp.descargar_videos(videos, os.path.join(out_dir, "src"),
                                    progress=lambda m, p: progress(m, 4 + int(p * 0.30)))
        if not paths:
            job["status"] = "error"
            job["message"] = "No se pudo descargar ningún video de Foreplay (reintenta)."
            return
        result = process_job(
            paths, out_dir,
            target_seconds=settings["target_seconds"], max_clip_seconds=settings["max_clip"],
            use_gemini=True, product_desc=settings.get("product_desc", ""),
            aspect=settings["aspect"], hook_text="", hook_pos="arriba", auto_hook=False,
            page_url="", enhance=False, effects=False,
            blur_captions=settings.get("blur_captions", True),
            text_mode=settings.get("text_mode", "tapar"),
            gemini_key=_load_env_key(),
            progress=lambda m, p: progress(m, 34 + int(p * 0.66)),
        )
        job["result"] = result
        job["status"] = "done" if result.get("ok") else "error"
        if not result.get("ok"):
            job["message"] = result.get("error", "Error desconocido")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


@app.post("/api/foreplay-clips")
def foreplay_clips(videos: str = Form(...), aspect: str = Form("1:1"),
                   target_seconds: float = Form(15.0), max_clip: float = Form(3.0),
                   blur_captions: bool = Form(True), text_mode: str = Form("tapar")):
    """Descarga los ads elegidos de Foreplay y los corta en clips."""
    import json as _json
    try:
        ads = _json.loads(videos)
        ads = [a for a in ads if isinstance(a, dict) and a.get("video")]
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Selección inválida")
    if not ads:
        raise HTTPException(400, "Elige al menos un ad con video")
    settings = {"aspect": aspect, "target_seconds": float(target_seconds),
                "max_clip": min(5.0, max(1.0, float(max_clip))),
                "blur_captions": bool(blur_captions), "text_mode": text_mode}
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_foreplay_clips_job, args=(job_id, ads, settings), daemon=True).start()
    return {"job_id": job_id}


# ─────────────────────────  EDITOR (línea de tiempo tipo CapCut)  ─────────────────────────
def _thumb(path: str) -> str:
    """Genera (o reusa) una miniatura jpg del clip para la línea de tiempo."""
    thumb = path + ".thumb.jpg"
    if not os.path.exists(thumb):
        try:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.2", "-i", path,
                            "-frames:v", "1", "-vf", "scale=160:-1", thumb],
                           check=True, capture_output=True, timeout=20)
        except Exception:  # noqa: BLE001
            return ""
    return thumb


@app.get("/api/editor-project")
def editor_project(job_id: str):
    """Arma el 'proyecto' editable (clips + miniatura + duración) de un trabajo ya procesado."""
    job = JOBS.get(job_id)
    if not job or not job.get("result"):
        raise HTTPException(404, "No hay un proyecto para ese trabajo")
    res = job["result"]
    clips = []
    for i, c in enumerate(res.get("clips") or []):
        p = c.get("path") if isinstance(c, dict) else c
        if not p or not os.path.exists(p):
            continue
        try:
            dur = _probe(p).duration
        except Exception:  # noqa: BLE001
            dur = 2.0
        seg = c.get("segment", {}) if isinstance(c, dict) else {}
        clips.append({"id": i, "path": p, "thumb": _thumb(p),
                      "duration": round(float(dur), 2),
                      "tag": seg.get("tag", ""), "score": seg.get("score")})
    return {"clips": clips, "aspect": res.get("aspect", "1:1")}


@app.post("/api/editor-export")
def editor_export(clips: str = Form(""), paths: str = Form("")):
    """Renderiza la línea de tiempo: recorta cada clip (in/out) y concatena en el ORDEN dado.

    `clips` = JSON [{path, in, out}] (con recorte). `paths` = JSON [ruta,...] (compat, sin recorte).
    """
    import json as _json
    try:
        if clips.strip():
            items = [c for c in _json.loads(clips) if isinstance(c, dict) and c.get("path")]
        else:
            items = [{"path": p} for p in _json.loads(paths or "[]") if isinstance(p, str)]
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Datos de la línea de tiempo inválidos")
    # Seguridad: solo clips DENTRO de WORK_DIR/UPLOAD_DIR (no rutas arbitrarias del sistema)
    items = [c for c in items if _within(c["path"], WORK_DIR, UPLOAD_DIR) and os.path.exists(c["path"])]
    if not items:
        raise HTTPException(400, "La línea de tiempo está vacía")

    job_id = uuid.uuid4().hex[:12]
    wd = os.path.join(WORK_DIR, job_id)
    os.makedirs(wd, exist_ok=True)

    plist = []
    for k, it in enumerate(items):
        p = it["path"]
        try:
            full = _probe(p).duration
        except Exception:  # noqa: BLE001
            full = None
        ci = max(0.0, float(it.get("in", 0) or 0))
        co = it.get("out")
        co = float(co) if co is not None else (full or 0)
        # ¿hay recorte real? (si no, usa el clip tal cual — más rápido y sin re-encode)
        if full and (ci > 0.05 or co < full - 0.05) and co > ci + 0.1:
            tp = os.path.join(wd, f"trim_{k:03d}.mp4")
            try:
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ci:.3f}", "-i", p,
                                "-t", f"{co - ci:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                                "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
                                "-ac", "2", tp], check=True, capture_output=True, timeout=90)
                plist.append(tp)
            except Exception:  # noqa: BLE001
                plist.append(p)
        else:
            plist.append(p)

    out = os.path.join(wd, "editor_export.mp4")
    concat_clips(plist, out, wd)
    return {"path": out}


@app.get("/api/last-project")
def last_project():
    """Devuelve el job MÁS RECIENTE que tenga clips (para abrirlo en el editor)."""
    best, best_created, best_n = None, -1, 0
    for jid, job in list(JOBS.items()):   # list() evita 'dict changed size during iteration'
        res = job.get("result") or {}
        clips = res.get("clips") or []
        if clips and job.get("created", 0) > best_created:
            best, best_created, best_n = jid, job.get("created", 0), len(clips)
    if not best:
        raise HTTPException(404, "Aún no has creado clips — usa 'Cortar clips' o 'Mi producto' primero")
    return {"job_id": best, "n_clips": best_n}


@app.post("/api/disruptive-angles")
async def disruptive_angles(producto: str = Form(""), link: str = Form(""),
                            ofertas: str = Form(""), precio: str = Form(""),
                            product_image: UploadFile | None = File(None)):
    """Paso 1: analiza producto/link → 6 conceptos disruptivos para que el usuario elija."""
    precio = ""   # REGLA GLOBAL: NUNCA se muestra precio en ningún ad
    if not producto.strip() and not link.strip():
        raise HTTPException(400, "Escribe tu producto o pega el link de la página")
    ctx_id = uuid.uuid4().hex[:12]
    image_path = None
    if product_image and product_image.filename:
        up = os.path.join(UPLOAD_DIR, ctx_id)
        os.makedirs(up, exist_ok=True)
        image_path = os.path.join(up, "prod_" + os.path.basename(product_image.filename))
        with open(image_path, "wb") as f:
            shutil.copyfileobj(product_image.file, f)
    ofertas_list = [o.strip() for o in ofertas.split(",") if o.strip()]
    page_text = ""
    if link.strip():
        try:
            page_text = fetch_page_text(link.strip(), max_chars=3000)
        except Exception:  # noqa: BLE001
            page_text = ""
    conceptos = generar_conceptos(producto.strip() or link.strip(), _load_anthropic_key(),
                                  page_text=page_text, ofertas=ofertas_list, precio=precio.strip())
    if not conceptos:
        raise HTTPException(502, "No se pudieron generar los conceptos (revisa la key de Claude)")
    JOBS[ctx_id] = {"status": "angles", "result": {"variantes": conceptos}, "created": time.time(),
                    "_image_path": image_path, "_precio": precio.strip(), "_ofertas": ofertas_list}
    return {"ctx_id": ctx_id, "conceptos": conceptos}


def _run_disruptive_v2_job(job_id, conceptos, precio, ofertas, image_path):
    job = JOBS[job_id]

    def progress(m, p):
        job["message"] = m
        job["progress"] = p

    # Full-prompt: Google AI dibuja el ad COMPLETO (texto ya escrito bien por Claude); la ortografía del
    # render se verifica y regenera dentro de generar_ads_fullprompt. (precio/ofertas ya van en el prompt.)
    try:
        r = generar_ads_fullprompt(conceptos, os.path.join(WORK_DIR, job_id), gemini_key=_load_env_key(),
                                   product_image_path=image_path, progress=progress)
        job["result"] = r
        job["status"] = "done" if r.get("ok") else "error"
        if not r.get("ok"):
            job["message"] = r.get("error", "Error desconocido")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


@app.post("/api/disruptive-images")
async def disruptive_images(ctx_id: str = Form(...), indices: str = Form(...)):
    """Paso 2: genera las imágenes (escena + texto compuesto) de los conceptos ELEGIDOS."""
    import json as _json
    ctx = JOBS.get(ctx_id)
    if not ctx or not (ctx.get("result") or {}).get("variantes"):
        raise HTTPException(404, "Primero analiza el producto (paso 1)")
    try:
        idxs = [int(i) for i in _json.loads(indices)]
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Selección inválida")
    todos = ctx["result"]["variantes"]
    elegidos = [dict(todos[i]) for i in idxs if 0 <= i < len(todos)]
    if not elegidos:
        raise HTTPException(400, "Elige al menos un concepto")
    ctx.update({"status": "running", "progress": 0, "message": "Iniciando...",
                "result": {"variantes": elegidos}})
    threading.Thread(target=_run_disruptive_v2_job,
                     args=(ctx_id, elegidos, ctx.get("_precio", ""), ctx.get("_ofertas", []),
                           ctx.get("_image_path")), daemon=True).start()
    return {"job_id": ctx_id}


@app.post("/api/regenerate-image")
def regenerate_image(job_id: str = Form(...), index: int = Form(...)):
    """Regenera UNA sola imagen (escena limpia + texto compuesto). Síncrono."""
    job = JOBS.get(job_id)
    if not job or not (job.get("result") or {}).get("variantes"):
        raise HTTPException(404, "No hay un proyecto de ads para ese job")
    variantes = job["result"]["variantes"]
    if index < 0 or index >= len(variantes):
        raise HTTPException(400, "Índice fuera de rango")
    v = variantes[index]
    out = os.path.join(WORK_DIR, job_id, f"ad_{index:02d}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:                              # full-prompt: ad completo + verificación de ortografía
        img = generar_ad_fullprompt(v, out, gemini_key=_load_env_key(),
                                    product_image_path=job.get("_image_path"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"No se pudo regenerar: {e}")
    if not img:
        raise HTTPException(502, v.get("error") or "Google no devolvió imagen (reintenta o revisa créditos)")
    v["imagen"] = img
    return {"imagen": img}


@app.post("/api/disruptive-add-product")
def disruptive_add_product(job_id: str = Form(...), index: int = Form(...)):
    """Mete el PRODUCTO real integrado en UNA imagen ya generada (2ª pasada). Síncrono."""
    job = JOBS.get(job_id)
    if not job or not (job.get("result") or {}).get("variantes"):
        raise HTTPException(404, "No hay un proyecto de ads para ese job")
    variantes = job["result"]["variantes"]
    if index < 0 or index >= len(variantes):
        raise HTTPException(400, "Índice fuera de rango")
    v = variantes[index]
    if not v.get("imagen"):
        raise HTTPException(400, "Esa imagen aún no está generada")
    prod = job.get("_image_path")
    if not (prod and os.path.exists(prod)):
        raise HTTPException(400, "No subiste foto del producto en el paso 1")
    try:
        res = _integrar_producto_ia(v["imagen"], prod, _load_env_key())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"No se pudo poner el producto: {e}")
    if not res:   # bloqueo/cuota/sin imagen → el ad quedó intacto; avisa de verdad
        raise HTTPException(502, "No se pudo integrar el producto (reintenta o revisa el tope de gasto de Google).")
    return {"imagen": v["imagen"]}


def _within(path: str, *bases: str) -> bool:
    """True si `path` está DENTRO de alguna de las carpetas base (sin traversal ni hermanos tipo 'work2')."""
    try:
        full = os.path.abspath(path)
    except Exception:  # noqa: BLE001
        return False
    for b in bases:
        base = os.path.abspath(b)
        if full == base or full.startswith(base + os.sep):
            return True
    return False


def _safe_path(path: str) -> str:
    """Solo permite servir archivos dentro de WORK_DIR o UPLOAD_DIR."""
    full = os.path.abspath(path)
    if not _within(full, WORK_DIR, UPLOAD_DIR):
        raise HTTPException(403, "Ruta no permitida")
    if not os.path.exists(full):
        raise HTTPException(404, "Archivo no existe")
    return full


_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".webp": "image/webp", ".gif": "image/gif", ".mp3": "audio/mpeg", ".webm": "video/webm"}


@app.get("/api/file")
def serve_file(path: str):
    """Sirve un clip/version/miniatura para previsualizar en el navegador."""
    full = _safe_path(path)
    ext = os.path.splitext(full)[1].lower()
    return FileResponse(full, media_type=_MIME.get(ext, "video/mp4"))


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
