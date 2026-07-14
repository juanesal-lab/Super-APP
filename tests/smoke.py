#!/usr/bin/env python
"""🔥 SUITE DE HUMO de la Super-APP — 100% OFFLINE, corre en <60s.

    ./venv/bin/python tests/smoke.py

Por qué existe: este repo lo construyen DOS IAs fusionando rápido, y ya hubo breaks
silenciosos (un merge dejó /api/config devolviendo null). Esta suite protege los flujos
críticos PARA SIEMPRE: si un check da ❌, un merge rompió algo real.

Reglas de la suite (respétalas al agregar checks — ver tests/README.md):
  - $0 de APIs y CERO red: hay una GUARDIA que bloquea cualquier socket saliente y
    EXPLOTA si algo intenta salir a internet (así detectamos fugas de red futuras).
  - Nada de servers: se usa FastAPI TestClient (ASGI in-process).
  - Los trabajos pesados (render/IA/descargas) se MOCKEAN: solo se verifica que el
    endpoint acepte sus params, valide honesto y cree el job.
  - ffmpeg LOCAL sí se usa (es gratis) para fixtures chicos de las unidades puras.
  - Cada check imprime ✅/❌ (⏭️ = skip por falta de ffmpeg/node); al final resumen N/N
    y exit code != 0 si algo falló.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

# ───────────────────────── 0) GUARDIA ANTI-RED (antes de importar NADA de la app) ─────────────────
# Bloquea todo socket saliente (requests, urllib, httpx real, yt-dlp, google-genai...).
# Si un check o un refactor futuro intenta salir a internet, esto EXPLOTA y el check da ❌.

class FugaDeRed(RuntimeError):
    """Algo intentó salir a la red durante la suite offline."""


def _instalar_guardia_red():
    import socket

    def _bloqueado(*a, **k):
        raise FugaDeRed(f"¡FUGA DE RED! algo intentó abrir una conexión: {a[:2]!r}")

    socket.socket.connect = _bloqueado          # cualquier connect (TCP/UDP)
    socket.socket.connect_ex = _bloqueado
    socket.create_connection = _bloqueado       # http.client / urllib3
    socket.getaddrinfo = _bloqueado             # resolución DNS (requests/urllib la llaman antes)


_instalar_guardia_red()

# Sin keys de verdad: el entorno queda LIMPIO (determinista en cualquier máquina) y ningún
# módulo encuentra una key con la que se le ocurra llamar a una API.
_ENV_KEYS = ["GEMINI_API_KEY", "GOOGLE_API_KEY", "ELEVENLABS_API_KEY", "ANTHROPIC_API_KEY",
             "FOREPLAY_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY", "SCRAPECREATORS_API_KEY",
             "SHOPIFY_STORE_DOMAIN", "SHOPIFY_ADMIN_API_TOKEN", "SHOPIFY_THEME_ID"]
for _k in _ENV_KEYS:
    os.environ.pop(_k, None)

# Sandbox de disco: uploads/work/.env de la suite viven en un tmp que se borra al final.
TMP = tempfile.mkdtemp(prefix="smoke_superapp_")
FFMPEG = shutil.which("ffmpeg")
NODE = shutil.which("node")


# ───────────────────────── mini-framework: checks con ✅/❌ y resumen N/N ─────────────────────────

_CHECKS: list[tuple[str, object]] = []
_RESULTS = {"ok": 0, "fail": 0, "skip": 0}
_FALLAS: list[str] = []


class Skip(Exception):
    """Lanzar dentro de un check para saltarlo (ej. no hay ffmpeg/node en esta máquina)."""


def check(nombre):
    def deco(fn):
        _CHECKS.append((nombre, fn))
        return fn
    return deco


@contextlib.contextmanager
def patched(obj, attr, valor):
    """Parchea obj.attr durante el bloque y SIEMPRE lo restaura (los mocks no se filtran)."""
    original = getattr(obj, attr)
    setattr(obj, attr, valor)
    try:
        yield
    finally:
        setattr(obj, attr, original)


def wait_for(cond, timeout=5.0, paso=0.02):
    """Espera a que cond() sea verdadero (los endpoints lanzan threads; los fakes son rápidos)."""
    fin = time.time() + timeout
    while time.time() < fin:
        if cond():
            return True
        time.sleep(paso)
    return cond()


# ───────────────────────── import de la app (bajo la guardia) ─────────────────────────

_IMPORT_ERROR = None
appmod = None
client = None
try:
    import app as appmod                      # backend/app.py (registra TODAS las rutas)
    import radar_api

    # Redirigir el disco y el .env de la app al sandbox (no ensucia el repo ni lee keys reales)
    appmod.UPLOAD_DIR = os.path.join(TMP, "uploads")
    appmod.WORK_DIR = os.path.join(TMP, "work")
    appmod.ENV_FILE = os.path.join(TMP, "env_vacio")   # no existe → cero keys, cero red
    os.makedirs(appmod.UPLOAD_DIR, exist_ok=True)
    os.makedirs(appmod.WORK_DIR, exist_ok=True)

    from fastapi.testclient import TestClient
    # OJO: sin `with` NO corre el lifespan → no baja el modelo EAST ni corre el GC de disco.
    client = TestClient(appmod.app)
except Exception as e:  # noqa: BLE001
    _IMPORT_ERROR = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"


def _fixture_mp4() -> str:
    """Video chico REAL (2s, con audio) hecho con ffmpeg local — gratis. Cacheado en TMP."""
    if not FFMPEG:
        raise Skip("no hay ffmpeg en esta máquina")
    p = os.path.join(TMP, "fixture.mp4")
    if not os.path.exists(p):
        subprocess.run(
            [FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", p],
            capture_output=True, timeout=60, check=True)
    return p


def _job(job_id: str) -> dict:
    return appmod.JOBS.get(job_id) or {}


def _runner_fake(capturas: list):
    """Runner de job falso: captura los args y marca el job como done al instante."""
    def fake(job_id, *a, **k):
        capturas.append((job_id, a, k))
        appmod.JOBS[job_id]["status"] = "done"
        appmod.JOBS[job_id]["result"] = {"ok": True, "_mock": True}
    return fake


# ═════════════════════════ 1) LA APP IMPORTA Y LAS RUTAS REGISTRAN ═════════════════════════

@check("la app importa completa (backend/app.py + radar_api) sin tocar la red")
def _c_import():
    assert _IMPORT_ERROR is None, f"backend/app.py NO importa:\n{_IMPORT_ERROR}"
    assert appmod.app.title == "CreativeMaxing"


@check("TODAS las rutas registran (>= 60 endpoints de API)")
def _c_rutas():
    from fastapi.routing import APIRoute
    rutas = [r.path for r in appmod.app.routes if isinstance(r, APIRoute)]
    # assert flexible: hoy son ~62; si un merge borra endpoints en masa, esto grita.
    assert len(rutas) >= 60, f"solo {len(rutas)} rutas registradas: ¿un merge borró endpoints? {sorted(rutas)}"
    for critica in ("/api/config", "/api/process", "/api/scripts", "/api/status/{job_id}",
                    "/api/busy", "/api/dub-preview", "/api/dub-generar", "/api/reaplicar-hook",
                    "/api/landing-generate", "/api/landing-publicar", "/api/variar-imagen",
                    "/api/radar/scan", "/api/montador/status", "/api/shopify-check"):
        assert critica in rutas, f"falta la ruta crítica {critica}"


@check("la guardia anti-red de la suite de verdad EXPLOTA si algo intenta salir")
def _c_guardia():
    import requests
    try:
        requests.get("http://example.com", timeout=3)
    except Exception:
        return              # bloqueado (FugaDeRed envuelta por requests) — perfecto
    raise AssertionError("requests.get salió a internet: la guardia anti-red no está funcionando")


# ═════════════════════════ 2) /api/config — EL BUG DEL NULL NUNCA MÁS ═════════════════════════

@check("/api/config devuelve el dict COMPLETO (jamás null) con todos los has_*")
def _c_config():
    r = client.get("/api/config")
    assert r.status_code == 200, f"HTTP {r.status_code}"
    cfg = r.json()
    # ESTE fue el bug real: un merge arrastró el return al fondo de otra función → null.
    assert isinstance(cfg, dict) and cfg, f"/api/config devolvió {cfg!r} (el bug del null volvió)"
    for k in ("has_gemini_key", "has_eleven_key", "has_anthropic_key", "has_foreplay_key",
              "has_pexels_key", "has_pixabay_key", "has_scrapecreators_key", "has_shopify"):
        assert k in cfg, f"falta {k} en /api/config"
        assert isinstance(cfg[k], bool), f"{k} no es bool: {cfg[k]!r}"
    assert isinstance(cfg.get("voices"), list) and cfg["voices"], "faltan las voces"
    assert isinstance(cfg.get("dub_langs"), list) and cfg["dub_langs"], "faltan los idiomas de doblaje"


@check("/api/config trae gemini_key_status y sin key es 'sin_key' (sin llamar a Google)")
def _c_config_gemini_status():
    cfg = client.get("/api/config").json()
    assert "gemini_key_status" in cfg, "falta gemini_key_status en /api/config"
    assert cfg["gemini_key_status"] == "sin_key", \
        f"sin key debería ser 'sin_key', vino {cfg['gemini_key_status']!r}"


# ═════════════════════════ 3) BÁSICOS: busy, status, shopify-check ═════════════════════════

@check("/api/busy responde {busy, jobs} coherente")
def _c_busy():
    r = client.get("/api/busy")
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j.get("busy"), bool) and isinstance(j.get("jobs"), int), f"formato raro: {j}"


@check("/api/status/{id} con job fake devuelve status/progress/message/result; sin job → 404")
def _c_status():
    appmod.JOBS["smoke_fake_job"] = {"status": "running", "progress": 42,
                                     "message": "probando", "result": None,
                                     "created": time.time(), "tipo": "smoke"}
    j = client.get("/api/status/smoke_fake_job").json()
    assert j["status"] == "running" and j["progress"] == 42 and j["message"] == "probando", f"{j}"
    assert "result" in j
    appmod.JOBS["smoke_fake_job"].update(status="done", result={"ok": True})
    j = client.get("/api/status/smoke_fake_job").json()
    assert j["status"] == "done" and j["result"] == {"ok": True}
    assert client.get("/api/status/no_existe_xxx").status_code == 404, "job inexistente debe dar 404"


@check("/api/shopify-check sin credenciales → error HONESTO (no 500, no mentir ok)")
def _c_shopify_check():
    r = client.get("/api/shopify-check")
    assert r.status_code == 200, f"HTTP {r.status_code}"
    j = r.json()
    assert j.get("ok") is False, f"sin credenciales debe ser ok:False, vino {j}"
    assert "dominio" in (j.get("error") or "").lower() or "claves" in (j.get("error") or "").lower(), \
        f"el error no explica qué falta: {j}"


# ═════════════════════════ 4) LOS FLUJOS ACEPTAN SUS PARAMS Y CREAN JOB ═════════════════════════

@check("/api/process acepta sus params, crea el job y normaliza settings (9:16 por defecto)")
def _c_process():
    caps: list = []
    with patched(appmod, "_run_job", _runner_fake(caps)):
        r = client.post("/api/process",
                        files=[("files", ("v1.mp4", b"\x00" * 4096, "video/mp4"))],
                        data={"product_desc": "repelente ultrasónico", "n_versions": "99",
                              "banner_oferta": "true", "oferta_texto": "OFERTA 2X1"})
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
        jid = r.json()["job_id"]
        assert wait_for(lambda: caps), "el endpoint no lanzó el job"
    job_id, (paths, settings), _ = caps[0]
    assert job_id == jid and _job(jid).get("tipo") == "cortar_clips"
    assert len(paths) == 1 and os.path.exists(paths[0]), "no guardó el video subido"
    assert settings["aspect"] == "9:16", f"el default debe ser 9:16 vertical, vino {settings['aspect']}"
    assert settings["n_versions"] == 8, f"n_versions debe caparse a 8, vino {settings['n_versions']}"
    assert settings["banner_oferta"] is True and settings["banner_line2"] == "OFERTA 2X1"
    assert _job(jid)["status"] == "done"


@check("/api/process sin videos → 400 con mensaje claro (no crea job fantasma)")
def _c_process_vacio():
    r = client.post("/api/process", data={"product_desc": "x"})
    assert r.status_code == 400, f"esperaba 400, vino {r.status_code}"
    assert "video" in r.json()["detail"].lower()


@check("/api/scripts con reference_url de Foreplay (mock) crea el job de guiones con la referencia")
def _c_scripts():
    caps: list = []

    def fake_descargar(url, dest):
        with open(dest, "wb") as f:
            f.write(b"\x00" * 2048)
        return True

    with patched(appmod, "_run_scripts_job", _runner_fake(caps)), \
         patched(appmod.fp, "descargar_video", fake_descargar):
        r = client.post("/api/scripts",
                        files=[("files", ("v1.mp4", b"\x00" * 4096, "video/mp4"))],
                        data={"product_desc": "rodillera de compresión",
                              "reference_url": "https://cdn.foreplay.co/ganador.mp4",
                              "reference_name": "ganador-31d"})
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
        jid = r.json()["job_id"]
        assert wait_for(lambda: caps), "no lanzó el job de guiones"
    _, (paths, settings), _ = caps[0]
    assert _job(jid).get("tipo") == "guiones"
    assert settings["reference_ad"] and os.path.exists(settings["reference_ad"]), \
        "no bajó/guardó el ad de referencia"
    assert settings["reference_name"] == "ganador-31d"
    assert settings["reference_warning"] is None


@check("/api/scripts con reference_url de dominio NO permitido → 400 (seguridad)")
def _c_scripts_url_mala():
    r = client.post("/api/scripts",
                    files=[("files", ("v1.mp4", b"\x00" * 1024, "video/mp4"))],
                    data={"reference_url": "https://malicioso.com/x.mp4"})
    assert r.status_code == 400, f"esperaba 400, vino {r.status_code}"


@check("/api/dub-preview con video subido crea el job de traducción (paso ①)")
def _c_dub_preview():
    caps: list = []
    with patched(appmod, "_run_dub_preview_job", _runner_fake(caps)):
        r = client.post("/api/dub-preview",
                        files=[("video", ("gringo.mp4", b"\x00" * 4096, "video/mp4"))],
                        data={"product_desc": "crema de veneno de abeja"})
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
        jid = r.json()["job_id"]
        assert wait_for(lambda: caps), "no lanzó el job de dub-preview"
    _, (vpath, desc), _ = caps[0]
    assert _job(jid).get("tipo") == "doblaje_traduccion"
    assert os.path.exists(vpath) and desc == "crema de veneno de abeja"
    # sin video y sin URL → error honesto
    assert client.post("/api/dub-preview", data={}).status_code == 400


@check("/api/dub-generar acepta guion editado + 2x1 y crea el job de voz (paso ②)")
def _c_dub_generar():
    caps: list = []
    with patched(appmod, "_run_dub_generar_job", _runner_fake(caps)):
        r = client.post("/api/dub-generar",
                        data={"prev_job_id": "prev123", "voz": "kate",
                              "textos": json.dumps(["Hola, mira esto", "Pídelo ya"]),
                              "oferta_2x1": "true", "oferta_texto": "Lleva dos"})
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
        jid = r.json()["job_id"]
        assert wait_for(lambda: caps), "no lanzó el job de dub-generar"
    _, (prev, voz, textos, oferta_2x1, oferta_texto, lang), _ = caps[0]
    assert _job(jid).get("tipo") == "doblaje_voz"
    assert prev == "prev123" and voz == "kate" and textos == ["Hola, mira esto", "Pídelo ya"]
    assert oferta_2x1 is True and oferta_texto == "Lleva dos" and lang == "es"
    # voz desconocida cae a juan_carlos (no rompe)
    caps.clear()
    with patched(appmod, "_run_dub_generar_job", _runner_fake(caps)):
        client.post("/api/dub-generar", data={"prev_job_id": "p2", "voz": "hacker"})
        assert wait_for(lambda: caps) and caps[0][1][1] == "juan_carlos"


@check("/api/reaplicar-hook re-quema el hook sobre la base _prehook y texto vacío lo quita")
def _c_reaplicar_hook():
    import pipeline.text_overlay as tov
    base = os.path.join(appmod.WORK_DIR, "smoke_reap", "v1_base.mp4")
    os.makedirs(os.path.dirname(base), exist_ok=True)
    with open(base, "wb") as f:
        f.write(b"\x00" * 1024)
    appmod.JOBS["smoke_reap"] = {
        "status": "done", "created": time.time(), "tipo": "cortar_clips",
        "result": {"ok": True, "versions": [
            {"name": "A", "path": base[:-4] + "_hk.mp4", "_prehook": base, "hook_text": "VIEJO"}]}}
    quemados: list = []

    def fake_burn(src, out, wd, texto, seconds=3.0, uid=""):
        quemados.append((src, texto))
        return out, True

    with patched(tov, "burn_hook_pill", fake_burn):
        r = client.post("/api/reaplicar-hook",
                        data={"job_id": "smoke_reap", "i": "0", "texto": "mira la solución"})
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    j = r.json()
    assert j["ok"] and j["hook_text"] == "MIRA LA SOLUCIÓN", f"{j}"
    assert quemados and quemados[0][0] == base, "no re-quemó sobre la base SIN hook (_prehook)"
    # texto vacío = quitar el hook → vuelve a la base
    r = client.post("/api/reaplicar-hook", data={"job_id": "smoke_reap", "i": "0", "texto": ""})
    assert r.json()["path"] == base and r.json()["hook_text"] == ""
    # job inexistente → 404 honesto
    assert client.post("/api/reaplicar-hook",
                       data={"job_id": "nope", "i": "0", "texto": "x"}).status_code == 404


@check("/api/landing-generate: gates honestos (precio/foto/key de Claude) y crea el job")
def _c_landing_generate():
    foto = ("fotos", ("real.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 512, "image/png"))
    # sin precio → 400
    r = client.post("/api/landing-generate", files=[foto],
                    data={"tipo": "landing", "producto": "rodillera"})
    assert r.status_code == 400 and "precio" in r.json()["detail"].lower(), f"{r.status_code} {r.text[:200]}"
    # sin foto → 400 (regla: el producto siempre con fotos reales)
    r = client.post("/api/landing-generate",
                    data={"tipo": "landing", "producto": "rodillera", "precio": "$79.900"})
    assert r.status_code == 400 and "foto" in r.json()["detail"].lower()
    # sin key de Claude → 400 honesto que dice QUÉ falta
    r = client.post("/api/landing-generate", files=[foto],
                    data={"tipo": "landing", "producto": "rodillera", "precio": "$79.900"})
    assert r.status_code == 400 and "claude" in r.json()["detail"].lower(), f"{r.text[:200]}"
    # con key (falsa, en el .env sandbox) + runner mockeado → crea el job
    with open(appmod.ENV_FILE, "w") as f:
        f.write("ANTHROPIC_API_KEY=sk-ant-smoke-fake\n")
    caps: list = []
    try:
        with patched(appmod, "_run_landing_job", _runner_fake(caps)):
            r = client.post("/api/landing-generate", files=[foto],
                            data={"tipo": "advertorial", "producto": "rodillera",
                                  "precio": "$79.900", "oferta": "2x1 + envío gratis"})
            assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
            jid = r.json()["job_id"]
            assert wait_for(lambda: caps), "no lanzó el job de landing"
    finally:
        os.remove(appmod.ENV_FILE)          # el sandbox vuelve a quedar sin keys
    _, (tipo, producto, link, precio, oferta, fotos), _ = caps[0]
    assert _job(jid).get("tipo") == "landing" and tipo == "advertorial"
    assert precio == "$79.900" and len(fotos) == 1 and os.path.exists(fotos[0])


@check("/api/landing-publicar: gate sin credenciales Shopify → NO publica y lo dice claro")
def _c_landing_publicar():
    appmod.JOBS["smoke_landing"] = {"status": "done", "created": time.time(), "tipo": "landing",
                                    "result": {"ok": True, "tipo": "landing", "producto": "x"}}
    r = client.post("/api/landing-publicar", data={"job_id": "smoke_landing"})
    assert r.status_code == 200, f"HTTP {r.status_code}"
    j = r.json()
    assert j.get("ok") is False and "shopify" in (j.get("error") or "").lower(), \
        f"sin credenciales debe negarse con error claro: {j}"
    # job inexistente → 404
    assert client.post("/api/landing-publicar", data={"job_id": "nope"}).status_code == 404


@check("/api/variar-imagen acepta la imagen ganadora + tipos y crea el job")
def _c_variar_imagen():
    caps: list = []
    with patched(appmod, "_run_variar_imagen_job", _runner_fake(caps)):
        r = client.post("/api/variar-imagen",
                        files=[("imagen", ("winner.png", b"\x89PNG" + b"\x00" * 256, "image/png"))],
                        data={"producto": "leggin cargo", "tipos": "estilo,fondo", "n": "4"})
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
        jid = r.json()["job_id"]
        assert wait_for(lambda: caps), "no lanzó el job de variar imagen"
    _, (src, out_dir, tipos, n, pro, producto), _ = caps[0]
    assert _job(jid).get("tipo") == "variar_imagen"
    assert os.path.exists(src) and tipos == ("estilo", "fondo") and n == 4 and producto == "leggin cargo"
    # sin imagen → rechazo honesto (400 del endpoint, o 422 de FastAPI por el File(...) requerido)
    assert client.post("/api/variar-imagen", data={"producto": "x"}).status_code in (400, 422)


@check("/api/radar/scan sin key → error honesto (cuota vs no-encontrado) y scan-status responde")
def _c_radar():
    with patched(radar_api, "_radar_key_ok", lambda: False):
        r = client.post("/api/radar/scan")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        j = r.json()
        assert j.get("ok") is False and "key" in (j.get("error") or "").lower(), \
            f"sin key debe decirlo claro, vino {j}"
    st = client.get("/api/radar/scan-status").json()
    assert st.get("status") in ("idle", "running", "done", "error"), f"{st}"


@check("/api/montador/status responde {up, instalado} sin colgarse (ping local bloqueado)")
def _c_montador():
    r = client.get("/api/montador/status")
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j.get("up"), bool) and isinstance(j.get("instalado"), bool), f"{j}"
    assert j["up"] is False   # la guardia bloquea el ping → debe degradar a False, no explotar


# ═════════════════════════ 5) UNIDADES PURAS CRÍTICAS ═════════════════════════

@check("video_ok: detecta inexistente y basura como False, y un mp4 real como True")
def _c_video_ok():
    from pipeline.ffmpeg_utils import video_ok
    assert video_ok("/no/existe.mp4") is False
    basura = os.path.join(TMP, "basura.mp4")
    with open(basura, "wb") as f:
        f.write(b"esto no es un mp4" * 10)
    assert video_ok(basura) is False, "un archivo basura no puede pasar como video entregable"
    fix = _fixture_mp4()   # Skip si no hay ffmpeg
    assert video_ok(fix, min_bytes=1000) is True, "un mp4 real y sano debe dar True"


@check("normalize_loudness deja el audio a -14 LUFS y devuelve un video válido")
def _c_normalize():
    from pipeline.ffmpeg_utils import normalize_loudness, video_ok
    fix = _fixture_mp4()   # Skip si no hay ffmpeg
    out = os.path.join(TMP, "norm.mp4")
    res = normalize_loudness(fix, out)
    assert res == out, f"con audio debía normalizar y devolver el out, devolvió {res!r}"
    assert video_ok(out, min_bytes=1000), "el video normalizado salió corrupto"


@check("_dub_2x1_line: 2x1 por defecto sin cifras, y respeta la oferta que escriba Jack")
def _c_dub_2x1():
    f = appmod._dub_2x1_line
    default = f("")
    assert "dos por uno" in default.lower() and default.endswith(".")
    assert not re.search(r"[\d$]", default), f"la frase por defecto no puede traer cifras: {default!r}"
    assert f("Lleva dos y paga uno") == "Lleva dos y paga uno."
    assert f("¿Lo quieres gratis?") == "¿Lo quieres gratis?"   # puntuación propia se respeta


@check("asignar_estructuras SIN IA (fallback): n=8 → 8 asignaciones con 8 estructuras DISTINTAS")
def _c_estructuras():
    from pipeline.estructuras_validadas import asignar_estructuras
    out = asignar_estructuras("repelente ultrasónico de plagas", n=8, gemini_key=None)
    assert len(out) == 8, f"pedí 8 y vinieron {len(out)}"
    ids = [a.get("estructura_id") for a in out]
    assert all(ids), f"asignaciones sin estructura_id: {out[:2]}"
    assert len(set(ids)) == 8, f"las 8 versiones deben salir con estructuras DISTINTAS: {ids}"
    assert all(a.get("avatar") for a in out), "cada asignación debe traer su avatar"


@check("landing_agent._limpiar_cifras: borra cifras INVENTADAS y respeta las EXACTAS de Jack")
def _c_limpiar_cifras():
    from pipeline.landing_agent import _limpiar_cifras
    texto = ("Antes $99.900, hoy solo $79.900 con 50% OFF. Es 100% natural. "
             "Ahorra $20.000 y llévalo con 2x1 + envío gratis.")
    avisos: list = []
    out = _limpiar_cifras(texto, ["$79.900", "2x1 + envío gratis"], avisos)
    assert "$79.900" in out, "borró el precio EXACTO de Jack (prohibido)"
    assert "2x1 + envío gratis" in out, "borró la oferta EXACTA de Jack"
    assert "100% natural" in out, "'100% natural' no es descuento, no se toca"
    assert "$99.900" not in out and "50% OFF" not in out and "$20.000" not in out, \
        f"dejó cifras inventadas: {out!r}"
    assert avisos, "debe avisar que borró cifras inventadas (honestidad)"
    # texto limpio → intacto y sin avisos
    avisos2: list = []
    assert _limpiar_cifras("Pagas al recibir.", ["$79.900"], avisos2) == "Pagas al recibir." \
        and not avisos2


@check("offer_banner.render_banner: con línea 2 vacía no crashea y rinde el PNG full-frame")
def _c_render_banner():
    from pipeline.offer_banner import render_banner
    img = render_banner(720, 1280, line2="")        # '' = solo 'ENVÍO GRATIS · PAGAS AL RECIBIR'
    assert img.size == (720, 1280) and img.mode == "RGBA"
    assert img.getbbox() is not None, "el banner salió totalmente vacío"
    img2 = render_banner(720, 1280, line2="OFERTA 2X1")
    assert img2.size == (720, 1280) and img2.getbbox() is not None


@check("hooks con IA caída: fallback GENÉRICOS seguros (todos distintos, sin cifras, en MAYÚSCULAS)")
def _c_hooks_fallback():
    from pipeline.hook_gen import generate_hook, generate_hooks_for_versions
    assert generate_hook(None) == "", "sin key debe devolver '' (el caller decide el fallback)"
    assert generate_hooks_for_versions(None, "x", [{"name": "A", "guion": ""}]) == [""]
    # el flujo completo: _agregar_hooks_por_version sin key → pone los genéricos rotando
    import pipeline.text_overlay as tov
    result = {"versions": [{"name": f"V{i}", "path": f"/smoke/v{i}.mp4"} for i in range(8)]}
    with patched(tov, "burn_hook_pill", lambda *a, **k: ("", False)):
        appmod._agregar_hooks_por_version(result, TMP, "repelente", lambda *a: None)
    hooks = [v.get("hook_text", "") for v in result["versions"]]
    assert all(hooks), f"quedó alguna versión sin hook: {hooks}"
    assert len(set(hooks)) == 8, f"los genéricos deben rotar (8 distintos): {hooks}"
    for h in hooks:
        assert h == h.upper() and not re.search(r"[\d$%]", h), \
            f"hook genérico inválido (cifras/minúsculas): {h!r}"


# ═════════════════════════ 6) FRONTEND: los bloques <script> pasan node --check ═════════════════════════

@check("frontend/index.html: 17+ bloques <script> y TODOS pasan node --check")
def _c_frontend_js():
    if not NODE:
        raise Skip("no hay node en esta máquina")
    html = open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8").read()
    bloques = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(bloques) >= 17, f"esperaba 17+ bloques <script>, hay {len(bloques)}"
    rotos = []
    for i, js in enumerate(bloques):
        p = os.path.join(TMP, f"bloque_{i}.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run([NODE, "--check", p], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            linea = html[:html.find(js)].count("\n") + 1
            rotos.append(f"bloque {i + 1} (línea ~{linea} del html): "
                         + (r.stderr or r.stdout).strip().splitlines()[-1][:160])
    assert not rotos, "JS roto en el frontend:\n  " + "\n  ".join(rotos)


# ═════════════════════════ runner ═════════════════════════

def main() -> int:
    print(f"\n🔥 SUITE DE HUMO Super-APP — offline, {len(_CHECKS)} checks "
          f"(guardia anti-red ACTIVA)\n" + "─" * 78)
    t0 = time.time()
    for nombre, fn in _CHECKS:
        try:
            fn()
        except Skip as s:
            _RESULTS["skip"] += 1
            print(f"⏭️  SKIP  {nombre}  ({s})")
            continue
        except Exception as e:  # noqa: BLE001 — un check roto NUNCA tumba la suite
            _RESULTS["fail"] += 1
            detalle = str(e) or traceback.format_exc(limit=3)
            _FALLAS.append(f"{nombre}\n      → {detalle}")
            print(f"❌ FALLA {nombre}\n      → {detalle}")
            continue
        _RESULTS["ok"] += 1
        print(f"✅ OK    {nombre}")

    total = _RESULTS["ok"] + _RESULTS["fail"]        # los skip no cuentan en el N/N
    print("─" * 78)
    print(f"Resumen: {_RESULTS['ok']}/{total} checks OK"
          + (f" · {_RESULTS['skip']} saltados" if _RESULTS["skip"] else "")
          + f" · {time.time() - t0:.1f}s")
    if _FALLAS:
        print(f"\n💥 {len(_FALLAS)} check(s) FALLARON — algo crítico se rompió:")
        for f in _FALLAS:
            print(f"   ❌ {f}")
    else:
        print("🟢 Todos los flujos críticos protegidos siguen vivos.")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if _FALLAS else 0


if __name__ == "__main__":
    sys.exit(main())
