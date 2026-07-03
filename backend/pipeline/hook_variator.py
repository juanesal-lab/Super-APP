"""🔁 VARIAR EL HOOK DEL WINNER — capa de VIDEO sobre el cerebro de Juan (creative_variator).

De UN creativo GANADOR salen N videos (default 4) que CONSERVAN el cuerpo validado y cambian
SOLO el HOOK (los primeros ~3s que enganchan). Por cada variación:
  1. creative_variator.generar_variaciones (Claude) da el hook nuevo + el brief de qué toma buscar.
  2. tiktok_search.buscar_tiktok encuentra la toma con ese brief (gratis, sin IA; excluye Colombia).
  3. downloader / CDN de tikwm la baja.
  4. voiceover narra el hook con la voz colombiana y caption_styles lo quema palabra x palabra.
  5. assemble (venc GPU) empalma hook nuevo + cuerpo y punch_pace le da el ritmo final.
Si no hay toma buena para una variación, se REUSA el hook original LIMPIO (text_translate
modo="tapar" cubre el texto quemado viejo) con el hook nuevo encima — nunca se queda sin video.
El texto del CUERPO en otro idioma se traduce (fondo del bloque + Poppins) y el español se deja
(text_translate modo="solo_otro").

REGLAS DE ORO: nunca precio (los hooks con cifras/$/% se descartan), búsquedas sin Colombia
(region != "CO"). El CTA vive en el cuerpo del ganador, que no se toca.
"""
from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import requests

from .analyze import Segment
from .assemble import _normalized_clip, add_voiceover, concat_clips, punch_pace
from .caption_styles import burn_word_captions
from .creative_variator import generar_variaciones
from .downloader import download_urls
from .ffmpeg_utils import probe
from .narrative import analyze_narrative, mmss_to_seconds
from .text_translate import traducir_texto_pantalla
from .tiktok_search import _ES_REGIONS, buscar_tiktok
from .voiceover import synthesize_with_timestamps

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_MAX_ESCENA_MB = 30
_HOOK_MIN, _HOOK_MAX = 2.0, 7.0      # duración sana del hook (la manda la voz en off)
_HOOK_DEFAULT = 3.0                  # si no se pudo leer la narrativa

# Regla de oro: NUNCA precio. Ofertas sin cifra ("2x1", "envío gratis") SÍ pasan; claims de
# beneficio tipo "100% algodón" también (el % solo bloquea si huele a DESCUENTO).
_PRECIO = re.compile(
    r"[$€]|\bprecio\b"
    r"|\d[\d.,]*\s*(?:cop|usd|pesos|mil)\b"            # 49.900 pesos / 20 mil / 30 usd
    r"|\b(?:cop|usd)\s*\d"                             # COP 49900 / USD 30
    r"|\b(?:pesos|d[oó]lares?|euros?)\b"               # "cuarenta mil pesos" (precio en letras)
    r"|\d+\s*%\s*(?:de\s+)?(?:descuento|dcto|off|rebaja|menos)"
    r"|(?:descuento|dcto|rebaja)s?\s*(?:del?\s*)?\d+\s*%",
    re.IGNORECASE)


def _sin_precio(texto: str) -> bool:
    return not _PRECIO.search(texto or "")


def _arco_de_blueprint(bp: dict | None) -> str:
    """Convierte los tramos de analyze_narrative en el arco_texto que espera el variator de Juan."""
    if not bp or not bp.get("segments"):
        return ""
    lineas = []
    for s in bp["segments"]:
        dice, ve = s.get("que_se_dice", ""), s.get("que_se_ve", "")
        lineas.append(f"[{s.get('etiqueta', '?')} {s.get('inicio', '')}-{s.get('fin', '')}] "
                      f"dice: \"{dice}\" | se ve: {ve}")
    return "\n".join(lineas)


def _fin_del_hook(bp: dict | None, dur: float) -> float:
    """Segundo donde TERMINA el hook original: el primer tramo HOOK del blueprint (con tope),
    o ~3s si no hay narrativa. Nunca más de la mitad del video."""
    fin = _HOOK_DEFAULT
    try:
        segs = (bp or {}).get("segments") or []
        if segs and segs[0].get("etiqueta") == "HOOK":
            fin = mmss_to_seconds(segs[0].get("fin", _HOOK_DEFAULT))
    except Exception:  # noqa: BLE001
        fin = _HOOK_DEFAULT
    return max(1.5, min(fin, _HOOK_MAX, dur * 0.5))


