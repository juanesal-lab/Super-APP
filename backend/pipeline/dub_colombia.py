"""Dubbing INTELIGENTE a español-Colombia, congruente con el creativo.

A diferencia de `dubbing.py` (ElevenLabs Dubbing = traducción literal a 8 idiomas),
este módulo:
  1. Entiende la NARRATIVA del video (reusa `narrative.py`): qué se dice, qué se ve
     y qué función cumple cada fase (HOOK/DOLOR/SOLUCIÓN/DESEO/CTA).
  2. Reescribe cada frase a **español colombiano natural** con el framework real de Juan
     (assets/guion-framework.md), adaptada a SU momento (hook potente, dolor emotivo,
     solución clara…) y congruente con lo que se ve. Vía Gemini. Policy-safe. 2x1 opcional.
  3. Genera la voz (ElevenLabs TTS, voz elegible) y la CALZA EXACTO a cada fase del video
     (estira/encoge con FFmpeg atempo) y la monta sobre el video → .mp4 doblado.

NO toca `dubbing.py`, `scripts.py`, `voiceover.py` ni `assemble.py`: solo importa/reusa.
Respeta la regla del proyecto: Gemini + ElevenLabs (no Anthropic). Degrada sin keys.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from typing import Callable

from .ffmpeg_utils import run, probe
from .narrative import analyze_narrative, mmss_to_seconds
from .scripts import CTA_OBLIGATORIO, _con_cta
from .voiceover import synthesize, synthesize_with_timestamps, VOICES

_MODEL = "gemini-2.5-flash"
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets")

# Ritmo hablado natural (más bajo = voz más calmada y menos "apretada"; deja aire para calzar)
_WORDS_PER_SEC = 2.2
# Límite de estiramiento del audio para no distorsionar la voz (atempo)
_TEMPO_MIN, _TEMPO_MAX = 0.85, 1.5


def _load_framework() -> str:
    """Carga el framework colombiano real de Juan (mismos assets que usa scripts.py)."""
    for name in ("guion-framework.md", "swipe-file-juan.md"):
        p = os.path.join(_ASSETS, name)
        if os.path.exists(p):
            try:
                return open(p, encoding="utf-8").read()
            except Exception:
                pass
    return ""


def _dur(path: str) -> float:
    """Duración en segundos de un archivo de audio o video (ffprobe)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", path],
            capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def _prompt(segments: list[dict], product_desc: str, oferta_2x1: bool) -> str:
    framework = _load_framework()[:12000]
    prod = product_desc.strip()
    oferta = (
        "🎁 OFERTA 2x1 (OBLIGATORIA, no opcional): el guion DEBE decir de forma natural y clara "
        "— idealmente justo antes del cierre — que al pedir uno/una se lleva otro/otra "
        "completamente GRATIS ('hoy están de 2x1: pides uno y te llegan dos'), con envío gratis "
        "y pago contra entrega. SIN precio ni cifras. Ajusta el género. Un guion que no mencione "
        "el 2x1 está MAL.\n"
        if oferta_2x1 else "")
    # Fases numeradas con su función, tiempo, largo objetivo, qué se ve y qué se dice
    fases = []
    for i, s in enumerate(segments):
        dur = max(0.5, mmss_to_seconds(s.get("fin")) - mmss_to_seconds(s.get("inicio")))
        objetivo = max(3, round(dur * _WORDS_PER_SEC))
        fases.append(
            f'#{i} [{s.get("etiqueta","")}] {s.get("inicio","")}-{s.get("fin","")} '
            f'(~{objetivo} palabras máx)\n'
            f'   se_ve: {s.get("que_se_ve","")}\n'
            f'   se_dice (original): {s.get("que_se_dice","")}')
    bloque = "\n".join(fases)
    return (
        "Eres copywriter senior y media buyer experto en ecommerce COD para el mercado "
        "COLOMBIANO. Vas a DOBLAR un anuncio a español colombiano natural, pero NO traduzcas "
        "literal: adapta cada frase a su FUNCIÓN narrativa y a lo que se ve en pantalla en ese "
        "momento, para que suene como un buen vendedor colombiano y frene el scroll.\n"
        + (f'Producto: "{prod}".\n' if prod else "")
        + "\nGUÍA DE VOZ Y FÓRMULAS (framework real de Juan, úsalo):\n" + framework +
        "\n\nREGLAS:\n"
        "- HOOK: potente, frena el scroll. DOLOR: emotivo, que se sienta. SOLUCIÓN: clara, "
        "presenta el producto. PRUEBA: evidencia concreta que da confianza (reseñas, "
        "demostración, 'llevo X semanas y…'), sin superlativos vacíos. DESEO/RESULTADO: "
        "aspiracional. CTA: cierre con urgencia (COD).\n"
        "- PROBLEM-AWARE FIRST (tráfico frío): nombra el DOLOR antes que el producto; no arranques "
        "vendiendo, arranca con el problema que el cliente reconoce.\n"
        "- Congruente con 'se_ve': habla del producto cuando el producto aparece, del problema "
        "cuando se ve el problema.\n"
        "- LARGO: el número de palabras es un MÁXIMO. Prefiere quedarte CORTO y natural que apretado "
        "(si te pasas, la voz suena acelerada). Frases cortas, HABLADAS (para decir en voz alta), sin "
        "comas largas ni enredos.\n"
        "- NO repitas la misma idea entre fases: cada fase aporta algo nuevo (no relleno).\n"
        "- Español colombiano natural, cercano, humano. Sin sonar caricaturesco.\n"
        "- POLICY-SAFE (Meta/TikTok): NADA de claims médicos/de salud, NADA de claims absolutos, "
        "NADA de groserías, NUNCA menciones precios.\n"
        f"- CTA OBLIGATORIO: la ÚLTIMA fase debe TERMINAR con esta frase EXACTA, palabra por palabra, "
        f"sin cambiar nada: \"{CTA_OBLIGATORIO}\".\n"
        + oferta +
        "\nTe paso las fases del anuncio:\n" + bloque +
        "\n\nDevuelve SOLO un JSON válido (array), un objeto por fase EN EL MISMO ORDEN, así:\n"
        '[{"i":0,"es_colombia":"la línea doblada, colombiana y natural",'
        '"por_que":"por qué esta versión cuadra con la fase y con lo que se ve"}, ...]'
    )


