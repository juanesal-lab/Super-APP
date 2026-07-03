"""Motor de subtítulos/textos para los videos — Poppins, auto-ajuste y 10 estilos.

Arregla lo FEO:
  - AUTO-AJUSTE: el texto SIEMPRE cabe. Word-wrap + baja el tamaño de fuente hasta entrar en el
    área segura (ancho = frame − 2*SAFE). NUNCA se corta.
  - SAFE ZONE de 120px por borde (donde va la UI de TikTok). Texto en el tercio inferior-medio.
  - POPPINS en todo (ExtraBold para hooks/títulos, Bold para subtítulos).
  - 10 estilos seleccionables (ver ESTILOS).

Como el ffmpeg de Super-APP NO trae libass ni drawtext, todo se dibuja con Pillow a un PNG
transparente del tamaño del frame y se hace overlay (posición ya "horneada"). Sin dependencias nuevas.

Nota v1: sin tiempos por-palabra, los estilos "animados" (karaoke/bounce/typewriter) se rinden con su
look estático PRO; la animación real por-palabra queda para v2 (necesita word-timestamps).
"""
from __future__ import annotations

import os
import re
from typing import Callable

# Emojis/pictogramas que Poppins NO tiene (salen como cuadrito □). Se quitan del texto.
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF"
    "\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF\U0000FE0F\U00002190-\U000021FF]",
    flags=re.UNICODE)


def _strip_emoji(t: str) -> str:
    return _EMOJI_RE.sub("", t or "").strip()

from PIL import Image, ImageDraw, ImageFont

from .ffmpeg_utils import run, probe
from .assemble import venc

_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets", "fonts")
_POPPINS_BOLD = os.path.join(_FONTS_DIR, "Poppins-Bold.ttf")
_POPPINS_XBOLD = os.path.join(_FONTS_DIR, "Poppins-ExtraBold.ttf")
# Fallbacks por si faltara Poppins
_FALLBACK = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]

SAFE = 120                      # margen seguro por borde (UI de TikTok)
ESTILOS = ["bold_outline", "hormozi", "yellow_highlight", "red_highlight", "highlight_box",
           "pill", "clean_minimal", "karaoke", "bounce", "typewriter"]

# Tamaño del subtítulo elegible por el usuario (regla de Juan: default MEDIANO, los gigantes no)
TAMANOS = {"pequeno": 0.66, "mediano": 0.82, "grande": 1.0}


def _tam(cap_size) -> float:
    return TAMANOS.get(str(cap_size or "mediano").lower().replace("ñ", "n"), 0.82)

# Palabras que NO son "clave" (para no resaltarlas)
_STOP = set("de la el que y a en un una los las por con para su tu mi es se lo le al del "
            "o u ni si no me te nos ¿ ? ¡ ! yo".split())

# ── ACENTO DINÁMICO: el color de resalte de las captions CONTRASTA con el color del producto/video ──
# Paleta curada (colores que se ven PRO en ads; nada de tonos sucios): nombre → RGB
_PALETA_ACENTO = [
    ("amarillo", (255, 214, 10)),
    ("naranja", (255, 138, 0)),
    ("rojo", (240, 60, 50)),
    ("fucsia", (255, 45, 170)),
    ("cian", (0, 220, 255)),
    ("verde neon", (57, 255, 106)),
    ("azul", (64, 140, 255)),
]
_ACCENT: tuple | None = None    # override activo (None = colores clásicos del estilo)


def set_accent(rgb: tuple | None):
    """Fija (o limpia con None) el color de acento dinámico de TODAS las captions."""
    global _ACCENT
    _ACCENT = (tuple(rgb[:3]) + (255,)) if rgb else None


