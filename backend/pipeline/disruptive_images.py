"""Generador de ADS DISRUPTIVOS de imagen.

Anthropic (Claude) = cerebro creativo: inventa 10 conceptos disruptivos + prompts siguiendo el estilo
de Juan (skill ads-disruptivos-imagen). Google AI (Nano Banana / gemini-2.5-flash-image) = generación
visual: convierte cada prompt en una imagen. Metes CUALQUIER producto -> 10 creativos listos.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PIL import Image, ImageDraw, ImageFont, ImageOps

_CLAUDE = "claude-opus-4-8"
_IMG_MODEL = "gemini-2.5-flash-image"   # Nano Banana

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


def _cursor(draw, x, y, s=52):
    """Dibuja un cursor-mano/flecha blanco (señal de 'clickeable')."""
    pts = [(x, y), (x, y + s), (x + s * 0.28, y + s * 0.72), (x + s * 0.44, y + s),
           (x + s * 0.60, y + s * 0.92), (x + s * 0.44, y + s * 0.64), (x + s * 0.72, y + s * 0.64)]
    draw.polygon(pts, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))


def componer_ad(scene_path: str, out_path: str, *, titular: str, sub: str = "", cta: str = "VER PRECIO",
                precio: str = "", ofertas: list[str] | None = None, banda_hex: str = "#111111",
                cta_hex: str = "#E11D2E", W: int = 1080, H: int = 1350) -> str:
    """Compone el ad final: escena (IA) + titular arriba + CTA/precio/ofertas abajo, con FUENTES REALES."""
    ofertas = [o for o in (ofertas or []) if o]
    scene = Image.open(scene_path).convert("RGB")
    img = ImageOps.fit(scene, (W, H), Image.LANCZOS)
    draw = ImageDraw.Draw(img, "RGBA")
    band = _hex(banda_hex, (17, 17, 17))

    # HEADER: banda de color + titular (auto-fit, Poppins ExtraBold)
    pad = 46
    font, lines, lh = _fit(draw, (titular or "").upper(), _FONT_XB, W - 2 * pad, H * 0.24, start=100, mins=42)
    sub_h = 44 if sub else 0
    header_h = int(len(lines) * lh + pad * 1.3 + sub_h)
    draw.rectangle([0, 0, W, header_h], fill=band + (232,))
    y = int(pad * 0.65)
    for l in lines:
        w = draw.textlength(l, font=font)
        draw.text(((W - w) // 2, y), l, font=font, fill=(255, 255, 255, 255))
        y += int(lh)
    if sub:
        sf = ImageFont.truetype(_FONT_B, 36)
        sw = draw.textlength(sub, font=sf)
        draw.text(((W - sw) // 2, y + 2), sub, font=sf, fill=(255, 255, 255, 235))

    # FOOTER (de abajo hacia arriba): precio -> CTA pill -> badges de oferta
    yb = H - 40
    # precio
    if precio:
        pf = ImageFont.truetype(_FONT_XB, 48)
        pw = draw.textlength(precio, font=pf)
        draw.rectangle([0, yb - 66, W, yb], fill=(0, 0, 0, 150))
        draw.text(((W - pw) // 2, yb - 58), precio, font=pf, fill=(255, 255, 255, 255))
        yb -= 86
    # CTA pill + cursor
    cf = ImageFont.truetype(_FONT_XB, 48)
    ctatxt = (cta or "VER PRECIO").upper()
    cw = draw.textlength(ctatxt, font=cf)
    bh = 100
    bw = int(cw + 130)
    bx = (W - bw) // 2
    by = yb - bh
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2, fill=_hex(cta_hex, (225, 29, 46)) + (255,))
    draw.text((bx + (bw - cw) // 2, by + (bh - 56) // 2), ctatxt, font=cf, fill=(255, 255, 255, 255))
    _cursor(draw, bx + bw - 40, by + bh - 30)
    yb = by - 20
    # badges de oferta (pills amarillas)
    if ofertas:
        of = ImageFont.truetype(_FONT_B, 34)
        widths = [draw.textlength(o.upper(), font=of) + 44 for o in ofertas]
        total = sum(widths) + 16 * (len(ofertas) - 1)
        x = (W - total) // 2
        for o, w in zip(ofertas, widths):
            draw.rounded_rectangle([x, yb - 56, x + w, yb - 4], radius=26, fill=(255, 214, 10, 255))
            draw.text((x + 22, yb - 50), o.upper(), font=of, fill=(20, 20, 20, 255))
            x += w + 16

    img.convert("RGB").save(out_path, quality=92)
    return out_path

# Estilo de Juan destilado (de la skill ads-disruptivos-imagen) -> system prompt del cerebro creativo.
_SISTEMA = """Eres un DIRECTOR DE ARTE DISRUPTIVO para ads de IMAGEN ESTÁTICA (Meta/Instagram/TikTok) de \
dropshipping en Colombia (pago contraentrega). Conviertes un producto en creativos que FRENAN EL SCROLL: \
ideas extraordinarias, exageradas, casi ABSURDAS (pattern-interrupt) que la gente no puede ignorar.

