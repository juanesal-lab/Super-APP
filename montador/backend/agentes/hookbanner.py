"""
hookbanner.py — Agente HOOK-BANNER del Montador.

Genera el PNG de la "pill" amarilla de beneficio que se quema sobre el tercio
superior del video durante el gancho (mejora 7 de research/MEJORAS-FUTURAS.md,
validada con prototipos/hookbanner-muestra.png y hookbanner-sobre-video.jpg):
rectángulo redondeado #FFDE00, texto negro Poppins ExtraBold en UNA línea y
sombra sutil (pill negra difuminada desplazada 4px).

Este módulo SOLO genera el PNG con fondo 100% transparente; el editor ya cablea
el overlay (posición y=0.16·H, fade-in, visible durante el gancho completo).
El archivo se escribe como APNG —sigue siendo un PNG válido para cualquier
visor— para que el fade-in del editor funcione (ver comentario en generar()).

El texto puede empezar con un emoji ("🚚 Envío GRATIS hoy"): si el agente
backend.agentes.emoji está disponible se renderiza a color delante de las
palabras; si no está (o no puede con ese emoji), se quita y la pill sale solo
con el texto. Jamás debería tumbar el build: el editor ya envuelve en try.
"""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]        # raíz del repo (montador-ads/)
FUENTES = BASE / "assets" / "fonts"

AMARILLO = (255, 222, 0, 255)   # #FFDE00 — el mismo YEL de los subtítulos karaoke
NEGRO    = (0, 0, 0, 255)

ANCHO_MAX    = 940              # ancho máx de la pill (frame de 1080 con aire a los lados)
FUENTE_MAX   = 64               # rango de fuente validado en el prototipo
FUENTE_MIN   = 44
FUENTE_PISO  = 28               # último recurso: la pill JAMÁS se sale del frame
PAD_X, PAD_Y = 44, 26           # padding generoso dentro de la pill
GAP_EMOJI    = 0.30             # aire emoji→texto (fracción del tamaño de fuente)
EMOJI_ESCALA = 1.12             # el emoji se ve un pelín más grande que la fuente

SOMBRA_DESP  = 4                # sombra = pill negra difuminada desplazada 4px
SOMBRA_BLUR  = 10
SOMBRA_ALPHA = 90               # sutil: se lee sobre fondos claros sin ensuciar oscuros
MARGEN       = 36               # aire del canvas alrededor de la pill (respira la sombra)
SS           = 2                # supersampling: se dibuja a 2x y se baja con LANCZOS

# El PNG se guarda como APNG (PNG animado, 100% retrocompatible) — ver comentario
# grande en generar(). 8 frames de 33ms cubren de sobra el fade-in de 0.15s.
FRAMES_APNG  = 8
FRAME_MS     = 33

# ------------------------------------------------------------------ emojis
# Rangos prácticos de emoji (los mismos bloques de la lista blanca del agente
# emoji: caras/objetos/transporte, misceláneos, dingbats, estrellas ⭐, ‼️⁉️,
# selectores de variante, ZWJ y keycap).
_RANGOS_EMOJI = (
    (0x1F000, 0x1FAFF),
    (0x2600,  0x27BF),
    (0x2B00,  0x2BFF),
    (0x203C,  0x203C),
    (0x2049,  0x2049),
    (0xFE00,  0xFE0F),
    (0x200D,  0x200D),
    (0x20E3,  0x20E3),
)

def _es_char_emoji(ch):
    o = ord(ch)
    return any(a <= o <= b for a, b in _RANGOS_EMOJI)

def _separar_emoji_inicial(texto):
    """Si el texto empieza con emoji lo separa: '🚚 Envío…' → ('🚚', 'Envío…')."""
    t = texto.strip()
    i = 0
    while i < len(t) and _es_char_emoji(t[i]):
        i += 1
    return (t[:i] or None), t[i:].strip()

