"""Generador de ADS DISRUPTIVOS de imagen.

Anthropic (Claude) = cerebro creativo: inventa 10 conceptos disruptivos + prompts siguiendo el estilo
de Juan (skill ads-disruptivos-imagen). Google AI (Nano Banana / gemini-2.5-flash-image) = generación
visual: convierte cada prompt en una imagen. Metes CUALQUIER producto -> 10 creativos listos.
"""
from __future__ import annotations

import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PIL import Image, ImageDraw, ImageFont, ImageOps

_CLAUDE = "claude-opus-4-8"
_IMG_MODEL = "gemini-2.5-flash-image"   # Nano Banana
_TXT_MODEL = "gemini-2.5-flash"         # para verificar ortografía del render

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FONT_XB = os.path.join(_BASE, "assets", "fonts", "Poppins-ExtraBold.ttf")
_FONT_B = os.path.join(_BASE, "assets", "fonts", "Poppins-Bold.ttf")


# ─────────────────────  COMPOSICIÓN DE TEXTO (fuentes reales, ortografía perfecta)  ───────────
def _hex(c, default=(17, 17, 17)):
    try:
        s = str(c).lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except (ValueError, TypeError):
        pass
    return default


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text, font_path, max_w, max_h, start=98, mins=38):
    """Encuentra el tamaño de fuente que hace caber `text` (con word-wrap) en max_w x max_h."""
    for size in range(start, mins - 1, -2):
        font = ImageFont.truetype(font_path, size)
        lines = _wrap(draw, text, font, max_w)
        lh = size * 1.12
        if all(draw.textlength(l, font=font) <= max_w for l in lines) and len(lines) * lh <= max_h:
            return font, lines, lh
    font = ImageFont.truetype(font_path, mins)
    return font, _wrap(draw, text, font, max_w), mins * 1.12


def _star(draw, cx, cy, r, fill=(255, 196, 0, 255)):
    pts = []
    for i in range(10):
        rr = r if i % 2 == 0 else r * 0.45
        a = math.pi * 2 * i / 10 - math.pi / 2
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    draw.polygon(pts, fill=fill)


def _stars(draw, cx, y, rating="4.9/5.0"):
    r, gap = 18, 45
    rf = ImageFont.truetype(_FONT_XB, 36)
    rtw = draw.textlength(rating, font=rf)
    x = cx - (gap * 5 + 16 + rtw) / 2
    for k in range(5):
        _star(draw, x + k * gap + r, y, r)
    draw.text((x + gap * 5 + 14, y - 20), rating, font=rf, fill=(255, 255, 255, 255))


def _starburst(draw, cx, cy, r, text, fill=(226, 29, 46, 255)):
    pts = []
    for i in range(28):
        rr = r if i % 2 == 0 else r * 0.74
        a = math.pi * 2 * i / 28 - math.pi / 2
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    draw.polygon(pts, fill=fill)
    lines = text.upper().split()
    f = ImageFont.truetype(_FONT_XB, int(r * 0.46))
    ly = cy - len(lines) * int(r * 0.26)
    for l in lines:
        lw = draw.textlength(l, font=f)
        draw.text((cx - lw / 2, ly), l, font=f, fill=(255, 255, 255, 255))
        ly += int(r * 0.52)


def _play_button(draw, cx, cy, r):
    """Botón de play falso estilo YouTube (el sello de Juan)."""
    w, h = int(r * 1.5), int(r * 1.05)
    draw.rounded_rectangle([cx - w, cy - h, cx + w, cy + h], radius=int(h * 0.3), fill=(230, 33, 23, 240))
    t = int(r * 0.6)
    draw.polygon([(cx - t * 0.42, cy - t), (cx - t * 0.42, cy + t), (cx + t * 0.85, cy)], fill=(255, 255, 255, 255))


def _arrow(draw, x1, y1, x2, y2, color=(255, 196, 0, 255), w=18):
    draw.line([x1, y1, x2, y2], fill=color, width=w)
    ang = math.atan2(y2 - y1, x2 - x1)
    s = 40
    draw.polygon([(x2, y2),
                  (x2 - s * math.cos(ang - 0.5), y2 - s * math.sin(ang - 0.5)),
                  (x2 - s * math.cos(ang + 0.5), y2 - s * math.sin(ang + 0.5))], fill=color)


def _cursor_hand(draw, x, y, s=46):
    """Cursor-mano blanco (per skill: 'cursor-mano blanca tocando')."""
    pts = [(x, y), (x, y + s), (x + s * 0.28, y + s * 0.72), (x + s * 0.44, y + s),
           (x + s * 0.60, y + s * 0.92), (x + s * 0.44, y + s * 0.64), (x + s * 0.72, y + s * 0.64)]
    draw.polygon(pts, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))


