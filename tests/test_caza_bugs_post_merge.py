# -*- coding: utf-8 -*-
"""Tests OFFLINE (cero red, cero APIs de pago) que reproducen los bugs cazados en el código
reciente de Super-APP. Se corren ANTES del fix (deben FALLAR) y DESPUÉS (deben pasar).

Uso:  ./venv/bin/python tests/test_caza_bugs_post_merge.py   (desde la raíz del repo)
"""
import os
import sys
import tempfile
import threading
import traceback

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # raíz del repo
sys.path.insert(0, os.path.join(WT, "backend"))

import app  # noqa: E402  (el backend FastAPI; importa pipeline y radar_api)
import radar_api  # noqa: E402
import pipeline.creative_search as cs  # noqa: E402
import pipeline.tiktok_search as tks  # noqa: E402
import pipeline.text_overlay as to  # noqa: E402
import pipeline.ffmpeg_utils as fu  # noqa: E402

FALLOS = []


def check(nombre, cond, detalle=""):
    if cond:
        print(f"  ✅ {nombre}")
    else:
        print(f"  ❌ {nombre} — {detalle}")
        FALLOS.append(nombre)


def _touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


# ══════════════════ BUG 1: /api/reaplicar-hook pierde la normalización -14 LUFS ══════════════════
# Orden real del post-proceso: música → banner → end_card → HOOKS (guarda v[_prehook]) →
# _normalizar_audio. El _prehook queda guardado ANTES del -14 LUFS → al re-aplicar (o quitar)
# el hook, el video final vuelve SIN volumen parejo.
def test_reaplicar_hook_normaliza():
    print("BUG 1 · reaplicar-hook debe re-normalizar el audio (-14 LUFS)")
    wd = tempfile.mkdtemp(prefix="t1_")
    base = _touch(os.path.join(wd, "vA_ec.mp4"))          # base pre-hook, pre-normalización
    con_hook = _touch(os.path.join(wd, "vA_ec_hk_ln.mp4"))  # lo que quedó tras hooks+loudness
    app.JOBS["t1job"] = {"result": {"versions": [
        {"name": "A", "path": con_hook, "_prehook": base, "hook_text": "VIEJO"}]}}

    llam = {"burn": 0, "norm": []}
    orig_burn, orig_norm = to.burn_hook_pill, fu.normalize_loudness

    def fake_burn(video_path, out_path, work_dir, text, seconds=3.0, uid=""):
        llam["burn"] += 1
        return _touch(out_path, b"hook"), True

    def fake_norm(p, out, target_lufs=-14.0):
        llam["norm"].append(p)
        return _touch(out, b"norm")

    to.burn_hook_pill, fu.normalize_loudness = fake_burn, fake_norm
    try:
        r = app.reaplicar_hook(job_id="t1job", i=0, texto="NUEVO HOOK")
        check("re-aplicar con texto pasa por normalize_loudness", bool(llam["norm"]),
              f"norm llamado {len(llam['norm'])} veces (el video final queda sin -14 LUFS)")
        check("el path devuelto es el normalizado", llam["norm"] and r["path"].endswith("_ln.mp4"),
              f"path={r['path']}")
        llam["norm"] = []
        r2 = app.reaplicar_hook(job_id="t1job", i=0, texto="")   # quitar hook → vuelve a la base
        check("quitar el hook también re-normaliza la base", bool(llam["norm"]),
              f"path={r2['path']} (base pre-normalización entregada tal cual)")
    finally:
        to.burn_hook_pill, fu.normalize_loudness = orig_burn, orig_norm
        app.JOBS.pop("t1job", None)


