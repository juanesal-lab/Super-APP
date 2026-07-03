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
from .assemble import venc   # encoder GPU (VideoToolbox) si está disponible; si no, libx264
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


def _burn_subs(inp: str, segments: list[dict], work_dir: str, out: str,
               style: str = "bold_outline", cap_size: str = "mediano") -> str:
    """Quema subtítulos por fase con el MOTOR caption_styles (Poppins, auto-ajuste, estilo elegible),
    SIN solaparse. Cada caption es un PNG del tamaño del frame (posición ya puesta) → overlay 0:0.

    Blindado contra el garabato: (1) recorta el fin de cada tramo al inicio del siguiente (nunca 2 a
    la vez); (2) valida ANTES de agregar el input (índices alineados).
    """
    from .caption_styles import render_caption
    info = probe(inp)
    W, H = info.width, info.height

    items = []
    for s in segments:
        txt = (s.get("es_colombia") or s.get("que_se_dice") or "").strip()
        ini, fin = mmss_to_seconds(s.get("inicio", 0)), mmss_to_seconds(s.get("fin", 0))
        if txt and fin > ini:
            items.append([ini, fin, txt])
    items.sort(key=lambda x: x[0])
    for i in range(len(items) - 1):
        if items[i][1] > items[i + 1][0]:
            items[i][1] = items[i + 1][0]

    inputs, filt, last, n = ["-i", inp], [], "[0:v]", 0
    for ini, fin, txt in items:
        if fin - ini < 0.15:
            continue
        png = os.path.join(work_dir, f"sub_{n}.png")
        render_caption(txt, W, H, style, cap_size=cap_size).save(png)   # PNG full-frame, auto-ajustado, Poppins
        inputs += ["-i", png]
        tag = f"[v{n}]"
        filt.append(f"{last}[{n + 1}:v]overlay=0:0:enable='between(t,{ini:.2f},{fin:.2f})'{tag}")
        last = tag; n += 1
    if n == 0:
        return inp
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt),
         "-map", last, "-map", "0:a?", "-c:a", "copy",
         *venc(),
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
             "-c:a", "copy", *venc(),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
        return out

    # Formato distinto (cuadrado/horizontal) -> fondo desenfocado + original completo centrado
    fc = (f"[0:v]split=2[bg][fg];"
          f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=22[bgb];"
          f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fgs];"
          f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    run(["ffmpeg", "-y", "-i", inp, "-filter_complex", fc,
         "-c:a", "copy", *venc(),
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
    caption_style: str = "bold_outline",
    caption_size: str = "mediano",
    oferta: str = "",
    banner_oferta: bool = False,
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
    word_timings: list[dict] = []

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
                word_timings = d.get("word_timings", [])
                paso("Doblaje CO", True, f"voz {d.get('voz')}")
            else:
                paso("Doblaje CO", False, d.get("error", "sin video"))
        except Exception as e:  # noqa: BLE001
            paso("Doblaje CO", False, str(e))
    else:
        paso("Doblaje CO", False, "falta ELEVENLABS_API_KEY")

    # 3) TAPAR (BLUR) LOS SUBTÍTULOS VIEJOS ----------------------------------
    #   Detecta SOLO el texto SOBREPUESTO (subtítulos/captions del original, NO el texto real de la
    #   escena: envases, letreros, logos), arma la ZONA donde viven y la tapa con blur CONTINUO — así
    #   NUNCA se asoma el subtítulo viejo y encima quedan limpios NUESTROS subtítulos.
    #   NO se traduce ni se agrega ningún otro texto (eso era lo que ensuciaba el creativo).
    report("🧽 Detectando la banda EXACTA de los subtítulos del original...", 40)
    try:
        from .subtitle_band import detect_subtitle_band, detect_top_band
        from .assemble import blur_boxes
        # EAST (cajas ajustadas) + presencia consistente -> banda TIGHT donde están los subtítulos
        # ABAJO + captions/títulos quemados ARRIBA (los dos, para que no se escape ninguno).
        bandas = [b for b in (detect_subtitle_band(current), detect_top_band(current)) if b]
        if bandas:
            out = os.path.join(work_dir, "sin_subs.mp4")
            current = blur_boxes(current, out, bandas)
            paso("Tapar subtítulos viejos", True,
                 f"{len(bandas)} banda(s) tapada(s) (arriba+abajo si hay)")
        else:
            paso("Tapar subtítulos viejos", True, "no detecté subtítulos quemados")
    except Exception as e:  # noqa: BLE001
        paso("Tapar subtítulos viejos", False, str(e))

    # 3b) VERTICALIZAR 9:16 (TEMPRANO — fija el lienzo final): el texto viejo ya se tapó, así las
    #     bandas del blur salen limpias, y lo que sigue (subtítulos/oferta) se pone sobre el 9:16 final
    #     y queda bien posicionado (no se re-escala después).
    if verticalizar:
        report("📱 Verticalizando a 9:16...", 52)
        try:
            out = os.path.join(work_dir, "vertical.mp4")
            current = _verticalize(current, out)
            paso("Vertical 9:16", True)
        except Exception as e:  # noqa: BLE001
            paso("Vertical 9:16", False, str(e))

    # (Música/efectos y oferta se quitaron a propósito: el creativo queda LIMPIO — solo voz en off
    #  + subtítulos viejos tapados + NUESTROS subtítulos encima. Nada de texto/audio adicional.)

    # 5) SUBTÍTULOS -----------------------------------------------------------
    #   Si hay tiempos por-palabra (del doblaje) -> subtítulos PALABRA POR PALABRA sincronizados
    #   (estilo adapta). Si no -> subtítulos por fase (bloque).
    report("💬 Poniendo subtítulos...", 70)
    subs = dub_segments or (blueprint.get("segments") if blueprint else [])
    if word_timings:
        try:
            from .caption_styles import burn_word_captions
            out = os.path.join(work_dir, "subs.mp4")
            current = burn_word_captions(current, word_timings, work_dir, out, style=caption_style, cap_size=caption_size)
            paso("Subtítulos", True, f"palabra x palabra · {len(word_timings)} palabras · {caption_style}")
        except Exception as e:  # noqa: BLE001
            paso("Subtítulos", False, str(e))
    elif subs:
        try:
            out = os.path.join(work_dir, "subs.mp4")
            current = _burn_subs(current, subs, work_dir, out, style=caption_style, cap_size=caption_size)
            paso("Subtítulos", True, f"{len(subs)} fase(s) · estilo {caption_style}")
        except Exception as e:  # noqa: BLE001
            paso("Subtítulos", False, str(e))
    else:
        paso("Subtítulos", False, "sin texto de guion")

    # 6b) BANNER DE OFERTA ARRIBA (opcional) — la IA lo pone donde no tape nada
    if banner_oferta:
        report("🏷️ Poniendo el banner de oferta (2x1 · envío gratis)...", 88)
        try:
            from .offer_banner import add_offer_banner
            out = os.path.join(work_dir, "banner.mp4")
            current = add_offer_banner(current, out, work_dir, gemini_key=gemini_key)
            paso("Banner oferta", True, "2x1 · envío gratis · pagas al recibir")
        except Exception as e:  # noqa: BLE001
            paso("Banner oferta", False, str(e))

    # 7) NORMALIZAR AUDIO ----------------------------------------------------
    report("🔊 Normalizando el audio...", 92)
    if _has_audio(current):
        try:
            out = os.path.join(work_dir, "final.mp4")
            current = _normalize(current, out)
            paso("Normalizar audio", True)
        except Exception as e:  # noqa: BLE001
            paso("Normalizar audio", False, str(e))

    # 7b) PACING punchy: si quedó largo (>~22s), acelera un pelín (video+audio+subs en sync) para
    #     retener más (los ganadores de TikTok van ágiles).
    report("⚡ Ajustando el ritmo (pacing)...", 96)
    try:
        from .assemble import punch_pace
        from .ffmpeg_utils import probe as _pb
        out = os.path.join(work_dir, "pace.mp4")
        antes = _pb(current).duration
        current = punch_pace(current, out)
        desp = _pb(current).duration
        paso("Pacing", True, f"{antes:.0f}s → {desp:.0f}s" if desp < antes - 0.5 else "ya era ágil")
    except Exception as e:  # noqa: BLE001
        paso("Pacing", False, str(e))

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