def _play_bar(draw, W, cy):
    _play_button(draw, W // 2, cy, 96)
    py = cy + 150
    draw.line([150, py, W - 150, py], fill=(255, 255, 255, 180), width=5)
    draw.ellipse([150 - 9, py - 9, 150 + 9, py + 9], fill=(255, 255, 255, 255))
    tf = ImageFont.truetype(_FONT_B, 30)
    draw.text((150, py - 46), "0:00 / 2:47", font=tf, fill=(255, 255, 255, 235))


def _quiz(draw, W, y, opciones=None):
    """Fila de pastillas tipo quiz con cursor-mano en una (per skill: selector/quiz)."""
    opciones = [o for o in (opciones or []) if o][:6] or ["MENOS DE 30", "30-39", "40-49", "50-59", "60-69", "70+"]
    f = ImageFont.truetype(_FONT_B, 26)
    ph, gap = 68, 16
    widths = [max(ph, draw.textlength(o.upper(), font=f) + 40) for o in opciones]
    total = sum(widths) + gap * (len(opciones) - 1)
    if total > W - 30:   # reparte en 2 filas si no cabe
        return _quiz_rows(draw, W, y, opciones, f, ph, gap, widths)
    x = (W - total) // 2
    for k, (o, w) in enumerate(zip(opciones, widths)):
        draw.rounded_rectangle([x, y, x + w, y + ph], radius=ph // 2, fill=(18, 28, 44, 240), outline=(255, 255, 255, 110), width=2)
        tw = draw.textlength(o.upper(), font=f)
        draw.text((x + (w - tw) / 2, y + (ph - 30) / 2), o.upper(), font=f, fill=(255, 255, 255, 255))
        if k == len(opciones) // 2:
            _cursor_hand(draw, int(x + w / 2 - 10), y + ph - 16)
        x += w + gap


def _quiz_rows(draw, W, y, opciones, f, ph, gap, widths):
    mid = (len(opciones) + 1) // 2
    for r, chunk in enumerate((opciones[:mid], opciones[mid:])):
        ws = [max(ph, draw.textlength(o.upper(), font=f) + 40) for o in chunk]
        total = sum(ws) + gap * (len(chunk) - 1)
        x = (W - total) // 2
        yy = y + r * (ph + 14)
        for k, (o, w) in enumerate(zip(chunk, ws)):
            draw.rounded_rectangle([x, yy, x + w, yy + ph], radius=ph // 2, fill=(18, 28, 44, 240), outline=(255, 255, 255, 110), width=2)
            tw = draw.textlength(o.upper(), font=f)
            draw.text((x + (w - tw) / 2, yy + (ph - 30) / 2), o.upper(), font=f, fill=(255, 255, 255, 255))
            if r == 0 and k == len(chunk) // 2:
                _cursor_hand(draw, int(x + w / 2 - 10), yy + ph - 16)
            x += w + gap


def _slider(draw, W, cy):
    """Slider antes/después: línea vertical + manija + ◄► + ANTES/DESPUÉS (per skill)."""
    lx = W // 2
    top, bot = cy - 250, cy + 250
    draw.line([lx, top, lx, bot], fill=(255, 255, 255, 240), width=8)
    r = 46
    draw.ellipse([lx - r, cy - r, lx + r, cy + r], fill=(255, 255, 255, 255))
    draw.polygon([(lx - 22, cy), (lx - 6, cy - 13), (lx - 6, cy + 13)], fill=(40, 40, 40, 255))
    draw.polygon([(lx + 22, cy), (lx + 6, cy - 13), (lx + 6, cy + 13)], fill=(40, 40, 40, 255))
    f = ImageFont.truetype(_FONT_XB, 34)
    for txt, cx in [("ANTES", lx - 175), ("DESPUÉS", lx + 175)]:
        tw = draw.textlength(txt, font=f)
        draw.rounded_rectangle([cx - tw / 2 - 16, top - 8, cx + tw / 2 + 16, top + 44], radius=10, fill=(0, 0, 0, 190))
        draw.text((cx - tw / 2, top), txt, font=f, fill=(255, 255, 255, 255))


def _chat_bubbles(draw, W, cy):
    """Chat de WhatsApp falso: burbujas verdes + doble check (per skill)."""
    f = ImageFont.truetype(_FONT_B, 30)
    msgs = [("¿Qué te tomaste? te ves increíble", False), ("😍 en serio, cuéntame", False),
            ("nada... solo esto 👇", True)]
    y = cy - 120
    for txt, mine in msgs:
        tw = draw.textlength(txt, font=f) + 40
        if mine:
            x = W - 90 - tw
            draw.rounded_rectangle([x, y, x + tw, y + 62], radius=18, fill=(37, 211, 102, 240))
        else:
            x = 90
            draw.rounded_rectangle([x, y, x + tw, y + 62], radius=18, fill=(245, 245, 245, 240))
        draw.text((x + 20, y + 14), txt, font=f, fill=(20, 20, 20, 255))
        y += 82


def componer_ad(scene_path: str, out_path: str, *, titular: str, sub: str = "", cta: str = "VER PRECIO",
                precio: str = "", ofertas: list[str] | None = None, formato: str = "",
                quiz_opciones: list | None = None,
                banda_hex: str = "#0B1E3B", cta_hex: str = "#E11D2E", rating: str = "4.9/5.0",
                cod: bool = True, W: int = 1080, H: int = 1350) -> str:
    """Compone un ad direct-response CARGADO (estilo Juan): titular + play falso + ⭐ + oferta + CTA + COD."""
    ofertas = [o for o in (ofertas or []) if o]
    img = ImageOps.fit(Image.open(scene_path).convert("RGB"), (W, H), Image.LANCZOS)
    draw = ImageDraw.Draw(img, "RGBA")
    band = _hex(banda_hex, (11, 30, 59))

    # HEADER: banda de color + titular (auto-fit, Poppins ExtraBold) + sub
    pad = 46
    font, lines, lh = _fit(draw, (titular or "").upper(), _FONT_XB, W - 2 * pad, H * 0.22, start=96, mins=42)
    sub_h = 46 if sub else 0
    header_h = int(len(lines) * lh + pad * 1.2 + sub_h)
    draw.rectangle([0, 0, W, header_h], fill=band + (235,))
    draw.rectangle([0, header_h, W, header_h + 7], fill=(255, 196, 0, 255))   # línea acento
    y = int(pad * 0.6)
    for l in lines:
        w = draw.textlength(l, font=font)
        draw.text(((W - w) // 2, y), l, font=font, fill=(255, 255, 255, 255))
        y += int(lh)
    if sub:
        sf = ImageFont.truetype(_FONT_B, 37)
        sw = draw.textlength(sub, font=sf)
        draw.text(((W - sw) // 2, y + 2), sub, font=sf, fill=(255, 214, 10, 255))

    # ELEMENTO FALSO-INTERACTIVO (el sello de Juan) — dispatch según formato de la skill
    fmt = (formato or "").lower()
    cy = int(H * 0.47)
    if any(k in fmt for k in ("slider", "antes", "despu", "before", "desliza")):
        _slider(draw, W, cy)
    elif any(k in fmt for k in ("quiz", "selector", "pastilla", "edad", "test", "calcula")):
        _quiz(draw, W, header_h + 34, quiz_opciones)
    elif any(k in fmt for k in ("chat", "whatsapp", "mensaje", "conversa")):
        _chat_bubbles(draw, W, cy)
    else:   # falso play ▶ por defecto (el más usado)
        _play_bar(draw, W, cy)

    # STARBURST de oferta (esquina sup-der, debajo del header)
    if ofertas:
        _starburst(draw, W - 118, header_h + 118, 96, ofertas[0])

    # FOOTER (de abajo hacia arriba): COD band -> precio -> CTA pill+flecha -> estrellas
    yb = H
    if cod:
        draw.rectangle([0, yb - 74, W, yb], fill=(10, 10, 10, 235))
        cf = ImageFont.truetype(_FONT_XB, 44)
        ct = "PAGO CONTRA ENTREGA"
        cw = draw.textlength(ct, font=cf)
        draw.text(((W - cw) // 2, yb - 62), ct, font=cf, fill=(255, 214, 10, 255))
        yb -= 74
    if precio:
        pf = ImageFont.truetype(_FONT_XB, 46)
        pw = draw.textlength(precio, font=pf)
        draw.text(((W - pw) // 2, yb - 60), precio, font=pf, fill=(255, 255, 255, 255))
        # sombra suave detrás
        yb -= 74
    # CTA pill + flecha
    cf = ImageFont.truetype(_FONT_XB, 46)
    ctatxt = (cta or "VER PRECIO").upper()
    cw = draw.textlength(ctatxt, font=cf)
    bh, bw = 98, int(cw + 120)
    bx, by = (W - bw) // 2, yb - bh - 8
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2, fill=_hex(cta_hex, (225, 29, 46)) + (255,))
    draw.text((bx + (bw - cw) // 2, by + (bh - 54) // 2), ctatxt, font=cf, fill=(255, 255, 255, 255))
    _arrow(draw, bx + bw + 78, by - 34, bx + bw + 14, by + bh // 2)   # flecha amarilla al CTA
    yb = by - 16
    # estrellas + rating
    _stars(draw, W // 2, yb - 24, rating)

    img.convert("RGB").save(out_path, quality=92)
    return out_path

# Estilo de Juan destilado (skill ads-disruptivos-imagen) + sus 5 ads ganadores -> cerebro creativo.
_SISTEMA = """Eres el MEJOR DIRECTOR DE ARTE de ads de IMAGEN para dropshipping en Colombia (pago \
contraentrega). Conviertes un producto en creativos ESTÁTICOS que FRENAN EL SCROLL: ideas SURREALES, \
arriesgadas, casi ABSURDAS, con el texto del anuncio YA INCRUSTADO en la MISMA imagen (todo lo dibuja el \
generador). El generador escribe bien el texto SOLO si se lo das corto, exacto y entre comillas.

⭐ NIVEL EXIGIDO — estos 5 fueron ÉXITOS REALES del operador (producto: gotas para la RETENCIÓN DE LÍQUIDOS). \
Este es el LISTÓN; iguálalo o supéralo. Fíjate lo surreales y relatables que son:
1. «¿AMANECES SINTIÉNDOTE UN HIPOPÓTAMO?» — mujer en pijama rosa frente al espejo y su REFLEJO es un \
HIPOPÓTAMO con la misma pijama. Sub: "No es peso. Es líquido retenido." → personificación surreal.
2. «¿PARA CUÁNDO EL BEBÉ?» — en un bus lleno un viejito le cede el asiento señalando su barriga hinchada; \
ella roja de vergüenza. Sub: "No estoy embarazada. Estoy inflamada." → escena vergonzosa social.
3. «MI JEAN SE RINDIÓ A LAS 4:37 PM» — el botón del jean salió disparado e quedó incrustado en la pared \
agrietada como una BALA, con marcador forense "evidencia #1". Sub: "La hinchazón de la tarde es real." → \
consecuencia absurda.
4. «NO ESTOY GORDA. ESTOY INFLADA.» — una amiga le saca un TAPÓN a la barriga de otra y la DESINFLA como \
globo (aire saliendo, papeles volando). CTA: "DESINFLARME YA". → metáfora literal extrema.
5. «A LAS 6PM YA ESTOY FLOTANDO» — antes/después 6:00 AM (normal) vs 6:00 PM (inflada como globo FLOTANDO \
al techo, la familia la sostiene con cuerdas en la cena). → antes/después imposible.

Son SURREALES pero SIEMPRE conectadas al dolor real; dan risa, vergüenza o miedo; y JAMÁS muestran un frasco \
sobre fondo blanco. ESE es el nivel. Nada tibio, obvio ni de catálogo.

LOS 6 MOTORES para inventar (usa uno DISTINTO por concepto, sin repetir):
personificación del dolor · metáfora literal extrema · consecuencia absurda · escena social vergonzosa · \
objeto/reflejo surreal · reacción facial extrema o antes/después imposible.

FÓRMULA VISUAL (todo en la MISMA imagen, de arriba a abajo):
1. Banda de color sólido arriba con el TITULAR en MAYÚSCULAS gruesas blancas (pregunta, shock o frase-gancho).
2. La ESCENA surreal fotorrealista (DSLR o UGC iPhone; nada de render plástico) — el HÉROE de la pieza.
3. UN elemento falso-interactivo (el sello): botón de play ▶ translúcido + barra de progreso "0:12 / 1:58"; \
o slider antes/después con manija redonda + flechas ◄►; o cursor-mano blanco tocando algo.
4. Franja blanca con el SUB en negrita oscura; y tercio inferior: el PRODUCTO pequeño (frasco ámbar), un \
BOTÓN redondeado (amarillo o rojo) con el CTA + cursor-mano blanco a punto de tocar, y el precio/oferta.

CUMPLIMIENTO Meta: nada de curas absolutas ni % médicos ("ayuda a / apoya el bienestar"). El antes/después \
o la transformación se hace SURREAL/metafórico (globo, hipopótamo), NUNCA un split clínico enfermo→sano de \
cuerpo/rostro. Sin desnudez ni sexo explícito: el shock es por drama y metáfora, no por piel.

Cada 'prompt' que entregues:
- UN SOLO párrafo en INGLÉS, fotorrealista, empieza con "Bold direct-response Facebook ad, 4:5 vertical, \
photorealistic." y describe la escena surreal + sujeto + emoción + el elemento falso-interactivo con \
precisión + el frasco ámbar pequeño abajo.
- Los TEXTOS incrustados van LITERALES en español (colombiano, tuteo), entre comillas, CORTOS, con su \
ubicación exacta (banda superior, franja, botón, precio). No inventes texto largo.
- Termina SIEMPRE con: thick sans-serif fonts, high contrast, saturated colors, professional \
direct-response ad composition, render all embedded text crisply and spelled exactly as written. Avoid: \
extra fingers, deformed hands, garbled or misspelled text, random logos, watermarks, nudity, low-res artifacts.

Devuelve EXACTAMENTE 10 variantes, 10 mecanismos/escenas MUY distintos, todas al nivel de los 5 ejemplos."""

_TOOL = {
    "name": "entregar_creativos",
    "description": "Entrega las 10 variantes de creativo disruptivo de imagen.",
    "input_schema": {
        "type": "object",
        "properties": {
            "variantes": {
                "type": "array",
                "description": "Exactamente 10 variantes, cada una con ángulo y formato DISTINTO.",
                "items": {
                    "type": "object",
                    "properties": {
                        "angulo": {"type": "string", "description": "nombre corto del ángulo de venta"},
                        "formato": {"type": "string", "description": "formato falso-interactivo usado"},
                        "concepto": {"type": "string", "description": "la idea loca en 1-2 frases (español)"},
                        "por_que": {"type": "string", "description": "por qué frena el scroll y convierte"},
                        "titular": {"type": "string", "description": "titular incrustado (español, corto, MAYÚSCULAS)"},
                        "apoyo": {"type": "string", "description": "sub/apoyo (español, opcional)"},
                        "precio_cta": {"type": "string", "description": "precio+oferta COD (opcional)"},
                        "boton_cta": {"type": "string", "description": "texto del botón/CTA falso"},
                        "prompt": {"type": "string", "description": "prompt de imagen (ver instrucciones del sistema)"},
                    },
                    "required": ["angulo", "formato", "concepto", "por_que", "titular", "prompt"],
                },
            }
        },
        "required": ["variantes"],
    },
}

# Cola de calidad que se pega al final de cada prompt de imagen.
_CIERRE = (" Thick bold sans-serif fonts, high contrast, saturated colors, professional direct-response "
           "advertising composition, 4:5 vertical aspect ratio, render all embedded text crisply and "
           "spelled EXACTLY as written. Avoid: extra fingers, deformed hands, garbled or misspelled text, "
           "random logos, watermarks, nudity, low-resolution artifacts.")


# ─────────────────────  V2: 6 ángulos con escena LIMPIA + datos para componer texto  ──────────
_SISTEMA_V2 = """Eres un DIRECTOR DE ARTE DISRUPTIVO para ads de IMAGEN de dropshipping en Colombia (COD).
Tu trabajo: convertir un producto en 10 conceptos que FRENAN EL SCROLL — ideas extraordinarias, exageradas,
casi ABSURDAS (pattern-interrupt), MUY DIFERENTES entre sí, que la gente no puede ignorar.

CLAVE (arquitectura nueva): el TEXTO del anuncio (titular, CTA, precio, ofertas) NO va dentro de la imagen
generada — se compone aparte con fuentes reales. Así que el `escena_prompt` debe describir SOLO LA ESCENA
VISUAL disruptiva, en INGLÉS, SIN NINGÚN TEXTO, letra, cartel ni palabra en la imagen (dilo explícito:
"absolutely no text, no letters, no words"). Deja aire arriba y abajo del encuadre para poner el texto luego.

REGLAS DE ORO:
- Cada concepto debe ser DISTINTO en mecanismo (miedo, deseo, humor, metáfora surreal, prueba/autoridad,
  curiosidad, comparación/precio) y en ESCENA. Nada de 6 versiones parecidas — literalmente muy diferentes.
- Dramatiza el dolor/deseo hasta lo absurdo. Metáforas LITERALES y extremas (ojeras = maletas, piel = cuero
  agrietado, dolor = ladrillo). Lo inesperado gana. PROHIBIDO el "frasco sobre fondo blanco + persona feliz".
- COHERENCIA: la escena debe TENER SENTIDO y conectar con el dolor/deseo real del producto (raro con
  propósito, no raro porque sí). Usa el contexto de la página de venta si te lo doy.
- HÉROE VISCERAL Y DRAMÁTICO como los ads que de verdad funcionan: anatomía extrema (corazón con arterias
  tapadas de grasa, próstata inflamada y brillante), cuerpo/piel llevados al límite de la metáfora (piel =
  cuero agrietado), o escena emocional UGC MUY relatable (la persona mirándose al espejo con el problema
  encima, cara de angustia). Fotorrealista DSLR o UGC iPhone, ALTÍSIMO impacto — nada tibio ni "bonito de
  catálogo". El resultado será un ad CARGADO (el botón de play falso, estrellas, oferta, flecha y COD se
  ponen ENCIMA aparte), así que la escena debe ser un HERO potente que deje aire arriba y abajo.
- Además del titular, ELIGE el `formato` falso-interactivo (el sello de Juan) que se dibuja ENCIMA. Usa
  EXACTAMENTE uno de estos 4 y VÁRIALOS entre las 10 (no todos iguales): "falso play" (botón ▶ + barra de
  progreso — el más usado), "quiz" (fila de pastillas con cursor-mano; SI eliges quiz, da `quiz_opciones`:
  4-6 opciones cortas tipo rangos de edad o síntomas), "slider antes/después" (para transformación de
  objeto/estado), "chat" (testimonio tipo WhatsApp). Que el formato encaje con el ángulo.

CUMPLIMIENTO Meta: nada de curas absolutas ni % médicos; antes/después de cuerpo/rostro insinuado (no split
clínico); sin desnudez ni contenido sexual explícito (shock por drama/metáfora, no por piel).

Para cada concepto das: el ángulo, la escena (prompt visual sin texto), y el TEXTO en español colombiano
(tuteo, corto) para componer: titular (gancho, MAYÚSCULAS), sub opcional, CTA ("VER PRECIO", "TOCA PARA
VER", "DESLIZA Y MIRÁ"), y 2 colores hex (banda del titular, botón CTA) que combinen con la escena y con
alto contraste. Devuelve EXACTAMENTE 10 conceptos, todos MUY diferentes entre sí."""

_TOOL_V2 = {
    "name": "proponer_conceptos",
    "description": "Propone 10 conceptos disruptivos (escena limpia + texto para componer).",
    "input_schema": {
        "type": "object",
        "properties": {
            "conceptos": {
                "type": "array",
                "description": "Exactamente 10 conceptos, MUY diferentes entre sí (mecanismo y escena distintos).",
                "items": {
                    "type": "object",
                    "properties": {
                        "angulo": {"type": "string", "description": "nombre corto del ángulo de venta"},
                        "mecanismo": {"type": "string", "description": "miedo/deseo/humor/metáfora/prueba/curiosidad/precio"},
                        "formato": {"type": "string", "description": "formato falso-interactivo EXACTO, uno de: 'falso play' | 'quiz' | 'slider antes/después' | 'chat'. Varía entre las 10."},
                        "quiz_opciones": {"type": "array", "items": {"type": "string"}, "description": "SOLO si formato='quiz': 4-6 opciones cortas de la fila de pastillas (ej. rangos de edad, síntomas). Vacío en otros formatos."},
                        "concepto": {"type": "string", "description": "la idea visual disruptiva en 1 frase (español)"},
                        "por_que": {"type": "string", "description": "por qué frena el scroll y convierte"},
                        "escena_prompt": {"type": "string", "description": "prompt VISUAL en inglés, SIN texto/letras en la imagen"},
                        "titular": {"type": "string", "description": "titular para componer (español, corto, MAYÚSCULAS)"},
                        "sub": {"type": "string", "description": "sub/apoyo opcional (español, corto)"},
                        "cta": {"type": "string", "description": "texto del botón CTA (español)"},
                        "banda_hex": {"type": "string", "description": "color hex de la banda del titular"},
                        "cta_hex": {"type": "string", "description": "color hex del botón CTA"},
                    },
                    "required": ["angulo", "mecanismo", "formato", "concepto", "escena_prompt", "titular", "cta"],
                },
            }
        },
        "required": ["conceptos"],
    },
}


def generar_conceptos_v2(producto: str, page_text: str, ofertas: list[str],
                         anthropic_key: str) -> list[dict]:
    """Claude propone 6 conceptos v2 (escena limpia + texto para componer). Devuelve [] si falla."""
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key)
        ctx = f"PRODUCTO: {producto}\n"
        if (page_text or "").strip():
            ctx += f"PÁGINA DE VENTA (contexto real del producto):\n{page_text.strip()[:2800]}\n"
        if ofertas:
            ctx += f"OFERTAS que se mostrarán (no las metas en la escena, se componen aparte): {', '.join(ofertas)}\n"
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=8000, system=_SISTEMA_V2,
            tools=[_TOOL_V2], tool_choice={"type": "tool", "name": "proponer_conceptos"},
            messages=[{"role": "user", "content": ctx + "\nPropón 10 conceptos disruptivos MUY diferentes "
                       "(cada uno con mecanismo Y escena distintos, tipo tus mejores ads)."}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "proponer_conceptos":
                return list(block.input.get("conceptos", []))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Conceptos v2 (Claude) no disponibles: {e}")
    return []


def generar_ad_compuesto(concepto: dict, out_path: str, *, gemini_key: str, precio: str = "",
                         ofertas: list[str] | None = None, product_image_path: str | None = None) -> str | None:
    """Genera la ESCENA (Nano Banana, sin texto) y le COMPONE el texto con fuentes reales."""
    scene = out_path + ".scene.png"
    sp = concepto.get("escena_prompt", "") + " Absolutely no text, no letters, no words, no captions anywhere."
    img = generar_imagen(sp, gemini_key, scene, product_image_path)
    if not img:
        return None
    try:
        componer_ad(scene, out_path,
                    titular=concepto.get("titular", ""), sub=concepto.get("sub", ""),
                    cta=concepto.get("cta", "VER PRECIO"), precio=precio, ofertas=ofertas,
                    formato=concepto.get("formato", "") or concepto.get("mecanismo", ""),
                    quiz_opciones=concepto.get("quiz_opciones") or None,
                    banda_hex=concepto.get("banda_hex", "#0B1E3B"),
                    cta_hex=concepto.get("cta_hex", "#E11D2E"))
        try:
            os.remove(scene)
        except OSError:
            pass
        return out_path
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Composición falló: {e}")
        return scene   # al menos la escena


def generar_conceptos(producto: str, anthropic_key: str, page_text: str = "",
                      ofertas: list[str] | None = None, precio: str = "",
                      mercado: str = "Colombia · español colombiano · pago contraentrega (COD)") -> list[dict]:
    """Claude inventa las 10 variantes full-prompt (concepto + copy + prompt rico). Devuelve [] si falla."""
    ofertas = [o for o in (ofertas or []) if o]
    ctx = f"PRODUCTO: {producto}\nMERCADO: {mercado}\n"
    if page_text.strip():
        ctx += f"\nCONTEXTO DE LA PÁGINA DE VENTA (para entender dolor/beneficio real):\n{page_text[:2500]}\n"
    if ofertas:
        ctx += f"\nOFERTAS a incrustar en el precio (úsalas): {', '.join(ofertas)}\n"
    if precio.strip():
        ctx += (f"\nPRECIO: {precio.strip()} — inclúyelo en la línea de precio junto con la oferta y "
                "'Paga al recibir' / 'Pago contraentrega'.\n")
    else:
        ctx += ("\nSIN PRECIO: NO pongas ninguna cifra de precio en la imagen. El CTA NO debe decir "
                "'VER PRECIO' (usa 'TOCA PARA VER', 'PEDIR AHORA', 'DESLIZA Y MIRA', etc.); si hay oferta "
                "(ej. 2x1) sí puedes mostrarla, pero sin cifra.\n")
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key)
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=16000, system=_SISTEMA,
            tools=[_TOOL], tool_choice={"type": "tool", "name": "entregar_creativos"},
            messages=[{"role": "user", "content":
                       ctx + "\nInventa las 10 variantes disruptivas al nivel de los 5 ejemplos "
                       "(mecanismos y escenas distintos, todas surreales y arriesgadas)."}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "entregar_creativos":
                return list(block.input.get("variantes", []))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Conceptos (Claude) no disponibles: {e}")
    return []


def _norm_words(s: str) -> set[str]:
    """Palabras normalizadas (sin tildes, MAYÚS, solo letras/números) de ≥3 chars, para comparar."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return {w for w in re.sub(r"[^A-Z0-9]", " ", s).split() if len(w) >= 3}


def _verificar_ortografia(img_path: str, textos: list[str], gemini_key: str) -> tuple[bool, list[str]]:
    """¿El texto GRANDE del ad quedó bien escrito? (ok, lista_de_malos).

    Truco anti-'auto-corrección': en vez de preguntar '¿está bien?' (el modelo lee lo que ESPERA, no lo
    que hay), le pedimos TRANSCRIBIR LITERAL letra por letra y comparamos palabra por palabra con lo
    esperado. Si una palabra esperada (≥3 letras) no aparece transcrita → mal escrita. Ante cualquier
    fallo devuelve ok=True (no bloquea la entrega)."""
    textos = [t.strip() for t in textos if t and t.strip()]
    if not textos or not gemini_key:
        return True, []
    try:
        from google import genai
        from google.genai import types
        with open(img_path, "rb") as f:
            ib = f.read()
        prompt = (
            "Transcribe LITERALMENTE, copiando los glifos EXACTOS aunque una palabra quede mal escrita o "
            "sin sentido (NO corrijas ni completes nada), TODO el texto GRANDE de este anuncio: el titular "
            "de la banda superior, el subtítulo, el botón y la línea de precio. IGNORA la etiqueta pequeña "
            'del frasco. Responde SOLO JSON: {"lineas":["...","...","..."]}')
        cl = genai.Client(api_key=gemini_key)
        resp = cl.models.generate_content(
            model=_TXT_MODEL, contents=[prompt, types.Part.from_bytes(data=ib, mime_type="image/png")])
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not m:
            return True, []
        lineas = json.loads(m.group(0)).get("lineas") or []
        vistas = set()
        for ln in lineas:
            vistas |= _norm_words(str(ln))
        malos = []
        for t in textos:
            faltan = _norm_words(t) - vistas
            if faltan:                         # alguna palabra esperada NO se transcribió igual → mal
                malos.append(t)
        return (len(malos) == 0), malos
    except Exception:  # noqa: BLE001
        return True, []


def generar_ad_fullprompt(variant: dict, out_path: str, *, gemini_key: str,
                          product_image_path: str | None = None, verify: bool = True,
                          max_regen: int = 2) -> str | None:
    """Genera el ad COMPLETO desde el prompt rico (Nano Banana dibuja TODO incl. texto). Verifica la
    ortografía del render y REGENERA si sale mal (hasta max_regen veces). Devuelve la ruta o None."""
    prompt = variant.get("prompt", "")
    if not prompt:
        return None
    textos = [variant.get("titular", ""), variant.get("apoyo", ""),
              variant.get("boton_cta", ""), variant.get("precio_cta", "")]
    last = None
    for intento in range(max_regen + 1):
        p = prompt if intento == 0 else (
            prompt + f" IMPORTANT (retry {intento}): make ABSOLUTELY every letter of the Spanish embedded "
            "text correct, complete and legible; do not misspell or repeat letters.")
        img = generar_imagen(p, gemini_key, out_path, product_image_path)
        if not img:
            return last          # error de generación (créditos/bloqueo) -> no insiste
        last = img
        if not verify:
            return img
        ok, _ = _verificar_ortografia(out_path, textos, gemini_key)
        if ok:
            return img
    return last                  # devuelve el último aunque no sea perfecto (mejor algo que nada)


def generar_ads_fullprompt(variants: list[dict], work_dir: str, *, gemini_key: str,
                           product_image_path: str | None = None,
                           progress: Callable[[str, int], None] | None = None) -> dict:
    """Paso 2 (full-prompt): para los conceptos ELEGIDOS genera el ad completo + verifica/regenera. Nunca lanza."""
    def rep(m, p):
        if progress:
            progress(m, int(p))

    os.makedirs(work_dir, exist_ok=True)
    if not gemini_key:
        return {"ok": False, "error": "Falta la API key de Gemini para generar las imágenes."}
    n = len(variants)
    done = [0]
    rep(f"Generando {n} ads completos con Google AI (revisando ortografía)...", 8)

    def _one(item):
        i, v = item
        out = os.path.join(work_dir, f"ad_{i:02d}.png")
        try:
            v["imagen"] = generar_ad_fullprompt(v, out, gemini_key=gemini_key,
                                                product_image_path=product_image_path)
        except Exception as e:  # noqa: BLE001
            v["imagen"] = None
            v["error"] = str(e)[:150]
        done[0] += 1
        rep(f"Ad {done[0]}/{n} listo...", 8 + int(done[0] / max(1, n) * 88))
        return v

    with ThreadPoolExecutor(max_workers=3) as ex:   # poca concurrencia por el rate-limit de Gemini
        variants = list(ex.map(_one, enumerate(variants)))
    ok = [v for v in variants if v.get("imagen")]
    rep("Listo", 100)
    return {"ok": True, "variantes": variants, "n_ok": len(ok), "n_total": n}


def generar_imagen(prompt: str, gemini_key: str, out_path: str,
                   product_image_path: str | None = None, tries: int = 4) -> str | None:
    """Nano Banana convierte el prompt en imagen (usa la foto del producto como referencia si hay).

    Reintenta ante errores transitorios de Google (500 INTERNAL / 503 / 429) con backoff."""
    import time
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=gemini_key)
    if product_image_path and os.path.exists(product_image_path):
        with open(product_image_path, "rb") as f:
            pb = f.read()
        mime = "image/png" if product_image_path.lower().endswith(".png") else "image/jpeg"
        contents = ["Use the product shown in this reference image (respect its exact shape, color and "
                    "label) placed into the following ad scene. " + prompt + _CIERRE,
                    types.Part.from_bytes(data=pb, mime_type=mime)]
    else:
        contents = [prompt + _CIERRE]

    for attempt in range(tries):
        try:
            resp = client.models.generate_content(model=_IMG_MODEL, contents=contents)
            for p in resp.candidates[0].content.parts:
                if getattr(p, "inline_data", None):
                    with open(out_path, "wb") as f:
                        f.write(p.inline_data.data)
                    return out_path
            return None   # respondió pero sin imagen (bloqueo de contenido) -> no reintenta
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            transitorio = any(c in msg for c in ("500", "INTERNAL", "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"))
            if transitorio and attempt < tries - 1:
                time.sleep(2.0 * (attempt + 1))   # backoff: 2s, 4s, 6s
                continue
            return None
    return None


def generar_ads_disruptivos(producto: str, work_dir: str, *, anthropic_key: str, gemini_key: str,
                            product_image_path: str | None = None,
                            progress: Callable[[str, int], None] | None = None) -> dict:
    """Flujo completo: Claude -> 10 conceptos -> Nano Banana -> 10 imágenes. Nunca lanza."""
    def rep(m, p):
        if progress:
            progress(m, int(p))

    os.makedirs(work_dir, exist_ok=True)
    if not anthropic_key:
        return {"ok": False, "error": "Falta la API key de Claude (Anthropic) para inventar los conceptos."}
    if not gemini_key:
        return {"ok": False, "error": "Falta la API key de Gemini para generar las imágenes."}

    rep("Claude está inventando 10 conceptos disruptivos...", 6)
    variantes = generar_conceptos(producto, anthropic_key)
    if not variantes:
        return {"ok": False, "error": "No se pudieron generar los conceptos (revisa la key de Claude)."}

    rep(f"Generando las {len(variantes)} imágenes con Nano Banana...", 28)
    done = [0]
    n = len(variantes)

    def _one(item):
        i, v = item
        out = os.path.join(work_dir, f"ad_{i:02d}.png")
        try:
            v["imagen"] = generar_imagen(v.get("prompt", ""), gemini_key, out, product_image_path)
        except Exception as e:  # noqa: BLE001
            v["imagen"] = None
            v["error"] = str(e)[:150]
        done[0] += 1
        rep(f"Imagen {done[0]}/{n} lista...", 28 + int(done[0] / max(1, n) * 68))
        return v

    with ThreadPoolExecutor(max_workers=3) as ex:   # poca concurrencia por el rate-limit de Gemini
        variantes = list(ex.map(_one, enumerate(variantes)))

    ok = [v for v in variantes if v.get("imagen")]
    rep("Listo", 100)
    return {"ok": True, "variantes": variantes, "n_ok": len(ok), "n_total": n}


def generar_ads_v2(conceptos: list[dict], work_dir: str, *, gemini_key: str, precio: str = "",
                   ofertas: list[str] | None = None, product_image_path: str | None = None,
                   progress: Callable[[str, int], None] | None = None) -> dict:
    """Paso 2: para los conceptos ELEGIDOS, genera escena (Nano Banana) + compone el texto. Nunca lanza."""
    def rep(m, p):
        if progress:
            progress(m, int(p))

    os.makedirs(work_dir, exist_ok=True)
    if not gemini_key:
        return {"ok": False, "error": "Falta la API key de Gemini para generar las imágenes."}
    n = len(conceptos)
    done = [0]
    rep(f"Generando {n} imágenes (escena + texto compuesto)...", 8)

    def _one(item):
        i, c = item
        out = os.path.join(work_dir, f"ad_{i:02d}.png")
        try:
            c["imagen"] = generar_ad_compuesto(c, out, gemini_key=gemini_key, precio=precio,
                                               ofertas=ofertas, product_image_path=product_image_path)
        except Exception as e:  # noqa: BLE001
            c["imagen"] = None
            c["error"] = str(e)[:150]
        done[0] += 1
        rep(f"Imagen {done[0]}/{n} lista...", 8 + int(done[0] / max(1, n) * 88))
        return c

    with ThreadPoolExecutor(max_workers=3) as ex:
        conceptos = list(ex.map(_one, enumerate(conceptos)))
    ok = [c for c in conceptos if c.get("imagen")]
    rep("Listo", 100)
    return {"ok": True, "variantes": conceptos, "n_ok": len(ok), "n_total": n}