# ══════════════════ BUG 2: path_45 (cut Meta) desincronizado de los post-pasos ══════════════════
# _run_job aplica música/banner/end_card/hooks SOLO sobre v["path"]; v["path_45"] se generó
# adentro de process_job y queda SIN esos pasos (Jack aprueba el 9:16 con banner y el 4:5 sale pelado).
def test_path_45_sincronizado():
    print("BUG 2 · path_45 debe re-generarse si el path principal recibió post-pasos")
    wd = tempfile.mkdtemp(prefix="t2_")
    p_main = _touch(os.path.join(wd, "vA.mp4"))
    p45 = _touch(os.path.join(wd, "vA_45.mp4"))
    manifest = {"ok": True, "versions": [
        {"name": "A_gancho", "path": p_main, "path_45": p45, "cut_times": [], "sfx_events": None}]}

    orig_pj, orig_ban, orig_norm = app.process_job, app._agregar_banner_oferta, app._normalizar_audio
    orig_crop = getattr(app, "_crop_45", None)

    def fake_pj(*a, **k):
        return manifest

    def fake_banner(versions, work_dir, progress, start=0.0, dur=0.0, line2=""):
        for v in versions:   # simula el re-encode del banner (nuevo archivo)
            v["path"] = _touch(v["path"][:-4] + "_of.mp4", b"banner")

    app.process_job = fake_pj
    app._agregar_banner_oferta = fake_banner
    app._normalizar_audio = lambda versions, wd_, progress: None
    if orig_crop is not None:   # tras el fix: el crop real se stubbea (sin ffmpeg)
        app._crop_45 = lambda src, dst: bool(_touch(dst, b"crop45"))
    try:
        app.JOBS["t2job"] = {"status": "running", "progress": 0, "message": "", "result": None}
        settings = {"target_seconds": 15.0, "max_clip_seconds": 2.5, "use_gemini": False,
                    "product_desc": "x", "aspect": "9:16", "hook_text": "", "hook_pos": "arriba",
                    "auto_hook": False, "page_url": "", "enhance": False, "musica": False,
                    "banner_oferta": True, "destino": "meta"}
        app._run_job("t2job", [p_main], settings)
        v = app.JOBS["t2job"]["result"]["versions"][0]
        check("path principal recibió el banner", v["path"].endswith("_of.mp4"), f"path={v['path']}")
        check("path_45 se re-generó desde el master FINAL (no quedó el viejo sin banner)",
              v.get("path_45") != p45 and v.get("path_45", "").endswith("_45.mp4")
              and os.path.exists(v.get("path_45", "")),
              f"path_45={v.get('path_45')} (sigue siendo el cut previo a los post-pasos)")
    finally:
        app.process_job, app._agregar_banner_oferta, app._normalizar_audio = orig_pj, orig_ban, orig_norm
        if orig_crop is not None:
            app._crop_45 = orig_crop
        app.JOBS.pop("t2job", None)