FILOSOFÍA (obligatoria):
- Dramatiza el dolor o la transformación hasta el límite de lo absurdo. PROHIBIDO el "frasco sobre fondo \
blanco + persona feliz sonriendo" (eso no frena a nadie).
- Lo inesperado gana: metáforas extremas y literales, escenas imposibles, personificación del dolor, \
consecuencias absurdas, objetos surreales, reacciones faciales exageradas.
- Piensa primero en la IDEA, no en el producto (el producto puede ir pequeño en el tercio inferior; la \
ESCENA vende, el producto cierra).
- Cada concepto debe sentirse NUEVO en el nicho. Si la idea ya se ve en el feed típico (frasco+persona \
feliz, antes/después clínico genérico, mano sosteniendo el producto), DESCÁRTALA y súbela una marcha.
- VARIEDAD OBLIGATORIA: las 10 variantes cubren mecanismos distintos (miedo, deseo, humor, metáfora \
surreal, prueba/autoridad, curiosidad nativa, comparación de precio, testimonio, dato de shock, \
antes/después de OBJETO). Nada de 10 versiones de la misma idea.

FÓRMULA DE 4 CAPAS (el esqueleto ganador de Juan), de arriba a abajo:
1. Titular-gancho en MAYÚSCULAS gruesas: una PREGUNTA, un DATO DE SHOCK o una COMPARACIÓN DE PRECIO.
2. Escena realista del dolor/deseo (foto DSLR realista o UGC iPhone; nada de render plástico).
3. UN elemento que PARECE interactivo (el sello de Juan; MÍNIMO 1 por pieza): falso play ▶ (triángulo \
blanco en círculo translúcido + barra de progreso "0:00 / 3:42"); selector/quiz de pastillas con \
CURSOR-MANO blanca tocando una; falso slider antes/después (línea vertical + manija + flechas ◄►, lados \
ANTES/DESPUÉS); cursor/dedo blanco sobre un botón amarillo/rojo; falso chat de WhatsApp (burbujas verdes, \
hora, doble check azul); falso post de Instagram (barra like/comentar/compartir); toca-para-revelar.
4. Cierre de conversión: botón CTA (rojo o amarillo) + precio en COP + "Pago contraentrega".

MOLDES DE COPY: pregunta-dolor ("¿DÓNDE...?", "¿HACE CUÁNTO...?"); dato de shock ("1 DE 10..."); \
comparación de precio ("CLÍNICA: $150.000 — ESTO: $79.900"); curiosidad/secreto ("El truco que no querían \
que supieras"); metáfora corporal. CTA: "TOCA PARA VER", "VER PRECIO", "DESLIZA Y MIRÁ". Prueba social: \
"+20.000 lo usan", "4.9/5 ★". Texto SIEMPRE en español colombiano (tuteo), CORTO y literal (los modelos \
de imagen escriben mal los textos largos), alto contraste.

CUMPLIMIENTO (para que Meta no lo banee): nada de curas absolutas ni porcentajes médicos inventados -> usa \
"ayuda a / apoya el bienestar / fórmula natural". Antes/después de CUERPO o ROSTRO está restringido: \
insinúa la transformación con escena y emoción, NO con un split clínico enfermo->sano. Antes/después de \
OBJETO (camisa, líquido) sí es seguro. Sin desnudez ni contenido sexual explícito: el shock se logra con \
drama, metáfora y emoción exagerada, no con piel.

