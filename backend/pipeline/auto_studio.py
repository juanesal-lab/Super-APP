"""MODO AUTOMÁTICO — un solo botón: creativo ganador (cualquier idioma) → creativo terminado.

Encadena TODO el gusanito sobre UN video, sin que el usuario active cada cosa:
  1. 📖 Narrativa (narrative.py) → blueprint que guía el resto
  2. 🇨🇴 Doblaje colombiano (dub_colombia.py)
  3. 🔤 Traducir texto en pantalla (text_translate.py)
  4. 🎵 Música por fase + 💥 SFX en los cambios de fase (phase_effects + voiceover.music + FFmpeg)
  5. 💬 Subtítulos por fase (del guion doblado)
  6. 📱 Verticalizar 9:16
  7. 🔊 Normalizar audio (loudnorm)
  8. 🧭 Supervisor opcional (supervisor.py) revisa pasos clave
  → SALIDA: el creativo listo para subir.

Diseño: cada paso está AISLADO (try/except). Si uno falla, NO tumba la cadena: se conserva
el video del paso anterior y se reporta cuál falló. Reusa todos los módulos existentes (de
Juan y míos) SIN editarlos. Gemini + ElevenLabs + FFmpeg (Anthropic solo opcional, capitán).

Nota: "cortar clips / reordenar escenas" son para material CRUDO (varios clips sueltos); sobre
un GANADOR ya editado no aplican (lo dañarían), así que en modo automático se omiten a propósito.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Callable

from PIL import Image, ImageDraw

from .ffmpeg_utils import run, probe
from .narrative import analyze_narrative, mmss_to_seconds
from .dub_colombia import generar_dub
from .text_translate import traducir_texto_pantalla, _font
from .phase_effects import phase_effect_plan
from . import voiceover

_SFX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets", "sfx")


def _dur(path: str) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nk=1:nw=1", path], capture_output=True,
                             text=True, timeout=30).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def _has_audio(path: str) -> bool:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                              "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return "audio" in out
    except Exception:
        return False


def _sfx_files() -> list[str]:
    if not os.path.isdir(_SFX_DIR):
        return []
    return [os.path.join(_SFX_DIR, f) for f in sorted(os.listdir(_SFX_DIR))
            if f.lower().endswith((".wav", ".mp3"))]


# ------------------------------------------------------------------ pasos FFmpeg

def _add_music_sfx(inp: str, plan: dict, eleven_key: str | None, product_desc: str,
                   work_dir: str, out: str) -> str:
    """Añade música de fondo (baja, bajo la voz) + SFX en el inicio de cada fase."""
    dur = _dur(inp)
    phases = plan.get("phases", [])
    inputs, fc, labels = ["-i", inp], [], ["[0:a]"] if _has_audio(inp) else []
    if not labels:
        return inp  # sin audio base no mezclamos
    idx = 1

    # música: estilo de la fase de mayor energía; ElevenLabs Music (puede fallar por permisos)
    if eleven_key and phases:
        top = max(phases, key=lambda p: p.get("musica", {}).get("energia", 0))
        estilo = top.get("musica", {}).get("estilo", "música de anuncio, energética")
        mf = os.path.join(work_dir, "music.mp3")
        try:
            voiceover.music(eleven_key, f"{estilo}. Para un anuncio de {product_desc or 'producto'}.",
                            mf, length_ms=int(max(10000, min(60000, dur * 1000))))
            inputs += ["-i", mf]
            fc.append(f"[{idx}:a]aloop=loop=-1:size=2000000000,volume=0.12[mus]")
            labels.append("[mus]"); idx += 1
        except Exception:
            pass

    # SFX en el inicio de cada fase
    for ph in phases:
        sfx = ph.get("sfx")
        if not sfx or not os.path.exists(sfx):
            continue
        ms = int(float(ph.get("inicio_s", 0)) * 1000)
        inputs += ["-i", sfx]
        fc.append(f"[{idx}:a]adelay={ms}|{ms},volume=0.7[s{idx}]")
        labels.append(f"[s{idx}]"); idx += 1

    if len(labels) < 2:      # solo la voz base -> nada que mezclar
        return inp
    fc.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first[a]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc),
         "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
         "-t", f"{dur:.3f}", "-movflags", "+faststart", out])
    return out


def _sub_png(text: str, W: int, out: str) -> int:
    """Renderiza un subtítulo (texto blanco con borde negro, fondo transparente). Devuelve alto."""
    strip_h = 260
    img = Image.new("RGBA", (W, strip_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    size = 60
    words = text.split()
    while size >= 28:
        f = _font(size)
        # wrap
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) <= W - 80 or not cur:
                cur = t
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        lh = (f.getbbox("Ag")[3] - f.getbbox("Ag")[1]) + 10
        if lh * len(lines) <= strip_h - 20:
            break
        size -= 4
    y = strip_h - lh * len(lines) - 10
    for ln in lines:
        w = d.textlength(ln, font=f)
        d.text(((W - w) // 2, y), ln, font=f, fill=(255, 255, 255, 255),
               stroke_width=max(2, size // 16), stroke_fill=(0, 0, 0, 255))
        y += lh
    img.save(out)
    return strip_h


def _burn_subs(inp: str, segments: list[dict], work_dir: str, out: str) -> str:
    """Quema subtítulos por fase en el tercio inferior (safe zone 120px), SIN solaparse.

    Blindado contra los 2 bugs que causaban el garabato: (1) dos subtítulos a la vez si sus
    tiempos se pisaban -> aquí se recorta el fin de cada uno al inicio del siguiente; (2)
    desalineación input↔tiempo -> aquí se valida ANTES de agregar el input.
    """
    info = probe(inp)
    W, H = info.width, info.height

    # 1) recolectar tramos válidos (texto + tiempos), ordenados por inicio
    items = []
    for s in segments:
        txt = (s.get("es_colombia") or s.get("que_se_dice") or "").strip()
        ini, fin = mmss_to_seconds(s.get("inicio", 0)), mmss_to_seconds(s.get("fin", 0))
        if txt and fin > ini:
            items.append([ini, fin, txt])
    items.sort(key=lambda x: x[0])
    # 2) evitar solape temporal: el fin de cada uno no pasa del inicio del siguiente
    for i in range(len(items) - 1):
        if items[i][1] > items[i + 1][0]:
            items[i][1] = items[i + 1][0]

    inputs, filt, last, n = ["-i", inp], [], "[0:v]", 0
    for ini, fin, txt in items:
        if fin - ini < 0.15:                        # quedó muy corto tras el recorte
            continue
        png = os.path.join(work_dir, f"sub_{n}.png")
        strip_h = _sub_png(txt, W, png)
        inputs += ["-i", png]                       # el input se agrega SOLO si es válido
        y = H - strip_h - 120                       # safe zone inferior de TikTok
        tag = f"[v{n}]"
        filt.append(f"{last}[{n + 1}:v]overlay=(W-w)/2:{y}:enable='between(t,{ini:.2f},{fin:.2f})'{tag}")
        last = tag; n += 1
    if n == 0:
        return inp
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt),
         "-map", last, "-map", "0:a?", "-c:a", "copy",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
    return out


def _verticalize(inp: str, out: str, w: int = 1080, h: int = 1920) -> str:
    """Lleva a 9:16 (1080×1920) SIN recortar contenido, de forma inteligente según el formato:

    - Si el video YA es ~9:16: solo ajusta el tamaño exacto (no toca la composición).
    - Si es CUADRADO u horizontal (viene "encuadrado"): NO agranda ni recorta los lados
      (eso cortaría textos/banners). En su lugar arma el clásico FONDO DESENFOCADO: una copia
      ampliada y borrosa del mismo video llena las barras, y el video ORIGINAL COMPLETO va
      centrado encima. Así no se pierde nada del creativo.
    """
    try:
        info = probe(inp)
        src_ar = info.width / info.height if info.height else 0
    except Exception:
        src_ar = 0
    target_ar = w / h

    if src_ar and abs(src_ar - target_ar) < 0.02:
        # Ya es (casi) 9:16 -> solo asegurar 1080×1920, sin recortar
        run(["ffmpeg", "-y", "-i", inp, "-vf", f"scale={w}:{h},setsar=1",
             "-c:a", "copy", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
        return out

    # Formato distinto (cuadrado/horizontal) -> fondo desenfocado + original completo centrado
    fc = (f"[0:v]split=2[bg][fg];"
          f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=22[bgb];"
          f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fgs];"
          f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    run(["ffmpeg", "-y", "-i", inp, "-filter_complex", fc,
         "-c:a", "copy", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
    return out


def _normalize(inp: str, out: str) -> str:
    """Normaliza el volumen (loudnorm, estándar de redes ~-14 LUFS)."""
    run(["ffmpeg", "-y", "-i", inp, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
         "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", out])
    return out


# ------------------------------------------------------------------ la cadena

def generar_creativo_auto(
    video_path: str, *,
    gemini_key: str | None = None,
    eleven_key: str | None = None,
    anthropic_key: str | None = None,
    product_desc: str = "",
    voz: str = "juan_carlos",
    oferta_2x1: bool = False,
    verticalizar: bool = True,
    work_dir: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Corre TODA la cadena sobre un video ganador. Cada paso está aislado (si falla, sigue).

    Devuelve {"ok":True,"video":ruta_final,"pasos":[{paso,ok,detalle}],"blueprint":..}.
    """
    pasos: list[dict] = []

    def report(msg, pct):
        if progress:
            progress(msg, pct)

    def paso(nombre, ok, detalle=""):
        pasos.append({"paso": nombre, "ok": ok, "detalle": detalle})

    gemini_key = gemini_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    eleven_key = eleven_key or os.environ.get("ELEVENLABS_API_KEY")
    if not os.path.exists(video_path):
        return {"ok": False, "error": "No encuentro el video de entrada.", "pasos": pasos}

    work_dir = work_dir or tempfile.mkdtemp(prefix="auto_")
    os.makedirs(work_dir, exist_ok=True)
    current = video_path            # el video va evolucionando paso a paso
    blueprint = None
    dub_segments: list[dict] = []

    # 1) NARRATIVA -----------------------------------------------------------
    report("📖 Leyendo la estructura narrativa...", 8)
    try:
        bp = analyze_narrative(current, api_key=gemini_key, product_desc=product_desc)
        if bp.get("ok"):
            blueprint = bp
            paso("Narrativa", True, f"{len(bp['segments'])} fases detectadas")
        else:
            paso("Narrativa", False, bp.get("error", ""))
    except Exception as e:  # noqa: BLE001
        paso("Narrativa", False, str(e))

    # 2) DOBLAJE COLOMBIANO --------------------------------------------------
    report("🇨🇴 Doblando a español colombiano...", 22)
    if eleven_key:
        try:
            wd = os.path.join(work_dir, "dub"); os.makedirs(wd, exist_ok=True)
            d = generar_dub(current, api_key=gemini_key, eleven_key=eleven_key,
                            product_desc=product_desc, voz=voz, oferta_2x1=oferta_2x1,
                            generar_video=True, work_dir=wd, blueprint=blueprint)
            if d.get("ok") and d.get("video"):
                current = d["video"]; dub_segments = d.get("segments", [])
                paso("Doblaje CO", True, f"voz {d.get('voz')}")
            else:
                paso("Doblaje CO", False, d.get("error", "sin video"))
        except Exception as e:  # noqa: BLE001
            paso("Doblaje CO", False, str(e))
    else:
        paso("Doblaje CO", False, "falta ELEVENLABS_API_KEY")

    # 3) TRADUCIR TEXTO EN PANTALLA -----------------------------------------
    report("🔤 Traduciendo el texto en pantalla...", 40)
    try:
        out = os.path.join(work_dir, "traducido.mp4")
        t = traducir_texto_pantalla(current, api_key=gemini_key, out_path=out)
        if t.get("ok"):
            current = t["video"]
            paso("Traducir texto", True, f"{len(t.get('bloques', []))} bloque(s)")
        else:
            paso("Traducir texto", False, t.get("error", ""))
    except Exception as e:  # noqa: BLE001
        paso("Traducir texto", False, str(e))

    # 4) MÚSICA + SFX POR FASE ----------------------------------------------
    report("🎵 Poniendo música y efectos por fase...", 58)
    if blueprint:
        try:
            plan = phase_effect_plan(blueprint, _dur(current), _sfx_files())
            if plan.get("ok"):
                out = os.path.join(work_dir, "musica_sfx.mp4")
                nc = _add_music_sfx(current, plan, eleven_key, product_desc, work_dir, out)
                changed = nc != current
                current = nc
                paso("Música + SFX", True, "aplicado" if changed else "sin cambios")
            else:
                paso("Música + SFX", False, plan.get("error", ""))
        except Exception as e:  # noqa: BLE001
            paso("Música + SFX", False, str(e))
    else:
        paso("Música + SFX", False, "sin blueprint")

    # 5) SUBTÍTULOS POR FASE -------------------------------------------------
    report("💬 Poniendo subtítulos...", 70)
    subs = dub_segments or (blueprint.get("segments") if blueprint else [])
    if subs:
        try:
            out = os.path.join(work_dir, "subs.mp4")
            nc = _burn_subs(current, subs, work_dir, out)
            current = nc
            paso("Subtítulos", nc != video_path, f"{len(subs)} fase(s)")
        except Exception as e:  # noqa: BLE001
            paso("Subtítulos", False, str(e))
    else:
        paso("Subtítulos", False, "sin texto de guion")

    # 6) VERTICALIZAR 9:16 ---------------------------------------------------
    report("📱 Verticalizando a 9:16...", 84)
    if verticalizar:
        try:
            out = os.path.join(work_dir, "vertical.mp4")
            current = _verticalize(current, out)
            paso("Vertical 9:16", True)
        except Exception as e:  # noqa: BLE001
            paso("Vertical 9:16", False, str(e))

    # 7) NORMALIZAR AUDIO ----------------------------------------------------
    report("🔊 Normalizando el audio...", 92)
    if _has_audio(current):
        try:
            out = os.path.join(work_dir, "final.mp4")
            current = _normalize(current, out)
            paso("Normalizar audio", True)
        except Exception as e:  # noqa: BLE001
            paso("Normalizar audio", False, str(e))

    # 8) SUPERVISOR (opcional) ----------------------------------------------
    try:
        from . import supervisor
        if (anthropic_key or os.environ.get("ANTHROPIC_API_KEY")) and supervisor.available():
            paso("Supervisor", True, "capitán activo (revisión disponible)")
    except Exception:
        pass

    # Copiar el resultado a un nombre estable dentro del work_dir
    final = os.path.join(work_dir, "creativo_final.mp4")
    try:
        if current != final:
            run(["ffmpeg", "-y", "-i", current, "-c", "copy", "-movflags", "+faststart", final])
        current = final
    except Exception:
        pass

    report("✅ Creativo terminado", 100)
    ok_pasos = sum(1 for p in pasos if p["ok"])
    return {"ok": True, "video": current, "pasos": pasos,
            "resumen": f"{ok_pasos}/{len(pasos)} pasos OK", "blueprint": blueprint}


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("Uso: python -m backend.pipeline.auto_studio <video.mp4> [descripcion]")
        raise SystemExit(1)

    def _p(m, p):
        print(f"[{p:3d}%] {m}", file=sys.stderr)

    r = generar_creativo_auto(sys.argv[1], product_desc=sys.argv[2] if len(sys.argv) > 2 else "",
                              progress=_p)
    print(json.dumps({k: v for k, v in r.items() if k != "blueprint"}, ensure_ascii=False, indent=2))
