"""VARIAR EL HOOK del winner — capa de VIDEO sobre creative_variator (creative scaling).

De UN creativo GANADOR saca N videos nuevos. Dos modos:
  - "hook":  cambia SOLO el gancho (0-3s): toma elegida SIN texto (ventana limpia vía EAST, $0),
             voz nueva CO de ElevenLabs + subtítulos palabra x palabra; el CUERPO queda INTACTO.
             Plan B si no hay ventana limpia: el hook original con su texto TAPADO (EAST blur).
  - "tomas": además del hook, REEMPLAZA la toma de CADA fase (video ~100% nuevo): por cada
             escena del brief [{fase, buscar}] busca la toma en TikTok ($0, sin IA), le saca su
             ventana limpia, la normaliza, narra el guion COMPLETO (voz CO) y ensambla en orden
             con concat + punch. Plan B por fase: metraje del propio winner.

El CEREBRO es creative_variator.generar_variaciones (no se toca — solo se consume).
REGLAS: tomas con region != "CO" SIEMPRE; el guion cierra contraentrega sin precio (lo garantiza
el cerebro); EAST y buscar_tiktok son GRATIS — las IAs de pago son narrativa (1 Gemini),
variaciones (1 Claude) y voz (1 ElevenLabs por variación).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Callable

import cv2
import requests

from . import text_detect as td
from .analyze import Segment
from .assemble import concat_clips, punch_pace, add_voiceover, _normalized_clip, venc, FPS
from .caption_styles import burn_word_captions
from .creative_variator import generar_variaciones
from .ffmpeg_utils import run, probe
from .narrative import analyze_narrative, mmss_to_seconds
from .tiktok_search import buscar_tiktok
from .voiceover import synthesize_with_timestamps

# Regla de oro: NUNCA precio. Ofertas sin cifra ("2x1", "envío gratis") SÍ pasan; claims tipo
# "100% algodón" también (el % solo bloquea si huele a DESCUENTO). Red de seguridad dura por si
# el cerebro (creative_variator) se le escapa una cifra.
_PRECIO = re.compile(
    r"[$€]|\bprecio\b"
    r"|\d[\d.,]*\s*(?:cop|usd|pesos|mil)\b"            # 49.900 pesos / 20 mil / 30 usd
    r"|\b(?:cop|usd)\s*\d"                             # COP 49900 / USD 30
    r"|\b(?:pesos|d[oó]lares?|euros?)\b"               # "cuarenta mil pesos" (en letras)
    r"|\d+\s*%\s*(?:de\s+)?(?:descuento|dcto|off|rebaja|menos)"
    r"|(?:descuento|dcto|rebaja)s?\s*(?:del?\s*)?\d+\s*%",
    re.IGNORECASE)


def _sin_precio(texto: str) -> bool:
    return not _PRECIO.search(texto or "")


_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_MAX_TOMA_MB = 25          # tope de descarga por toma (igual que la verificación profunda)
_MIN_FASE_S = 1.5          # ninguna fase queda más corta que esto
_HOOK_FALLBACK_S = 3.0     # si la narrativa no marca el HOOK, se asume 0-3s


# ---------------------------------------------------------------- ventana limpia (EAST, $0)

def ventana_limpia(video_path: str, dur: float, *, desde: float = 0.0, step_s: float = 0.5,
                   max_scan_s: float = 60.0) -> tuple[float, float] | None:
    """Busca una ventana de `dur` segundos SIN texto quemado (EAST) desde `desde`. Devuelve
    (inicio, fin) o None. Muestrea 1 frame cada `step_s`; racha limpia >= dur gana. $0 (local)."""
    if dur <= 0 or not td.available() and not td.ensure_model():
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    total = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / (cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total = min(total or max_scan_s, max_scan_s)
    if desde >= total - dur:                     # no alcanza desde ahí → busca desde el inicio
        desde = 0.0
    net = td._load()
    limpio_desde, mejor = None, None
    t = max(0.0, desde)
    try:
        while t < total:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            boxes = td._detect(net, frame)
            if not boxes:
                if limpio_desde is None:
                    limpio_desde = t
                if t + step_s - limpio_desde >= dur:
                    mejor = (limpio_desde, limpio_desde + dur)
                    break
            else:
                limpio_desde = None
            t += step_s
    except Exception:  # noqa: BLE001 — si EAST falla a mitad, que decida el plan B (no abortar)
        mejor = None
    finally:
        cap.release()
    return mejor


# ---------------------------------------------------------------- helpers

def _dur_media(path: str) -> float:
    info = probe(path)
    return float(info.duration or 0.0)


def _dur_av(path: str) -> float:
    """Duración por formato — sirve para AUDIO y video (probe() exige stream de video)."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
        return float((out.stdout or "").strip() or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _hook_fin(blueprint: dict | None) -> float:
    """Fin del primer tramo HOOK según la narrativa (clamp 1.5-6s; fallback 3s)."""
    try:
        for s in (blueprint or {}).get("segments") or []:
            if (s.get("etiqueta") or "").upper().startswith("HOOK"):
                fin = mmss_to_seconds(s.get("fin", "00:03"))
                return max(1.5, min(6.0, float(fin)))
    except Exception:  # noqa: BLE001
        pass
    return _HOOK_FALLBACK_S


def _arco_de(blueprint: dict | None) -> str:
    """El arco del winner como texto (transcripción etiquetada) para el cerebro."""
    filas = []
    for s in (blueprint or {}).get("segments") or []:
        que = (s.get("que_se_dice") or "").strip()
        if que:
            filas.append(f"[{s.get('etiqueta', '?')}] {que}")
    return "\n".join(filas)


def _descargar_toma(cand: dict, out_path: str) -> bool:
    """Baja el mp4 directo de un candidato de TikTok (sigue redirects: tikwm→CDN siempre redirige)."""
    url = cand.get("play") or ""
    if not url:
        return False
    try:
        with requests.get(url, headers=_UA, timeout=40, stream=True, allow_redirects=True) as r:
            if r.status_code != 200:
                return False
            tam = 0
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    tam += len(chunk)
                    if tam > _MAX_TOMA_MB * (1 << 20):
                        return False
                    f.write(chunk)
        return _dur_media(out_path) >= 1.0
    except Exception:  # noqa: BLE001
        return False


def _buscar_toma(buscar: str, out_path: str, usadas: set[str]) -> str | None:
    """Busca la toma en TikTok ($0, sin IA) y baja el mejor candidato NO usado y NO colombiano."""
    cands = [c for c in buscar_tiktok(buscar, count=15, pages=1)
             if c.get("region") != "CO" and 4 <= c.get("dur", 0) <= 90
             and c.get("url") not in usadas]
    cands.sort(key=lambda c: -(c.get("plays") or 0))
    for c in cands[:4]:
        if _descargar_toma(c, out_path):
            usadas.add(c.get("url", ""))
            return out_path
    return None


def _cortar(src: str, a: float, b: float, out: str, dims: tuple[int, int]) -> str:
    """Corta [a,b] normalizado a dims con audio garantizado (para concat sin sorpresas)."""
    seg = Segment(video=src, source_index=0, start=a, end=b, score=50.0)
    return _normalized_clip(seg, out, dims)


def _voz(eleven_key: str, texto: str, voz: str, out_mp3: str) -> tuple[str, list[dict]]:
    words = synthesize_with_timestamps(eleven_key, texto, voz, out_mp3)
    return out_mp3, words


# ---------------------------------------------------------------- armado por variación

def _armar_hook(winner: str, var: dict, hook_fin: float, wd: str, *,
                voz: str, eleven_key: str, pasos: list) -> str | None:
    """Modo 'hook': hook nuevo (ventana limpia o tapado) + voz CO + subs; CUERPO INTACTO."""
    dims_info = probe(winner)
    dims = (dims_info.width or 1080, dims_info.height or 1920)

    mp3, words = _voz(eleven_key, var["hook"], voz, os.path.join(wd, "hook_vo.mp3"))
    vo_dur = max((w.get("end") or 0.0) for w in words) if words else _dur_av(mp3)
    vo_dur = max(1.2, vo_dur + 0.15)

    # Toma para el hook: 1º ventana limpia DESPUÉS del hook original (que no se repita metraje
    # con el cuerpo). Plan B: el hook original con su texto TAPADO (EAST blur).
    win = ventana_limpia(winner, vo_dur, desde=hook_fin)
    if win and win[0] < hook_fin:                          # el fallback interno rebuscó desde 0:
        win = None                                         # se solaparía con el cuerpo → plan B
    base = os.path.join(wd, "hook_base.mp4")
    if win:
        _cortar(winner, win[0], win[1], base, dims)
        pasos.append({"paso": "Toma del hook", "ok": True,
                      "detalle": f"ventana limpia {win[0]:.1f}-{win[1]:.1f}s (EAST)"})
    else:
        crudo = os.path.join(wd, "hook_crudo.mp4")
        _cortar(winner, 0.0, max(vo_dur, hook_fin), crudo, dims)
        try:
            base = td.mask_video(crudo, base)              # OJO: devuelve in_path si no tapó nada
            tapado = base != crudo
            pasos.append({"paso": "Toma del hook", "ok": True,
                          "detalle": "plan B: hook original con texto tapado" if tapado
                                     else "plan B: hook original (EAST no vio texto que tapar)"})
        except Exception as e:  # noqa: BLE001
            base = crudo
            pasos.append({"paso": "Toma del hook", "ok": False, "detalle": f"sin tapar: {e}"})

    con_voz = os.path.join(wd, "hook_voz.mp4")
    add_voiceover(base, mp3, con_voz)                      # dura EXACTO lo que la voz
    con_subs = burn_word_captions(con_voz, words, wd, os.path.join(wd, "hook_subs.mp4"))
    hook_listo = os.path.join(wd, "hook_48k.mp4")          # audio a 48k = mismos parámetros que el
    run(["ffmpeg", "-y", "-i", con_subs, "-c:v", "copy",   # cuerpo (el concat exige streams iguales)
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", hook_listo])

    cuerpo = os.path.join(wd, "cuerpo.mp4")                # intacto: mismo metraje y su audio
    total = _dur_media(winner)
    if total - hook_fin < 0.5:
        pasos.append({"paso": "Cuerpo", "ok": False, "detalle": "winner sin cuerpo tras el hook"})
        return hook_listo
    run(["ffmpeg", "-y", "-ss", f"{hook_fin:.3f}", "-i", winner,
         "-vf", f"scale={dims[0]}:{dims[1]}:force_original_aspect_ratio=increase,"
                f"crop={dims[0]}:{dims[1]},setsar=1,fps={FPS}",
         *venc(), "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", cuerpo])
    return concat_clips([hook_listo, cuerpo], os.path.join(wd, "final.mp4"), wd)


def _armar_tomas(winner: str, var: dict, wd: str, *, voz: str, eleven_key: str,
                 usadas: set[str], pasos: list,
                 progress: Callable[[str], None] | None = None) -> str | None:
    """Modo 'tomas': narra el guion completo y reemplaza la toma de CADA fase (buscada en TikTok)."""
    dims = (1080, 1920)                                    # las tomas de TikTok son 9:16
    mp3, words = _voz(eleven_key, var["guion"], voz, os.path.join(wd, "guion_vo.mp3"))
    vo_dur = max((w.get("end") or 0.0) for w in words) if words else _dur_av(mp3)
    escenas = [e for e in (var.get("escenas") or []) if (e.get("buscar") or "").strip()]
    if not escenas:
        pasos.append({"paso": "Escenas", "ok": False, "detalle": "el cerebro no dio brief de escenas"})
        return None

    dur_fase = max(_MIN_FASE_S, vo_dur / len(escenas))
    clips = []
    for i, esc in enumerate(escenas):
        if progress:
            progress(f"🎬 Toma {i + 1}/{len(escenas)}: {esc.get('fase', '?')}")
        toma = _buscar_toma(esc["buscar"], os.path.join(wd, f"toma_{i:02d}_raw.mp4"), usadas)
        origen, desde = "TikTok", 0.0
        if not toma:                                       # plan B: metraje del propio winner,
            toma, origen = winner, "winner (plan B)"       # arrancando en un punto DISTINTO por
            desde = i * dur_fase                           # fase (que no se repita la misma toma)
        toma_dur = _dur_media(toma)
        win = ventana_limpia(toma, dur_fase, desde=desde)
        a = win[0] if win else min(desde, max(0.0, toma_dur - dur_fase))
        b = a + min(dur_fase, max(1.0, toma_dur - a))
        clip = _cortar(toma, a, b, os.path.join(wd, f"toma_{i:02d}.mp4"), dims)
        detalle = f"{origen}, ventana limpia {a:.1f}s"
        if not win:                                        # sin ventana limpia → texto TAPADO (EAST)
            try:
                clip = td.mask_video(clip, os.path.join(wd, f"toma_{i:02d}_tapada.mp4"))
                detalle = f"{origen}, sin ventana limpia → texto tapado"
            except Exception as e:  # noqa: BLE001
                detalle = f"{origen}, sin tapar: {e}"
        clips.append(clip)
        pasos.append({"paso": f"Fase {esc.get('fase', i)}", "ok": True, "detalle": detalle})

    montaje = concat_clips(clips, os.path.join(wd, "montaje.mp4"), wd)
    con_voz = os.path.join(wd, "voz.mp4")
    add_voiceover(montaje, mp3, con_voz)
    con_subs = burn_word_captions(con_voz, words, wd, os.path.join(wd, "subs.mp4"))
    return punch_pace(con_subs, os.path.join(wd, "final.mp4"))


# ---------------------------------------------------------------- API principal

def variar_hook(winner_path: str, product_desc: str, *,
                n: int = 4, modo: str = "hook", voz: str = "juan_carlos",
                page_text: str = "", evitar: list[str] | None = None,
                gemini_key: str | None = None, eleven_key: str | None = None,
                anthropic_key: str | None = None,
                variaciones: list[dict] | None = None, hook_fin: float | None = None,
                work_dir: str | None = None,
                progress: Callable[[str, int], None] | None = None) -> dict:
    """1 ganador → N videos con hook nuevo (modo 'hook') o hook + tomas nuevas (modo 'tomas').

    `variaciones`: si vienen pre-generadas (🎲 otro hook / tests) NO se llama al cerebro; con
    `hook_fin` dado tampoco se re-analiza la narrativa (los devuelve el primer run en el result).
    Devuelve {"ok", "modo", "arco", "hook_fin", "variaciones":[{hook, angulo, guion,
    copy_pantalla, video, pasos}]}."""
    gemini_key = gemini_key or os.environ.get("GEMINI_API_KEY")
    eleven_key = eleven_key or os.environ.get("ELEVENLABS_API_KEY")
    anthropic_key = anthropic_key or os.environ.get("ANTHROPIC_API_KEY")

    def report(m, p):
        if progress:
            progress(m, p)

    if not os.path.exists(winner_path):
        return {"ok": False, "error": "No encuentro el video ganador."}
    if not eleven_key:
        return {"ok": False, "error": "Falta la API key de ElevenLabs (ponla en 🔑 Claves)."}
    modo = "tomas" if str(modo).strip().lower() in ("tomas", "hook+tomas", "hook_tomas") else "hook"
    work_dir = work_dir or os.path.join(os.path.dirname(winner_path), "varhook")
    os.makedirs(work_dir, exist_ok=True)

    blueprint = None
    necesita_narrativa = variaciones is None or (modo == "hook" and hook_fin is None)
    if necesita_narrativa:
        report("📖 Leyendo el arco del ganador (narrativa)...", 5)
        try:
            bp = analyze_narrative(winner_path, api_key=gemini_key, product_desc=product_desc)
            blueprint = bp if bp.get("ok") else None
        except Exception:  # noqa: BLE001
            blueprint = None
    if hook_fin is None:
        hook_fin = _hook_fin(blueprint)
    arco = _arco_de(blueprint) or product_desc

    if variaciones is None:
        if not anthropic_key:
            return {"ok": False, "error": "Falta la API key de Anthropic (ponla en 🔑 Claves)."}
        report(f"🧠 Generando {n} variaciones ({'hook + tomas' if modo == 'tomas' else 'solo hook'})...", 12)
        variaciones = generar_variaciones(arco, product_desc, anthropic_key,
                                          page_text=page_text, n=n + 2,
                                          con_escenas=(modo == "tomas"), evitar=evitar)
    # REGLA DE ORO: nunca precio — filtro duro sobre hooks/copys (por eso se piden 2 de más)
    variaciones = [v for v in (variaciones or [])
                   if _sin_precio(v.get("hook", "")) and _sin_precio(v.get("copy_pantalla", ""))][:n]
    if not variaciones:
        return {"ok": False, "error": "El cerebro no entregó variaciones (revisa la key de Anthropic)."}

    salida, usadas = [], set()
    for i, var in enumerate(variaciones):
        pasos: list[dict] = []
        pct = 15 + int(80 * i / max(1, len(variaciones)))
        report(f"🎬 Variación {i + 1}/{len(variaciones)}: “{var.get('hook', '')[:40]}...”", pct)
        wd = os.path.join(work_dir, f"var_{i:02d}")
        os.makedirs(wd, exist_ok=True)
        video = None
        try:
            if modo == "tomas":
                video = _armar_tomas(winner_path, var, wd, voz=voz, eleven_key=eleven_key,
                                     usadas=usadas, pasos=pasos,
                                     progress=(lambda m: report(m, pct)) if progress else None)
            else:
                video = _armar_hook(winner_path, var, hook_fin, wd,
                                    voz=voz, eleven_key=eleven_key, pasos=pasos)
        except Exception as e:  # noqa: BLE001
            pasos.append({"paso": "Armado", "ok": False, "detalle": str(e)})
        # ── QA CREATIVOS por variación (portero, CLAUDE.md §7): 9:16 + zonas seguras + visual ──
        qa = None
        if video:
            try:
                from .qa_creativos import qa_video
                qa = qa_video(video, gemini_key=gemini_key, work_dir=wd)
                pasos.append({"paso": "QA creativos", "ok": qa["aprobado"],
                              "detalle": qa["resolucion"] + (" · " + "; ".join(qa["motivos"])
                                                             if qa["motivos"] else " · OK")})
            except Exception as e:  # noqa: BLE001
                pasos.append({"paso": "QA creativos", "ok": True, "detalle": f"QA no corrió: {e}"})
        salida.append({"hook": var.get("hook", ""), "angulo": var.get("angulo", ""),
                       "guion": var.get("guion", ""), "copy_pantalla": var.get("copy_pantalla", ""),
                       "escenas": var.get("escenas") or [], "video": video, "pasos": pasos,
                       "qa": qa, "qa_rechazado": bool(qa) and not qa.get("aprobado", True)})

    # solo cuentan como OK las variaciones con video Y que el QA no rechazó
    ok_n = sum(1 for v in salida if v["video"] and not v.get("qa_rechazado"))
    report("✅ Variaciones listas", 100)
    return {"ok": ok_n > 0, "modo": modo, "arco": arco, "hook_fin": hook_fin,
            "variaciones": salida, "resumen": f"{ok_n}/{len(salida)} videos OK"}