Genera EXACTAMENTE 10 variantes. Cada 'prompt' debe ser un párrafo en texto plano, en INGLÉS para el \
generador de imagen PERO con los textos incrustados del anuncio LITERALES en español (entre comillas y con \
su ubicación), describiendo: escena + sujeto + emoción + el elemento disruptivo + el elemento \
falso-interactivo con precisión + el producto + los textos incrustados + estilo/luz + realismo, en 4:5 \
vertical."""

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
Tu trabajo: convertir un producto en 6 conceptos que FRENAN EL SCROLL — ideas extraordinarias, exageradas,
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
- Fotorrealista (DSLR o UGC iPhone), alto impacto.

CUMPLIMIENTO Meta: nada de curas absolutas ni % médicos; antes/después de cuerpo/rostro insinuado (no split
clínico); sin desnudez ni contenido sexual explícito (shock por drama/metáfora, no por piel).

Para cada concepto das: el ángulo, la escena (prompt visual sin texto), y el TEXTO en español colombiano
(tuteo, corto) para componer: titular (gancho, MAYÚSCULAS), sub opcional, CTA ("VER PRECIO", "TOCA PARA
VER", "DESLIZA Y MIRÁ"), y 2 colores hex (banda del titular, botón CTA) que combinen con la escena y con
alto contraste. Devuelve 6."""

_TOOL_V2 = {
    "name": "proponer_conceptos",
    "description": "Propone 6 conceptos disruptivos (escena limpia + texto para componer).",
    "input_schema": {
        "type": "object",
        "properties": {
            "conceptos": {
                "type": "array",
                "description": "Exactamente 6 conceptos, MUY diferentes entre sí (mecanismo y escena distintos).",
                "items": {
                    "type": "object",
                    "properties": {
                        "angulo": {"type": "string", "description": "nombre corto del ángulo de venta"},
                        "mecanismo": {"type": "string", "description": "miedo/deseo/humor/metáfora/prueba/curiosidad/precio"},
                        "concepto": {"type": "string", "description": "la idea visual disruptiva en 1 frase (español)"},
                        "por_que": {"type": "string", "description": "por qué frena el scroll y convierte"},
                        "escena_prompt": {"type": "string", "description": "prompt VISUAL en inglés, SIN texto/letras en la imagen"},
                        "titular": {"type": "string", "description": "titular para componer (español, corto, MAYÚSCULAS)"},
                        "sub": {"type": "string", "description": "sub/apoyo opcional (español, corto)"},
                        "cta": {"type": "string", "description": "texto del botón CTA (español)"},
                        "banda_hex": {"type": "string", "description": "color hex de la banda del titular"},
                        "cta_hex": {"type": "string", "description": "color hex del botón CTA"},
                    },
                    "required": ["angulo", "mecanismo", "concepto", "escena_prompt", "titular", "cta"],
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
            messages=[{"role": "user", "content": ctx + "\nPropón 6 conceptos disruptivos MUY diferentes."}],
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
                    banda_hex=concepto.get("banda_hex", "#111111"),
                    cta_hex=concepto.get("cta_hex", "#E11D2E"))
        try:
            os.remove(scene)
        except OSError:
            pass
        return out_path
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Composición falló: {e}")
        return scene   # al menos la escena


def generar_conceptos(producto: str, anthropic_key: str,
                      mercado: str = "Colombia · español colombiano · pago contraentrega (COD)") -> list[dict]:
    """Claude inventa las 10 variantes (concepto + copy + prompt). Devuelve [] si falla."""
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key)
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=12000, system=_SISTEMA,
            tools=[_TOOL], tool_choice={"type": "tool", "name": "entregar_creativos"},
            messages=[{"role": "user", "content":
                       f"PRODUCTO: {producto}\nMERCADO: {mercado}\n\n"
                       "Inventa las 10 variantes disruptivas (ángulos y formatos distintos, "
                       "todas pasando el listón de originalidad)."}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "entregar_creativos":
                return list(block.input.get("variantes", []))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Conceptos (Claude) no disponibles: {e}")
    return []


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