# ══════════════ BUG 3: el contexto global _TK_FAST contamina flujos concurrentes ══════════════
# Mientras corre una búsqueda rápida (job TikTok en 2do plano, ~1 min), CUALQUIER otro flujo que
# entre a tiktok_search cae en modo rápido ajeno: buscar_broll devuelve [] (el botón 🎭 B-roll
# queda mudo) y el juez profundo del /api/tiktok-search clásico se saltea.
def test_tk_fast_sin_contaminacion():
    print("BUG 3 · una búsqueda rápida NO debe apagar el b-roll ni el juez profundo de otros flujos")
    foto = _touch(os.path.join(tempfile.mkdtemp(prefix="t3_"), "ref.jpg"), b"\xff\xd8\xffjpg")
    info = {"keywords": "rodillera", "variants": ["rodillera", "knee brace"], "desc": "rodillera negra"}
    cands = [{"id": str(i), "url": f"https://www.tiktok.com/@u/video/{i}", "title": f"rodillera {i}",
              "cover": f"http://c/{i}.jpg", "play": f"http://v/{i}.mp4", "plays": 100 - i,
              "likes": 5, "region": "MX", "dur": 30} for i in range(6)]

    llam = {"deep": 0, "broll": 0}
    gate, dentro = threading.Event(), threading.Event()

    def fake_cover(cand, rb, rd, key):
        dentro.set()
        gate.wait(timeout=10)   # congela la búsqueda rápida para simular la concurrencia real
        return {"match": True, "confianza": "alta", "muestra": True, "es": True, "overlay": 2}

    def fake_deep(cand, rb, rd, key):
        llam["deep"] += 1
        return {"match": True, "confianza": "alta", "muestra": True, "es": True, "overlay": 2}

    def fake_broll(*a, **k):
        llam["broll"] += 1
        return [{"url": "b1"}]

    orig = {}

    def _patch(name, fn):
        """Parchea el punto REAL que usa el flujo SIN desmontar el diseño vigente: en el código
        pre-fix (monkeypatch de creative_search) se parchea el _orig_* que llaman los wrappers,
        dejando los wrappers instalados; en el post-fix (sin wrappers) se parchea tiktok_search."""
        k = "_orig_" + name.lstrip("_")
        if hasattr(cs, k):
            orig[("cs", k)] = getattr(cs, k)
            setattr(cs, k, fn)
        else:
            orig[("tks", name)] = getattr(tks, name)
            setattr(tks, name, fn)

    orig[("tks", "buscar_tiktok")] = tks.buscar_tiktok
    orig[("tks", "_foreplay_candidatos")] = tks._foreplay_candidatos
    tks.buscar_tiktok = lambda q, count=40, pages=2: [dict(c) for c in cands]
    tks._foreplay_candidatos = lambda *a, **k: []
    _patch("_verificar", fake_cover)
    _patch("_verificar_video", fake_deep)
    _patch("buscar_broll", fake_broll)

    kwargs = dict(image_path=foto, nombre="rodillera", api_key="FAKE", count=4,
                  anthropic_key=None, analisis=info, image_paths=[foto],
                  rellenar_n=True, explorar_cuentas=False)
    res = []
    th = threading.Thread(target=lambda: res.append(cs._tiktok_rapido(dict(kwargs), 0)), daemon=True)
    try:
        th.start()
        dentro.wait(timeout=10)
        # ── concurrente: otro flujo pide B-ROLL mientras la búsqueda rápida sigue corriendo ──
        broll = tks.buscar_broll("rodillera negra", "rodillera", "FAKE", n=5)
        check("buscar_broll concurrente devuelve resultados (no [] por el modo rápido ajeno)",
              bool(broll), "devolvió [] — el botón 🎭 B-roll queda mudo mientras corre el job TikTok")
        gate.set()
        th.join(timeout=30)
        r = res[0] if res else {}
        check("la búsqueda rápida confirma por portada (links > 0)", bool(r.get("links")),
              f"links={len(r.get('links') or [])}")
        check("la búsqueda rápida con deep=0 NO bajó ningún video", llam["deep"] == 0,
              f"deep llamado {llam['deep']} veces")
        check("la búsqueda rápida NO gastó b-roll interno", llam["broll"] == 1,
              f"broll llamado {llam['broll']} veces (1 = solo el concurrente)")
        # ── y el flujo CLÁSICO (sin modo rápido) conserva el juez profundo + b-roll ──
        llam["deep"] = llam["broll"] = 0
        gate.set()
        r2 = tks.buscar(**kwargs)
        check("el flujo clásico SÍ verifica por contenido (deep > 0)", llam["deep"] > 0,
              f"deep={llam['deep']}")
        check("el flujo clásico SÍ trae b-roll", llam["broll"] == 1, f"broll={llam['broll']}")
        check("el flujo clásico confirma links", bool(r2.get("links")), "0 links")
    finally:
        gate.set()
        for (mod, name), fn in orig.items():
            setattr(cs if mod == "cs" else tks, name, fn)