def _buscar_escena(brief: str, hook: str, usadas: set[str], lock: threading.Lock,
                   n_cands: int = 8) -> list[dict]:
    """Candidatos de TikTok para el brief (sin IA, gratis). Excluye Colombia (regla de oro),
    duraciones raras y escenas ya usadas por otra variación. Los mejores primero."""
    query = (brief or "").strip() or " ".join((hook or "").split()[:5])
    cands = buscar_tiktok(query, count=30, pages=1)
    if not cands and brief:                       # el brief no dio nada → intenta con el hook
        cands = buscar_tiktok(" ".join(hook.split()[:5]), count=30, pages=1)
    out = []
    with lock:
        vistos = set(usadas)
    for c in cands:
        if c.get("region") == "CO" or c["url"] in vistos:
            continue
        if not (3 <= c.get("dur", 0) <= 90):
            continue
        out.append(c)
    out.sort(key=lambda c: (1 if c.get("region") in _ES_REGIONS else 0, c.get("plays", 0)),
             reverse=True)
    return out[:n_cands]


def _ventana_limpia(path: str, sdur: float, need: float) -> tuple[float, int]:
    """Elige el tramo de la toma con MENOS texto quemado (EAST local, $0): los memes/captions de
    TikTok entran y salen — casi siempre hay una ventana limpia. Devuelve (t0, cajas_de_texto);
    cajas=-1 si no hay modelo EAST (desconocido). Empates → lo más cerca de ~1/4 (salta intros)."""
    t0_def = max(0.0, min(sdur * 0.25, sdur - need))
    try:
        import cv2
        from . import text_detect as TD
        if not TD.available():
            return t0_def, -1
        net = TD._load()
        span = max(0.0, sdur - need)
        cands = [i * span / 5 for i in range(6)] if span > 1.0 else [t0_def]
        cap = cv2.VideoCapture(path)
        mejor, mejor_n = t0_def, 10 ** 9
        try:
            for t0 in cands:
                n = 0
                for f in (0.15, 0.5, 0.85):
                    cap.set(cv2.CAP_PROP_POS_MSEC, (t0 + need * f) * 1000.0)
                    ok, fr = cap.read()
                    if ok and fr is not None:
                        n += len(TD._detect(net, fr))
                if n < mejor_n or (n == mejor_n and abs(t0 - t0_def) < abs(mejor - t0_def)):
                    mejor, mejor_n = t0, n
        finally:
            cap.release()
        return mejor, mejor_n
    except Exception:  # noqa: BLE001
        return t0_def, -1