def _parse_array(text: str) -> list[dict] | None:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def adaptar_guion(
    video_path: str | None = None, *,
    blueprint: dict | None = None,
    api_key: str | None = None,
    product_desc: str = "",
    oferta_2x1: bool = False,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Paso 1-2 (barato, sin ElevenLabs): narrativa → guion doblado colombiano por fase.

    Devuelve {"ok":True,"duration":s,"segments":[{etiqueta,inicio,fin,que_se_ve,
    original,es_colombia,por_que}]}  o  {"ok":False,"error":...}.
    """
    def report(m, p):
        if progress:
            progress(m, p)

    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {"ok": False, "error": "Falta la API key de Gemini."}

    # 1) Narrativa: usa el blueprint dado o analiza el video (reusa narrative.py)
    if blueprint and blueprint.get("ok") and blueprint.get("segments"):
        narr = blueprint
    elif video_path:
        report("Analizando la narrativa del video...", 15)
        narr = analyze_narrative(video_path, api_key=api_key,
                                 product_desc=product_desc, progress=progress)
        if not narr.get("ok"):
            return {"ok": False, "error": "No se pudo analizar el video: " + narr.get("error", "")}
    else:
        return {"ok": False, "error": "Pasa un video_path o un blueprint."}

    segs = narr["segments"]

    # 2) Reescritura colombiana por fase (una llamada a Gemini)
    report("Adaptando el guion a español colombiano...", 60)
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=_MODEL, contents=[_prompt(segs, product_desc, oferta_2x1)])
        data = _parse_array(resp.text or "")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Error adaptando el guion: {e}"}
    if not data:
        return {"ok": False, "error": "Gemini no devolvió un JSON válido."}

    by_idx = {int(d["i"]): d for d in data if isinstance(d, dict) and "i" in d}
    out_segs = []
    for i, s in enumerate(segs):
        d = by_idx.get(i, {})
        out_segs.append({
            "etiqueta": s.get("etiqueta", ""),
            "inicio": s.get("inicio", ""), "fin": s.get("fin", ""),
            "que_se_ve": s.get("que_se_ve", ""),
            "original": s.get("que_se_dice", ""),
            "es_colombia": str(d.get("es_colombia", "")).strip(),
            "por_que": str(d.get("por_que", "")).strip(),
        })
    # Red de seguridad: si el modelo no puso el CTA exacto en ninguna fase, lo añadimos a la última.
    joined = " ".join(s["es_colombia"] for s in out_segs).lower()
    if CTA_OBLIGATORIO.lower() not in joined:
        for seg in reversed(out_segs):
            if seg["es_colombia"]:
                seg["es_colombia"] = _con_cta(seg["es_colombia"])
                break

    report("Guion colombiano listo", 100)
    return {"ok": True, "duration": narr.get("duration", 0), "segments": out_segs}


def _fit_audio(inp: str, target: float, out: str) -> tuple[float, float]:
    """Estira/encoge el audio para acercarlo a `target` segundos (atempo, sin distorsionar).

    Solo acelera si la voz es más larga que la fase (hasta 1.5x). Si es más corta, la deja
    natural. Devuelve (duración_final, tempo) — el tempo sirve para reescalar los tiempos por palabra.
    """
    a = _dur(inp)
    if a <= 0 or target <= 0:
        return a, 1.0
    ratio = a / target
    tempo = min(_TEMPO_MAX, max(_TEMPO_MIN, ratio)) if ratio > 1.0 else 1.0
    if abs(tempo - 1.0) < 0.02:
        run(["ffmpeg", "-y", "-i", inp, "-c", "copy", out])
        return _dur(out), 1.0
    run(["ffmpeg", "-y", "-i", inp, "-filter:a", f"atempo={tempo:.4f}", out])
    return _dur(out), tempo


def generar_dub(
    video_path: str, *,
    api_key: str | None = None,
    eleven_key: str | None = None,
    product_desc: str = "",
    voz: str = "juan_carlos",
    oferta_2x1: bool = False,
    generar_video: bool = True,
    work_dir: str | None = None,
    blueprint: dict | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Dub colombiano COMPLETO: guion + voz elegible + calce exacto a cada fase + video doblado.

    Devuelve {"ok":True,"voz":..,"segments":[..],"audio":ruta_mp3,"video":ruta_mp4|None}.
    Si falta la key de ElevenLabs, devuelve solo el guion (segments) sin audio.
    """
    def report(m, p):
        if progress:
            progress(m, p)

    eleven_key = eleven_key or os.environ.get("ELEVENLABS_API_KEY")
    work_dir = work_dir or tempfile.mkdtemp(prefix="dubco_")
    os.makedirs(work_dir, exist_ok=True)

    # 1-2) Guion colombiano por fase
    g = adaptar_guion(video_path, blueprint=blueprint, api_key=api_key,
                      product_desc=product_desc, oferta_2x1=oferta_2x1, progress=progress)
    if not g.get("ok"):
        return g
    segments = g["segments"]

    if not eleven_key:
        return {"ok": True, "voz": voz, "segments": segments, "audio": None, "video": None,
                "aviso": "Sin ELEVENLABS_API_KEY: devuelvo solo el guion (sin audio)."}
    if voz not in VOICES:
        voz = "juan_carlos"

    # 3) TTS por fase + calce exacto a la duración de la fase
    # OPTIMIZACIÓN: generar las voces EN PARALELO (antes era 1 x 1 = el cuello de botella).
    # Cada fase es independiente -> ThreadPoolExecutor. ~N veces más rápido.
    from concurrent.futures import ThreadPoolExecutor
    total = len(segments)
    report(f"Generando {total} voces colombianas en paralelo...", 62)

    def _voz(i_s):
        i, s = i_s
        texto = s["es_colombia"].strip()
        if not texto:
            return None
        ini = mmss_to_seconds(s["inicio"])
        dur = max(0.5, mmss_to_seconds(s["fin"]) - ini)
        raw = os.path.join(work_dir, f"voz_{i:02d}.mp3")
        fit = os.path.join(work_dir, f"voz_{i:02d}_fit.mp3")
        try:
            # Con timestamps: capturamos el tiempo de CADA palabra (para subtítulos sincronizados)
            words = synthesize_with_timestamps(eleven_key, texto, voz, raw)
            dfin, tempo = _fit_audio(raw, dur, fit)
            # Tiempos RELATIVOS al inicio de la frase (se anclan después, en secuencia)
            palabras = []
            for w in (words or []):
                st, en = w.get("start"), w.get("end")
                if st is None or en is None:
                    continue
                palabras.append({"word": w.get("word", ""), "start": st / tempo, "end": en / tempo})
            return (fit, ini, dfin, palabras)
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=min(6, max(1, total))) as ex:
        res = [r for r in ex.map(_voz, list(enumerate(segments))) if r]

    if not res:
        return {"ok": False, "error": "No se pudo generar ninguna voz (revisa la key de ElevenLabs)."}

    # 4) SECUENCIAL: las frases van SEGUIDAS (con una pausa natural corta), sin silencios largos
    #    entre ellas. Cada frase arranca donde terminó la anterior + PAUSA -> doblaje fluido.
    PAUSA = 0.16
    clips: list[tuple[str, float]] = []      # (ruta_fit, posición en segundos)
    word_timings: list[dict] = []
    pos = min(res[0][1], 0.5)                 # arranca cerca del inicio (no arrancar tarde)
    for (fit, _ini, dfin, rel) in res:
        clips.append((fit, pos))
        for w in rel:
            word_timings.append({"word": w["word"], "start": pos + w["start"], "end": pos + w["end"]})
        pos += dfin + PAUSA
    word_timings.sort(key=lambda w: w["start"])

    # 4b) Montar la pista completa: cada frase en su posición SECUENCIAL
    vid_dur = probe(video_path).duration if video_path else 0.0
    inputs, fc, labels = [], [], []
    for k, (path, ini) in enumerate(clips):
        inputs += ["-i", path]
        ms = int(ini * 1000)
        fc.append(f"[{k}:a]adelay={ms}|{ms}[a{k}]")
        labels.append(f"[a{k}]")
    if len(labels) == 1:
        # una sola fase: amix no aplica (necesita >=2). Solo colocar y rellenar.
        mix = f"{labels[0]}apad[a]"
    else:
        mix = "".join(labels) + f"amix=inputs={len(labels)}:normalize=0,apad[a]"
    audio_out = os.path.join(work_dir, "dub_colombia.mp3")
    report("Uniendo la voz con el tiempo del video...", 92)
    dur_arg = ["-t", f"{vid_dur:.3f}"] if vid_dur > 0 else []
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc) + ";" + mix,
         "-map", "[a]", *dur_arg, audio_out])

    video_out = None
    if generar_video and video_path:
        report("Montando la voz sobre el video...", 97)
        video_out = os.path.join(work_dir, "video_doblado.mp4")
        run(["ffmpeg", "-y", "-i", video_path, "-i", audio_out,
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
             "-t", f"{vid_dur:.3f}", "-movflags", "+faststart", video_out])

    report("Dub colombiano listo", 100)
    return {"ok": True, "voz": voz, "segments": segments, "audio": audio_out, "video": video_out,
            "word_timings": word_timings}


# --- CLI de prueba: python -m backend.pipeline.dub_colombia <video> [descripcion] ---
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m backend.pipeline.dub_colombia <video.mp4> [descripcion] "
              "[--solo-guion] [--2x1] [--voz kate|juan_carlos]")
        raise SystemExit(1)

    video = sys.argv[1]
    desc = ""
    solo_guion = "--solo-guion" in sys.argv
    oferta = "--2x1" in sys.argv
    voz = "juan_carlos"
    for a in sys.argv[2:]:
        if a == "--voz":
            pass
        elif not a.startswith("--") and not desc:
            desc = a
    if "--voz" in sys.argv:
        vi = sys.argv.index("--voz")
        if vi + 1 < len(sys.argv):
            voz = sys.argv[vi + 1]

    def _p(m, p):
        print(f"[{p:3d}%] {m}", file=sys.stderr)

    if solo_guion:
        res = adaptar_guion(video, product_desc=desc, oferta_2x1=oferta, progress=_p)
    else:
        res = generar_dub(video, product_desc=desc, voz=voz, oferta_2x1=oferta, progress=_p)
    print(json.dumps(res, ensure_ascii=False, indent=2))