def _quitar_emojis(texto):
    """Quita TODO carácter emoji restante (Pillow los pintaría como tofu)."""
    limpio = "".join(ch for ch in texto if not _es_char_emoji(ch))
    return re.sub(r"\s+", " ", limpio).strip()

def _emoji_render(cluster, alto_px):
    """Imagen RGBA a color del emoji vía backend.agentes.emoji, o None.

    El agente emoji puede no existir todavía (cargar() devuelve None) o no
    soportar ese emoji: en ambos casos se devuelve None y la pill sale sin él.
    """
    from backend.agentes import cargar
    mod = cargar("emoji")
    if mod is None or not hasattr(mod, "emoji_png"):
        return None
    # se intenta tal cual, sin selector de variante (U+FE0F) y solo el 1er codepoint
    intentos = dict.fromkeys([cluster, cluster.replace("\ufe0f", ""), cluster[:1]])
    for intento in intentos:
        if not intento:
            continue
        try:
            img = mod.emoji_png(intento, int(alto_px))
        except Exception:
            img = None
        if img is not None:
            return img.convert("RGBA")
    return None

# ------------------------------------------------------------------ tipografía
def _fuente(sz):
    """Poppins ExtraBold con la misma cadena de fallbacks del editor."""
    from PIL import ImageFont
    for p in [FUENTES / "Poppins-ExtraBold.ttf", FUENTES / "Poppins-Bold.ttf",
              Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")]:
        try:
            return ImageFont.truetype(str(p), sz)
        except Exception:
            continue
    return ImageFont.load_default()

def _ancho_contenido(d, texto, f, sz_ss, emoji_aspecto):
    """Ancho del contenido (texto + emoji opcional + aire) a escala SS."""
    bb = d.textbbox((0, 0), texto, font=f)
    ancho = bb[2] - bb[0]
    if emoji_aspecto is not None:
        alto_emoji = int(sz_ss * EMOJI_ESCALA)
        ancho += int(alto_emoji * emoji_aspecto) + int(sz_ss * GAP_EMOJI)
    return ancho

# ------------------------------------------------------------------ API
def generar(texto: str, workdir) -> str | None:
    """PNG de la pill del banner (ancho máx ~940px, fondo 100% transparente).

    Devuelve la ruta (str) del PNG en workdir, o None si el texto queda vacío
    (por ejemplo si solo traía un emoji y el agente emoji no está disponible).
    """
    from PIL import Image, ImageDraw, ImageFilter

    texto = (texto or "").strip()
    if not texto:
        return None
    emoji_cluster, resto = _separar_emoji_inicial(texto)
    palabras = _quitar_emojis(resto if emoji_cluster else texto)
    if not palabras:
        return None

    # Emoji a color (una sola llamada, al tamaño más grande posible; luego solo
    # se REDUCE con LANCZOS — nunca se agranda, que se pixela).
    emoji_img = None
    if emoji_cluster:
        emoji_img = _emoji_render(emoji_cluster, FUENTE_MAX * EMOJI_ESCALA * SS)
    emoji_aspecto = (emoji_img.width / emoji_img.height) if emoji_img is not None else None

    # Tamaño de fuente: de 64 a 44 hasta que TODO quepa en una línea de ~940px.
    # Piso de emergencia 28 (textos larguísimos): antes de cortar, se encoge.
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    candidatos = (list(range(FUENTE_MAX, FUENTE_MIN - 1, -2)) +
                  list(range(FUENTE_MIN - 2, FUENTE_PISO - 1, -2)))
    limite = (ANCHO_MAX - 2 * PAD_X) * SS
    sz = candidatos[-1]
    for cand in candidatos:
        if _ancho_contenido(probe, palabras, _fuente(cand * SS), cand * SS, emoji_aspecto) <= limite:
            sz = cand
            break

    # ---- layout final (todo a escala SS) ----
    sz_ss = sz * SS
    f = _fuente(sz_ss)
    bb = probe.textbbox((0, 0), palabras, font=f)
    ancho_texto = bb[2] - bb[0]
    bb_ref = probe.textbbox((0, 0), "Ag", font=f)     # alto de línea de referencia
    alto_linea = bb_ref[3] - bb_ref[1]                # (estable entre textos distintos)
    alto_emoji = int(sz_ss * EMOJI_ESCALA) if emoji_img is not None else 0
    ancho_emoji = int(alto_emoji * emoji_aspecto) if emoji_img is not None else 0
    gap = int(sz_ss * GAP_EMOJI) if emoji_img is not None else 0

    pill_w = ancho_emoji + gap + ancho_texto + 2 * PAD_X * SS
    pill_h = max(alto_linea, alto_emoji) + 2 * PAD_Y * SS
    radio = int(pill_h * 0.40)                        # bien redondeada, como el prototipo
    margen = MARGEN * SS
    lienzo_w = pill_w + 2 * margen
    lienzo_h = pill_h + 2 * margen + SOMBRA_DESP * SS

    # ---- sombra: pill negra difuminada, desplazada 4px hacia abajo ----
    lienzo = Image.new("RGBA", (lienzo_w, lienzo_h), (0, 0, 0, 0))
    ImageDraw.Draw(lienzo).rounded_rectangle(
        (margen, margen + SOMBRA_DESP * SS, margen + pill_w, margen + SOMBRA_DESP * SS + pill_h),
        radius=radio, fill=(0, 0, 0, SOMBRA_ALPHA))
    lienzo = lienzo.filter(ImageFilter.GaussianBlur(SOMBRA_BLUR * SS))

    # ---- pill + contenido encima ----
    d = ImageDraw.Draw(lienzo)
    d.rounded_rectangle((margen, margen, margen + pill_w, margen + pill_h),
                        radius=radio, fill=AMARILLO)
    cx = margen + PAD_X * SS
    cy = margen + pill_h // 2
    if emoji_img is not None:
        em = emoji_img.resize((ancho_emoji, alto_emoji), Image.LANCZOS)
        lienzo.alpha_composite(em, (cx, cy - alto_emoji // 2))
        cx += ancho_emoji + gap
    d.text((cx - bb[0], cy - (bb[3] - bb[1]) // 2 - bb[1]), palabras, font=f, fill=NEGRO)

    # ---- bajar de 2x a 1x con LANCZOS (bordes y texto limpios) ----
    final = lienzo.resize((lienzo_w // SS, lienzo_h // SS), Image.LANCZOS)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    salida = workdir / "hookbanner.png"

    # ---- guardar como APNG (PNG animado, 100% retrocompatible) ----
    # GOTCHA REAL (verificado con el chain exacto del editor): el editor aplica
    # `fade=t=in:d=0.15:alpha=1` a este archivo antes del overlay. Un PNG estático
    # es UN solo frame en t=0 → el fade lo deja 100% transparente y overlay repite
    # ese frame invisible durante TODO el video (el banner jamás se vería). Con un
    # APNG de varios frames que cubren la ventana del fade, el fade-in anima de
    # verdad y el último frame (ya opaco) es el que overlay repite mientras el
    # enable esté encendido. Pillow colapsa frames idénticos consecutivos (y con
    # uno solo guarda un PNG plano), así que cada frame lleva un marcador
    # INVISIBLE: el pixel (0,0) del margen transparente con alpha 7…1; el último
    # frame — el que se ve todo el gancho — queda perfectamente limpio (alpha 0).
    frames = []
    for k in range(FRAMES_APNG):
        fr = final.copy()
        marca = FRAMES_APNG - 1 - k
        if marca:
            fr.putpixel((0, 0), (0, 0, 0, marca))
        frames.append(fr)
    try:
        frames[0].save(salida, save_all=True, append_images=frames[1:],
                       duration=FRAME_MS, loop=1)
    except Exception:
        final.save(salida)      # Pillow sin soporte APNG: PNG plano (mejor que nada)
    return str(salida)