# ══════════════════ BUG 4: /api/busy no ve el escaneo del Radar ══════════════════
# El auto-update (run.sh) consulta /api/busy antes de reiniciar; el escaneo del Radar (2-5 min,
# ~69 créditos de ScrapeCreators) vive en radar_api._SCAN con subprocesos hijos → un reinicio a
# mitad de escaneo lo mata y quema los créditos.
def test_busy_ve_radar():
    print("BUG 4 · /api/busy debe reportar busy mientras el Radar escanea")
    jobs_previos = dict(app.JOBS)
    app.JOBS.clear()
    st_previo = dict(radar_api._SCAN)
    try:
        radar_api._SCAN.update(status="running", message="Escaneando la Meta Ad Library...")
        r = app.busy()
        check("busy=True con el Radar escaneando", r.get("busy") is True,
              f"respuesta={r} (el auto-update reiniciaría a mitad del escaneo)")
        radar_api._SCAN.update(status="idle", message="")
        r2 = app.busy()
        check("busy=False con el Radar quieto y sin jobs", r2.get("busy") is False, f"respuesta={r2}")
    finally:
        radar_api._SCAN.clear()
        radar_api._SCAN.update(st_previo)
        app.JOBS.update(jobs_previos)


# ═══════════ BUG 5: la voz elegida no llega al estado de "🔄 Regenerar versión" ═══════════
# _run_render_job guarda {"voz": s.get("voz")} pero `s` son los settings de /api/scripts, que NUNCA
# traen "voz" (la voz elegida viaja en voice_key). _stash_regen filtra None → regenerar "otro guion"
# siempre narra con juan_carlos aunque Jack haya elegido kate.
def test_regen_conserva_voz():
    print("BUG 5 · el estado de regeneración debe guardar la voz ELEGIDA (voice_key)")
    wd = tempfile.mkdtemp(prefix="t5_")
    manifest = {"ok": True, "versions": [{"name": "A_gancho", "path": _touch(os.path.join(wd, "a.mp4")),
                                          "n_clips": 1, "segments": []}],
                "_regen": {"versions": {}, "settings": {}}}
    orig_rv, orig_syn, orig_norm = app.render_versions, app.synthesize, app._normalizar_audio
    import pipeline.voiceover as vo
    orig_acel = vo.acelerar
    try:
        app.render_versions = lambda *a, **k: manifest
        app.synthesize = lambda key, txt, v, out: _touch(out, b"mp3")
        vo.acelerar = lambda mp3, words, factor=1.12: words
        app._normalizar_audio = lambda versions, wd_, progress: None
        app.JOBS["t5job"] = {
            "status": "running", "progress": 0, "message": "", "result": None,
            "work_dir": wd, "selected": [], "has_audio_by_src": {}, "used_gemini": False,
            "n_sources": 1,
            "settings": {"target_seconds": 15.0, "max_clip_seconds": 2.5, "product_desc": "x",
                         "aspect": "9:16", "enhance": False, "hook_text": "", "hook_pos": "arriba",
                         "auto_hook": False, "page_url": "", "captions": False, "use_music": False}}
        app._run_render_job("t5job", ["guion de prueba"], "kate", None, None, 1, 0)
        estado = app.JOBS["t5job"].get("_regen") or {}
        check("estado de regen guarda voz='kate' (la elegida)",
              (estado.get("settings") or {}).get("voz") == "kate",
              f"settings.voz={(estado.get('settings') or {}).get('voz')!r} → regen narraría con juan_carlos")
    finally:
        app.render_versions, app.synthesize, app._normalizar_audio = orig_rv, orig_syn, orig_norm
        vo.acelerar = orig_acel
        app.JOBS.pop("t5job", None)


if __name__ == "__main__":
    for t in (test_reaplicar_hook_normaliza, test_path_45_sincronizado,
              test_tk_fast_sin_contaminacion, test_busy_ve_radar, test_regen_conserva_voz):
        try:
            t()
        except Exception:
            print(f"  💥 {t.__name__} reventó:")
            traceback.print_exc()
            FALLOS.append(t.__name__ + " (excepción)")
        print()
    if FALLOS:
        print(f"RESULTADO: {len(FALLOS)} fallo(s): {FALLOS}")
        sys.exit(1)
    print("RESULTADO: todos los tests pasan ✅")
