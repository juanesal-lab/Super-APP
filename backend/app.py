"""Servidor web local de CreativeMaxing."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

import requests
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

import sys
sys.path.insert(0, os.path.dirname(__file__))
from pipeline.orchestrator import process_job, analyze_select, render_versions
from pipeline.assemble import export_resolution, list_sfx, concat_clips
from pipeline.ffmpeg_utils import probe as _probe, video_ok as _video_ok
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
                                        generar_ad_fullprompt, _integrar_producto_ia,
                                        editar_imagen_ia, _error_amigable, _IMG_MODEL_DRAFT)
from pipeline.image_variator import variar_imagen
from pipeline import foreplay_search as fp
from pipeline.hook_variator import variar_hook
from pipeline.creative_variator import generar_variaciones
from pipeline import asistente as asst

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE, "uploads")
WORK_DIR = os.path.join(BASE, "work")
FRONTEND = os.path.join(BASE, "frontend")
ENV_FILE = os.path.join(BASE, ".env")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)


def _gc_disk(days: int = 3, keep_recent: int = 25) -> None:
    """Limpia del DISCO los trabajos viejos de work/ y uploads/ (la app solo limpiaba MEMORIA →
    el disco crecía sin límite; se medían ~50GB de renders viejos). Borra subcarpetas con más de
    `days` días SIN tocar las `keep_recent` más nuevas ni nada modificado hace poco. 100% seguro:
    solo carpetas (no archivos sueltos), con try/except, y nunca las recientes."""
    import shutil
    import time as _t
    corte = _t.time() - days * 86400
    for base in (WORK_DIR, UPLOAD_DIR):
        try:
            subdirs = [os.path.join(base, d) for d in os.listdir(base)
                       if os.path.isdir(os.path.join(base, d)) and not d.startswith("_")]
        except OSError:
            continue
        # conserva SIEMPRE las más nuevas (por si el usuario vuelve a un trabajo reciente)
        subdirs.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
        for p in subdirs[keep_recent:]:
            try:
                if os.path.getmtime(p) < corte:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Baja el modelo EAST (~92 MB) la primera vez, en segundo plano para no
    # frenar el arranque del servidor. Así el usuario no hace nada manual.
    from pipeline.text_detect import ensure_model
    threading.Thread(target=ensure_model, daemon=True).start()
    # Auto-limpieza de disco al arrancar (renders viejos >3 días) — evita que work/ crezca a decenas
    # de GB. En segundo plano para no frenar el arranque.
    threading.Thread(target=_gc_disk, daemon=True).start()
    yield


app = FastAPI(title="CreativeMaxing", lifespan=lifespan)


# Estado de trabajos en memoria
JOBS: dict[str, dict] = {}


def _persist_disruptive(job_id: str):
    """Guarda el job de Ads imagen a disco (work/<id>/job.json) para que Regenerar / ➕Producto /
    🎲Otro ángulo / ✏️Ajustar SIGAN funcionando aunque el server se reinicie (antes: 404)."""
    import json as _json
    job = JOBS.get(job_id)
    if not job:
        return
    data = {k: job.get(k) for k in ("status", "result", "created", "_image_path", "_precio",
                                    "_ofertas", "_producto", "_page_text", "_tipo", "_hd")}
    try:
        d = os.path.join(WORK_DIR, job_id)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "job.json"), "w") as f:
            _json.dump(data, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def _stash_regen(job: dict, result, job_id: str, extra: dict | None = None):
    """Saca `_regen` (estado para regenerar UNA versión) del manifest → lo guarda en el job y a
    disco (work/<id>/regen.json), y lo QUITA del result que va al frontend (es pesado: pool de
    segmentos + fases). Pedido de Juan: reemplazar una versión sin rehacer el lote."""
    import json as _json
    if not isinstance(result, dict):
        return
    regen = result.pop("_regen", None)
    if not regen:
        return
    if extra:                      # ej. la voz elegida (para regenerar "otro guion")
        regen.setdefault("settings", {}).update({k: v for k, v in extra.items() if v is not None})
    job["_regen"] = regen
    try:
        d = os.path.join(WORK_DIR, job_id)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "regen.json"), "w") as f:
            _json.dump(regen, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def _load_regen(job_id: str) -> dict | None:
    """Estado de regeneración desde memoria o disco (sobrevive reinicios)."""
    job = JOBS.get(job_id)
    if job and job.get("_regen"):
        return job["_regen"]
    import json as _json
    try:
        with open(os.path.join(WORK_DIR, job_id, "regen.json")) as f:
            return _json.load(f)
    except Exception:  # noqa: BLE001
        return None


def _get_job(job_id: str) -> dict | None:
    """JOBS en memoria, o recuperado de disco si el server se reinició."""
    import json as _json
    job = JOBS.get(job_id)
    if job:
        return job
    p = os.path.join(WORK_DIR, job_id, "job.json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                job = _json.load(f)
            JOBS[job_id] = job
            return job
        except Exception:  # noqa: BLE001
            return None
    return None


def _lanzar_job(job_id: str, fn, *args) -> None:
    """Lanza el worker de un job en 2º plano Y guarda la receta (fn + args) en el job para que
    el botón 🔄 Reintentar del panel de trabajos pueda relanzarlo con UN clic si falla.
    Los archivos de entrada viven en uploads/<id>/ (se conservan días) → el reintento los reusa;
    si ya no están, el worker falla con su error honesto de siempre. Solo memoria (no persiste
    reinicios): tras un reinicio el panel ofrece 'volver a la pestaña' en vez de reintentar."""
    j = JOBS.get(job_id)
    if j is not None:
        j["_retry"] = (fn, args)
    threading.Thread(target=fn, args=(job_id, *args), daemon=True).start()

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


def _load_pexels_key() -> str | None:
    return _load_key("PEXELS_API_KEY")


def _load_pixabay_key() -> str | None:
    return _load_key("PIXABAY_API_KEY")


def _load_shopify() -> tuple[str | None, str | None, str | None]:
    """(dominio, admin_token, theme_id opcional) para el módulo Crear Landings."""
    return (_load_key("SHOPIFY_STORE_DOMAIN"), _load_key("SHOPIFY_ADMIN_API_TOKEN"),
            _load_key("SHOPIFY_THEME_ID"))


# --- Chequeo EN VIVO de la key de Gemini (auditoría: la pill decía "configurada ✓" con la key en 429) ---
# Cache en memoria por key con TTL: no le pegamos a Google en cada refresh del front.
_GEMINI_CHECK_TTL = 600  # 10 minutos
_GEMINI_CHECK_CACHE: dict[str, tuple[float, dict]] = {}


def _check_gemini_key(key: str) -> dict:
    """Valida la key de Gemini GENERANDO de verdad (1 token con flash — el caso real de Jack:
    'prepayment credits depleted' devuelve 200 al listar modelos pero 429 al GENERAR, y la pill
    decía 'ok' mintiendo). Costo: fracción de centavo por chequeo, cacheado 10 min; si no hay
    créditos, el 429 es gratis. Devuelve {"ok": True} si genera, {"ok": False, "reason":
    "invalida"|"cuota"}, y {"ok": None, "reason": "red"} si no hubo respuesta (no se castiga)."""
    cacheado = _GEMINI_CHECK_CACHE.get(key)
    if cacheado and time.time() - cacheado[0] < _GEMINI_CHECK_TTL:
        return cacheado[1]
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            params={"key": key},
            json={"contents": [{"parts": [{"text": "ok"}]}],
                  "generationConfig": {"maxOutputTokens": 1}},
            timeout=10)
        if r.status_code == 200:
            res = {"ok": True}
        elif r.status_code in (400, 403):
            res = {"ok": False, "reason": "invalida"}
        elif r.status_code == 429:
            res = {"ok": False, "reason": "cuota"}
        else:
            res = {"ok": None, "reason": "red"}  # respuesta rara de Google: no castigamos la key
    except Exception:  # noqa: BLE001
        res = {"ok": None, "reason": "red"}  # timeout / excepción de red: desconocido, no inválida
    _GEMINI_CHECK_CACHE[key] = (time.time(), res)
    return res


def _agregar_banner_oferta(versions: list[dict], work_dir: str, progress,
                           start: float = 0.0, dur: float = 0.0,
                           line2: str = "OFERTA 2X1") -> None:
    """Cortar clips: pill 'ENVÍO GRATIS · PAGAS AL RECIBIR' + 2ª línea (por defecto 'OFERTA 2X1',
    pero Jack puede poner SU oferta o dejarla vacía = solo envío gratis). La IA elige la altura para
    no tapar caras/producto (offer_banner.safe_top_y). `start`/`dur`: el banner aparece en ese
    segundo por esa duración (no choca con el gancho). `line2`: texto de la 2ª línea ('' = sin ella)."""
    from pipeline.offer_banner import add_offer_banner
    from pipeline.assemble import WORKERS
    from concurrent.futures import ThreadPoolExecutor
    line2 = (line2 or "").strip()
    cuando = f" (aparece al seg {start:.0f})" if start and start > 0 else ""
    etq = line2 or "envío gratis"
    progress(f"🏷️ Poniendo el banner de oferta ({etq}){cuando}...", 97)
    gk = _load_env_key()

    # EN PARALELO (antes en serie: 1 llamada Gemini + 1 re-encode por versión, una tras otra).
    # add_offer_banner ya usa un PNG con nombre único por versión (no se pisan).
    def _banner_one(v):
        try:
            out = v["path"][:-4] + "_of.mp4"
            v["path"] = add_offer_banner(v["path"], out, work_dir, line2=line2,
                                         start=start, dur=dur, gemini_key=gk)
        except Exception:  # noqa: BLE001
            pass

    with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(versions)))) as ex:
        list(ex.map(_banner_one, versions))


def _agregar_end_card(versions: list[dict], work_dir: str, progress,
                      line1: str = "PAGAS AL RECIBIR",
                      line2: str = "ENVÍO GRATIS A TODA COLOMBIA",
                      cta: str = "PIDE EL TUYO AQUÍ 👇") -> None:
    """🏁 END-CARD de CTA: cierre de 1.5s al final de cada versión con la oferta clara
    ('PAGAS AL RECIBIR' + envío gratis + pill de CTA) — patrón ganador en ads COD para
    rematar la conversión. SIN precios. En paralelo, igual que _agregar_banner_oferta."""
    from pipeline.end_card import append_end_card
    from pipeline.assemble import WORKERS
    from concurrent.futures import ThreadPoolExecutor
    progress("🏁 Poniendo el cierre final (pagas al recibir)...", 98)

    # EN PARALELO: cada versión es un concat independiente (PNG/clip con nombre único, no se pisan)
    def _ec_one(v):
        try:
            out = v["path"][:-4] + "_ec.mp4"
            v["path"] = append_end_card(v["path"], out, work_dir,
                                        line1=line1, line2=line2, cta=cta)
        except Exception:  # noqa: BLE001
            pass

    with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(versions)))) as ex:
        list(ex.map(_ec_one, versions))


def _agregar_hooks_por_version(result: dict, work_dir: str, product_desc: str, progress) -> None:
    """🎯 Un HOOK de texto (pastilla blanca arriba, 0-3s) por versión, COHERENTE con lo que dice
    cada ángulo (referencia de Jack: 'MIRA LA SOLUCIÓN'). La IA lo escribe; Jack lo edita/re-aplica
    desde los resultados (/api/reaplicar-hook). Se aplica AL FINAL (encima de todo) sobre una base
    que se guarda en v['_prehook'] para poder re-aplicar otro texto sin doble overlay.
    Guarda v['hook_text'] (lo que se muestra en la cajita editable del front)."""
    from pipeline.text_overlay import burn_hook_pill
    from pipeline.hook_gen import generate_hooks_for_versions
    from pipeline.assemble import WORKERS
    from concurrent.futures import ThreadPoolExecutor
    versions = result.get("versions") or []
    if not versions:
        return
    progress("🎯 Escribiendo los hooks de texto por versión...", 98)
    gk = _load_env_key()
    # guion por versión (para que el hook sea coherente con lo que DICE) — del estado de regen
    guiones: dict[str, str] = {}
    try:
        for nm, d in ((result.get("_regen") or {}).get("versions") or {}).items():
            guiones[str(nm)] = d.get("guion", "") or ""
    except Exception:  # noqa: BLE001
        guiones = {}
    infos = [{"name": v.get("name", f"V{i}"),
              "guion": guiones.get(v.get("name", ""), "")} for i, v in enumerate(versions)]
    try:
        hooks = generate_hooks_for_versions(gk, product_desc, infos)
    except Exception:  # noqa: BLE001
        hooks = [""] * len(versions)
    # fallback por versión si la IA no dio hook para alguna. Con key: elegir_hook (Gemini adapta al
    # producto). Sin key/IA caída: hooks genéricos SEGUROS de curiosidad (rotando, nunca off-topic ni
    # cifras) — mejor eso que un hook de librería que no cuadra con el producto.
    _GEN = ["MÍRALO HASTA EL FINAL", "NO VAS A CREER ESTO", "MIRA LA DIFERENCIA",
            "ESTO LO CAMBIA TODO", "LO QUE NADIE TE CONTÓ", "MÍRALO ANTES DE QUE SE AGOTE",
            "PRESTA ATENCIÓN A ESTO", "ASÍ DE FÁCIL"]
    for i, v in enumerate(versions):
        h = ((hooks[i] if i < len(hooks) else "") or "").strip()
        if not h and gk:                    # la IA está viva pero el batch no dio esta → que adapte una
            try:
                from pipeline.winner_blueprint import elegir_hook
                h = (elegir_hook(product_desc, gk, angulo=v.get("name", "")) or "").strip()
            except Exception:  # noqa: BLE001
                h = ""
        if not h:                           # IA caída/sin key → genérico seguro (coherente, no inventa)
            h = _GEN[i % len(_GEN)]
        v["hook_text"] = h.upper()[:50]

    def _one(item):
        i, v = item
        try:
            base = v["path"]
            out = base[:-4] + "_hk.mp4"
            new, ok = burn_hook_pill(base, out, work_dir, v["hook_text"], seconds=3.0,
                                     uid=f"{i}_{os.path.basename(base)}")
            if ok:
                v["_prehook"] = base       # base SIN hook → re-aplicar otro texto sin doble overlay
                v["path"] = new
        except Exception:  # noqa: BLE001
            pass

    with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(versions)))) as ex:
        list(ex.map(_one, list(enumerate(versions))))


def _agregar_musica_sfx(versions: list[dict], work_dir: str, product_desc: str, progress) -> None:
    """Cortar clips: música de fondo (baja) + SFX variados en los cortes, conservando el audio del clip."""
    from pipeline.assemble import add_music_sfx, WORKERS
    from concurrent.futures import ThreadPoolExecutor
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
    # EN PARALELO (antes en serie): cada versión es un remux de audio independiente (-c:v copy).
    def _mx_one(v):
        cuts = list(v.get("cut_times") or [])   # tiempos REALES post-dissolve (build_variations)
        if not cuts:
            acc = 0.0
            for sg in (v.get("segments") or [])[:-1]:
                acc += float(sg.get("duration", 0)); cuts.append(acc)
        # sound design CON INTENCIÓN: los eventos ya vienen calculados en el manifest
        # (orchestrator.sound_design_events); tuplas por si viajaron como listas (JSON).
        events = [(float(t), p, float(vol)) for t, p, vol in (v.get("sfx_events") or [])] or None
        try:
            out = v["path"][:-4] + "_mx.mp4"
            v["path"] = add_music_sfx(v["path"], out, music_path=music_path, sfx_paths=sfx,
                                      cut_times=cuts, sfx_events=events)
        except Exception:  # noqa: BLE001
            pass

    with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(versions)))) as ex:
        list(ex.map(_mx_one, versions))


def _normalizar_audio(versions: list[dict], work_dir: str, progress) -> None:
    """ÚLTIMO paso del post-proceso: normaliza el loudness del audio FINAL de cada versión a
    -14 LUFS (estándar TikTok/Reels) — antes los ads salían con volúmenes dispares (unos bajitos,
    otros reventados) y eso mata retención. Siempre activo (corrección técnica, no creativa) y
    best-effort: si falla una versión se queda como estaba, nunca rompe el job. También normaliza
    v['path_45'] (cut 4:5 para Meta) si existe. Solo re-encodea audio (-c:v copy → barato)."""
    from pipeline.ffmpeg_utils import normalize_loudness
    from pipeline.assemble import WORKERS
    from concurrent.futures import ThreadPoolExecutor
    if not versions:
        return
    progress("🔊 Normalizando el volumen de todas las versiones (-14 LUFS)...", 99)

    # EN PARALELO (mismo patrón que _agregar_musica_sfx): cada versión es independiente.
    def _norm_one(v):
        try:
            for key in ("path", "path_45"):
                p = v.get(key)
                if not p:
                    continue
                out = p[:-4] + "_ln.mp4"
                v[key] = normalize_loudness(p, out)   # si falla/sin audio devuelve p (queda igual)
        except Exception:  # noqa: BLE001
            pass

    with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(versions)))) as ex:
        list(ex.map(_norm_one, versions))


def _qa_tecnico_versiones(versions: list[dict], progress) -> None:
    """QA TÉCNICO de cada versión FINAL (después de normalizar el audio): caza los defectos BARATOS
    que `video_ok` no ve — frames negros, imagen congelada, silencios largos, clipping/audio mudo,
    duración disparatada, streams enfermos. Corre EN PARALELO por versión (mismo patrón que los otros
    post-pasos) y guarda v['qa_tecnico'] = {ok, defectos, metrica}. HONESTO y NO BLOQUEANTE: si hay
    defectos NO frena la entrega, solo se pinta un badge rojo en la tarjeta para que Jack lo sepa."""
    from pipeline.qa_tecnico import revisar_version
    from pipeline.assemble import WORKERS
    from concurrent.futures import ThreadPoolExecutor
    if not versions:
        return
    progress("🩺 Revisión técnica final (frames negros, congelados, audio)...", 99)

    def _qa_one(v):
        try:
            # duración esperada: la suma de los segmentos del guion, si el manifest la trae
            dur_esp = None
            try:
                segs = v.get("segments") or []
                if segs:
                    dur_esp = sum(float(s.get("duration", 0) or 0) for s in segs) or None
            except Exception:  # noqa: BLE001
                dur_esp = None
            v["qa_tecnico"] = revisar_version(v.get("path", ""), dur_esperada=dur_esp)
        except Exception:  # noqa: BLE001
            v["qa_tecnico"] = {"ok": True, "defectos": [], "metrica": {}}

    with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(versions)))) as ex:
        list(ex.map(_qa_one, versions))


def _crop_45(src: str, dst: str) -> bool:
    """Re-corta el master 9:16 FINAL a 4:5 (mismo crop central que el _mk45 del orchestrator)."""
    from pipeline.ffmpeg_utils import run as _ffrun
    from pipeline.assemble import venc
    try:
        _ffrun(["ffmpeg", "-y", "-i", src, "-vf", "crop=iw:iw*5/4:0:(ih-iw*5/4)/2,setsar=1",
                *venc(), "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "copy", dst])
        return os.path.exists(dst)
    except Exception:  # noqa: BLE001
        return False


def _sincronizar_path_45(versions: list[dict], paths_previos: dict[int, str], progress) -> None:
    """FIX de desincronía del cut 4:5 (Meta): el path_45 se genera DENTRO de process_job /
    render_versions, pero los post-pasos de aquí (música → banner → end-card → hooks) solo
    re-escriben v['path'] → el 4:5 salía SIN música/banner/cierre/hook (distinto del 9:16 que
    Jack aprueba). Si el path principal CAMBIÓ tras los post-pasos y hay path_45, se re-corta
    el 4:5 desde el master FINAL. Se llama ANTES de _normalizar_audio (así el 4:5 nuevo también
    queda a -14 LUFS). Best-effort: si el crop falla, queda el 4:5 viejo (no rompe el job)."""
    pend = [v for v in (versions or [])
            if v.get("path_45") and v.get("path") and v["path"] != paths_previos.get(id(v))]
    if not pend:
        return
    progress("Re-generando el cut 4:5 (Meta) con los pasos finales...", 99)
    from pipeline.assemble import WORKERS
    from concurrent.futures import ThreadPoolExecutor

    def _s45_one(v):
        out = v["path"][:-4] + "_45.mp4"
        if _crop_45(v["path"], out):
            v["path_45"] = out

    with ThreadPoolExecutor(max_workers=min(WORKERS, len(pend))) as ex:
        list(ex.map(_s45_one, pend))


def _run_job(job_id: str, paths: list[str], settings: dict):
    job = JOBS[job_id]

    def progress(msg: str, pct: int):
        job["message"] = msg
        job["progress"] = pct

    # guardo los inputs para el flujo "1 de prueba → N más" (re-render reusando estos mismos videos)
    job["_src_paths"] = list(paths)
    job["_src_settings"] = settings
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
            hook_seconds=settings.get("hook_seconds", 0.0),
            auto_hook=settings["auto_hook"],
            page_url=settings["page_url"],
            enhance=settings["enhance"],
            effects=settings.get("effects", False),
            blur_captions=settings.get("blur_captions", False),
            text_mode=settings.get("text_mode", "tapar"),
            caption_pos=settings.get("caption_pos", "abajo"),
            destino=settings.get("destino", "tiktok"),
            gemini_key=_load_env_key(),
            broll_fases=settings.get("broll_fases"),
            n_versions=int(settings.get("n_versions", 8)),
            start_version=int(settings.get("start_version", 0)),
            blur_strength=settings.get("blur_strength", "medio"),
            progress=progress,
        )
        # cuántas versiones se han generado de ESTE origen (para el "N más": arranca donde quedó)
        job["_generated"] = int(settings.get("start_version", 0)) + len((result or {}).get("versions") or [])
        # foto de los paths ANTES de los post-pasos → para re-cortar el 4:5 si el master cambia
        _prev45 = {id(v): v.get("path") for v in ((result or {}).get("versions") or [])
                   if isinstance(v, dict)} if isinstance(result, dict) else {}
        if isinstance(result, dict) and result.get("ok") and result.get("versions") \
                and settings.get("musica", True):
            _agregar_musica_sfx(result["versions"], os.path.join(WORK_DIR, job_id),
                                settings.get("product_desc", ""), progress)
        if result.get("ok") and result.get("versions") and settings.get("banner_oferta"):
            _agregar_banner_oferta(result["versions"], os.path.join(WORK_DIR, job_id), progress,
                                   start=settings.get("banner_start", 0.0),
                                   dur=settings.get("banner_dur", 0.0),
                                   line2=settings.get("banner_line2", "OFERTA 2X1"))
        if result.get("ok") and result.get("versions") and settings.get("end_card"):
            _agregar_end_card(result["versions"], os.path.join(WORK_DIR, job_id), progress)
        if result.get("ok") and result.get("versions") and settings.get("hooks_por_version"):
            _agregar_hooks_por_version(result, os.path.join(WORK_DIR, job_id),
                                       settings.get("product_desc", ""), progress)
        # cut 4:5 (Meta): si los post-pasos cambiaron el master, re-cortarlo del path FINAL
        if isinstance(result, dict) and result.get("ok") and result.get("versions"):
            _sincronizar_path_45(result["versions"], _prev45, progress)
        # ÚLTIMO paso siempre: volumen parejo a -14 LUFS en el audio final de cada versión
        if isinstance(result, dict) and result.get("ok") and result.get("versions"):
            _normalizar_audio(result["versions"], os.path.join(WORK_DIR, job_id), progress)
        # QA técnico final (aditivo, no bloquea): badge honesto si algo salió con defectos
        if isinstance(result, dict) and result.get("ok") and result.get("versions"):
            _qa_tecnico_versiones(result["versions"], progress)
        _stash_regen(job, result, job_id)
        job["result"] = result
        job["status"] = "done" if result.get("ok") else "error"
        if not result.get("ok"):
            job["message"] = result.get("error", "Error desconocido")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


# Assets estáticos del frontend (ej. /assets/garage/*.webp del home)
from fastapi.staticfiles import StaticFiles
app.mount("/assets", StaticFiles(directory=os.path.join(BASE, "assets")), name="assets")

# 📡 Radar Ganadores (spy tool) — módulo en radar/, endpoints en backend/radar_api.py
from radar_api import router as radar_router
app.include_router(radar_router)


@app.post("/api/descubrir")
def api_descubrir(vertical: str = Form("gadgets"), segmento: str = Form(""),
                  min_dias: int = Form(20)):
    """🧭 Descubrir productos ganadores — vista segmentada SOBRE los datos del Radar (no escanea,
    no gasta créditos de scraping). Corre EN SEGUNDO PLANO porque los agentes de IA (veredicto +
    solucionador) tardan; el front sondea /api/status. Si no hay escaneo del Radar, sin_datos honesto."""
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "running", "progress": 5, "message": "Leyendo el Radar...",
                    "result": None, "created": time.time()}

    def _run():
        job = JOBS[job_id]

        def progress(m, p):
            job["message"] = m
            job["progress"] = int(p)

        try:
            from pipeline.descubridor import descubrir
            job["result"] = descubrir(vertical, segmento or None, gemini_key=_load_env_key(),
                                      anthropic_key=_load_anthropic_key(), min_dias=min_dias,
                                      progress=progress)
            job["status"] = "done"
            job["progress"] = 100
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"
            job["message"] = f"Error: {e}"

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}


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
    cfg = {
        "has_gemini_key": bool(_load_env_key()),
        "has_eleven_key": bool(_load_eleven_key()),
        "has_anthropic_key": bool(_load_anthropic_key()),
        "has_foreplay_key": bool(_load_foreplay_key()),
        "has_pexels_key": bool(_load_pexels_key()),
        "has_pixabay_key": bool(_load_pixabay_key()),
        "has_scrapecreators_key": bool(_load_key("SCRAPECREATORS_API_KEY")),   # 📡 Radar
        "has_shopify": bool(_load_shopify()[0] and _load_shopify()[1]),
        "voices": [{"key": k, "label": v["label"]} for k, v in VOICES.items()],
        "dub_langs": [{"code": c, "label": n} for c, n in DUB_LANGS.items()],
    }
    # Aditivo: estado EN VIVO de la key de Gemini ("ok"|"invalida"|"cuota"|"desconocido"|"sin_key").
    # NO reemplaza has_gemini_key (otros flujos lo usan). try/except total: el config
    # NUNCA se puede romper por este chequeo. (Este bloque + return vivían aquí; un merge con la
    # sesión paralela los había arrastrado al fondo de montador_start → /api/config devolvía null.)
    try:
        gk = _load_env_key()
        if not gk:
            cfg["gemini_key_status"] = "sin_key"
        else:
            chk = _check_gemini_key(gk)
            if chk.get("ok") is True:
                cfg["gemini_key_status"] = "ok"
            elif chk.get("ok") is False:
                cfg["gemini_key_status"] = chk.get("reason") or "desconocido"
            else:
                cfg["gemini_key_status"] = "desconocido"
    except Exception:  # noqa: BLE001
        cfg["gemini_key_status"] = "desconocido"
    return cfg


# ── 🎬 MONTADOR: app INDEPENDIENTE que VIAJA en este repo (subcarpeta montador/, su propio server
#    en :8440, sus propios agentes y su propio .env). Super-APP solo la MUESTRA en un iframe y la
#    PRENDE con su run.sh — NUNCA toca su código. Al viajar en el repo, Jack la recibe con git pull. ──
_MONTADOR_DIR = os.path.join(BASE, "montador")     # antes ~/montador-ads (repo aparte); ahora va bundleado
_MONTADOR_URL = "http://127.0.0.1:8440"


@app.get("/api/montador/status")
def montador_status():
    """¿Está viva la app Montador (:8440)? Solo hace ping; no la modifica.
    `instalado`: ¿está la carpeta montador/ en esta copia del repo? (tras git pull, sí en ambas máquinas)."""
    instalado = os.path.exists(os.path.join(_MONTADOR_DIR, "run.sh"))
    try:
        import urllib.request
        with urllib.request.urlopen(_MONTADOR_URL, timeout=1.5) as r:
            return {"up": 200 <= getattr(r, "status", 200) < 500, "instalado": instalado}
    except Exception:  # noqa: BLE001
        return {"up": False, "instalado": instalado}


@app.post("/api/montador/start")
def montador_start():
    """Prende Montador desde la subcarpeta montador/. En la 1ª vez (ej. el Mac de Jack) crea su venv
    e instala sus dependencias SOLO, y luego lanza su run.sh — todo desprendido (no altera su código)."""
    if not os.path.exists(os.path.join(_MONTADOR_DIR, "run.sh")):
        raise HTTPException(404, "No encuentro la carpeta montador/ en este repo. Haz git pull.")
    # 1ª vez: si no hay venv, lo crea + instala requirements; luego exec run.sh (uvicorn en :8440).
    script = ('cd "$MDIR" || exit 1; '
              'if [ ! -x venv/bin/python ]; then python3 -m venv venv && '
              './venv/bin/pip install -q -r requirements.txt; fi; '
              'exec ./run.sh')
    try:
        subprocess.Popen(["/bin/bash", "-c", script], cwd=_MONTADOR_DIR,
                         env={**os.environ, "MDIR": _MONTADOR_DIR},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"No pude lanzar Montador: {e}")


@app.get("/api/caption-preview")
def caption_preview(style: str = "hormozi", size: str = "mediano"):
    """Preview PNG de un estilo de subtítulo (para elegir viendo cómo se ve)."""
    import io
    from PIL import Image
    from pipeline.caption_styles import _render_wordgroup, ESTILOS
    st = style if style in ESTILOS else "hormozi"
    W, H = 640, 260
    grp = [{"word": "MIRA"}, {"word": "ESTO"}, {"word": "GRATIS"}]
    try:
        cap = _render_wordgroup(grp, 1, W, H, st, size)
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "no se pudo renderizar el preview")
    bg = Image.new("RGB", (W, H), (32, 30, 36))
    bg.paste(cap, (0, 0), cap)
    buf = io.BytesIO()
    bg.save(buf, "PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


_KEY_ENV = {"gemini": "GEMINI_API_KEY", "eleven": "ELEVENLABS_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY", "foreplay": "FOREPLAY_API_KEY",
            "pexels": "PEXELS_API_KEY", "pixabay": "PIXABAY_API_KEY",   # bancos de video para B-ROLL
            "scrapecreators": "SCRAPECREATORS_API_KEY",                 # 📡 Radar (Meta Ad Library)
            "shopify_domain": "SHOPIFY_STORE_DOMAIN", "shopify_token": "SHOPIFY_ADMIN_API_TOKEN",
            "shopify_theme": "SHOPIFY_THEME_ID"}
# Prefijos esperados por proveedor: evita pegar el key equivocado en el campo equivocado
# (fue lo que pasó: un key de Anthropic terminó en GEMINI_API_KEY y rompió todo lo de Gemini).
_KEY_PREFIX = {"gemini": ("AIza", "AQ."), "eleven": ("sk_",), "anthropic": ("sk-ant-",),
               "shopify_token": ("shpat_", "shpca_")}
_KEY_LABEL = {"gemini": "Gemini (empieza con AIza o AQ.)",
              "eleven": "ElevenLabs (empieza con sk_)",
              "anthropic": "Claude/Anthropic (empieza con sk-ant-)",
              "shopify_token": "Shopify Admin API (empieza con shpat_)"}


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
    # 📡 El motor del Radar lee SU PROPIO radar/.env (radar.py load_api_key) — se escribe también ahí
    if provider == "scrapecreators":
        try:
            renv = os.path.join(BASE, "radar", ".env")
            rlines = []
            if os.path.exists(renv):
                rlines = [l for l in open(renv) if not l.startswith(env_name + "=")]
            rlines.append(f"{env_name}={key}\n")
            with open(renv, "w") as f:
                f.writelines(rlines)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}


def _safe_link_paths(link_paths: list[str]) -> list[str]:
    """Solo acepta rutas de videos ya BAJADOS que estén dentro de UPLOAD_DIR/WORK_DIR y existan (seguridad)."""
    out = []
    for p in link_paths or []:
        ap = os.path.abspath(p)
        if _within(ap, UPLOAD_DIR, WORK_DIR) and os.path.exists(ap):
            out.append(ap)
    return out


def _parse_broll(broll_paths: list[str]) -> tuple[list[str], dict]:
    """Decodifica los B-roll del front ("ruta" o "ruta::fase") → (rutas seguras, {ruta: fase}).
    La fase por defecto es "problema" (el B-roll clásico de Jack = la escena del DOLOR)."""
    rutas, fases = [], {}
    for item in broll_paths or []:
        p, _, f = item.partition("::")
        safe = _safe_link_paths([p])
        if safe:
            rutas.append(safe[0])
            fases[safe[0]] = (f.strip().lower() or "problema")
    return rutas, fases


@app.post("/api/process")
def process(
    files: list[UploadFile] = File(None),
    link_paths: list[str] = Form([]),
    broll_paths: list[str] = Form([]),
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
    banner_oferta: bool = Form(False),
    banner_start: float = Form(0.0),
    banner_dur: float = Form(0.0),
    oferta_texto: str = Form("OFERTA 2X1"),   # 2ª línea del banner (tu oferta; vacío = solo envío gratis)
    end_card: bool = Form(False),             # 🏁 cierre final 1.5s "PAGAS AL RECIBIR" al final
    hooks_por_version: bool = Form(False),    # 🎯 hook de texto (pastilla) por versión, 0-3s, editable
    hook_seconds: float = Form(0.0),
    destino: str = Form("tiktok"),
    n_versions: int = Form(8),          # "1 de prueba → N más": el front manda 1 en la prueba
    blur_strength: str = Form("medio"), # fuerza del desenfoque de textos (suave/medio/fuerte)
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
    broll_rutas, broll_fases = _parse_broll(broll_paths)   # B-roll marcados (entran al pool con fase)
    paths += broll_rutas
    if not paths:
        raise HTTPException(400, "Sube al menos un video o baja unos de TikTok")

    JOBS[job_id] = {
        "status": "running", "progress": 0,
        "message": "Iniciando...", "result": None,
        "created": time.time(), "tipo": "cortar_clips",
    }
    settings = {
        "target_seconds": float(target_seconds),
        "max_clip_seconds": min(5.0, max(1.0, float(max_clip))),
        "use_gemini": bool(use_gemini),
        "product_desc": product_desc.strip(),
        "aspect": aspect if aspect in ("1:1", "9:16", "4:5", "16:9") else "9:16",
        "hook_text": hook_text.strip(),
        "hook_pos": hook_pos if hook_pos in ("arriba", "centro", "abajo") else "arriba",
        "auto_hook": bool(auto_hook),
        "page_url": page_url.strip(),
        "enhance": bool(enhance),
        "effects": bool(effects),
        "blur_captions": bool(blur_captions),
        "banner_oferta": bool(banner_oferta),
        "banner_start": max(0.0, float(banner_start)),
        "banner_dur": max(0.0, float(banner_dur)),
        "banner_line2": oferta_texto.strip(),          # tu oferta (o '' = solo envío gratis)
        "end_card": bool(end_card),                    # 🏁 cierre final 1.5s al final de cada versión
        "hooks_por_version": bool(hooks_por_version),   # 🎯 hook por versión (pastilla 0-3s, editable)
        "hook_seconds": max(0.0, float(hook_seconds)),
        "text_mode": text_mode if text_mode in ("tapar", "traducir") else "tapar",
        "caption_pos": caption_pos if caption_pos in ("abajo", "arriba", "ambos") else "abajo",
        "broll_fases": broll_fases,
        "destino": destino if destino in ("tiktok", "meta") else "tiktok",
        "n_versions": max(1, min(8, int(n_versions))),
        "start_version": 0,
        "blur_strength": blur_strength if blur_strength in ("suave", "medio", "fuerte") else "medio",
    }
    if settings["hooks_por_version"]:      # el hook por versión reemplaza al global (no doble pastilla)
        settings["hook_text"] = ""
        settings["auto_hook"] = False
    threading.Thread(target=_run_job, args=(job_id, paths, settings), daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/reaplicar-hook")
def reaplicar_hook(job_id: str = Form(...), i: int = Form(...), texto: str = Form("")):
    """🎯 Re-aplica el HOOK de texto (pastilla arriba, 0-3s) de UNA versión con el texto que Jack
    escribió. Vuelve a quemar sobre la base SIN hook (v['_prehook']) → no se acumulan overlays.
    Texto vacío = quitar el hook (vuelve a la base). Devuelve la ruta nueva para refrescar el video."""
    job = JOBS.get(job_id)
    if not job or not isinstance(job.get("result"), dict):
        raise HTTPException(404, "Ese proyecto ya no está disponible (genera de nuevo).")
    versions = job["result"].get("versions") or []
    if i < 0 or i >= len(versions):
        raise HTTPException(400, "Versión inválida")
    v = versions[i]
    base = v.get("_prehook") or v.get("path")
    if not base or not os.path.exists(base):
        raise HTTPException(400, "No se puede re-aplicar el hook en esta versión.")

    def _norm14(p: str) -> str:
        # FIX: v['_prehook'] se guarda ANTES del último post-paso (-14 LUFS), así que todo lo
        # que salga de aquí (hook nuevo O quitar el hook) debe RE-normalizarse — si no, esta
        # versión vuelve con el volumen dispar que la normalización ya había corregido.
        from pipeline.ffmpeg_utils import normalize_loudness
        try:
            return normalize_loudness(p, p[:-4] + "_ln.mp4")   # si falla/sin audio devuelve p
        except Exception:  # noqa: BLE001
            return p

    txt = (texto or "").strip()
    if not txt:                       # quitar el hook: volver a la base sin pastilla (normalizada)
        v["path"] = _norm14(base)
        v["hook_text"] = ""
        return {"ok": True, "path": v["path"], "hook_text": ""}
    from pipeline.text_overlay import burn_hook_pill
    c = int(v.get("_hk_n", 0)) + 1    # contador → nombre único (el navegador no cachea el viejo)
    v["_hk_n"] = c
    out = base[:-4] + f"_hk{c}.mp4"
    new, ok = burn_hook_pill(base, out, os.path.dirname(base), txt, seconds=3.0, uid=f"re{i}_{c}")
    if not ok:
        raise HTTPException(500, "No se pudo aplicar el hook (revisa que el video exista).")
    new = _norm14(new)                # volumen parejo también en el hook re-aplicado
    v["path"] = new
    v["hook_text"] = txt.upper()[:50]
    return {"ok": True, "path": new, "hook_text": v["hook_text"]}


@app.post("/api/more-versions")
def more_versions(job_id: str = Form(...), n: int = Form(1)):
    """Genera N versiones MÁS del mismo origen (flujo '1 de prueba → N más'). Reusa los videos ya
    subidos + los mismos ajustes; arranca donde quedó la última tanda. Devuelve un job_id nuevo
    para polling con /api/status. Máx 8 versiones en total."""
    src = JOBS.get(job_id)
    if not src or not src.get("_src_paths"):
        raise HTTPException(404, "Ese proyecto no está disponible para generar más (genera de nuevo).")
    ya = int(src.get("_generated", 1))
    if ya >= 8:
        raise HTTPException(400, "Ya tienes las 8 versiones (es el máximo).")
    n = max(1, min(7, min(int(n), 8 - ya)))
    rid = uuid.uuid4().hex[:12]
    JOBS[rid] = {"tipo": "mas_versiones", "status": "running", "progress": 0, "message": "Iniciando…",
                 "result": None, "created": time.time()}
    threading.Thread(target=_run_more_versions_job, args=(rid, job_id, ya, n), daemon=True).start()
    return {"job_id": rid}


def _run_more_versions_job(rid: str, src_job: str, start_version: int, n: int):
    """Re-render de N versiones extra (start_version..+n) reusando los MISMOS videos y ajustes del
    proyecto origen. Mismo post-proceso (música + banner) que el lote normal."""
    job = JOBS[rid]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = int(pct)

    try:
        src = JOBS.get(src_job) or {}
        paths = src.get("_src_paths") or []
        s = dict(src.get("_src_settings") or {})
        if not paths:
            job["status"] = "error"; job["message"] = "El proyecto origen ya no está (genera de nuevo)."
            return
        wd = os.path.join(WORK_DIR, rid)
        result = process_job(
            paths, wd,
            target_seconds=s["target_seconds"], max_clip_seconds=s["max_clip_seconds"],
            use_gemini=s["use_gemini"], product_desc=s["product_desc"], aspect=s["aspect"],
            hook_text=s["hook_text"], hook_pos=s["hook_pos"], hook_seconds=s.get("hook_seconds", 0.0),
            auto_hook=s["auto_hook"], page_url=s["page_url"], enhance=s["enhance"],
            effects=s.get("effects", False), blur_captions=s.get("blur_captions", False),
            text_mode=s.get("text_mode", "tapar"), caption_pos=s.get("caption_pos", "abajo"),
            destino=s.get("destino", "tiktok"), gemini_key=_load_env_key(),
            broll_fases=s.get("broll_fases"),
            n_versions=n, start_version=start_version,
            blur_strength=s.get("blur_strength", "medio"), progress=progress)
        # foto de los paths ANTES de los post-pasos → para re-cortar el 4:5 si el master cambia
        _prev45 = {id(v): v.get("path") for v in ((result or {}).get("versions") or [])
                   if isinstance(v, dict)} if isinstance(result, dict) else {}
        if isinstance(result, dict) and result.get("ok") and result.get("versions") \
                and s.get("musica", True):
            _agregar_musica_sfx(result["versions"], wd, s.get("product_desc", ""), progress)
        if result.get("ok") and result.get("versions") and s.get("banner_oferta"):
            _agregar_banner_oferta(result["versions"], wd, progress,
                                   start=s.get("banner_start", 0.0), dur=s.get("banner_dur", 0.0),
                                   line2=s.get("banner_line2", "OFERTA 2X1"))
        if result.get("ok") and result.get("versions") and s.get("end_card"):
            _agregar_end_card(result["versions"], wd, progress)
        if result.get("ok") and result.get("versions") and s.get("hooks_por_version"):
            _agregar_hooks_por_version(result, wd, s.get("product_desc", ""), progress)
        # cut 4:5 (Meta): si los post-pasos cambiaron el master, re-cortarlo del path FINAL
        if isinstance(result, dict) and result.get("ok") and result.get("versions"):
            _sincronizar_path_45(result["versions"], _prev45, progress)
        # ÚLTIMO paso siempre: volumen parejo a -14 LUFS en el audio final de cada versión
        if isinstance(result, dict) and result.get("ok") and result.get("versions"):
            _normalizar_audio(result["versions"], wd, progress)
        # QA técnico final (aditivo, no bloquea): badge honesto si algo salió con defectos
        if isinstance(result, dict) and result.get("ok") and result.get("versions"):
            _qa_tecnico_versiones(result["versions"], progress)
        _stash_regen(job, result, rid)
        job["result"] = result
        job["status"] = "done" if result.get("ok") else "error"
        if not result.get("ok"):
            job["message"] = result.get("error", "No se pudieron generar más versiones")
        else:
            # avanzar el contador del ORIGEN para que un 2º "N más" siga donde quedó (sin duplicar)
            src["_generated"] = start_version + len(result.get("versions") or [])
            job["message"] = "Listo"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error generando más versiones: {e}"


@app.post("/api/feedback")
def feedback(job_id: str = Form(""), texto: str = Form(""), issues: str = Form(""),
             version_path: str = Form("")):
    """Canal a la TERMINAL (el Claude que CONSTRUYE la app): desde la prueba, Jack anota qué mejorar
    y se guarda en feedback-jack.md (raíz del repo) para mejorar el CÓDIGO. No corrige por sí mismo —
    es la bitácora de mejoras pedidas desde la app (la IA la lee al arrancar)."""
    texto = (texto or "").strip()
    issues = (issues or "").strip()
    if not texto and not issues:
        raise HTTPException(400, "Escribe qué mejorar antes de enviarlo.")
    from datetime import datetime
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (f"\n## {stamp}" + (f" · job {job_id}" if job_id else "") + "\n"
             + (f"- **Problemas marcados:** {issues}\n" if issues else "")
             + (f"- **Jack dice:** {texto}\n" if texto else "")
             + (f"- **Video:** {version_path}\n" if version_path else ""))
    fpath = os.path.join(BASE, "feedback-jack.md")
    try:
        nuevo = not os.path.exists(fpath)
        with open(fpath, "a", encoding="utf-8") as f:
            if nuevo:
                f.write("# 📮 Feedback de Jack desde la app (para que la terminal/Claude mejore el CÓDIGO)\n\n"
                        "Cada entrada = una prueba que no gustó + qué mejorar. La IA lo lee al arrancar "
                        "una sesión y ajusta el código (blur, sincronía, etc.). Al resolver, marca la "
                        "entrada como ✅ hecho.\n")
            f.write(entry)
        return {"ok": True, "message": "Anotado ✅ — Claude lo verá y lo mejora en el código."}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"No se pudo guardar el feedback: {e}")


# ---- Cortar clips DESDE LINKS de TikTok (pegar links -> bajar -> cortar) ----

@app.post("/api/fetch-links")
def fetch_links(links: str = Form("")):
    """Baja videos de TikTok al servidor y devuelve sus rutas (para cortarlos luego con /api/process,
    después de que el usuario configure los ajustes). NO corta nada aquí."""
    urls = [u for u in links.split() if u.startswith("http")]
    if not urls:
        raise HTTPException(400, "Pega al menos un link de TikTok")
    job_id = uuid.uuid4().hex[:12]
    out_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(out_dir, exist_ok=True)
    dl = download_urls(urls, out_dir)
    vids = [{"path": d["path"], "name": d.get("filename") or os.path.basename(d["path"]),
             "url": d.get("url", "")}
            for d in dl if d.get("ok") and d.get("path")]
    if not vids:
        return {"videos": [], "error": "No se pudo bajar ningún video (revisa los links)"}
    return {"videos": vids}


@app.post("/api/broll-dolor")
def broll_dolor(producto: str = Form(""), angulo: str = Form(""),
                landing_url: str = Form(""), n: int = Form(8)):
    """🎭 Busca B-ROLL amarrado al ÁNGULO/PUNTO DE DOLOR sacado de la LANDING (fuente de verdad):
    lee la página de venta → deriva el ángulo/dolor (y hasta el producto) → busca en TikTok (sin
    Colombia) → juzga la portada Y verifica el CONTENIDO de cada video (frames de adentro) para que
    de verdad ilustre la escena, PREFIERE b-roll SIN texto encima. Devuelve links por fase.

    Con la LANDING NO hace falta escribir el producto (pedido de Angelo): se puede pegar el link en
    el campo de ángulo también. Mínimo 5 escenas. Hace falta landing O un ángulo con sustancia."""
    producto, angulo, landing_url = producto.strip(), angulo.strip(), landing_url.strip()
    # Se puede pegar la landing en el campo de ÁNGULO: si el ángulo es un link, se usa como landing.
    if not landing_url and angulo.startswith(("http://", "https://")):
        landing_url, angulo = angulo, ""
    landing_text = ""
    if landing_url:
        if not landing_url.startswith(("http://", "https://")):
            raise HTTPException(400, "La landing debe ser un link http(s) válido")
        landing_text = fetch_page_text(landing_url)
        if not landing_text:
            raise HTTPException(400, "No pude leer esa landing (¿link correcto y público?). "
                                     "Pégala bien o escribe el ángulo a mano.")
    # Hace falta de dónde sacar el ángulo: landing, o un ángulo con sustancia, o el producto escrito.
    if not landing_text and len(angulo.split()) < 3 and not producto:
        raise HTTPException(400, "Pega la LANDING del producto (recomendado, aquí mismo en el campo) "
                                 "o escribe el ángulo / punto de dolor con detalle — de ahí saco los "
                                 "B-roll acordes.")
    # nombre para las búsquedas: el producto escrito, o algo derivable del ángulo/landing (buscar_broll
    # arma las queries desde el landing_text de todos modos, así que el nombre es secundario).
    nombre = producto or (angulo[:60] if angulo else "producto")
    from pipeline.tiktok_search import buscar_broll
    px, pb = _load_pexels_key(), _load_pixabay_key()
    res = buscar_broll(nombre, nombre, _load_env_key(),
                       n=max(5, min(16, n)), angulo=angulo,     # MÍNIMO 5 (pedido de Angelo)
                       anthropic_key=_load_anthropic_key(), landing_text=landing_text,
                       pexels_key=px, pixabay_key=pb)            # 🎬 STOCK = fuente principal de b-roll
    if not res:
        err = ("No encontré escenas que cuadren — afina la landing o el punto de dolor."
               if (px or pb) else
               "No encontré b-roll bueno. TikTok da mayormente memes para b-roll: conecta una "
               "API GRATIS de banco de video en 🔑 Claves (Pexels o Pixabay, 2 min) y te traigo "
               "clips limpios y reales del ángulo.")
        return {"links": [], "error": err}
    return {"links": res, "con_landing": bool(landing_text),
            "fuente": "stock" if (px or pb) else "tiktok"}


def _gc_jobs(keep: int = 80):
    """Evita que JOBS crezca sin límite (fuga de RAM en sesiones largas): si hay muchos, borra los MÁS
    VIEJOS que YA terminaron (nunca toca los que están 'running')."""
    if len(JOBS) <= keep:
        return
    terminados = sorted((kv for kv in list(JOBS.items()) if kv[1].get("status") != "running"),
                        key=lambda kv: kv[1].get("created", 0))
    for jid, _ in terminados[:len(JOBS) - keep]:
        JOBS.pop(jid, None)


@app.get("/api/busy")
def busy():
    """¿Hay algún trabajo (render/guiones/etc.) en curso ahora mismo? Lo usa el auto-actualizador
    (run.sh) para NO reiniciar la app a mitad de un render cuando baja cambios de Juan.
    FIX: también cuenta el escaneo del 📡 Radar — vive en radar_api._SCAN (no en JOBS) y corre
    subprocesos hijos: un reinicio a mitad de escaneo lo mataba y quemaba ~69 créditos."""
    activo = any(j.get("status") == "running" for j in JOBS.values())
    try:
        import radar_api as _ra
        radar_activo = _ra._SCAN.get("status") == "running"
    except Exception:  # noqa: BLE001
        radar_activo = False
    n = sum(1 for j in JOBS.values() if j.get("status") == "running") + (1 if radar_activo else 0)
    return {"busy": activo or radar_activo, "jobs": n}


@app.get("/api/status/{job_id}")
def status(job_id: str):
    _gc_jobs()   # limpieza oportunista de trabajos viejos ya terminados
    job = _get_job(job_id)   # memoria, o disco si el server se reinició
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    # 🤖 Bitácora para el asistente (punto ÚNICO: el front sondea este endpoint para TODO job).
    # Anota inicio y fin (con error o con qué produjo) UNA sola vez; best-effort, nunca rompe.
    try:
        st = job.get("status")
        if st == "running" and not job.get("_ev_ini"):
            job["_ev_ini"] = True
            asst.log_evento(WORK_DIR, "job_inicio", job=job_id, tipo=job.get("tipo", ""))
        if st in ("done", "error") and not job.get("_ev_fin"):
            job["_ev_fin"] = True
            detalle = (str(job.get("message", ""))[:200] if st == "error"
                       else asst._resumen_result(job.get("result")))
            asst.log_evento(WORK_DIR, "job_fin", job=job_id, tipo=job.get("tipo", ""),
                            status=st, detalle=detalle)
    except Exception:  # noqa: BLE001
        pass
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
                caption_size=settings.get("caption_size", "mediano"),
                oferta=settings.get("oferta", ""),
                banner_oferta=settings.get("banner_oferta", False),
                modo_ganador=settings.get("modo_ganador", False),
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
def auto(
    files: list[UploadFile] = File(...),
    product_desc: str = Form(""),
    voz: str = Form("juan_carlos"),
    oferta_2x1: bool = Form(False),
    verticalizar: bool = Form(True),
    caption_style: str = Form("bold_outline"),
    caption_size: str = Form("mediano"),
    oferta: str = Form(""),
    banner_oferta: bool = Form(False),
    modo_ganador: bool = Form(False),
):
    if not files:
        raise HTTPException(400, "Sube al menos un video ganador")
    job_id, paths = _save_uploads(files)
    JOBS[job_id] = {"tipo": "crear_creativo", "status": "running", "progress": 0,
                    "message": "Iniciando...", "result": None, "created": time.time()}
    settings = {
        "product_desc": product_desc.strip(),
        "voz": voz if voz in ("kate", "juan_carlos") else "juan_carlos",
        "oferta_2x1": bool(oferta_2x1),
        "verticalizar": bool(verticalizar),
        "caption_style": caption_style,
        "caption_size": caption_size,
        "oferta": oferta.strip(),
        "banner_oferta": bool(banner_oferta),
        "modo_ganador": bool(modo_ganador),
    }
    threading.Thread(target=_run_auto_job, args=(job_id, paths, settings), daemon=True).start()
    return {"job_id": job_id}


# ---- BUSCAR CREATIVOS EN TIKTOK (foto + nombre -> links reales) ----

_UA_FOTO = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
            "Accept": "image/avif,image/webp,image/*,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.8"}


def _tipo_imagen(b: bytes) -> str | None:
    """Detecta el formato real por bytes mágicos (no confía en la extensión del link)."""
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def _bajar_foto_url(url: str, destino_dir: str) -> str | None:
    """Baja la foto de un LINK. Si pegan el link de la PÁGINA del producto (no de la imagen),
    pesca la imagen principal (og:image/twitter:image). WEBP/GIF se convierten a JPG para que
    los jueces de visión no se atoren. Devuelve la ruta local o None."""
    try:
        url = url.strip()
        if not url.lower().startswith(("http://", "https://")):
            return None
        r = requests.get(url, timeout=20, headers=_UA_FOTO, allow_redirects=True)
        if r.status_code != 200:
            return None
        data = r.content
        if _tipo_imagen(data[:16]) is None:
            # no es una imagen: probablemente pegaron la PÁGINA → buscar og:image / twitter:image
            html = r.text[:400_000]
            m = (re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::src)?["\'][^>]*?content=["\']([^"\']+)["\']', html, re.I)
                 or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*?(?:property|name)=["\'](?:og:image|twitter:image)(?::src)?["\']', html, re.I))
            if not m:
                return None
            r = requests.get(m.group(1).replace("&amp;", "&"), timeout=20, headers=_UA_FOTO, allow_redirects=True)
            if r.status_code != 200:
                return None
            data = r.content
        if len(data) > 15 * 1024 * 1024 or len(data) < 2000:
            return None
        ext = _tipo_imagen(data[:16])
        if not ext:
            return None
        os.makedirs(destino_dir, exist_ok=True)
        p = os.path.join(destino_dir, f"url_{hashlib.md5(url.encode()).hexdigest()[:10]}.{ext}")
        with open(p, "wb") as o:
            o.write(data)
        if ext in ("webp", "gif"):
            try:
                from PIL import Image
                jpg = p.rsplit(".", 1)[0] + ".jpg"
                Image.open(p).convert("RGB").save(jpg, quality=92)
                os.remove(p)
                p = jpg
            except Exception:  # noqa: BLE001 — sin PIL se queda el original (mejor que nada)
                pass
        return p
    except Exception:  # noqa: BLE001
        return None


def _guardar_fotos_busqueda(foto, fotos, fotos_url: str = "") -> list[str]:
    """Guarda las fotos de búsqueda (campo viejo `foto` + campo nuevo `fotos` + links `fotos_url`,
    máx 3 en total) y devuelve rutas."""
    d = os.path.join(UPLOAD_DIR, "tksearch")
    paths: list[str] = []
    for up in ([foto] if foto is not None else []) + list(fotos or []):
        if up is None or not up.filename:
            continue
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, os.path.basename(up.filename))
        with open(p, "wb") as o:
            shutil.copyfileobj(up.file, o)
        if p not in paths:
            paths.append(p)
        if len(paths) >= 3:
            return paths
    for u in re.split(r"[\n,]+", fotos_url or ""):
        if len(paths) >= 3:
            break
        if u.strip():
            p = _bajar_foto_url(u, d)
            if p and p not in paths:
                paths.append(p)
    return paths


def _frames_de_videos(videos_ref, total: int = 5) -> list[str]:
    """Guarda los VIDEOS del producto (máx 2, tope 100MB c/u) y saca sus MEJORES frames como fotos de
    referencia MULTI-FRAME: los más NÍTIDOS, sin negros ni borrosos (mejores_frames = varianza del
    Laplaciano de cv2). Hasta ~`total` frames en total (repartidos si hay 2 videos). Más frames de
    referencia = MUCHO mejor match del MISMO producto. Cero llamadas de IA extra (los frames van
    dentro de la misma llamada de analizar_foto). Cualquier video que falle se ignora sin romper."""
    from pipeline.tiktok_search import mejores_frames
    vids = [up for up in list(videos_ref or []) if up is not None and up.filename][:2]
    if not vids:
        return []
    d = os.path.join(UPLOAD_DIR, "tksearch")
    os.makedirs(d, exist_ok=True)
    por_video = max(2, -(-total // len(vids)))            # ceil(total / n_videos), mínimo 2
    out: list[str] = []
    for up in vids:
        vp = os.path.join(d, os.path.basename(up.filename))
        try:
            with open(vp, "wb") as o:
                escrito = 0
                while True:
                    chunk = up.file.read(1 << 20)
                    if not chunk:
                        break
                    escrito += len(chunk)
                    if escrito > 100 * 1024 * 1024:      # tope 100MB por video
                        break
                    o.write(chunk)
        except Exception:  # noqa: BLE001
            continue
        try:
            out += mejores_frames(vp, n=por_video, out_dir=d)
        except Exception:  # noqa: BLE001
            continue
    return out[:total + 1]                                # tope 6 (5 + margen)


def _thumbs_b64(paths: list[str], w: int = 160) -> list[str]:
    """Miniaturas (data-URI base64) de los frames elegidos → el frontend las muestra para que el
    usuario VEA qué fotogramas se usaron. Solo previsualización (no viajan los archivos)."""
    out: list[str] = []
    try:
        import base64

        import cv2
    except ImportError:
        return out
    for p in paths:
        try:
            img = cv2.imread(p)
            if img is None:
                continue
            h, ww = img.shape[:2]
            if ww > w:
                img = cv2.resize(img, (w, int(h * w / ww)))
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                out.append("data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode())
        except Exception:  # noqa: BLE001
            continue
    return out


def _fotos_desde_urls(fotos_url: str) -> list[str]:
    """Descarga FOTOS pegadas como URL (una por línea, máx 3) al mismo dir de búsqueda → entran al
    MISMO flujo que las fotos subidas. Usa _bajar_foto_url: valida por bytes mágicos, convierte
    WEBP/GIF→JPG y si pegan el link de la PÁGINA del producto pesca la og:image sola. La URL que
    falle se ignora sin romper nada."""
    d = os.path.join(UPLOAD_DIR, "tksearch")
    out: list[str] = []
    for u in [x.strip() for x in (fotos_url or "").splitlines() if x.strip()][:3]:
        p = _bajar_foto_url(u, d)
        if p and p not in out:
            out.append(p)
    return out

def _texto_landing(landing: str) -> str:
    """Texto útil de la página de venta (o "" si falla — nunca rompe la búsqueda)."""
    landing = (landing or "").strip()
    if not landing:
        return ""
    try:
        return fetch_page_text(landing, max_chars=2500)
    except Exception:  # noqa: BLE001
        return ""


@app.post("/api/tiktok-search")
def tiktok_search(nombre: str = Form(""), count: int = Form(20),
                        foto: UploadFile = File(None),
                        fotos: list[UploadFile] = File([]),
                        videos_ref: list[UploadFile] = File([]),
                        fotos_url: str = Form(""),
                        landing: str = Form("")):
    """`foto` (una, campo viejo) sigue igual; `fotos` acepta hasta 3 del MISMO producto (multi-foto).
    `fotos_url`: LINKS de fotos pegados (una por línea; si pegan el link de la PÁGINA se pesca la
    og:image sola; máx 3 fotos combinadas con las subidas). `videos_ref` (máx 2): videos del producto
    → 2 frames c/u entran como fotos de referencia extra (tope total 4 imágenes, fotos primero).
    `landing`: link de la página de venta → contexto para la ficha y los términos. Todo opcional."""
    from pipeline.tiktok_search import buscar
    fotos_paths = (_guardar_fotos_busqueda(foto, fotos) + _fotos_desde_urls(fotos_url))[:3]
    frames_video = _frames_de_videos(videos_ref)         # 5 mejores frames del video del producto
    img_paths = (fotos_paths + frames_video)[:6]         # fotos primero, luego frames (tope 6)
    if not (nombre.strip() or img_paths):
        raise HTTPException(400, "Dame el nombre del producto, una foto o un video")
    _t0 = time.time()
    try:
        r = buscar(image_path=(img_paths[0] if img_paths else None), nombre=nombre.strip(),
                   api_key=_load_env_key(), count=int(count),
                   anthropic_key=_load_anthropic_key(),   # Claude = 2º juez de que sea el mismo producto
                   foreplay_key=_load_foreplay_key(),     # + ads ganadores de Foreplay al mismo pool
                   image_paths=img_paths or None,         # fotos + frames: ficha + jueces con más ángulos
                   landing_text=_texto_landing(landing),  # página de venta → mejores términos
                   rellenar_n=True)                       # devolver los N pedidos (por tiers, mismo producto)
    except Exception as e:  # noqa: BLE001
        # 🤖 bitácora: sin esto la búsqueda se esfumaba y NADIE podía confirmar después qué pasó
        asst.log_evento(WORK_DIR, "busqueda", fuente="tiktok-search", producto=nombre.strip(),
                        ok=False, error=str(e)[:200], seg=int(time.time() - _t0))
        raise
    asst.log_evento(WORK_DIR, "busqueda", fuente="tiktok-search", producto=nombre.strip(),
                    ok=bool(r.get("links")), tiktok=len(r.get("links") or []),
                    error=str(r.get("error") or "")[:200], seg=int(time.time() - _t0))
    r["frames_video"] = _thumbs_b64(frames_video)        # miniaturas de los frames usados (para la UI)
    return r


# ---- BUSCAR CREATIVOS (Foreplay RÁPIDO ya + TikTok en 2do plano: foto + nombre -> dos grupos) ----
# El dueño quería "resultados lo más rápido posible". TikTok es LENTO (tikwm serializa a 1 req/s →
# ~52s). Antes esta respuesta ESPERABA a TikTok. Ahora: se analiza la foto UNA vez, se responde YA
# con Foreplay (~10-15s) + un `tiktok_job`, y TikTok corre en un JOB en 2do plano que el front sondea
# con /api/status/{job_id} y lo inyecta en su sección al terminar. Aditivo: /api/creative-search-job
# (2 fases progresivas) y /api/tiktok-search siguen IGUAL.

def _run_tiktok_bg_job(job_id: str, img_path: str | None, img_paths: list[str],
                       nombre: str, count: int, analisis: dict):
    """FASE TIKTOK en 2do plano (el cuello de botella). Reusa el `analisis` ya calculado por la fase
    Foreplay → 0 llamadas extra a Gemini. Vuelca el resultado en JOBS para que el front lo inyecte."""
    from pipeline.creative_search import buscar_tiktok_solo
    job = JOBS[job_id]
    _t0 = time.time()
    try:
        # tk_deep_max=0: juez de PORTADA (estricto, marca verificado_producto) SIN bajar videos —
        # igual que hacía el /api/creative-search bloqueante viejo (~52s). El deep (bajar+juzgar
        # videos) multiplicaba el tiempo a varios minutos; en 2do plano no compensa la espera.
        r = buscar_tiktok_solo(image_path=img_path, nombre=nombre, gemini_key=_load_env_key(),
                               anthropic_key=_load_anthropic_key(), count=count,
                               image_paths=img_paths or None, analisis=analisis,
                               rellenar_n=True, tk_deep_max=0)
        job["result"] = r
        job["progress"] = 100
        job["message"] = "✅ TikTok listo"
        job["status"] = "done"
        _tk = r.get("tiktok") or {}
        asst.log_evento(WORK_DIR, "busqueda", fuente="creative-search-tiktok-bg", producto=nombre,
                        ok=bool(_tk.get("links")), tiktok=len(_tk.get("links") or []),
                        candidatos_tk=len(_tk.get("candidatos") or []),
                        error_tiktok=str(_tk.get("error") or "")[:150],
                        seg=int(time.time() - _t0))
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = "Error TikTok: " + str(e)[:200]
        asst.log_evento(WORK_DIR, "busqueda", fuente="creative-search-tiktok-bg", producto=nombre,
                        ok=False, error=str(e)[:200], seg=int(time.time() - _t0))


@app.post("/api/creative-search")
def creative_search(nombre: str = Form(""), count: int = Form(20),
                          fp_count: int = Form(20), foto: UploadFile = File(None),
                          fotos: list[UploadFile] = File([]),
                          videos_ref: list[UploadFile] = File([]),
                          fotos_url: str = Form(""),
                          landing: str = Form("")):
    """Foto + nombre del producto → Foreplay RÁPIDO ya + TikTok en 2do plano (job).
    /api/tiktok-search y /api/foreplay-search siguen funcionando IGUAL; esto es aditivo.
    `fotos` acepta hasta 3 del MISMO producto (frente/lado/empaque) → ficha y jueces más precisos.
    `fotos_url`: LINKS de fotos pegados (uno por línea; si pegan la PÁGINA se pesca la og:image sola).
    `videos_ref` (máx 2): videos del producto → 2 frames c/u como fotos de referencia extra (tope
    total 4, fotos primero). `landing`: link de la página de venta → contexto para la ficha.
    Respuesta: {ok, keywords, desc, variants, foreplay:{...}, tiktok:{pendiente:true}, tiktok_job}."""
    from pipeline.creative_search import buscar_foreplay_rapido, analizar_producto
    fotos_paths = (_guardar_fotos_busqueda(foto, fotos) + _fotos_desde_urls(fotos_url))[:3]
    frames_video = _frames_de_videos(videos_ref)         # 5 mejores frames del video del producto
    img_paths = (fotos_paths + frames_video)[:6]         # fotos primero, luego frames (tope 6)
    img_path = img_paths[0] if img_paths else None
    if not (nombre.strip() or img_path):
        raise HTTPException(400, "Dame el nombre del producto, una foto o un video")
    _t0 = time.time()
    landing_text = _texto_landing(landing)
    tk_job = ""
    try:
        # 1 sola llamada de análisis, compartida por Foreplay y TikTok (cero doble costo de Gemini)
        analisis = analizar_producto(image_path=img_path, nombre=nombre.strip(),
                                     gemini_key=_load_env_key(), image_paths=img_paths or None,
                                     landing_text=landing_text)
        # TikTok (lento por tikwm 1 req/s) arranca YA en 2do plano; el front lo inyecta al terminar
        tk_job = uuid.uuid4().hex[:12]
        JOBS[tk_job] = {"tipo": "tiktok_bg", "status": "running", "progress": 0,
                        "message": "⏳ Buscando en TikTok…", "result": None, "created": time.time()}
        threading.Thread(target=_run_tiktok_bg_job,
                         args=(tk_job, img_path, img_paths, nombre.strip(), int(count), analisis),
                         daemon=True).start()
        # Foreplay RÁPIDO (reusa el MISMO análisis) → responde en ~10-15s SIN esperar a TikTok
        fr = buscar_foreplay_rapido(image_path=img_path, nombre=nombre.strip(),
                                    gemini_key=_load_env_key(), foreplay_key=_load_foreplay_key(),
                                    anthropic_key=_load_anthropic_key(), fp_count=int(fp_count),
                                    image_paths=img_paths or None, landing_text=landing_text,
                                    rellenar_n=True, analisis=analisis)
    except Exception as e:  # noqa: BLE001
        # 🤖 bitácora del asistente: la búsqueda era 100% efímera (ni job ni archivo) → si fallaba,
        # después NADIE (ni la IA) podía decir qué pasó. Ahora queda anotado el error concreto.
        asst.log_evento(WORK_DIR, "busqueda", fuente="creative-search", producto=nombre.strip(),
                        ok=False, error=str(e)[:200], seg=int(time.time() - _t0))
        raise
    _fp = fr.get("foreplay") or {}
    asst.log_evento(WORK_DIR, "busqueda", fuente="creative-search", producto=nombre.strip(),
                    ok=bool(fr.get("ok")), foreplay=len(_fp.get("ads") or []),
                    # 🟡 candidatos sin confirmar (sección aparte): también quedan anotados
                    candidatos_fp=len(_fp.get("candidatos") or []),
                    error_foreplay=str(_fp.get("error") or "")[:150],
                    tiktok_job=tk_job, seg=int(time.time() - _t0))
    r = {"ok": bool(fr.get("ok")), "keywords": fr.get("keywords") or nombre.strip(),
         "desc": fr.get("desc", ""), "variants": fr.get("variants") or [],
         "foreplay": _fp,
         # TikTok llega por el job en 2do plano → placeholder para que el front pinte "⏳ Buscando…"
         "tiktok": {"pendiente": True, "links": [], "candidatos": [], "broll": []},
         "tiktok_job": tk_job,
         # la foto queda guardada para 🔄 cambiar / 🎯 más con este ángulo (solo el basename viaja)
         "foto": os.path.basename(img_path) if img_path else "",
         "frames_video": _thumbs_b64(frames_video)}       # miniaturas de los frames usados (UI)
    return r


# ---- BUSCAR CREATIVOS EN 2 FASES (JOB con resultados PROGRESIVOS: rápidos primero, exactos después) ----
# Pedido de Jack: "Buscar creativos" se demoraba MUCHO porque TODO se verificaba a fondo antes de
# mostrar nada. Ahora es un JOB: FASE 1 (segundos) muestra candidatos por PORTADA marcados
# "⏳ verificando"; FASE 2 sube los CONFIRMADOS (verificación profunda por contenido, cero relleno) a
# "✅ exactos" y descarta los que no son el mismo producto. El front hace poll() a /api/status/{id}.
# ADITIVO: /api/creative-search (bloqueante) y /api/tiktok-search siguen IGUAL.

def _run_creative_search_job(job_id: str, img_paths: list[str], frames_video: list[str],
                             nombre: str, count: int, fp_count: int, landing_text: str):
    from pipeline.creative_search import buscar_creativos_progresivo
    job = JOBS[job_id]
    img_path = img_paths[0] if img_paths else None
    foto_base = os.path.basename(img_path) if img_path else ""
    thumbs = _thumbs_b64(frames_video)                   # miniaturas de los frames del video (para la UI)
    _t0 = time.time()

    def progress(res, msg, pct):
        job["message"] = msg
        job["progress"] = pct
        if res is not None:                              # resultado PARCIAL → el front lo pinta ya
            res = dict(res)
            res["foto"] = foto_base
            res["frames_video"] = thumbs
            job["result"] = res

    try:
        r = buscar_creativos_progresivo(
            image_path=img_path, nombre=nombre, gemini_key=_load_env_key(),
            foreplay_key=_load_foreplay_key(), anthropic_key=_load_anthropic_key(),
            count=count, fp_count=fp_count, image_paths=img_paths or None,
            landing_text=landing_text, progress=progress)
        r = dict(r)
        r["foto"] = foto_base
        r["frames_video"] = thumbs
        job["result"] = r
        job["progress"] = 100
        job["message"] = "✅ Listo"
        job["status"] = "done"
        _tk, _fp = r.get("tiktok") or {}, r.get("foreplay") or {}
        asst.log_evento(WORK_DIR, "busqueda", fuente="creative-search-job", producto=nombre,
                        ok=bool(r.get("ok")), tiktok=len(_tk.get("links") or []),
                        foreplay=len(_fp.get("ads") or []),
                        candidatos_tk=len(_tk.get("candidatos") or []),
                        candidatos_fp=len(_fp.get("candidatos") or []),
                        seg=int(time.time() - _t0))
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = "Error: " + str(e)[:200]
        asst.log_evento(WORK_DIR, "busqueda", fuente="creative-search-job", producto=nombre,
                        ok=False, error=str(e)[:200], seg=int(time.time() - _t0))


@app.post("/api/creative-search-job")
def creative_search_job(nombre: str = Form(""), count: int = Form(20),
                        fp_count: int = Form(20), foto: UploadFile = File(None),
                        fotos: list[UploadFile] = File([]),
                        videos_ref: list[UploadFile] = File([]),
                        fotos_url: str = Form(""), landing: str = Form("")):
    """Arranca la búsqueda en 2 FASES como JOB en segundo plano y devuelve {job_id}. El frontend
    sondea /api/status/{job_id}: primero llegan los PRELIMINARES (fase='preliminar'), luego los
    EXACTOS confirmados (fase='final'). Mismos params que /api/creative-search."""
    fotos_paths = (_guardar_fotos_busqueda(foto, fotos) + _fotos_desde_urls(fotos_url))[:3]
    frames_video = _frames_de_videos(videos_ref)         # 5 mejores frames del video del producto
    img_paths = (fotos_paths + frames_video)[:6]         # fotos primero, luego frames (tope 6)
    if not (nombre.strip() or img_paths):
        raise HTTPException(400, "Dame el nombre del producto, una foto o un video")
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"tipo": "buscar_creativos", "status": "running", "progress": 0,
                    "message": "Iniciando…", "result": None, "created": time.time()}
    threading.Thread(target=_run_creative_search_job,
                     args=(job_id, img_paths, frames_video, nombre.strip(), int(count),
                           int(fp_count), _texto_landing(landing)), daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/creative-more")
def creative_more(fuente: str = Form("tiktok"), nombre: str = Form(""),
                        desc: str = Form(""), terminos: str = Form(""), angulo: str = Form(""),
                        excluir: str = Form(""), n: int = Form(1), foto: str = Form("")):
    """n creativos NUEVOS para una fuente: 🔄 cambiar (n=1, sin angulo) o 🎯 más con ese ángulo
    (angulo = título del creativo que gustó). `excluir` = urls/ids ya mostrados (uno por línea)."""
    from pipeline.creative_search import buscar_mas
    if fuente not in ("tiktok", "foreplay"):
        raise HTTPException(400, "fuente debe ser tiktok o foreplay")
    img_path = None
    if foto.strip():
        p = os.path.join(UPLOAD_DIR, "tksearch", os.path.basename(foto.strip()))
        if os.path.exists(p):
            img_path = p
    r = buscar_mas(fuente=fuente, nombre=nombre.strip(), desc=desc.strip(),
                   terminos=[t.strip() for t in terminos.splitlines() if t.strip()],
                   angulo=angulo.strip(),
                   excluir=[e.strip() for e in excluir.splitlines() if e.strip()],
                   n=int(n), image_path=img_path,
                   gemini_key=_load_env_key(), foreplay_key=_load_foreplay_key())
    asst.log_evento(WORK_DIR, "busqueda", fuente=f"creative-more:{fuente}",
                    producto=nombre.strip(), ok=bool(r.get("ok")),
                    items=len(r.get("items") or []), error=str(r.get("error") or "")[:150])
    return r


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
            caption_style=settings.get("caption_style", "karaoke"),
            caption_size=settings.get("caption_size", "mediano"),
            gemini_key=_load_env_key(), eleven_key=_load_eleven_key(),
            work_dir=os.path.join(WORK_DIR, job_id), progress=progress,
        )
        _stash_regen(job, result, job_id, {"voz": settings.get("voz")})   # era s.get → NameError (crash 100%)
        # honestidad: si el mp4 final salió truncado/corrupto NO se entrega como "listo"
        if result.get("ok") and not _video_ok(result.get("video") or ""):
            result = dict(result, ok=False,
                          error="El video clonado salió corrupto/truncado — vuelve a intentar.")
        job["result"] = result
        job["status"] = "done" if result.get("ok") else "error"
        if not result.get("ok"):
            job["message"] = result.get("error", "Error")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"; job["message"] = f"Error: {e}"


@app.post("/api/clone")
def clone(
    winner: UploadFile = File(...),
    photos: list[UploadFile] = File([]),
    videos: list[UploadFile] = File([]),
    product_desc: str = Form(""),
    old_desc: str = Form(""),
    doblar: bool = Form(False),
    voz: str = Form("juan_carlos"),
    verticalizar: bool = Form(True),
    caption_style: str = Form("karaoke"),
    caption_size: str = Form("mediano"),
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

    JOBS[job_id] = {"tipo": "clonar_ganador", "status": "running", "progress": 0,
                    "message": "Iniciando...", "result": None, "created": time.time()}
    settings = {
        "product_desc": product_desc.strip(), "old_desc": old_desc.strip(),
        "doblar": bool(doblar), "voz": voz if voz in ("kate", "juan_carlos") else "juan_carlos",
        "verticalizar": bool(verticalizar),
        "caption_style": caption_style, "caption_size": caption_size,
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

        mix = settings.get("mix")
        n_guiones = sum(mix.values()) if mix else 10
        # 🎯 AVATARES + ESTRUCTURAS VALIDADAS (fix "8 sabores del mismo helado", 2026-07-11):
        # cada guion del lote ataca un COMPRADOR distinto con una estructura ganadora distinta
        # (biblioteca destilada del research en assets/estructuras-validadas.json) y su PROPIA
        # duración de voz. Best-effort: sin Gemini rota la biblioteca; si falla del todo → None
        # y el flujo queda EXACTO como antes.
        asignaciones = None
        try:
            from pipeline.estructuras_validadas import asignar_estructuras
            funnel_seq = ((["TOFU"] * mix.get("TOFU", 0) + ["MOFU"] * mix.get("MOFU", 0)
                           + ["BOFU"] * mix.get("BOFU", 0)) if mix else None)
            progress("Asignando avatares y estructuras validadas (IA)...", 66)
            asignaciones = asignar_estructuras(settings["product_desc"], n_guiones,
                                               _load_env_key(), funnel_seq=funnel_seq) or None
        except Exception:  # noqa: BLE001
            asignaciones = None
        progress(f"Generando {n_guiones} guiones de voz en off"
                 + (" (embudo TOFU/MOFU/BOFU)..." if mix else
                    (" (un avatar y una estructura por guion)..." if asignaciones else "...")), 70)
        scripts = generate_scripts(_load_env_key(), settings["product_desc"], page_text,
                                   settings["target_seconds"], sample, blueprint=blueprint,
                                   oferta_2x1=settings.get("oferta_2x1", False), mix=mix,
                                   asignaciones=asignaciones)
        if not scripts:
            # Nunca terminar "Guiones listos" con 0 guiones (auditoría 2026-07-06)
            raise RuntimeError("La IA corrió pero no entregó ningún guion — reintenta.")
        # Guardar estado para la fase 2 (renderizado con voz)
        job.update({
            "selected": selected, "has_audio_by_src": a["has_audio_by_src"],
            "used_gemini": a["used_gemini"], "n_sources": a["n_sources"],
            "settings": settings, "work_dir": wd,
        })
        result = {"ok": True, "scripts": scripts, "blueprint": blueprint}
        # 🧬 Honestidad con la referencia (campos ADITIVOS, no cambian el shape existente):
        #  - reference_name → hubo referencia y SÍ se clonó su estructura (para que Jack sepa qué testea)
        #  - reference_warning → la referencia no se pudo bajar (Foreplay) o la IA no pudo analizarla
        ref_warn = settings.get("reference_warning")
        if ref and os.path.exists(ref) and blueprint is None and not ref_warn:
            ref_warn = ("No se pudo analizar la estructura del anuncio de referencia (IA) — "
                        "los guiones se generaron SIN clonarla.")
        if blueprint is not None:
            result["reference_name"] = settings.get("reference_name") or "anuncio de referencia"
        if ref_warn:
            result["reference_warning"] = ref_warn
        job["result"] = result
        job["status"] = "done"; job["message"] = "Guiones listos"; job["progress"] = 100
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"; job["message"] = f"Error: {e}"


@app.post("/api/scripts")
def scripts(
    files: list[UploadFile] = File(None),
    link_paths: list[str] = Form([]),
    broll_paths: list[str] = Form([]),
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
    banner_oferta: bool = Form(False),
    banner_start: float = Form(0.0),
    banner_dur: float = Form(0.0),
    oferta_texto: str = Form("OFERTA 2X1"),   # 2ª línea del banner (tu oferta; vacío = solo envío gratis)
    end_card: bool = Form(False),             # 🏁 cierre final 1.5s "PAGAS AL RECIBIR" al final
    hooks_por_version: bool = Form(False),    # 🎯 hook de texto (pastilla) por versión, 0-3s, editable
    hook_seconds: float = Form(0.0),
    blur_strength: str = Form("medio"),
    caption_style: str = Form("hormozi"),
    caption_size: str = Form("mediano"),
    destino: str = Form("tiktok"),
    tofu: int = Form(0),   # embudo TOFU/MOFU/BOFU: nº de guiones de cada etapa (0/0/0 = clásico)
    mofu: int = Form(0),
    bofu: int = Form(0),
    reference_ad: UploadFile | None = File(None),
    reference_url: str = Form(""),    # 🧬 URL de un GANADOR de Foreplay para clonar su estructura
    reference_name: str = Form(""),   # nombre del ad de referencia (informativo, sale en el resultado)
):
    job_id, paths = _save_uploads(files or [])
    paths += _safe_link_paths(link_paths)      # videos bajados de TikTok
    broll_rutas, broll_fases = _parse_broll(broll_paths)
    paths += broll_rutas
    if not paths:
        raise HTTPException(400, "Sube al menos un video o baja unos de TikTok")
    # Anuncio de referencia (opcional) para clonar su estructura narrativa
    ref_path = None
    ref_warning = None
    if reference_ad is not None and reference_ad.filename:
        ref_path = os.path.join(UPLOAD_DIR, job_id,
                                "reference_" + os.path.basename(reference_ad.filename))
        with open(ref_path, "wb") as rf:
            shutil.copyfileobj(reference_ad.file, rf)
        if not reference_name.strip():
            reference_name = os.path.basename(reference_ad.filename)
    elif reference_url.strip():
        # 🧬 "Usar estructura de este ganador" (pestaña Foreplay): se baja el video del CDN de
        # Foreplay y se usa EXACTAMENTE igual que un reference_ad subido a mano (mismo ref_path).
        # Solo su CDN por seguridad — misma validación que /api/dub.
        from urllib.parse import urlparse
        host = (urlparse(reference_url).hostname or "").lower()
        if not (host == "foreplay.co" or host.endswith(".foreplay.co")):
            raise HTTPException(400, "URL de referencia no permitida")
        rp = os.path.join(UPLOAD_DIR, job_id, "reference_foreplay.mp4")
        if fp.descargar_video(reference_url.strip(), rp):
            ref_path = rp
        else:
            # honesto: los guiones siguen, pero el resultado AVISA que no se clonó nada
            ref_warning = ("No se pudo bajar el anuncio de referencia de Foreplay — "
                           "los guiones se generaron SIN clonar su estructura.")
    JOBS[job_id] = {"tipo": "guiones", "status": "running", "progress": 0, "message": "Iniciando...",
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
        "destino": destino if destino in ("tiktok", "meta") else "tiktok",
        "use_music": bool(use_music), "captions": bool(use_captions),
        "oferta_2x1": bool(oferta_2x1),
        "banner_oferta": bool(banner_oferta),   # banner 2x1 arriba — antes SOLO existía sin voz
        "banner_start": max(0.0, float(banner_start)),   # "aparece al seg N" (fix: antes se ignoraba)
        "banner_dur": max(0.0, float(banner_dur)),       # "dura M s" (0 = hasta el final)
        "banner_line2": oferta_texto.strip(),            # tu oferta (o '' = solo envío gratis)
        "end_card": bool(end_card),                      # 🏁 cierre final 1.5s al final de cada versión
        "hooks_por_version": bool(hooks_por_version),    # 🎯 hook por versión (pastilla 0-3s, editable)
        "hook_seconds": max(0.0, float(hook_seconds)),
        "blur_strength": blur_strength if blur_strength in ("suave", "medio", "fuerte") else "medio",
        "caption_style": caption_style, "caption_size": caption_size,
        "reference_ad": ref_path,
        "reference_name": reference_name.strip(),   # 🧬 nombre del ganador (sale en el resultado)
        "reference_warning": ref_warning,           # aviso honesto si la referencia no se pudo bajar
        "broll_fases": broll_fases,
    }
    # Embudo TOFU/MOFU/BOFU (seleccionable): si el usuario pidió alguna etapa, se generan guiones
    # etiquetados por etapa (arco + hook + CTA por temperatura). Si 0/0/0 → guiones clásicos.
    _mix = {"TOFU": max(0, int(tofu)), "MOFU": max(0, int(mofu)), "BOFU": max(0, int(bofu))}
    if sum(_mix.values()) > 0:
        settings["mix"] = _mix
    if settings["hooks_por_version"]:      # el hook por versión reemplaza al global (no doble pastilla)
        settings["hook_text"] = ""
        settings["auto_hook"] = False
    threading.Thread(target=_run_scripts_job, args=(job_id, paths, settings), daemon=True).start()
    return {"job_id": job_id}


N_VERSIONS = 8   # DEBE ir igual a orchestrator._N_VERSIONS: con 6, las versiones G/H salían
                 # sin voz/guion/subtítulos (el plan por guion solo cubre versiones CON voz)


def _run_render_job(job_id: str, scripts: list[str], voice_key: str,
                    voces: list[str] | None = None, stages: list[str] | None = None,
                    n_versions: int = N_VERSIONS, start_version: int = 0,
                    metas: list[dict] | None = None):
    job = JOBS[job_id]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = pct

    try:
        s = job["settings"]
        wd = job["work_dir"]
        os.makedirs(wd, exist_ok=True)
        key = _load_eleven_key()
        # Dos modos (fusión):
        #  • EMBUDO (hay etapas, una por guion) → UNA versión por guion (1:1), cada una etiquetada
        #    con su etapa TOFU/MOFU/BOFU. nv = nº de guiones, desde 0.
        #  • "1 de prueba → N más" (sin etapas) → tajada [sv : sv+nv] de las 8 (defaults = las 8).
        #    Índice ABSOLUTO (sv+i) para que 'B' reciba SIEMPRE el mismo guion/voz salga en la
        #    prueba o en "N más". El pool YA enmascarado (job["selected"]) se reusa (barato).
        stage_mode = bool(stages) and len(stages) == len(scripts)
        if stage_mode:
            nv, sv = len(scripts), 0
            chosen = [scripts[i] for i in range(nv)]
            _voz = lambda i: voces[i % len(voces)] if voces else voice_key   # noqa: E731
        else:
            nv = max(1, min(N_VERSIONS - int(start_version), int(n_versions)))
            sv = max(0, min(N_VERSIONS - 1, int(start_version)))
            _cyc = scripts * (N_VERSIONS // max(1, len(scripts)) + 1)
            chosen = [_cyc[sv + i] for i in range(nv)]
            _voz = lambda i: voces[(sv + i) % len(voces)] if voces else voice_key   # noqa: E731
        from pipeline.voiceover import acelerar as _acelerar_vo
        from concurrent.futures import ThreadPoolExecutor
        pares = [(chosen[i], _voz(i)) for i in range(nv)]
        unicos = sorted(set(pares))
        progress(f"Generando {len(unicos)} voces con ElevenLabs (en paralelo)...", 14)
        hechas_ct = [0]

        def _tts_par(par):
            txt, v_i = par
            vp = os.path.join(wd, f"vo_{unicos.index(par)}.mp3")
            try:
                if s.get("captions"):
                    wt = synthesize_with_timestamps(key, txt, v_i, vp)
                else:
                    synthesize(key, txt, v_i, vp); wt = None
                # Manual Maestro §6: locución 1.1-1.2× = más enérgica y retiene mejor
                wt = _acelerar_vo(vp, wt, factor=1.12) or wt
                hechas_ct[0] += 1
                progress(f"Voces listas: {hechas_ct[0]}/{len(unicos)} (ElevenLabs)...",
                         14 + int(24 * hechas_ct[0] / max(1, len(unicos))))
                return par, (vp, wt)
            except Exception:  # noqa: BLE001
                return par, None

        hechas: dict = {}
        with ThreadPoolExecutor(max_workers=min(4, len(unicos))) as ex:
            for par, r in ex.map(_tts_par, unicos):
                if r:
                    hechas[par] = r
        if not hechas:
            raise RuntimeError("ElevenLabs no devolvió ninguna voz (revisa la API key/créditos)")
        respaldo = list(hechas.values())    # si un par falló, esa versión usa otra narración hecha
        version_vos = [hechas.get(p) or respaldo[i % len(respaldo)] for i, p in enumerate(pares)]
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
            destino=s.get("destino", "tiktok"),
            music_path=music_path,
            blur_captions=s.get("blur_captions", False), text_mode=s.get("text_mode", "tapar"),
            caption_pos=s.get("caption_pos", "abajo"),
            captions=s.get("captions", False), caption_style=s.get("caption_style", "hormozi"),
            caption_size=s.get("caption_size", "mediano"),
            used_gemini=job["used_gemini"], n_sources=job["n_sources"],
            target_seconds=s["target_seconds"], max_clip_seconds=s["max_clip_seconds"],
            broll_fases=s.get("broll_fases"), n_versions=nv, start_version=sv,
            stages=(stages if stage_mode else None),
            blur_strength=s.get("blur_strength", "medio"), progress=progress)
        # foto de los paths ANTES de los post-pasos → para re-cortar el 4:5 si el master cambia
        _prev45 = {id(v): v.get("path") for v in ((manifest or {}).get("versions") or [])
                   if isinstance(v, dict)} if isinstance(manifest, dict) else {}
        # Banner "Oferta 2x1 · envío gratis" arriba — mismo paso que en _run_job (sin voz);
        # antes el toggle se IGNORABA en esta ruta (queja de Jack: "no está haciendo lo del 2x1").
        # FIX 2026-07-08: ahora respeta el "aparece al seg N · dura M" (antes iba full-video desde
        # el seg 0 aunque Jack pusiera 5 — su queja "le puse esto y no hizo caso").
        if manifest.get("ok") and manifest.get("versions") and s.get("banner_oferta"):
            _agregar_banner_oferta(manifest["versions"], wd, progress,
                                   start=s.get("banner_start", 0.0), dur=s.get("banner_dur", 0.0),
                                   line2=s.get("banner_line2", "OFERTA 2X1"))
        if manifest.get("ok") and manifest.get("versions") and s.get("end_card"):
            _agregar_end_card(manifest["versions"], wd, progress)
        if manifest.get("ok") and manifest.get("versions") and s.get("hooks_por_version"):
            _agregar_hooks_por_version(manifest, wd, s.get("product_desc", ""), progress)
        # cut 4:5 (Meta): si los post-pasos cambiaron el master, re-cortarlo del path FINAL
        if isinstance(manifest, dict) and manifest.get("ok") and manifest.get("versions"):
            _sincronizar_path_45(manifest["versions"], _prev45, progress)
        # ÚLTIMO paso siempre: volumen parejo a -14 LUFS en el audio final de cada versión
        if isinstance(manifest, dict) and manifest.get("ok") and manifest.get("versions"):
            _normalizar_audio(manifest["versions"], wd, progress)
        # QA técnico final (aditivo, no bloquea): badge honesto si algo salió con defectos
        if isinstance(manifest, dict) and manifest.get("ok") and manifest.get("versions"):
            _qa_tecnico_versiones(manifest["versions"], progress)
        # 🎯 avatar/estructura de cada versión (aditivo, 2026-07-11): viaja al manifest para que
        # Jack SEPA qué avatar testea con cada video. `metas` va paralelo a `scripts`, así que el
        # mapeo guion→versión es el MISMO que el de `chosen` (1:1 en embudo; cíclico desde sv si no).
        if metas and isinstance(manifest, dict) and manifest.get("ok"):
            for _i, _v in enumerate(manifest.get("versions") or []):
                _m = metas[_i % len(metas)] if stage_mode else metas[(sv + _i) % len(metas)]
                if isinstance(_m, dict) and isinstance(_v, dict):
                    if _m.get("avatar"):
                        _v["avatar"] = str(_m["avatar"])[:80]
                    if _m.get("estructura"):
                        _v["estructura"] = str(_m["estructura"])[:80]
        if music_warning and isinstance(manifest, dict):
            manifest["music_warning"] = music_warning
        # FIX: `s` son los settings de /api/scripts y NUNCA traen "voz" (siempre daba None →
        # regenerar "otro guion" narraba con juan_carlos aunque Jack eligiera kate). La voz
        # elegida llega en `voice_key` (el parámetro `voice` de /api/render).
        _stash_regen(job, manifest, job_id, {"voz": voice_key})
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
           voz_jc: int = Form(0), voz_kate: int = Form(0),
           scripts_json: str = Form(""), script_text: str = Form(""),
           stages_json: str = Form(""),
           metas_json: str = Form(""),   # 🎯 avatar/estructura por guion (paralelo a scripts_json)
           n_versions: int = Form(8), start_version: int = Form(0)):
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
    # Embudo: etapa por guion seleccionado (paralelo a scripts_json). Si viene y calza, cada
    # versión = un guion etiquetado con su etapa; si no, comportamiento clásico (8 versiones).
    stages: list[str] | None = None
    if stages_json.strip():
        try:
            _s = [str(x).strip().upper() for x in _json.loads(stages_json)]
            _s = [x if x in ("TOFU", "MOFU", "BOFU") else "" for x in _s]
            if len(_s) == len(scripts) and any(_s):
                stages = _s
        except Exception:
            stages = None
    # 🎯 Avatar/estructura por guion (aditivo): solo si calza 1:1 con los guiones elegidos.
    metas: list[dict] | None = None
    if metas_json.strip():
        try:
            _m = [x if isinstance(x, dict) else {} for x in _json.loads(metas_json)]
            if len(_m) == len(scripts) and any(x.get("avatar") or x.get("estructura") for x in _m):
                metas = _m
        except Exception:
            metas = None
    job["tipo"] = "render_versiones"; job["created"] = time.time()
    job["status"] = "running"; job["progress"] = 0; job["message"] = "Iniciando..."; job["result"] = None
    # Mezcla personalizada de voces: N versiones con juan_carlos + M con kate (0/0 = todas con `voice`)
    voces = (["juan_carlos"] * max(0, min(8, int(voz_jc)))
             + ["kate"] * max(0, min(8, int(voz_kate)))) or None
    nv = max(1, min(8, int(n_versions)))
    sv = max(0, min(7, int(start_version)))
    threading.Thread(target=_run_render_job,
                     args=(job_id, scripts, voice, voces, stages, nv, sv),
                     kwargs={"metas": metas},
                     daemon=True).start()
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
        # Distinguir CUOTA/KEY caída vs producto no encontrado (auditoría 2026-07-06): antes un 429
        # terminaba en "describe mejor tu producto", culpando al usuario por un fallo de la IA.
        try:
            ranges = detect_product_ranges(_load_env_key(), old_path, old_desc)
        except RuntimeError as e:
            job["status"] = "error"
            job["message"] = f"No pude buscar el producto (la IA no corrió): {e}"
            return
        if not ranges:
            job["status"] = "error"
            job["message"] = ("La IA revisó el video y NO encontró el producto viejo. "
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
def swap(old: UploadFile = File(...), new_files: list[UploadFile] = File(...),
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
    JOBS[job_id] = {"tipo": "reemplazar_producto", "status": "running", "progress": 0, "message": "Iniciando...",
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
                if not _video_ok(d["video"]):   # mp4 truncado/corrupto → error honesto, no "Listo"
                    job["status"] = "error"
                    job["message"] = "El video doblado salió corrupto/truncado — vuelve a intentar."
                    return
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
        if not _video_ok(out):   # mp4 truncado/corrupto → error honesto, no "Listo"
            job["status"] = "error"
            job["message"] = "El video doblado salió corrupto/truncado — vuelve a intentar."
            return
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
def dub(video: UploadFile = File(None), target_lang: str = Form("en"),
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
    JOBS[job_id] = {"tipo": "doblaje", "status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_dub_job,
                     args=(job_id, vpath, target_lang, source_lang, bool(oferta_2x1),
                           product_desc.strip()),
                     daemon=True).start()
    return {"job_id": job_id}


# ══════════════ DOBLAR EN 2 PASOS: ① traducir (revisar/editar) → ② voz + oferta ══════════════
def _save_dub_upload(video, video_url: str) -> tuple[str, str]:
    """Guarda el video subido (o baja el de Foreplay) y devuelve (job_id, ruta). Reusa la misma
    validación que /api/dub."""
    job_id = uuid.uuid4().hex[:12]
    up = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(up, exist_ok=True)
    vpath = os.path.join(up, "dub_video.mp4")
    if (video_url or "").strip():
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
    return job_id, vpath


def _run_dub_preview_job(job_id: str, video_path: str, product_desc: str):
    """Paso ①: transcribe + traduce a español colombiano por fase (SIN gastar voz de ElevenLabs).
    Deja el original y la traducción de cada frase para que Jack la revise/edite antes del paso ②."""
    job = JOBS[job_id]

    def progress(msg, pct=None):
        job["message"] = msg
        if pct is not None:
            job["progress"] = pct

    try:
        from pipeline.dub_colombia import adaptar_guion
        g = adaptar_guion(video_path, api_key=_load_env_key(), product_desc=product_desc,
                          oferta_2x1=False, progress=progress)   # 2x1 se decide en el paso ②
        if not g.get("ok"):
            job["status"] = "error"; job["message"] = g.get("error", "No se pudo traducir")
            return
        segs = g["segments"]
        job["_dub_video"] = video_path            # se reusa en el paso ②
        job["_dub_segments"] = segs
        job["_dub_product"] = product_desc
        job["result"] = {"ok": True, "duration": g.get("duration", 0),
                         "segments": [{"i": i, "etiqueta": s.get("etiqueta", ""),
                                       "inicio": s.get("inicio", ""), "fin": s.get("fin", ""),
                                       "original": s.get("original", ""),
                                       "es_colombia": s.get("es_colombia", "")}
                                      for i, s in enumerate(segs)]}
        job["status"] = "done"; job["progress"] = 100; job["message"] = "Traducción lista"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"; job["message"] = f"Error traduciendo: {e}"


@app.post("/api/dub-preview")
def dub_preview(video: UploadFile = File(None), video_url: str = Form(""),
                product_desc: str = Form("")):
    """Paso ①: sube el video → devuelve la traducción por frase (original + español) para revisar."""
    job_id, vpath = _save_dub_upload(video, video_url)
    JOBS[job_id] = {"tipo": "doblaje_traduccion", "status": "running", "progress": 0, "message": "Analizando el video...",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_dub_preview_job, args=(job_id, vpath, product_desc.strip()),
                     daemon=True).start()
    return {"job_id": job_id}


def _dub_2x1_line(oferta_texto: str) -> str:
    """Frase de oferta que la VOZ dirá (2x1 por defecto, o la que Jack escriba). Sin precios."""
    t = (oferta_texto or "").strip()
    if t:
        return t if t.endswith((".", "!", "?", "…")) else t + "."
    return "Y hoy están de dos por uno: pides uno y te llega otro completamente gratis."


def _run_dub_generar_job(job_id: str, prev_job_id: str, voz: str, textos: list[str],
                         oferta_2x1: bool, oferta_texto: str, target_lang: str):
    """Paso ②: genera el video doblado con la voz elegida (o doblaje exacto), usando el guion que
    Jack revisó/editó en el paso ①, y menciona el 2x1 en la voz si lo pidió."""
    job = JOBS[job_id]

    def progress(msg, pct=None):
        job["message"] = msg
        if pct is not None:
            job["progress"] = pct

    try:
        prev = JOBS.get(prev_job_id) or {}
        video_path = prev.get("_dub_video")
        segs = prev.get("_dub_segments")
        if not video_path or not os.path.exists(video_path):
            job["status"] = "error"; job["message"] = ("El paso de traducir ya no está disponible "
                                                        "(vuelve a subir el video y tradúcelo).")
            return
        wd = os.path.join(WORK_DIR, job_id)
        os.makedirs(wd, exist_ok=True)

        # ── Doblaje EXACTO: conserva la voz original (ElevenLabs Dubbing), su propia traducción ──
        if voz == "exacto":
            progress("Doblaje exacto (conservando la voz original)...", 15)
            out = os.path.join(wd, f"dubbed_{target_lang}.mp4")
            dub_video(_load_eleven_key(), video_path, target_lang, out,
                      source_lang="auto", progress=lambda m: progress(m))
            if not _video_ok(out):   # mp4 truncado/corrupto → error honesto, no "Listo"
                job["status"] = "error"
                job["message"] = "El video doblado salió corrupto/truncado — vuelve a intentar."
                return
            job["result"] = {"ok": True, "path": out, "target_lang": target_lang, "voz": "exacto"}
            job["status"] = "done"; job["progress"] = 100
            job["message"] = "Listo (doblaje exacto · voz original)"
            return

        # ── Voz elegida (Kate / Juan Carlos): guion REVISADO por Jack + 2x1 opcional en la voz ──
        from pipeline.dub_colombia import generar_dub
        # aplicar las ediciones de Jack sobre las frases (textos[i] reemplaza es_colombia)
        merged = []
        for i, s in enumerate(segs or []):
            t = textos[i] if (textos and i < len(textos)) else s.get("es_colombia", "")
            s2 = dict(s); s2["es_colombia"] = (t or "").strip()
            merged.append(s2)
        if oferta_2x1:   # la voz menciona el 2x1: se antepone la frase de oferta a la ÚLTIMA fase con texto
            for s in reversed(merged):
                if s.get("es_colombia"):
                    s["es_colombia"] = _dub_2x1_line(oferta_texto) + " " + s["es_colombia"]
                    break
        progress("Generando la voz del doblaje...", 20)
        d = generar_dub(video_path, api_key=_load_env_key(), eleven_key=_load_eleven_key(),
                        product_desc=prev.get("_dub_product", ""), voz=voz,
                        segments_override=merged, generar_video=True, work_dir=wd,
                        progress=lambda m, p=None: progress(m, p if p is not None else 55))
        if d.get("ok") and d.get("video"):
            if not _video_ok(d["video"]):   # mp4 truncado/corrupto → error honesto, no "Listo"
                job["status"] = "error"
                job["message"] = "El video doblado salió corrupto/truncado — vuelve a intentar."
                return
            etq = "es-CO · 2x1" if oferta_2x1 else "es-CO"
            job["result"] = {"ok": True, "path": d["video"], "target_lang": etq,
                             "voz": d.get("voz", voz)}
            job["status"] = "done"; job["progress"] = 100; job["message"] = "Video doblado listo"
        else:
            job["status"] = "error"; job["message"] = d.get("error", "No se pudo generar el doblaje")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "dubbing_write" in msg:
            msg = ("Tu API key de ElevenLabs no tiene el permiso 'Dubbing'. "
                   "Actívalo en elevenlabs.io → API Keys (Dubbing → Write).")
        job["status"] = "error"; job["message"] = msg


@app.post("/api/dub-generar")
def dub_generar(prev_job_id: str = Form(...), voz: str = Form("juan_carlos"),
                textos: str = Form("[]"), oferta_2x1: bool = Form(False),
                oferta_texto: str = Form(""), target_lang: str = Form("es")):
    """Paso ②: genera el video doblado con la voz elegida (kate/juan_carlos/exacto) usando el guion
    revisado del paso ①. `textos` = JSON array con las frases editadas (una por fase)."""
    import json as _json
    try:
        lst = _json.loads(textos) if textos else []
        lst = [str(x) for x in lst] if isinstance(lst, list) else []
    except Exception:  # noqa: BLE001
        lst = []
    if voz not in ("kate", "juan_carlos", "exacto"):
        voz = "juan_carlos"
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"tipo": "doblaje_voz", "status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_dub_generar_job,
                     args=(job_id, prev_job_id.strip(), voz, lst, bool(oferta_2x1),
                           oferta_texto.strip(), target_lang.strip() or "es"),
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
def download_videos(urls: str = Form(...)):
    """Baja videos desde una lista de links (uno por línea) con yt-dlp."""
    links = [u.strip() for u in urls.replace(",", "\n").splitlines() if u.strip()]
    if not links:
        raise HTTPException(400, "Pega al menos un link")
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"tipo": "descargar_videos", "status": "running", "progress": 0, "message": "Iniciando...",
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
            archivos_locales=settings.get("archivos_locales") or [],
            product_url=product_url, image_path=image_path,
            product_desc=product_desc, settings=settings,
            gemini_key=_load_env_key(), eleven_key=_load_eleven_key(), progress=progress,
        )
        # Banner de oferta ARRIBA (2x1 · envío gratis · pagas al recibir), igual que en Cortar clips
        if result.get("ok") and result.get("versions") and settings.get("banner_oferta"):
            _agregar_banner_oferta(result["versions"], os.path.join(WORK_DIR, job_id), progress,
                                   start=settings.get("banner_start", 0.0),
                                   dur=settings.get("banner_dur", 0.0),
                                   line2=settings.get("banner_line2", "OFERTA 2X1"))
        # Estado para "🔄 Regenerar UNA versión" (faltaba SOLO aquí → daba 404 y filtraba el pool
        # pesado _regen al frontend). Mismo patrón que Cortar clips / render con voz.
        _stash_regen(job, result, job_id, {"voz": settings.get("voz")})
        job["result"] = result
        job["status"] = "done" if result.get("ok") else "error"
        if not result.get("ok"):
            job["message"] = result.get("error", "Error desconocido")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


def _run_regen_version_job(job_id: str, src_job: str, name: str, motivo: str):
    """Regenera UNA versión (motivo: edicion/clips/guion/otra) y la reemplaza en el resultado."""
    job = JOBS[job_id]

    def progress(m, p):
        job["message"] = m; job["progress"] = int(p)

    try:
        from pipeline.regen import regenerar_version
        estado = _load_regen(src_job)
        if not estado:
            job["status"] = "error"; job["message"] = "Ese proyecto es viejo; genera de nuevo para poder regenerar versiones."
            return
        nueva = regenerar_version(estado, name, motivo, gemini_key=_load_env_key(),
                                  eleven_key=_load_eleven_key(),
                                  voz=(estado.get("settings", {}).get("voz") or "juan_carlos"),
                                  progress=progress)
        if not nueva:
            job["status"] = "error"; job["message"] = "No se pudo regenerar esa versión (reintenta)."
            return
        # re-persistir el estado mutado (uso/orden/guion de la versión) y devolver la versión nueva
        sj = JOBS.get(src_job)
        if sj is not None:
            sj["_regen"] = estado
            res = sj.get("result") or {}
            for i, v in enumerate((res.get("versions") or [])):
                if v.get("name") == name:
                    res["versions"][i] = {**v, **nueva}
                    break
        try:
            import json as _json
            with open(os.path.join(WORK_DIR, src_job, "regen.json"), "w") as f:
                _json.dump(estado, f, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass
        job["result"] = {"ok": True, "version": nueva}
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"; job["message"] = f"Error: {e}"


@app.post("/api/regenerate-version")
def regenerate_version_ep(job_id: str = Form(...), name: str = Form(...),
                          motivo: str = Form("otra")):
    """Regenera la versión `name` del proyecto `job_id` con un MOTIVO. Devuelve un job_id nuevo
    para hacer polling del progreso (usa el mismo /api/status)."""
    estado = _load_regen(job_id)
    if not estado:
        raise HTTPException(404, "No hay estado para regenerar (proyecto viejo: genera de nuevo).")
    if name not in (estado.get("versions") or {}):
        raise HTTPException(400, "Esa versión no existe en el proyecto.")
    rid = uuid.uuid4().hex[:12]
    JOBS[rid] = {"tipo": "regenerar_version", "status": "running", "progress": 0, "message": "Iniciando…",
                 "result": None, "created": time.time()}
    threading.Thread(target=_run_regen_version_job, args=(rid, job_id, name, motivo),
                     daemon=True).start()
    return {"job_id": rid}


@app.post("/api/producto-clips")
def producto_clips(
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
    voz_en_off: bool = Form(False),
    voz: str = Form("juan_carlos"),
    voz_jc: int = Form(0),
    voz_kate: int = Form(0),
    oferta_2x1: bool = Form(False),
    banner_oferta: bool = Form(False),
    banner_start: float = Form(0.0),
    banner_dur: float = Form(0.0),
    hook_seconds: float = Form(0.0),
    caption_style: str = Form("hormozi"),
    caption_size: str = Form("mediano"),
    subtitulos: bool = Form(True),
    vo_guiones: int = Form(0),
    tofu: int = Form(0),   # embudo TOFU/MOFU/BOFU (0/0/0 = clásico 8 versiones)
    mofu: int = Form(0),
    bofu: int = Form(0),
    destino: str = Form("tiktok"),
    winner_files: list[UploadFile] = File([]),
):
    """Semi-auto: links de ganadores Y/O videos locales + tu producto → clips en una pasada."""
    links = [u.strip() for u in winner_urls.replace(",", "\n").splitlines() if u.strip()]
    locales: list[str] = []
    if not links and not any(f and f.filename for f in (winner_files or [])):
        raise HTTPException(400, "Pega al menos un link o elige videos de tu computador")

    job_id = uuid.uuid4().hex[:12]
    image_path = None
    if product_image and product_image.filename:
        up = os.path.join(UPLOAD_DIR, job_id)
        os.makedirs(up, exist_ok=True)
        image_path = os.path.join(up, "producto_" + os.path.basename(product_image.filename))
        with open(image_path, "wb") as f:
            shutil.copyfileobj(product_image.file, f)
    for wf in (winner_files or []):
        if wf and wf.filename:
            d = os.path.join(UPLOAD_DIR, job_id); os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "gan_" + os.path.basename(wf.filename))
            with open(p, "wb") as f:
                shutil.copyfileobj(wf.file, f)
            locales.append(p)

    settings = {
        "aspect": aspect,
        "target_seconds": float(target_seconds),
        "max_clip": min(5.0, max(1.0, float(max_clip))),
        "destino": destino if destino in ("tiktok", "meta") else "tiktok",
        "blur_captions": bool(blur_captions),
        "text_mode": text_mode,
        "use_gemini": True,
        "musica": bool(musica),
        "bajar_volumen": bool(bajar_volumen),
        "voz_en_off": bool(voz_en_off),
        "voz": voz if voz in ("kate", "juan_carlos") else "juan_carlos",
        # Mezcla personalizada: N versiones con juan_carlos + M con kate (0/0 = todas con `voz`)
        "voz_jc": max(0, min(8, int(voz_jc))),
        "voz_kate": max(0, min(8, int(voz_kate))),
        "oferta_2x1": bool(oferta_2x1),
        "banner_oferta": bool(banner_oferta),
        "banner_start": max(0.0, float(banner_start)),
        "banner_dur": max(0.0, float(banner_dur)),
        "hook_seconds": max(0.0, float(hook_seconds)),
        "caption_style": caption_style if caption_style in (
            "hormozi", "karaoke", "highlight_box", "bold_outline", "yellow_highlight")
            else "hormozi",
        "caption_size": caption_size if caption_size in ("pequeno", "mediano", "grande") else "mediano",
        "subtitulos": bool(subtitulos),
        # Control de costo de ElevenLabs: cuántas narraciones distintas (0 = una por versión).
        # El selector manda 8 (una por video) → equivale al comportamiento por defecto.
        "vo_guiones": vo_guiones if vo_guiones in (2, 4) else 0,
        "archivos_locales": locales,
    }
    # Embudo TOFU/MOFU/BOFU (voz en off): una versión por guion, cada una etiquetada por etapa.
    _mix = {"TOFU": max(0, int(tofu)), "MOFU": max(0, int(mofu)), "BOFU": max(0, int(bofu))}
    if sum(_mix.values()) > 0:
        settings["mix"] = _mix
    JOBS[job_id] = {"tipo": "producto_clips", "status": "running", "progress": 0, "message": "Iniciando...",
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


@app.get("/api/shopify-check")
def shopify_check():
    """Valida las credenciales de Shopify (request de prueba) + detecta el tema publicado.
    Es el 'gate' de arranque del módulo Crear Landings."""
    from pipeline import shopify_admin as sh
    dom, tok, theme = _load_shopify()
    v = sh.validar(dom or "", tok or "")
    if not v.get("ok"):
        return v
    t = sh.tema_publicado(dom, tok, theme)
    if not t.get("ok"):
        return {"ok": False, "error": t.get("error", "No pude detectar el tema")}
    return {"ok": True, "shop": v.get("shop"), "moneda": v.get("moneda"),
            "tema": {"id": t.get("id"), "nombre": t.get("nombre"), "rol": t.get("rol")}}


# ─────────────────────  🛍️ CREAR LANDINGS (motor: pipeline/landing_agent)  ─────────────────────

def _persist_landing(job_id: str):
    """Persiste el job de landing a work/<id>/job.json (mismo patrón que _persist_disruptive):
    el gate de aprobación + publicar siguen funcionando aunque el server se reinicie."""
    import json as _json
    job = JOBS.get(job_id)
    if not job:
        return
    data = {k: job.get(k) for k in ("tipo", "status", "progress", "message", "result", "created")}
    try:
        d = os.path.join(WORK_DIR, job_id)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "job.json"), "w") as f:
            _json.dump(data, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def _run_landing_job(job_id: str, tipo: str, producto: str, link: str, precio: str, oferta: str,
                     fotos: list[str]):
    from pipeline.landing_agent import generar_landing
    job = JOBS[job_id]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = pct

    try:
        page_text = ""
        if (link or "").strip():
            progress("Leyendo la página real del producto…", 3)
            try:
                page_text = fetch_page_text(link.strip(), max_chars=3000)
            except Exception:  # noqa: BLE001
                page_text = ""
        r = generar_landing(tipo, producto, page_text, precio, oferta, fotos,
                            gemini_key=_load_env_key() or "", anthropic_key=_load_anthropic_key() or "",
                            work_dir=os.path.join(WORK_DIR, job_id), progress=progress)
        job["result"] = r
        job["status"] = "done" if r.get("ok") else "error"
        if not r.get("ok"):
            job["message"] = r.get("error", "Error desconocido")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"
    _persist_landing(job_id)


@app.post("/api/landing-generate")
def landing_generate(tipo: str = Form(...), producto: str = Form(""), link: str = Form(""),
                     precio: str = Form(""), oferta: str = Form(""),
                     fotos: list[UploadFile] = File(default=[])):
    """Genera la landing/advertorial ENTERA (copy + imágenes + preview) en segundo plano.
    NADA se sube a Shopify aquí: el preview se aprueba con /api/landing-publicar (gate obligatorio)."""
    tipo = "advertorial" if str(tipo).lower().startswith("advert") else "landing"
    if not producto.strip() and not link.strip():
        raise HTTPException(400, "Escribe tu producto o pega el link de la página")
    if not precio.strip():
        raise HTTPException(400, "Escribe el precio EXACTO (se usa tal cual, jamás se inventa)")
    fotos = [f for f in (fotos or []) if f and f.filename]
    if not fotos:
        raise HTTPException(400, "Sube al menos una foto REAL del producto (regla: el producto "
                                 "siempre con tus fotos)")
    if not _load_anthropic_key():
        raise HTTPException(400, "Falta la API key de Claude (ANTHROPIC_API_KEY) en 🔑 Claves — "
                                 "es la que escribe el copy")
    job_id = uuid.uuid4().hex[:12]
    up = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(up, exist_ok=True)
    paths = []
    for i, f in enumerate(fotos[:6]):
        p = os.path.join(up, f"foto_{i}_" + os.path.basename(f.filename))
        with open(p, "wb") as out:
            shutil.copyfileobj(f.file, out)
        paths.append(p)
    JOBS[job_id] = {"tipo": "landing", "status": "running", "progress": 0, "message": "Iniciando…",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_landing_job,
                     args=(job_id, tipo, producto.strip(), link.strip(), precio.strip(),
                           oferta.strip(), paths), daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/landing-publicar")
def landing_publicar(job_id: str = Form(...)):
    """GATE de aprobación: solo se llama cuando Jack hace clic en '✅ Aprobar y subir a Shopify'.
    Sube imágenes al CDN y crea SOLO recursos nuevos cm-* (jamás toca lo existente)."""
    from pipeline.landing_agent import publicar_en_shopify
    job = _get_job(job_id)
    manifest = (job or {}).get("result")
    if not manifest:
        raise HTTPException(404, "No encuentro esa landing generada (¿expiró el trabajo?)")
    if not manifest.get("ok"):
        return {"ok": False, "error": "Esa generación terminó con error — regenera antes de publicar."}
    dom, tok, theme = _load_shopify()
    if not (dom and tok):
        return {"ok": False, "error": "Faltan las credenciales de Shopify en 🔑 Claves "
                                       "(dominio + Admin API token) — no se publicó nada."}
    return publicar_en_shopify(manifest, dom, tok, theme,
                               manifest.get("tipo", "landing"), manifest.get("producto", ""))


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


def _run_foreplay_producto_job(job_id: str, image_path: str | None, nombre: str,
                               solo_activos: bool):
    from pipeline.creative_search import foreplay_producto
    job = JOBS[job_id]

    def progress(msg, pct):
        job["message"] = msg
        job["progress"] = pct

    try:
        r = foreplay_producto(image_path=image_path, nombre=nombre,
                              foreplay_key=_load_foreplay_key(), gemini_key=_load_env_key(),
                              solo_activos=solo_activos, progress=progress)
        job["result"] = r
        job["status"] = "done" if r.get("ok") else "error"
        if not r.get("ok"):
            job["message"] = r.get("error", "Error")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"; job["message"] = f"Error: {e}"


@app.post("/api/foreplay-producto")
def foreplay_producto_api(nombre: str = Form(""), solo_activos: bool = Form(False),
                                foto: UploadFile | None = File(None)):
    """📸 Producto exacto: foto y/o nombre → TODOS los creativos de ESE producto en Foreplay
    (todos los términos, páginas grandes, juez visual). Job en background con progreso."""
    if not _load_foreplay_key():
        raise HTTPException(400, "Falta la API key de Foreplay (ponla en 🔑 Claves)")
    image_path = None
    job_id = uuid.uuid4().hex[:12]
    if foto is not None and foto.filename:
        d = os.path.join(UPLOAD_DIR, job_id)
        os.makedirs(d, exist_ok=True)
        image_path = os.path.join(d, "producto_" + os.path.basename(foto.filename))
        with open(image_path, "wb") as f:
            shutil.copyfileobj(foto.file, f)
    if not (nombre.strip() or image_path):
        raise HTTPException(400, "Dame el nombre del producto o su foto")
    JOBS[job_id] = {"tipo": "foreplay_producto", "status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time()}
    threading.Thread(target=_run_foreplay_producto_job,
                     args=(job_id, image_path, nombre.strip(), bool(solo_activos)),
                     daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/foreplay-search")
def foreplay_search(query: str = Form(""), live: bool = Form(True),
                    languages: str = Form(""), niches: str = Form(""),
                    video_only: bool = Form(True), running_min_days: int = Form(0),
                    video_max_seconds: int = Form(0), cursor: str = Form(""),
                    limit: int = Form(0), order: str = Form(""),
                    fallback_idiomas: bool = Form(True)):
    """Busca ads ganadores en Foreplay (+100M) por keyword/idioma/nicho.
    Si el idioma pedido no llena el `limit`, completa con ganadores del mismo nicho en
    otro idioma (marcados `otro_idioma=True` → se doblan con 🎙️ Doblar)."""
    key = _load_foreplay_key()
    if not key:
        raise HTTPException(400, "Falta la API key de Foreplay (ponla en 🔑 Claves)")
    r = fp.buscar_ads(query, api_key=key, live=live, languages=languages, niches=niches,
                      video_only=video_only,
                      running_min_days=running_min_days or None,
                      video_max_seconds=video_max_seconds or None, cursor=cursor,
                      limit=limit or None,
                      order=order if order in ("newest", "oldest", "longest_running") else "",
                      fallback_idiomas=fallback_idiomas)
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
def foreplay_clips(videos: str = Form(...), aspect: str = Form("9:16"),
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
    JOBS[job_id] = {"tipo": "foreplay_clips", "status": "running", "progress": 0, "message": "Iniciando...",
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
    return {"clips": clips, "aspect": res.get("aspect", "9:16")}


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
def disruptive_angles(producto: str = Form(""), link: str = Form(""),
                            ofertas: str = Form(""), precio: str = Form(""),
                            tipo: str = Form("disruptivo"),
                            product_image: UploadFile | None = File(None)):
    """Paso 1: analiza producto/link → conceptos para elegir. tipo: disruptivo | advertorial."""
    precio = ""   # REGLA GLOBAL: NUNCA se muestra precio en ningún ad
    tipo = "advertorial" if str(tipo).lower().startswith("advert") else "disruptivo"
    if not producto.strip() and not link.strip():
        raise HTTPException(400, "Escribe tu producto o pega el link de la página")
    if tipo == "advertorial" and not (product_image and product_image.filename):
        raise HTTPException(400, "El advertorial necesita la FOTO de tu producto (se ve en la escena).")
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
                                  page_text=page_text, ofertas=ofertas_list, precio=precio.strip(),
                                  tipo=tipo)
    if not conceptos:
        raise HTTPException(502, "No se pudieron generar los conceptos (revisa la key de Claude)")
    JOBS[ctx_id] = {"tipo": "ads_imagen", "status": "angles", "result": {"variantes": conceptos, "tipo": tipo},
                    "created": time.time(),
                    "_image_path": image_path, "_precio": precio.strip(), "_ofertas": ofertas_list,
                    "_producto": producto.strip() or link.strip(), "_page_text": page_text,
                    "_tipo": tipo}
    _persist_disruptive(ctx_id)   # sobrevive reinicios del server
    return {"ctx_id": ctx_id, "conceptos": conceptos, "tipo": tipo}


def _run_disruptive_v2_job(job_id, conceptos, precio, ofertas, image_path, hd=False):
    job = JOBS[job_id]

    def progress(m, p):
        job["message"] = m
        job["progress"] = p

    # Full-prompt: Google AI dibuja el ad COMPLETO (texto ya escrito bien por Claude); la ortografía del
    # render se verifica y regenera dentro de generar_ads_fullprompt. (precio/ofertas ya van en el prompt.)
    try:
        r = generar_ads_fullprompt(conceptos, os.path.join(WORK_DIR, job_id), gemini_key=_load_env_key(),
                                   product_image_path=image_path, hd=hd, progress=progress)
        job["result"] = r
        job["status"] = "done" if r.get("ok") else "error"
        if not r.get("ok"):
            job["message"] = r.get("error", "Error desconocido")
        _persist_disruptive(job_id)   # sobrevive reinicios del server
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


@app.post("/api/disruptive-images")
def disruptive_images(ctx_id: str = Form(...), indices: str = Form(...),
                      modelo: str = Form("rapida")):
    """Paso 2: genera las imágenes de los conceptos ELEGIDOS.
    modelo: 'rapida' = Nano Banana 1 (~$0.04) | 'pro' = Nano Banana 2 (~$0.13)."""
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
    hd = str(modelo).lower() in ("pro", "hd", "2", "nano2", "nanobanana2")
    ctx["_hd"] = hd          # el modelo elegido: regenerar/otro ángulo lo reusan
    ctx.update({"tipo": "ads_imagen", "created": time.time(), "status": "running", "progress": 0, "message": "Iniciando...",
                "result": {"variantes": elegidos}})
    threading.Thread(target=_run_disruptive_v2_job,
                     args=(ctx_id, elegidos, ctx.get("_precio", ""), ctx.get("_ofertas", []),
                           ctx.get("_image_path"), hd), daemon=True).start()
    return {"job_id": ctx_id}


@app.post("/api/regenerate-image")
def regenerate_image(job_id: str = Form(...), index: int = Form(...)):
    """Regenera UNA sola imagen (escena limpia + texto compuesto). Síncrono."""
    job = _get_job(job_id)
    if not job or not (job.get("result") or {}).get("variantes"):
        raise HTTPException(404, "No hay un proyecto de ads para ese job")
    variantes = job["result"]["variantes"]
    if index < 0 or index >= len(variantes):
        raise HTTPException(400, "Índice fuera de rango")
    v = variantes[index]
    hd = bool(v.get("hd") or job.get("_hd"))     # mismo modelo con el que se generó el lote
    out = os.path.join(WORK_DIR, job_id, f"ad_{index:02d}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:                              # full-prompt: ad completo + ortografía + producto integrado
        img = generar_ad_fullprompt(v, out, gemini_key=_load_env_key(),
                                    product_image_path=job.get("_image_path"),
                                    integrar_producto=bool(job.get("_image_path")), hd=hd)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"No se pudo regenerar: {e}")
    if not img:
        raise HTTPException(502, v.get("error") or "Google no devolvió imagen (reintenta o revisa créditos)")
    v["imagen"] = img
    v["hd"] = hd
    _persist_disruptive(job_id)
    return {"imagen": img}


@app.post("/api/disruptive-hd")
def disruptive_hd(job_id: str = Form(...), index: int = Form(...)):
    """✨ HD: re-renderiza UNA imagen elegida con el modelo PRO (Nano Banana 2, ~$0.13).
    El lote sale en borrador barato (~$0.04) — solo se paga calidad pro en las que Juan va a usar."""
    job = _get_job(job_id)
    if not job or not (job.get("result") or {}).get("variantes"):
        raise HTTPException(404, "No hay un proyecto de ads para ese job")
    variantes = job["result"]["variantes"]
    if index < 0 or index >= len(variantes):
        raise HTTPException(400, "Índice fuera de rango")
    v = variantes[index]
    # Si la imagen YA existe (con el producto puesto y/o ajustes), HD la REFINA TAL CUAL —
    # misma escena, mismo producto, mismos ajustes — con el modelo PRO. Antes se re-dibujaba
    # desde el prompt: salía OTRA escena y si la 2ª pasada del producto fallaba, lo perdía.
    if v.get("imagen") and os.path.exists(v["imagen"]):
        errs: list = []
        img = editar_imagen_ia(v["imagen"], (
            "Recrea esta MISMA imagen absolutamente idéntica pero en máxima calidad HD "
            "fotorrealista: más nitidez, mejor iluminación y texturas. NO cambies NADA del "
            "contenido: misma composición, mismo producto, mismos textos en español letra por "
            "letra, mismos colores. Entrégala en formato CUADRADO 1:1 exacto (si no lo es, "
            "extiende el fondo con coherencia — sin deformar nada)."), _load_env_key(), errors=errs)
        if not img:
            raise HTTPException(502, "HD no salió (tu imagen quedó intacta): "
                                + (_error_amigable(errs[0]) if errs else "reintenta en un momento"))
    else:
        out = os.path.join(WORK_DIR, job_id, f"ad_{index:02d}.png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            img = generar_ad_fullprompt(v, out, gemini_key=_load_env_key(),
                                        product_image_path=job.get("_image_path"),
                                        integrar_producto=bool(job.get("_image_path")), hd=True)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"No se pudo renderizar en HD: {e}")
        if not img:
            raise HTTPException(502, v.get("error") or "Google no devolvió imagen (reintenta o revisa créditos)")
    v["imagen"] = img
    v["hd"] = True
    _persist_disruptive(job_id)
    return {"imagen": img}


@app.post("/api/disruptive-add-product")
def disruptive_add_product(job_id: str = Form(...), index: int = Form(...)):
    """Mete el PRODUCTO real integrado en UNA imagen ya generada (2ª pasada). Síncrono."""
    job = _get_job(job_id)
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
        # modelo BARATO para poner el producto (el PRO se reserva para el botón HD y a veces
        # está sin cuota — con el barato el botón funciona siempre y cuesta ~3x menos)
        res = _integrar_producto_ia(v["imagen"], prod, _load_env_key(), model=_IMG_MODEL_DRAFT)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"No se pudo poner el producto: {e}")
    if not res:   # bloqueo/cuota/sin imagen → el ad quedó intacto; avisa de verdad
        raise HTTPException(502, "No se pudo integrar el producto (reintenta o revisa el tope de gasto de Google).")
    v["producto_integrado"] = True
    _persist_disruptive(job_id)
    return {"imagen": v["imagen"]}


@app.post("/api/disruptive-edit-image")
def disruptive_edit_image(job_id: str = Form(...), index: int = Form(...), instruccion: str = Form(...)):
    """✏️ AJUSTE con instrucción del usuario: 'ponle la luz más roja', 'quita el texto de arriba', etc.
    Edita la imagen ya generada cambiando SOLO lo pedido. Síncrono."""
    job = _get_job(job_id)
    if not job or not (job.get("result") or {}).get("variantes"):
        raise HTTPException(404, "No hay un proyecto de ads para ese job")
    variantes = job["result"]["variantes"]
    if index < 0 or index >= len(variantes):
        raise HTTPException(400, "Índice fuera de rango")
    if not instruccion.strip():
        raise HTTPException(400, "Dime qué quieres ajustar")
    v = variantes[index]
    if not v.get("imagen"):
        raise HTTPException(400, "Esa imagen aún no está generada")
    try:
        res = editar_imagen_ia(v["imagen"], instruccion.strip(), _load_env_key())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"No se pudo ajustar: {e}")
    if not res:
        raise HTTPException(502, "Google no devolvió la imagen ajustada (reintenta o revisa créditos)")
    _persist_disruptive(job_id)
    return {"imagen": v["imagen"]}


@app.post("/api/disruptive-swap-concept")
def disruptive_swap_concept(job_id: str = Form(...), index: int = Form(...)):
    """Cambia UN concepto por otro TOTALMENTE DIFERENTE (evita los ya mostrados) y lo renderiza. Síncrono."""
    job = _get_job(job_id)
    if not job or not (job.get("result") or {}).get("variantes"):
        raise HTTPException(404, "No hay un proyecto de ads para ese job")
    variantes = job["result"]["variantes"]
    if index < 0 or index >= len(variantes):
        raise HTTPException(400, "Índice fuera de rango")
    producto = job.get("_producto", "")
    if not producto:
        raise HTTPException(400, "Este proyecto es viejo; vuelve a analizar el producto para usar 'otro ángulo'")
    # evita TODOS los ángulos/titulares ya mostrados (para que salga algo distinto)
    evitar = [c.get("titular", "") for c in variantes if c.get("titular")]
    try:
        nuevos = generar_conceptos(producto, _load_anthropic_key(), page_text=job.get("_page_text", ""),
                                   evitar=evitar, n=3, plantillas_fijas=False,
                                   tipo=job.get("_tipo", "disruptivo"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"No se pudo pensar otro ángulo: {e}")
    if not nuevos:
        raise HTTPException(502, "Claude no devolvió otro concepto (revisa la key de Claude)")
    nuevo = nuevos[0]
    hd = bool(job.get("_hd"))     # mismo modelo del lote
    out = os.path.join(WORK_DIR, job_id, f"ad_{index:02d}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        img = generar_ad_fullprompt(nuevo, out, gemini_key=_load_env_key(),
                                    product_image_path=job.get("_image_path"),
                                    integrar_producto=bool(job.get("_image_path")), hd=hd)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"No se pudo generar el nuevo ángulo: {e}")
    if not img:
        raise HTTPException(502, nuevo.get("error") or "Google no devolvió imagen (reintenta o revisa créditos)")
    nuevo["imagen"] = img
    nuevo["hd"] = hd
    variantes[index] = nuevo   # reemplaza el concepto viejo por el nuevo
    _persist_disruptive(job_id)
    return {"variante": nuevo}


# ---- VARIAR IMAGEN GANADORA: subes una imagen que sirvió -> variaciones (mismo producto/ángulo) ----

def _run_variar_imagen_job(job_id, src, out_dir, tipos, n, pro, producto):
    job = JOBS[job_id]

    def progress(m, p):
        job["message"] = m
        job["progress"] = p

    try:
        r = variar_imagen(src, out_dir, _load_env_key(), tipos=tipos, n=n, pro=pro,
                          product_desc=producto, progress=progress)
        job["result"] = r
        job["status"] = "done" if r.get("ok") else "error"
        if not r.get("ok"):
            job["message"] = r.get("error") or "Google no devolvió imágenes (revisa créditos/clave)"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = f"Error: {e}"


@app.post("/api/variar-imagen")
def variar_imagen_endpoint(imagen: UploadFile = File(...),
                           producto: str = Form(""),
                           tipos: str = Form("estilo,escenario,fondo"),
                           n: int = Form(6),
                           modelo: str = Form("rapida")):
    """Sube UNA imagen ganadora -> genera N variaciones (mismo producto/ángulo, distinto tipo).
    modelo: 'rapida' = Nano Banana 1 (~$0.04) | 'pro' = Nano Banana 2 (~$0.13)."""
    if not (imagen and imagen.filename):
        raise HTTPException(400, "Sube la imagen que te funcionó")
    job_id = uuid.uuid4().hex[:12]
    up = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(up, exist_ok=True)
    src = os.path.join(up, "winner_" + os.path.basename(imagen.filename))
    with open(src, "wb") as f:
        shutil.copyfileobj(imagen.file, f)
    tset = tuple(t.strip() for t in tipos.split(",") if t.strip()) or ("estilo", "escenario", "fondo")
    n = max(1, min(int(n or 6), 10))
    pro = str(modelo).lower() in ("pro", "hd", "2", "nano2", "nanobanana2")
    JOBS[job_id] = {"tipo": "variar_imagen", "status": "running", "progress": 0, "message": "Iniciando...",
                    "created": time.time(), "_src": src, "_producto": producto.strip(), "_pro": pro}
    threading.Thread(target=_run_variar_imagen_job,
                     args=(job_id, src, os.path.join(WORK_DIR, job_id), tset, n, pro, producto.strip()),
                     daemon=True).start()
    return {"job_id": job_id}


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
         ".webp": "image/webp", ".gif": "image/gif", ".mp3": "audio/mpeg", ".webm": "video/webm",
         ".html": "text/html"}  # .html: el preview del módulo Crear Landings (iframe)


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
    # Si el master YA está en ese ancho, se sirve TAL CUAL (0s en vez de re-codificar ~1.5 min)
    try:
        src_w = _probe(full).width
    except Exception:  # noqa: BLE001
        src_w = None
    if src_w and src_w == width:
        return FileResponse(full, media_type="video/mp4", filename=f"{name}_{width}w.mp4")
    out_dir = os.path.join(os.path.dirname(full), "downloads")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{name}_{width}w.mp4")
    if not os.path.exists(out_path):
        export_resolution(full, out_path, width)
    return FileResponse(out_path, media_type="video/mp4",
                        filename=f"{name}_{width}w.mp4")


# ==================== 🔁 VARIAR HOOK (creative scaling de video) ====================

def _persist_varhook(job_id: str):
    """Persiste el job de Variar hook a work/<id>/job.json — mismo patrón que _persist_disruptive
    (si el server se reinicia, el poll del front y el 🎲 siguen funcionando)."""
    import json as _json
    job = JOBS.get(job_id)
    if not job:
        return
    data = {k: job.get(k) for k in ("status", "result", "created", "_winner", "_producto",
                                    "_modo", "_voz", "_page_text")}
    try:
        d = os.path.join(WORK_DIR, job_id)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "job.json"), "w") as f:
            _json.dump(data, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def _run_varhook_job(job_id: str, winner: str, producto: str, modo: str, n: int, voz: str):
    job = JOBS[job_id]

    def progress(m, p):
        job["message"], job["progress"] = m, p

    try:
        r = variar_hook(winner, producto, n=n, modo=modo, voz=voz,
                        gemini_key=_load_env_key(), eleven_key=_load_eleven_key(),
                        anthropic_key=_load_anthropic_key(),
                        work_dir=os.path.join(WORK_DIR, job_id), progress=progress)
        if r.get("ok"):
            job["result"], job["status"] = r, "done"
        else:
            job["status"] = "error"
            job["message"] = r.get("error") or "No se pudieron armar las variaciones"
    except Exception as e:  # noqa: BLE001
        job["status"], job["message"] = "error", str(e)
    _persist_varhook(job_id)


@app.post("/api/variar-hook")
def variar_hook_ep(producto: str = Form(""), link: str = Form(""),
                   modo: str = Form("hook"), n: int = Form(4),
                   voz: str = Form("juan_carlos"), video: UploadFile = File(None)):
    """1 creativo GANADOR → N videos: hook nuevo (modo 'hook', default) o hook + tomas nuevas
    por fase (modo 'tomas'). Retrocompatible: sin `modo`, se comporta como solo-hook."""
    if not producto.strip():
        raise HTTPException(400, "Describe el producto (nombre + qué hace)")
    job_id = uuid.uuid4().hex[:12]
    src_dir = os.path.join(WORK_DIR, job_id, "src")
    os.makedirs(src_dir, exist_ok=True)
    winner = None
    if video is not None and getattr(video, "filename", ""):
        winner = os.path.join(src_dir, "winner.mp4")
        with open(winner, "wb") as f:
            shutil.copyfileobj(video.file, f)
    elif link.strip():
        bajados = download_urls([link.strip()], src_dir)
        winner = next((b.get("path") for b in bajados if b.get("ok") and b.get("path")), None)
    if not winner or not os.path.exists(winner):
        raise HTTPException(400, "Sube el video ganador o pega su link de TikTok")
    JOBS[job_id] = {"tipo": "variar_hook", "status": "running", "progress": 0, "message": "Iniciando...",
                    "result": None, "created": time.time(), "_winner": winner,
                    "_producto": producto, "_modo": modo, "_voz": voz, "_page_text": ""}
    threading.Thread(target=_run_varhook_job,
                     args=(job_id, winner, producto, modo, max(1, min(8, n)), voz),
                     daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/variar-hook-otro")
def variar_hook_otro(job_id: str = Form(...), index: int = Form(...)):
    """🎲 Otro hook: regenera UNA variación con evitar=[hooks ya mostrados] y re-arma su video.
    Mismo patrón que /api/disruptive-swap-concept (síncrono, muta el job y persiste)."""
    job = _get_job(job_id)
    if not job or not (job.get("result") or {}).get("variaciones"):
        raise HTTPException(404, "Ese trabajo ya no existe. Genera las variaciones de nuevo.")
    variaciones = job["result"]["variaciones"]
    if not (0 <= index < len(variaciones)):
        raise HTTPException(400, "Índice fuera de rango")
    winner, producto = job.get("_winner") or "", job.get("_producto") or ""
    if not (winner and os.path.exists(winner) and producto):
        raise HTTPException(400, "Proyecto viejo sin contexto — genera las variaciones de nuevo.")
    modo = job.get("_modo") or job["result"].get("modo") or "hook"
    evitar = [v.get("hook", "") for v in variaciones if v.get("hook")]
    arco = job["result"].get("arco") or producto
    nuevas = generar_variaciones(arco, producto, _load_anthropic_key(),
                                 page_text=job.get("_page_text") or "", n=1,
                                 con_escenas=(modo == "tomas"), evitar=evitar)
    if not nuevas:
        raise HTTPException(502, "El cerebro no entregó otra variación (revisa la key de Anthropic)")
    wd = os.path.join(WORK_DIR, job_id, f"otro_{uuid.uuid4().hex[:6]}")
    r = variar_hook(winner, producto, modo=modo, voz=job.get("_voz") or "juan_carlos",
                    variaciones=nuevas[:1], hook_fin=job["result"].get("hook_fin"),
                    gemini_key=_load_env_key(), eleven_key=_load_eleven_key(),
                    anthropic_key=_load_anthropic_key(), work_dir=wd)
    v = (r.get("variaciones") or [None])[0]
    if not (v and v.get("video")):
        raise HTTPException(502, "No se pudo armar el video de la nueva variación")
    variaciones[index] = v
    JOBS[job_id] = job         # re-ancla en memoria (por si _gc_jobs lo sacó durante el render largo)
    _persist_varhook(job_id)
    return {"variacion": v}


# ═══ 🤖 ASISTENTE DE LA APP — responde con el estado REAL del backend, nunca "revisá vos" ═══
# Queja real de Jack (2026-07-10): una IA le contestó "no puedo confirmarte desde mi lado...
# revisá vos la sección Buscar creativos". Este endpoint vive EN el proceso de los jobs:
# junta la evidencia (JOBS en memoria + bitácora work/_eventos.jsonl + estado de las keys)
# y con eso responde. Si algo lo excede, anota la duda para Claude (terminal) en
# /Users/jaca/Vidaria/data/dudas-superapp.jsonl y avisa por Telegram si es urgente.

_FP_USAGE_CACHE: dict = {"t": 0.0, "v": None}


def _foreplay_creditos() -> dict | None:
    """Créditos de Foreplay con cache de 10 min (fp.usage pega HTTP; no en cada mensaje)."""
    key = _load_foreplay_key()
    if not key:
        return None
    if time.time() - _FP_USAGE_CACHE["t"] < 600 and _FP_USAGE_CACHE["v"] is not None:
        return _FP_USAGE_CACHE["v"]
    try:
        u = fp.usage(key)
    except Exception as e:  # noqa: BLE001
        u = {"ok": False, "error": str(e)[:120]}
    _FP_USAGE_CACHE.update(t=time.time(), v=u)
    return u


def _evidencia_asistente() -> dict:
    """La foto REAL del backend que el asistente usa para responder: jobs, bitácora y keys."""
    ev = {
        "ahora": time.strftime("%Y-%m-%d %H:%M:%S"),
        "jobs": asst.snapshot_jobs(JOBS),
        "eventos_recientes": asst.leer_eventos(WORK_DIR, 40),
        "nota_eventos": ("'busqueda' = una corrida de Buscar creativos/TikTok con sus conteos "
                         "reales (tiktok/foreplay = cuántos encontró) y su error si falló. "
                         "'job_inicio'/'job_fin' = trabajos de video/imagen."),
    }
    try:
        gk = _load_env_key()
        chk = _check_gemini_key(gk) if gk else None
        ev["keys"] = {
            "gemini": ("sin_key" if not gk else
                       ("ok" if (chk or {}).get("ok") is True else
                        (chk or {}).get("reason") or "desconocido")),
            "elevenlabs_configurada": bool(_load_eleven_key()),
            "anthropic_configurada": bool(_load_anthropic_key()),
            "foreplay_configurada": bool(_load_foreplay_key()),
            "foreplay_creditos": _foreplay_creditos(),
        }
    except Exception:  # noqa: BLE001
        ev["keys"] = {}
    return ev


@app.post("/api/asistente")
def asistente_chat(mensaje: str = Form(...), historial: str = Form("[]")):
    """Chat del asistente. SIEMPRE mira primero el estado real (jobs + bitácora + keys) y
    responde con evidencia. Si el modelo detecta algo que lo excede, la duda queda anotada
    en el puente con Claude y (si es urgente) avisa por Telegram."""
    import json as _json
    msg = (mensaje or "").strip()
    if not msg:
        raise HTTPException(400, "Escribí la pregunta")
    try:
        hist = _json.loads(historial) if (historial or "").strip() else []
        if not isinstance(hist, list):
            hist = []
    except Exception:  # noqa: BLE001
        hist = []

    ev = _evidencia_asistente()
    r = asst.responder(msg, hist, ev, _load_env_key())

    duda, anotada = r.get("duda"), False
    if isinstance(duda, dict) and str(duda.get("duda", "")).strip():
        anotada = asst.anotar_duda(duda.get("tema", "SuperApp"), duda.get("duda", ""),
                                   duda.get("contexto", ""), duda.get("urgencia", "normal"))
        if anotada and duda.get("urgencia") == "alta":
            asst.notificar_telegram("🚨 SuperApp (asistente): "
                                    f"{duda.get('tema', '')} — {str(duda.get('duda', ''))[:400]}\n"
                                    "Quedó anotada para Claude en dudas-superapp.jsonl")
        if anotada and "claude" not in str(r.get("respuesta", "")).lower():
            r["respuesta"] = (str(r.get("respuesta", "")) +
                              "\n\n📝 Le dejé la duda anotada a Claude (el orquestador en la "
                              "terminal) para que lo resuelva.")

    asst.log_evento(WORK_DIR, "asistente", pregunta=msg[:150], motor=r.get("motor", ""),
                    duda_anotada=anotada)
    return {"ok": True, "respuesta": r.get("respuesta", ""), "motor": r.get("motor", ""),
            "duda_anotada": anotada}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8420)