def accent_for_video(video_path: str, samples: int = 5) -> tuple | None:
    """Color de acento que CONTRASTA con el video: saca el color dominante (HSV medio de varios
    frames, ponderado por saturación) y elige de la paleta el de tono más LEJANO (rueda de color).
    Si el video es neutro (gris/blanco), devuelve el amarillo clásico. None si no se pudo leer."""
    try:
        import cv2
        import numpy as np
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        hues, sats = [], []
        for k in range(samples):
            if total > 1:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (k + 0.5) / samples))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            centro = frame[h // 4: 3 * h // 4, w // 4: 3 * w // 4]     # el producto suele ir al centro
            hsv = cv2.cvtColor(cv2.resize(centro, (64, 64)), cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
            m = hsv[:, 1] > 60                                          # solo píxeles con color real
            if m.sum() < 50:
                continue
            # tono dominante ponderado por saturación (promedio circular)
            ang = hsv[m, 0] / 180.0 * 2 * np.pi
            wgt = hsv[m, 1]
            hues.append(np.arctan2((np.sin(ang) * wgt).sum(), (np.cos(ang) * wgt).sum()))
            sats.append(float(wgt.mean()))
        cap.release()
        if not hues:
            return _PALETA_ACENTO[0][1]      # video neutro → amarillo clásico
        dom = float(np.arctan2(np.mean([np.sin(h) for h in hues]), np.mean([np.cos(h) for h in hues])))

        def dist_circular(rgb):
            r, g, b = [c / 255.0 for c in rgb]
            hsv = cv2.cvtColor(np.uint8([[[b * 255, g * 255, r * 255]]]), cv2.COLOR_BGR2HSV)[0][0]
            a = hsv[0] / 180.0 * 2 * np.pi
            d = abs(a - dom) % (2 * np.pi)
            return min(d, 2 * np.pi - d)
        # el color de la paleta con el tono MÁS OPUESTO al dominante = máximo contraste
        return max(_PALETA_ACENTO, key=lambda p: dist_circular(p[1]))[1]
    except Exception:  # noqa: BLE001
        return None


def _fontpath(bold_x: bool) -> str:
    p = _POPPINS_XBOLD if bold_x else _POPPINS_BOLD
    if os.path.exists(p):
        return p
    for f in _FALLBACK:
        if os.path.exists(f):
            return f
    return p


def _keywords(text: str, n: int = 2) -> set:
    """Elige hasta n palabras 'clave' (las más largas que no son stopwords) para resaltar."""
    words = [w.strip(".,!?¡¿:;\"'()").upper() for w in text.split()]
    cand = [w for w in words if len(w) >= 4 and w.lower() not in _STOP]
    cand.sort(key=len, reverse=True)
    return set(cand[:n])


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text, fontpath, max_w, max_h, size0, min_size=30):
    """Devuelve (font, lines, line_h, size) que CABE en (max_w, max_h). Nunca se corta."""
    size = size0
    while size >= min_size:
        font = ImageFont.truetype(fontpath, size)
        lines = _wrap(draw, text, font, max_w)
        line_h = int(size * 1.18)          # interlineado JUNTO (Poppins tiene métricas muy altas)
        widest = max((draw.textlength(ln, font=font) for ln in lines), default=0)
        if widest <= max_w and line_h * len(lines) <= max_h:
            return font, lines, line_h, size
        size -= 3
    font = ImageFont.truetype(fontpath, min_size)
    return font, _wrap(draw, text, font, max_w), int(min_size * 1.18), min_size


def _draw_words_line(draw, words, x, y, font, base_col, kw_col, keywords, stroke):
    """Dibuja una línea palabra por palabra, coloreando las keywords distinto."""
    space = draw.textlength(" ", font=font)
    for w in words:
        clean = w.strip(".,!?¡¿:;\"'()").upper()
        col = kw_col if clean in keywords else base_col
        draw.text((x, y), w, font=font, fill=col,
                  stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        x += draw.textlength(w, font=font) + space


def _line_width(draw, words, font):
    space = draw.textlength(" ", font=font)
    return sum(draw.textlength(w, font=font) for w in words) + space * (len(words) - 1)


def render_caption(text: str, W: int, H: int, style: str = "bold_outline",
                   cap_size: str = "mediano") -> Image.Image:
    """Devuelve un PNG RGBA (W×H, transparente) con el subtítulo en el estilo pedido, auto-ajustado
    dentro de la zona segura, en el tercio inferior-medio. Overlay directo en 0:0.
    `cap_size`: pequeno | mediano (default) | grande."""
    text = _strip_emoji(text)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if not text:
        return img
    draw = ImageDraw.Draw(img)
    f = _tam(cap_size)
    max_w = W - 2 * SAFE
    max_h = int(H * 0.34 * f)                   # alto máximo del bloque de texto
    xbold = style in ("hormozi", "bounce")
    fontpath = _fontpath(xbold)
    disp = text.upper() if style in ("hormozi",) else text
    size0 = int(H * (0.066 if style in ("hormozi", "bounce") else 0.05) * f)
    font, lines, line_h, size = _fit(draw, disp, fontpath, max_w, max_h, size0,
                                     min_size=max(18, int(30 * f)))
    stroke = max(2, size // 9)
    keywords = _keywords(text)

    total_h = line_h * len(lines)
    y0 = int(H * 0.80) - total_h // 2          # bloque en el tercio INFERIOR (tapa menos)
    y0 = max(int(H * 0.55), min(y0, H - SAFE - total_h))

    yellow, red, white = (255, 214, 10, 255), (240, 60, 50, 255), (255, 255, 255, 255)
    if _ACCENT:                      # acento dinámico: contrasta con el color del producto/video
        yellow = red = _ACCENT

    def centered_x(ln_words, f):
        return (W - _line_width(draw, ln_words, f)) // 2

    # --- PILL / CÁPSULA: caja redondeada sólida detrás del texto (sin contorno) ---
    if style == "pill":
        pad = int(size * 0.4)
        for i, ln in enumerate(lines):
            w = draw.textlength(ln, font=font)
            x = (W - w) // 2; y = y0 + i * line_h
            draw.rounded_rectangle([x - pad, y - pad // 2, x + w + pad, y + line_h - int(line_h*0.2) + pad // 2],
                                   radius=int(line_h * 0.4), fill=(255, 214, 10, 255))
            draw.text((x, y), ln, font=font, fill=(20, 20, 20, 255))
        return img

    # --- CLEAN MINIMAL: blanco, sin contorno, sombra suave ---
    if style == "clean_minimal":
        for i, ln in enumerate(lines):
            x = (W - draw.textlength(ln, font=font)) // 2; y = y0 + i * line_h
            draw.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0, 120))    # sombra
            draw.text((x, y), ln, font=font, fill=white)
        return img

    # --- BOUNCE (look estático "wordpop"): pocas palabras, grandes y centradas ---
    if style == "bounce":
        for i, ln in enumerate(lines):
            x = (W - draw.textlength(ln, font=font)) // 2; y = y0 + i * line_h
            draw.text((x, y), ln, font=font, fill=white, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        return img

    # --- HIGHLIGHT BOX: la keyword lleva una caja de color detrás ---
    if style == "highlight_box":
        for i, ln in enumerate(lines):
            words = ln.split(); x = centered_x(words, font); y = y0 + i * line_h
            space = draw.textlength(" ", font=font)
            for w in words:
                clean = w.strip(".,!?¡¿:;\"'()").upper(); ww = draw.textlength(w, font=font)
                if clean in keywords:
                    draw.rounded_rectangle([x - 6, y + 4, x + ww + 6, y + line_h - int(line_h*0.18)],
                                           radius=10, fill=yellow)
                    draw.text((x, y), w, font=font, fill=(20, 20, 20, 255))
                else:
                    draw.text((x, y), w, font=font, fill=white, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
                x += ww + space
        return img

    # --- KARAOKE (look estático): blanco, con caja amarilla en la 1ª palabra (arranque del sweep) ---
    if style == "karaoke":
        for i, ln in enumerate(lines):
            words = ln.split(); x = centered_x(words, font); y = y0 + i * line_h
            space = draw.textlength(" ", font=font)
            for j, w in enumerate(words):
                ww = draw.textlength(w, font=font)
                if i == 0 and j == 0:
                    draw.rounded_rectangle([x - 6, y + 4, x + ww + 6, y + line_h - int(line_h*0.18)],
                                           radius=10, fill=yellow)
                    draw.text((x, y), w, font=font, fill=(20, 20, 20, 255))
                else:
                    draw.text((x, y), w, font=font, fill=white, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
                x += ww + space
        return img

    # --- TYPEWRITER (look estático): blanco con cursor ▌ al final ---
    if style == "typewriter":
        for i, ln in enumerate(lines):
            ln2 = ln + ("▌" if i == len(lines) - 1 else "")
            x = (W - draw.textlength(ln2, font=font)) // 2; y = y0 + i * line_h
            draw.text((x, y), ln2, font=font, fill=white, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        return img

    # --- HORMOZI / YELLOW / RED / BOLD_OUTLINE: palabra por palabra con keyword resaltada ---
    kw_col = {"hormozi": yellow, "yellow_highlight": yellow, "red_highlight": red}.get(style, white)
    kws = keywords if style in ("hormozi", "yellow_highlight", "red_highlight") else set()
    for i, ln in enumerate(lines):
        words = ln.split(); x = centered_x(words, font); y = y0 + i * line_h
        _draw_words_line(draw, words, x, y, font, white, kw_col, kws, stroke)
    return img


def _render_wordgroup(group: list[dict], active: int, W: int, H: int, style: str,
                      cap_size: str = "mediano") -> Image.Image:
    """Dibuja un grupo corto de palabras (2-4) con la palabra ACTIVA resaltada (estilo adapta).

    Palabra por palabra: se muestran pocas palabras a la vez y la que se está diciendo se resalta.
    `cap_size`: pequeno | mediano (default) | grande.
    """
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    words = [_strip_emoji(w.get("word", "")) for w in group]
    words = [w for w in words if w]
    if not words:
        return img
    draw = ImageDraw.Draw(img)
    f = _tam(cap_size)
    text = " ".join(words)
    max_w = W - 2 * SAFE
    xbold = style in ("hormozi", "bounce", "wordpop")
    fontpath = _fontpath(xbold)
    disp = text.upper() if style in ("hormozi", "karaoke", "wordpop") else text
    # Más pequeño, líneas juntas y en el tercio INFERIOR (tapa menos el video)
    font, lines, line_h, size = _fit(draw, disp, fontpath, max_w, int(H * 0.165 * f), int(H * 0.046 * f),
                                     min_size=max(16, int(30 * f)))
    stroke = max(3, size // 8)
    total_h = line_h * len(lines)
    y0 = max(int(H * 0.60), min(int(H * 0.80) - total_h // 2, H - SAFE - total_h))
    yellow, red, white = (255, 214, 10, 255), (240, 60, 50, 255), (255, 255, 255, 255)
    accent = _ACCENT or (red if style == "red_highlight" else yellow)
    boxed = style in ("pill", "highlight_box", "karaoke")
    kws = _keywords(text) if style in ("hormozi", "yellow_highlight", "red_highlight") else set()

    # re-partir en líneas manteniendo el índice global de cada palabra
    disp_words = disp.split()
    idx = 0
    y = y0
    for ln in lines:
        ln_words = ln.split()
        wln = _line_width(draw, ln_words, font)
        x = (W - wln) // 2
        space = draw.textlength(" ", font=font)
        for w in ln_words:
            is_active = (idx == active)
            clean = w.strip(".,!?¡¿:;\"'()").upper()
            is_kw = clean in kws
            ww = draw.textlength(w, font=font)
            if is_active and boxed:
                draw.rounded_rectangle([x - 8, y + 4, x + ww + 8, y + line_h - int(line_h * 0.18)],
                                       radius=12, fill=accent)
                draw.text((x, y), w, font=font, fill=(20, 20, 20, 255))
            else:
                col = accent if (is_active or is_kw) else white
                draw.text((x, y), w, font=font, fill=col,
                          stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += ww + space
            idx += 1
        y += line_h
    return img


def burn_word_captions(inp: str, words: list[dict], work_dir: str, out: str,
                       style: str = "karaoke", group_size: int = 4,
                       cap_size: str = "mediano") -> str:
    """Quema subtítulos PALABRA POR PALABRA sincronizados (usa tiempos reales de ElevenLabs).

    Agrupa en bloques cortos (group_size) y resalta la palabra que se está diciendo. Estilo adapta.
    """
    words = [w for w in (words or []) if w.get("word", "").strip() and w.get("end", 0) > w.get("start", 0)]
    if not words:
        return inp
    # Ordenar por inicio: la clave para que NO se dupliquen (dos grupos a la vez).
    words = sorted(words, key=lambda w: float(w["start"]))
    info = probe(inp)
    W, H = info.width, info.height
    groups = [words[i:i + group_size] for i in range(0, len(words), group_size)]

    inputs, filt, last, n = ["-i", inp], [], "[0:v]", 0
    for gi, g in enumerate(groups):
        for j, w in enumerate(g):
            gidx = gi * group_size + j                      # índice GLOBAL en toda la lista
            start = float(w["start"])
            # fin = inicio de la SIGUIENTE palabra de TODA la lista (no solo del grupo) →
            # garantiza que en cada instante haya UN solo subtítulo visible (nunca duplicados).
            nxt = float(words[gidx + 1]["start"]) if gidx + 1 < len(words) else float(w["end"]) + 0.3
            end = max(start + 0.05, nxt)
            png = os.path.join(work_dir, f"wc_{n}.png")
            _render_wordgroup(g, j, W, H, style, cap_size).save(png)
            inputs += ["-i", png]
            filt.append(f"{last}[{n + 1}:v]overlay=0:0:enable='between(t,{start:.2f},{end:.2f})'[v{n}]")
            last = f"[v{n}]"; n += 1
    if n == 0:
        return inp
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt),
         "-map", last, "-map", "0:a?", "-c:a", "copy", *venc(),
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
    return out


def render_offer_pill(text: str, W: int, H: int) -> Image.Image:
    """Pill pequeña de OFERTA (Poppins) arriba-centro, sin tapar la cara, auto-ajustada."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text = _strip_emoji(text)
    if not text:
        return img
    draw = ImageDraw.Draw(img)
    size = int(H * 0.030)
    font = ImageFont.truetype(_fontpath(False), size)
    tw = draw.textlength(text.upper(), font=font)
    padx, pady = int(size * 0.7), int(size * 0.45)
    bw, bh = tw + 2 * padx, size + 2 * pady
    x = (W - bw) // 2; y = int(H * 0.11)         # bajo la parte superior (evita el notch/UI)
    draw.rounded_rectangle([x, y, x + bw, y + bh], radius=bh // 2, fill=(240, 60, 50, 255))
    draw.text((x + padx, y + pady - int(size*0.05)), text.upper(), font=font, fill=(255, 255, 255, 255))
    return img
