"""END-CARD de CTA al final del creativo (opcional): cierre de ~1.5s que remata la conversión.

Patrón ganador en ads COD: terminar con una tarjeta oscura de oferta clara —
'PAGAS AL RECIBIR' grande + 'ENVÍO GRATIS A TODA COLOMBIA' + pill naranja de CTA.
SIN cifras de precio (regla de oro de Jack). Mismo motor PIL y estética que
offer_banner (Poppins bold vía caption_styles._fontpath + _NARANJA).
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from .caption_styles import _fontpath, _fit, _strip_emoji
from .ffmpeg_utils import probe, run
from .assemble import venc
from .offer_banner import _NARANJA

_FONDO = (22, 19, 26, 255)      # mismo tono oscuro (#16131a-ish) de los banners sólidos


def render_end_card(W: int, H: int,
                    line1: str = "PAGAS AL RECIBIR",
                    line2: str = "ENVÍO GRATIS A TODA COLOMBIA",
                    cta: str = "PIDE EL TUYO AQUÍ 👇") -> Image.Image:
    """Tarjeta final W×H: fondo oscuro sólido, line1 GRANDE centrada en blanco bold,
    line2 mediana, y el CTA en una pill naranja + flecha hacia abajo (apunta al botón del ad).
    Todo auto-ajustado con _fit (nunca se corta). Los emojis se quitan del texto (Poppins no
    los dibuja) y el 👇 se reemplaza por una flecha dibujada."""
    img = Image.new("RGBA", (W, H), _FONDO)
    d = ImageDraw.Draw(img)
    fp = _fontpath(True)

    margin_x = int(W * 0.07)
    max_w = W - 2 * margin_x

    line1 = _strip_emoji((line1 or "").strip().upper())
    line2 = _strip_emoji((line2 or "").strip().upper())
    cta = _strip_emoji((cta or "").strip().upper())

    # ── medir cada bloque (mismo motor _fit de los banners) ──
    f1 = ls1 = lh1 = None
    if line1:
        f1, ls1, lh1, _ = _fit(d, line1, fp, max_w, int(H * 0.20), int(H * 0.052),
                               min_size=max(24, int(H * 0.024)))
    f2 = ls2 = lh2 = None
    if line2:
        f2, ls2, lh2, _ = _fit(d, line2, fp, max_w, int(H * 0.10), int(H * 0.026),
                               min_size=max(18, int(H * 0.015)))
    fc = cs = None
    pill_w = pill_h = px = py = 0
    if cta:
        # el CTA cabe en UNA línea dentro de la pill (max_h chico → _fit lo encoge hasta 1 línea)
        fc, _lsc, _lhc, cs = _fit(d, cta, fp, int(max_w * 0.9), int(H * 0.05),
                                  int(H * 0.030), min_size=max(18, int(H * 0.016)))
        cw = d.textlength(cta, font=fc)
        px, py = int(cs * 0.85), int(cs * 0.55)
        pill_w, pill_h = int(cw + 2 * px), int(cs + 2 * py)

    gap1 = int(H * 0.028)                       # entre line1 y line2
    gap2 = int(H * 0.045)                       # entre line2 y la pill del CTA
    tri_gap, tri_h, tri_w = int(H * 0.020), int(H * 0.020), int(W * 0.055)

    total = 0
    if ls1:
        total += lh1 * len(ls1)
    if ls2:
        total += (gap1 if ls1 else 0) + lh2 * len(ls2)
    if cta:
        total += (gap2 if (ls1 or ls2) else 0) + pill_h + tri_gap + tri_h

    y = (H - total) // 2                        # bloque completo centrado vertical

    # ── line1 GRANDE en blanco bold ──
    if ls1:
        for ln in ls1:
            w = d.textlength(ln, font=f1)
            d.text(((W - w) / 2, y), ln, font=f1, fill=(255, 255, 255, 255))
            y += lh1
        y += gap1 if ls2 else 0

    # ── line2 mediana (blanco suave para jerarquía) ──
    if ls2:
        for ln in ls2:
            w = d.textlength(ln, font=f2)
            d.text(((W - w) / 2, y), ln, font=f2, fill=(235, 232, 240, 255))
            y += lh2

    # ── CTA en pill naranja (misma _NARANJA de los banners) + flecha abajo ──
    if cta:
        y += gap2 if (ls1 or ls2) else 0
        x0 = (W - pill_w) / 2
        d.rounded_rectangle([x0, y, x0 + pill_w, y + pill_h],
                            radius=pill_h // 2, fill=_NARANJA)
        cw = d.textlength(cta, font=fc)
        d.text(((W - cw) / 2, y + py), cta, font=fc, fill=(255, 255, 255, 255))
        y += pill_h + tri_gap
        # flecha ▼ dibujada (el 👇 no existe en Poppins): apunta al botón del anuncio
        d.polygon([((W - tri_w) / 2, y), ((W + tri_w) / 2, y), (W / 2, y + tri_h)],
                  fill=_NARANJA)
    return img


def append_end_card(video_path: str, out_path: str, work_dir: str, dur: float = 1.5,
                    line1: str = "PAGAS AL RECIBIR",
                    line2: str = "ENVÍO GRATIS A TODA COLOMBIA",
                    cta: str = "PIDE EL TUYO AQUÍ 👇") -> str:
    """Concatena la end-card `dur` segundos AL FINAL del video. Conserva el audio original
    (la card lleva pista silenciosa anullsrc para que el concat no se rompa); si el video
    no trae audio, la salida tampoco. Devuelve out_path o el original si algo falla."""
    try:
        info = probe(video_path)
        W, H, fps = info.width, info.height, (info.fps or 30.0)
        base = os.path.basename(out_path)       # nombres ÚNICOS por versión (van en paralelo)
        png = os.path.join(work_dir, base + ".endcard.png")
        render_end_card(W, H, line1=line1, line2=line2, cta=cta).save(png)

        # 1) clip de `dur`s desde el PNG, mismo WxH/fps, CON audio silencioso (anullsrc)
        clip = os.path.join(work_dir, base + ".endcard.mp4")
        run(["ffmpeg", "-y", "-loop", "1", "-t", f"{float(dur):.2f}", "-i", png,
             "-f", "lavfi", "-t", f"{float(dur):.2f}", "-i", "anullsrc=r=44100:cl=stereo",
             "-r", f"{fps:.3f}", *venc(), "-c:a", "aac", "-ar", "44100",
             "-pix_fmt", "yuv420p", "-shortest", clip])

        # 2) concat (filter): normalizo fps/SAR (y audio si hay) para que no se rompa
        vf = (f"[0:v]fps={fps:.3f},setsar=1[v0];[1:v]fps={fps:.3f},setsar=1[v1];")
        if info.has_audio:
            fc = (vf + "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
                       "[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
                       "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")
            maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac"]
        else:
            fc = vf + "[v0][v1]concat=n=2:v=1:a=0[v]"
            maps = ["-map", "[v]", "-an"]
        run(["ffmpeg", "-y", "-i", video_path, "-i", clip, "-filter_complex", fc,
             *maps, *venc(), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path])
        return out_path
    except Exception:  # noqa: BLE001
        return video_path