def _bajar_escena(cand: dict, out_base: str) -> str | None:
    """Baja la toma: primero el mp4 directo de tikwm (rápido), si no yt-dlp. None si falla."""
    play = cand.get("play") or ""
    if play:
        try:
            out = out_base + ".mp4"
            with requests.get(play, headers=_UA, timeout=45, stream=True,
                              allow_redirects=True) as r:   # tikwm→CDN SIEMPRE redirige
                r.raise_for_status()
                total = 0
                with open(out, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        total += len(chunk)
                        if total > _MAX_ESCENA_MB * (1 << 20):
                            raise ValueError("escena demasiado pesada")
                        f.write(chunk)
            if probe(out).duration >= 1.0:
                return out
        except Exception:  # noqa: BLE001
            pass
    try:
        res = download_urls([cand["url"]], os.path.dirname(out_base))
        if res and res[0].get("ok") and probe(res[0]["path"]).duration >= 1.0:
            return res[0]["path"]
    except Exception:  # noqa: BLE001
        pass
    return None


def variar_hook(
    winner_path: str,
    *,
    product_desc: str = "",
    n: int = 4,
    voz: str = "juan_carlos",
    caption_style: str = "hormozi",
    traducir_cuerpo: bool = True,
    evitar: list[str] | None = None,
    gemini_key: str | None = None,
    eleven_key: str | None = None,
    anthropic_key: str | None = None,
    work_dir: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Genera n videos variando SOLO el hook del ganador (cuerpo intacto).

    Devuelve {"ok", "videos":[{path, hook, angulo, copy_pantalla, brief, fuente_url,
    fuente_titulo, origen}], "pasos":[...], "resumen"}. `evitar`: hooks ya vistos que no
    gustaron (se le pasan al cerebro de Juan para que dé otros). Nunca lanza.
    """
    pasos: list[dict] = []

    def report(m, p):
        if progress:
            progress(m, p)

    def paso(nombre, ok, det=""):
        pasos.append({"paso": nombre, "ok": bool(ok), "detalle": det})

    gemini_key = gemini_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    eleven_key = eleven_key or os.environ.get("ELEVENLABS_API_KEY")
    anthropic_key = anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
    if not os.path.exists(winner_path):
        return {"ok": False, "error": "No encuentro el video ganador.", "pasos": pasos}
    if not anthropic_key:
        return {"ok": False, "error": "Falta la API key de Anthropic (pestaña 🔑 Claves) — es el cerebro que inventa los hooks.", "pasos": pasos}
    if not eleven_key:
        return {"ok": False, "error": "Falta la API key de ElevenLabs (pestaña 🔑 Claves) — narra el hook con la voz colombiana.", "pasos": pasos}

    work_dir = work_dir or os.path.splitext(winner_path)[0] + "_varhook"
    os.makedirs(work_dir, exist_ok=True)
    n = max(1, min(int(n), 6))

    try:
        info = probe(winner_path)
        dur = info.duration
        dims = (info.width - info.width % 2, info.height - info.height % 2)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"No pude leer el video: {e}", "pasos": pasos}

    # 1) Narrativa del ganador (dónde termina el hook + arco para el cerebro de Juan)
    report("📖 Leyendo la narrativa del ganador...", 6)
    bp = None
    if gemini_key:
        try:
            r = analyze_narrative(winner_path, api_key=gemini_key, product_desc=product_desc)
            bp = r if r.get("ok") else None
        except Exception:  # noqa: BLE001
            bp = None
    hook_fin = _fin_del_hook(bp, dur)
    arco = _arco_de_blueprint(bp)
    paso("Narrativa", bool(bp), f"hook original 0-{hook_fin:.1f}s" + ("" if bp else " (sin Gemini: ~3s)"))

    # 2) Variaciones de hook (cerebro de Juan). Pide 2 extra por si alguna trae precio o falla.
    report("🧠 Inventando hooks nuevos (Claude)...", 14)
    variaciones = generar_variaciones(arco or f"(sin transcripción; video de {dur:.0f}s)",
                                      product_desc, anthropic_key,
                                      n=n + 2, con_escenas=True, evitar=evitar or [])
    variaciones = [v for v in variaciones if (v.get("hook") or "").strip()
                   and _sin_precio(v.get("hook", "")) and _sin_precio(v.get("copy_pantalla", ""))]
    if not variaciones:
        return {"ok": False, "error": "El cerebro no devolvió variaciones (¿key de Anthropic ok?).",
                "pasos": pasos}
    variaciones = variaciones[:n]
    paso("Hooks nuevos", True, f"{len(variaciones)} hooks (sin precio ✓)")

    # 3) Cuerpo del ganador (una sola vez, compartido): corte normalizado + texto extranjero traducido
    report("✂️ Separando el cuerpo del ganador...", 22)
    body = os.path.join(work_dir, "cuerpo.mp4")
    try:
        _normalized_clip(Segment(video=winner_path, source_index=0, start=hook_fin,
                                 end=dur, score=0.0), body, dims)
        paso("Cuerpo", True, f"{hook_fin:.1f}s → {dur:.1f}s")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"No pude cortar el cuerpo: {e}", "pasos": pasos}
    if traducir_cuerpo and gemini_key:
        report("🔤 Traduciendo el texto del cuerpo (si hay en otro idioma)...", 30)
        try:
            t = traducir_texto_pantalla(body, api_key=gemini_key,
                                        out_path=os.path.join(work_dir, "cuerpo_es.mp4"),
                                        modo="solo_otro")
            if t.get("ok"):
                body = t["video"]
                paso("Texto del cuerpo", True,
                     f"{len(t.get('bloques', []))} bloque(s); el español se deja igual")
            else:
                paso("Texto del cuerpo", False, t.get("error", ""))
        except Exception as e:  # noqa: BLE001
            paso("Texto del cuerpo", False, str(e))

    # Hook original normalizado (plan B si a una variación no le sirve ninguna toma de TikTok)
    hook_orig = os.path.join(work_dir, "hook_original.mp4")
    try:
        _normalized_clip(Segment(video=winner_path, source_index=0, start=0.0,
                                 end=hook_fin, score=0.0), hook_orig, dims)
    except Exception:  # noqa: BLE001
        hook_orig = None
    hook_orig_limpio: dict = {"path": None}      # se limpia UNA vez, solo si hace falta
    limpieza_lock = threading.Lock()

    usadas: set[str] = set()
    usadas_lock = threading.Lock()
    listos = {"n": 0}

    def _hook_original_limpio() -> str | None:
        """Tapar el texto quemado del hook original (1 sola vez, compartido entre variaciones)."""
        with limpieza_lock:
            if hook_orig_limpio["path"]:
                return hook_orig_limpio["path"]
            if not hook_orig:
                return None
            src = hook_orig
            if gemini_key:
                try:
                    t = traducir_texto_pantalla(src, api_key=gemini_key,
                                                out_path=os.path.join(work_dir, "hook_orig_limpio.mp4"),
                                                modo="tapar")
                    if t.get("ok"):
                        src = t["video"]
                        paso("Hook original", True, "texto viejo tapado (plan B listo)")
                    else:
                        paso("Hook original", False,
                             f"no se pudo tapar el texto viejo: {t.get('error', '')} — va sin limpiar")
                except Exception as e:  # noqa: BLE001
                    paso("Hook original", False, f"no se pudo tapar el texto viejo: {e} — va sin limpiar")
            else:
                paso("Hook original", False, "sin key de Gemini: el texto viejo del hook queda sin tapar")
            hook_orig_limpio["path"] = src
            return src

    def _armar(i: int, var: dict) -> dict:
        hook_txt = var["hook"].strip()
        brief = ""
        for e in var.get("escenas") or []:
            if str(e.get("fase", "")).strip().upper().startswith("HOOK"):
                brief = e.get("buscar", "").strip()
                break
        vdir = os.path.join(work_dir, f"v{i+1}")
        os.makedirs(vdir, exist_ok=True)
        out: dict = {"hook": hook_txt, "angulo": var.get("angulo", ""),
                     "copy_pantalla": var.get("copy_pantalla", ""), "brief": brief,
                     "fuente_url": "", "fuente_titulo": "", "origen": "", "ok": False}

        # a) Voz en off del hook (ElevenLabs, cortica = barata). Su duración manda.
        try:
            vo = os.path.join(vdir, "hook_vo.mp3")
            words = synthesize_with_timestamps(eleven_key, hook_txt, voz, vo)
        except Exception as e:  # noqa: BLE001
            out["error"] = f"voz: {e}"
            return out
        try:
            vo_dur = probe(vo).duration
        except Exception:  # noqa: BLE001
            vo_dur = max((w.get("end", 0) for w in words), default=_HOOK_DEFAULT)
        need = max(_HOOK_MIN, min(_HOOK_MAX, vo_dur + 0.25))

        # b) Toma nueva de TikTok con el brief de Juan (sin Colombia; sin repetir entre variaciones).
        #    Las tomas casi siempre traen SU texto quemado (memes/captions) que pelearía con
        #    nuestro hook → EAST local ($0) busca la ventana SIN texto; se prueban hasta 3
        #    descargas y gana la primera limpia (si ninguna, la de menos texto).
        escena = None                        # la mejor: (path, cand, t0, n_texto)
        descargas = 0
        for cand in _buscar_escena(brief, hook_txt, usadas, usadas_lock):
            if descargas >= 3:
                break
            with usadas_lock:
                if cand["url"] in usadas:
                    continue
                usadas.add(cand["url"])
            p = _bajar_escena(cand, os.path.join(vdir, f"escena_{descargas}"))
            if not p:
                with usadas_lock:  # descarga fallida → se libera para las otras variaciones
                    usadas.discard(cand["url"])
                continue
            descargas += 1
            try:
                sdur = probe(p).duration
                t0, n_texto = _ventana_limpia(p, sdur, need)
            except Exception:  # noqa: BLE001
                continue
            if escena is None or n_texto < escena[3]:
                escena = (p, cand, t0, n_texto)
            if n_texto == 0:                 # ventana limpia → no hay que buscar más
                break

        # c) Clip del hook: la toma nueva; si falla al procesarse → hook original LIMPIO (plan B)
        clip = None
        if escena:
            try:
                path, cand, t0, n_texto = escena
                sdur = probe(path).duration
                clip = os.path.join(vdir, "hook_clip.mp4")
                _normalized_clip(Segment(video=path, source_index=0, start=t0,
                                         end=min(sdur, t0 + need), score=0.0), clip, dims)
                out.update(fuente_url=cand["url"], fuente_titulo=cand.get("title", ""),
                           origen="toma nueva de TikTok"
                           + (" (ventana sin texto)" if n_texto == 0 else ""))
                # Si NI la mejor ventana quedó limpia (o EAST no está) → tapar con Gemini (clip
                # cortico = llamada barata). Con ventana limpia no se gasta nada.
                if gemini_key and n_texto != 0:
                    try:
                        t = traducir_texto_pantalla(clip, api_key=gemini_key,
                                                    out_path=os.path.join(vdir, "hook_clip_limpio.mp4"),
                                                    modo="tapar")
                        if t.get("ok") and t.get("bloques"):
                            clip = t["video"]
                            out["origen"] = "toma nueva de TikTok (texto original tapado)"
                    except Exception:  # noqa: BLE001
                        pass          # con texto de la toma es feo pero no fatal
            except Exception as e:  # noqa: BLE001
                paso(f"Toma para «{hook_txt[:36]}»", False,
                     f"la descarga no sirvió ({e}) — uso el hook original")
                clip = None
        if clip is None:
            base = _hook_original_limpio()
            if not base:
                out["error"] = "sin toma de TikTok y no pude preparar el hook original"
                return out
            clip = base
            out["origen"] = "hook original limpio (no hubo toma nueva)"
            out.update(fuente_url="", fuente_titulo="")

        # d) Voz encima (el video se corta/loopea a la duración de la voz) + texto palabra x palabra
        try:
            con_voz = add_voiceover(clip, vo, os.path.join(vdir, "hook_voz.mp4"))
        except Exception as e:  # noqa: BLE001
            out["error"] = f"voz sobre el clip: {e}"
            return out
        try:
            con_subs = burn_word_captions(con_voz, words, vdir,
                                          os.path.join(vdir, "hook_subs.mp4"),
                                          style=caption_style)
        except Exception as e:  # noqa: BLE001
            con_subs = con_voz
            paso(f"Texto de «{hook_txt[:36]}»", False, f"no se pudo quemar ({e}) — va solo con voz")

        # e) Hook nuevo + cuerpo del ganador, y pacing final
        try:
            final = concat_clips([con_subs, body], os.path.join(vdir, f"variacion_{i+1}.mp4"), vdir)
            final = punch_pace(final, os.path.join(vdir, f"variacion_{i+1}_pace.mp4"))
        except Exception as e:  # noqa: BLE001
            out["error"] = f"ensamble: {e}"
            return out
        out.update(path=final, ok=True)
        with usadas_lock:
            listos["n"] += 1
            k = listos["n"]
        report(f"🎬 Variación {k}/{len(variaciones)} lista: «{hook_txt[:48]}»",
               35 + int(60 * k / len(variaciones)))
        return out

    report("🎬 Armando las variaciones (toma + voz + texto + ensamble)...", 35)
    resultados: list[dict | None] = [None] * len(variaciones)
    with ThreadPoolExecutor(max_workers=2) as ex:      # 2: el encoder GPU serializa sesiones
        futs = {ex.submit(_armar, i, v): i for i, v in enumerate(variaciones)}
        for f in as_completed(futs):
            i = futs[f]
            try:
                resultados[i] = f.result()
            except Exception as e:  # noqa: BLE001
                resultados[i] = {"ok": False, "error": str(e),
                                 "hook": variaciones[i].get("hook", "")}

    videos = [r for r in resultados if r and r.get("ok")]
    fallidas = [r for r in resultados if r and not r.get("ok")]
    for r in fallidas:
        paso(f"Variación «{(r.get('hook') or '')[:40]}»", False, r.get("error", ""))
    con_toma = sum(1 for v in videos if v["origen"].startswith("toma"))
    paso("Variaciones", bool(videos),
         f"{len(videos)}/{len(variaciones)} listas ({con_toma} con toma nueva de TikTok)")

    report("✅ Hooks variados", 100)
    if not videos:
        return {"ok": False, "error": "Ninguna variación se pudo armar. " +
                (fallidas[0].get("error", "") if fallidas else ""), "pasos": pasos}
    return {"ok": True, "videos": videos, "pasos": pasos,
            "hook_fin": round(hook_fin, 2),
            "resumen": f"{len(videos)} video(s) con hook nuevo · cuerpo del ganador intacto"}


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("Uso: python -m backend.pipeline.hook_variator <ganador.mp4> [--desc 'producto'] "
              "[--n 4] [--voz juan_carlos] [--estilo hormozi]")
        raise SystemExit(1)
    args = sys.argv[2:]

    def _arg(flag, default):
        return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else default

    def _p(m, p):
        print(f"[{p:3d}%] {m}", file=sys.stderr)

    r = variar_hook(sys.argv[1], product_desc=_arg("--desc", ""), n=int(_arg("--n", 4)),
                    voz=_arg("--voz", "juan_carlos"), caption_style=_arg("--estilo", "hormozi"),
                    progress=_p)
    r.pop("videos_raw", None)
    print(json.dumps(r, ensure_ascii=False, indent=2))
