"""Generador de ADS DISRUPTIVOS de imagen.

Anthropic (Claude) = cerebro creativo: inventa 10 conceptos disruptivos + prompts siguiendo el estilo
de Juan (skill ads-disruptivos-imagen). Google AI (Nano Banana 2 / gemini-3-pro-image) = generación
visual: dibuja el ad completo (video nativo) desde cada prompt. Metes CUALQUIER producto -> 10 creativos.
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PIL import Image

_CLAUDE = "claude-opus-4-8"
_IMG_MODEL = "gemini-3-pro-image-preview"    # Nano Banana 2 — calidad pro (~$0.13/imagen)
_IMG_MODEL_DRAFT = "gemini-2.5-flash-image"  # Nano Banana 1 — borradores (~$0.04/imagen): el lote
                                             # sale BARATO y ✨ HD re-renderiza solo las elegidas
_TXT_MODEL = "gemini-2.5-flash"             # para verificar ortografía del render

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FONT_XB = os.path.join(_BASE, "assets", "fonts", "Poppins-ExtraBold.ttf")
_FONT_B = os.path.join(_BASE, "assets", "fonts", "Poppins-Bold.ttf")


# Cerebro creativo calibrado con EVIDENCIA REAL: 724 ads estáticos con 30+ días corriendo (321 con 3+ años)
# bajados de Foreplay el 2026-07-04 + 56 revisados uno a uno. Detalle: assets/ads-estaticos-validados.md.
_SISTEMA = """Eres el MEJOR DIRECTOR DE ARTE de ads de IMAGEN para dropshipping en Colombia (pago \
contraentrega). Conviertes un producto en creativos ESTÁTICOS que FRENAN EL SCROLL con ideas ATREVIDAS de \
CONCEPTO pero de ejecución 100% FOTOGRÁFICA REAL, con el texto del anuncio YA INCRUSTADO en la MISMA imagen \
(todo lo dibuja el generador). El generador escribe bien el texto SOLO si se lo das corto, exacto y entre comillas.

⚖️ LA DOCTRINA (aprendida de 724 ads reales con 30+ días corriendo — 321 llevan AÑOS pagando tráfico):
en los ganadores longevos hay CERO personas CGI, CERO pieles de porcelana, CERO metáforas imposibles sobre \
cuerpos y CERO botones de play falsos. La gente conecta con lo que parece FOTO DE VERDAD; lo que huele a IA \
dispara el CPC. "Lo real ya ganó; lo inventado suena a anuncio."
🧪 PRUEBA DE FUEGO por variante: ¿esta escena se puede FOTOGRAFIAR con cámara, actores y utilería en una \
tarde? Si NO → reescríbela hasta que sí. El concepto puede ser audaz; la FOTO debe ser posible.

⭐ EL LISTÓN — ganadores REALES de la evidencia (iguala su ejecución):
1. El tambor de la lavadora ABIERTO lleno de mugre real, casi sin texto → asco real = scroll frenado (años corriendo).
2. "READ THIS BEFORE BUYING [marca]" escrito A MANO en un sticky pegado al frasco sobre un mesón real → contrarian nativo.
3. "90 DAYS FOR BETTER HAIR" en tipografía GIGANTE + frasco real + "+4,000,000 BOTTLES SOLD" → número que prueba.
4. "KNEE PAIN ISN'T REAL" + foto real de mujer SALTANDO con la rodillera + un lápiz de utilería "borrando" el dolor + "170,000+ 5-Star Reviews" → metáfora FOTOGRAFIABLE.
5. BEFORE / 2 WEEKS AFTER: la MISMA nuca, el MISMO ángulo, la MISMA luz — progreso creíble, no milagro.
6. Corrector de postura PUESTO en un señor real + FLECHAS amarillas dibujadas mostrando la tensión → mecanismo visible.
7. Frascos artesanales EN LA MANO en el jardín con su etiqueta simple ("Natural Antibiotic") → UGC puro, familias enteras de estos llevan años.

LOS 8 MOTORES psicológicos (usa uno DISTINTO por concepto): asco/miedo del problema real · prueba social \
numérica · autoridad clínica · contraste antes/después honesto · nosotros-vs-ellos · curiosidad contrarian · \
mecanismo revelado · humor de utilería.

🏆 LOS 12 ARQUETIPOS VALIDADOS (el `formato` de cada variante es UNO de estos, tal cual):
problema_crudo (el problema real en macro feo, casi sin texto) · antes_despues_honesto (misma persona/ángulo/luz \
+ ancla de tiempo) · ugc_en_mano (producto en la mano/en uso en lugar real con luz natural) · nota_manuscrita \
(sticky/letrero a mano sobre escena real) · tipografia_numero (titular gigante + producto real + UN número de \
prueba) · versus (✓/✗ contra la alternativa, competidor tachado) · autoridad_clinica (rayos X rojo/verde, \
experto de bata, diagrama sobre cuerpo real) · mecanismo_flechas (foto real + flechas/callouts dibujados) · \
oferta_apilada (bundle con flechas "Buy this → Get this FREE", barra de urgencia, 2x1 — fotos reales) · \
bodegon_ingredientes (origen natural en bodegón cálido) · ilustracion_honesta (caricatura CLARAMENTE dibujada, \
máx 1) · metafora_fotografiable (metáfora montada con UTILERÍA real en set, humor de prop — máx 1).

🔒 LAS 2 PRIMERAS VARIANTES SON FIJAS — plantillas PROBADAS (ganadoras reales de la casa, y la evidencia \
las respalda: el contrarian manuscrito y las capturas de reseñas aparecen entre los longevos). Genera \
SIEMPRE estas 2 de PRIMERO, adaptadas al producto (español colombiano), y de la 3 a la 10 van con los \
8 motores y los 12 arquetipos:

  VARIANTE 1 · "no_compres" (CONTRARIAN / psicología inversa):
  Titular GIGANTE a la izquierda, tipografía enorme y seria, tipo "NO COMPRES ESTO." (o "NO LO USES.").
  Debajo, en fuente más chica, el remate con el DOLOR: "Si te gusta [seguir con el problema]"
  (ej: "Si te gusta vivir hinchada", "Si disfrutas el dolor de espalda"). A la DERECHA, una zona LIMPIA
  y VACÍA reservada para el producto (se pega después — NO dibujes producto ahí). Abajo, barra de
  CREDIBILIDAD: 3 viñetas con ✓ (beneficios/ingredientes clave) y "★★★★★ 4.7 · +50.000 clientes felices".
  Fondo sobrio (crema/claro), look de post editorial PREMIUM, no de anuncio chillón. SIN precio.

  VARIANTE 2 · "capturas" (PRUEBA SOCIAL):
  Arriba, un titular corto tipo "TU DOSIS DIARIA DE [beneficio]" + una zona LIMPIA reservada para el
  producto (se pega después). Debajo/al lado, una PILA de 3-4 CAPTURAS de comentarios reales estilo
  Facebook/Instagram: foto de perfil difuminada, comentario en español colombiano elogiando el producto,
  "Me gusta · Responder", antigüedad ("3 sem"), y 1-2 con reacciones ("❤️ 2"). Se ven ORGÁNICOS y
  creíbles (no perfectos). Abajo un logo/CTA sencillo tipo "PRUEBA [marca]". SIN precio.

  (Estas 2 son limpias y viven de la CREDIBILIDAD. Igual que todas:
   deja la zona del producto VACÍA para pegarlo después, y JAMÁS pongas precio.)

REGLA MADRE: el creativo NO debe PARECER un anuncio pulido. Debe parecer CONTENIDO REAL (la foto que alguien
tomó, el post que alguien subió) que frena el scroll por INCÓMODO, CLARO o CURIOSO. NADA de "banda de color
de anuncio arriba con el titular". Full-bleed, máximo ~12 palabras grandes, 2ª persona.

FÓRMULA VISUAL (ejecución fotográfica SIEMPRE):
- La escena es una FOTOGRAFÍA creíble: cámara de celular o cámara normal, luz natural o de interior real,
  encuadre imperfecto de humano (ligeramente descentrado, fondo vivido real). PERSONAS: piel REAL con poros,
  arrugas, manchas y brillos naturales; manos normales; nada de piel plástica ni simetría de maniquí.
- Los ELEMENTOS GRÁFICOS permitidos van DIBUJADOS ENCIMA de la foto (así lo hacen los longevos): flechas,
  círculos rojo/verde, checks ✓/✗, chips de texto, sticky notes, barra de urgencia, tipografía gigante.
  La foto es real; el diseño va encima.
- CTA: si acaso, UNA pastilla redondeada simple con el texto. SIN botón de play, SIN barra de progreso,
  SIN marco de teléfono, SIN manijas de slider — NADA que finja ser interfaz de video o de app.

PRODUCTO: NO dibujes NINGÚN frasco/producto en la imagen (el producto REAL del cliente se PEGA aparte
después). Deja LIMPIO y despejado el tercio inferior IZQUIERDO (sin texto ni objetos ahí). Excepción: si el
arquetipo pide el producto EN USO (ugc_en_mano, mecanismo_flechas), descríbelo como objeto GENÉRICO sin marca
y deja igual la zona limpia para pegar el frasco real.

🚫 LISTA NEGRA (jamás en un 'prompt'): piel convertida en otro material (porcelana/cemento/desierto/estatua),
personas CGI o "casi reales", reflejos imposibles, gente flotando o desinflándose, botón de play falso,
marco de celular, slider falso, split clínico enfermo→sano. Si el ángulo pide metáfora, usa el arquetipo
metafora_fotografiable: UTILERÍA real en un set real (máximo 1 de las 10).

CUMPLIMIENTO Meta: nada de curas absolutas ni % médicos ("ayuda a / apoya el bienestar"). El antes/después
va HONESTO (misma persona, mismo ángulo, misma luz, ancla de tiempo tipo "en 3 semanas"), progreso modesto y
creíble — nunca enfermo→sano ni cuerpo idealizado. Sin desnudez: el gancho es por realidad e interés, no por piel.

🎯 REGLA DE PROFUNDIDAD DEL ÁNGULO (la más importante — sin esto la imagen queda "genérica"):
La imagen debe CONTAR el ángulo COMPLETO, no ilustrar el producto en general. Para cada variante declara:
- `dolor_visual`: cómo se VE el dolor ESPECÍFICO de ese ángulo (quién sufre, en qué situación, qué se nota
  físicamente). "Una persona preocupada" NO sirve; "esconde los pies en la arena mientras todos andan en
  sandalias" SÍ.
- `solucion_visual`: cómo se INSINÚA la transformación/promesa en la MISMA imagen — el giro (una mitad ya
  aliviada, la reacción de alivio, el antes/después, o la zona limpia donde entrará el producto como héroe).
PRUEBA DEL ÁNGULO: alguien que vea SOLO la imagen (sin leer el titular) debe poder decir QUÉ duele y QUÉ se
promete. Si la escena podría servir para cualquier otro producto del nicho → es genérica: recházala y hazla
más específica. El 'prompt' DEBE poner en escena dolor_visual Y solucion_visual, con el dolor como
protagonista y la solución como giro visible.

Cada 'prompt' que entregues:
- UN SOLO párrafo en INGLÉS. Empieza con "authentic photograph, shot on a phone camera" (o "candid photo")
  — JAMÁS "advertisement", "render", "3D" ni "illustration" (salvo el arquetipo ilustracion_honesta, que
  empieza "hand-drawn flat illustration, clearly a drawing"). Describe: la escena real + el sujeto y su
  emoción + la luz (natural de ventana, interior de casa, exterior nublado) + textura de piel real (visible
  pores, natural skin texture and imperfections) + los elementos gráficos DIBUJADOS encima (flechas, chips,
  sticky, tipografía) + el titular incrustado.
- Di EXPLÍCITO: "no product or bottle anywhere in the image, keep the lower-left area clean and empty"
  (o el genérico sin marca si el arquetipo lo pide en uso).
- Los TEXTOS incrustados van LITERALES en español (colombiano, tuteo), entre comillas, CORTOS. SIN precio.
- Incluye la `escena_real`: DÓNDE se tomó la "foto" (el baño de una casa, la cocina, el jardín, el gimnasio),
  QUIÉN sale (edad/tipo real, ej. "señora de 52 con canas") y QUÉ utilería hay. Eso ancla el realismo.

DISTRIBUCIÓN OBLIGATORIA de los 10 (para que NO salgan todos iguales):
- Las variantes 1 y 2 son las 2 PLANTILLAS FIJAS de arriba: la 1 = "no_compres" (contrarian) y la 2 =
  "capturas" (prueba social), adaptadas al producto. Su `formato` es "post_editorial" y su 'prompt'
  describe un POST/imagen editorial LIMPIO: fondo sobrio, tipografía gruesa; contrarian = titular gigante +
  zona de producto vacía + barra de credibilidad (la versión FOTO con sticky manuscrito también vale); capturas =
  zona de producto + pila de comentarios estilo Facebook. Español entre comillas, sin precio.
- De la 3 a la 10 (8 variantes): cada una con UN arquetipo distinto de los 12 (pon el `formato` EXACTO con
  la palabra del arquetipo). Usa AL MENOS 6 arquetipos diferentes; máximo 1 metafora_fotografiable y máximo
  1 ilustracion_honesta; al menos 3 con personas reales de piel visible (eso conecta). Cada concepto un
  motor psicológico DISTINTO.
- ESPECÍFICO OBLIGATORIO: "alguien preocupado mirándose al espejo" NO pasa la prueba del ángulo — la escena
  debe delatar el dolor CONCRETO de ESTE producto (qué zona del cuerpo, en qué momento del día, qué se nota).

Devuelve EXACTAMENTE 10 variantes (1-2 = plantillas fijas, 3-10 = arquetipos), al nivel del LISTÓN de
evidencia (el tambor sucio, el sticky manuscrito, el 90-days con número, la rodillera saltando)."""

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
                        "formato": {"type": "string", "description": "arquetipo validado EXACTO: 'problema_crudo' | 'antes_despues_honesto' | 'ugc_en_mano' | 'nota_manuscrita' | 'tipografia_numero' | 'versus' | 'autoridad_clinica' | 'mecanismo_flechas' | 'oferta_apilada' | 'bodegon_ingredientes' | 'ilustracion_honesta' | 'metafora_fotografiable' (o 'post_editorial' para las 2 fijas). Mínimo 6 distintos."},
                        "mecanismo": {"type": "string", "description": "el motor psicológico: asco/miedo real | prueba social numérica | autoridad clínica | antes/después honesto | nosotros-vs-ellos | curiosidad contrarian | mecanismo revelado | humor de utilería. DISTINTO por concepto."},
                        "escena_real": {"type": "string", "description": "cómo se FOTOGRAFÍA de verdad: lugar real + quién sale (edad/tipo) + utilería + luz. Si no se puede montar con cámara y actores en una tarde, la variante está mal."},
                        "concepto": {"type": "string", "description": "la idea loca en 1-2 frases (español)"},
                        "por_que": {"type": "string", "description": "por qué frena el scroll y convierte"},
                        "dolor_visual": {"type": "string", "description": "cómo se VE el DOLOR ESPECÍFICO de este ángulo en la imagen (quién sufre, dónde, qué se nota). Concreto, no 'persona triste'."},
                        "solucion_visual": {"type": "string", "description": "cómo se INSINÚA la solución/transformación de este ángulo en la MISMA imagen (el giro, el alivio, el después, o la zona donde entra el producto como héroe). Si el ángulo es 100% dolor, di dónde queda el espacio de la promesa."},
                        "titular": {"type": "string", "description": "titular incrustado (español, corto, MAYÚSCULAS)"},
                        "apoyo": {"type": "string", "description": "sub/apoyo (español, opcional)"},
                        "precio_cta": {"type": "string", "description": "precio+oferta COD (opcional)"},
                        "boton_cta": {"type": "string", "description": "texto del botón/CTA falso"},
                        "prompt": {"type": "string", "description": "prompt de imagen: DEBE poner en escena dolor_visual Y solucion_visual (ver instrucciones)"},
                    },
                    "required": ["angulo", "formato", "concepto", "por_que", "dolor_visual",
                                 "solucion_visual", "escena_real", "titular", "prompt"],
                },
            }
        },
        "required": ["variantes"],
    },
}

# Cola de calidad que se pega al final de cada prompt de imagen (doctrina: foto real, no CGI).
_CIERRE = (" Authentic real photograph aesthetic: shot on a phone camera, natural lighting, candid slightly "
           "imperfect framing, real human skin with visible pores and natural imperfections, natural skin "
           "tones. 1:1 perfectly SQUARE aspect ratio. Thick bold sans-serif fonts for overlaid text, high "
           "contrast, render all embedded text crisply and spelled EXACTLY as written. NOT CGI, NOT a 3D "
           "render, NOT an illustration, no plastic porcelain skin, no perfect mannequin symmetry, no fake "
           "video player interface. Avoid: extra fingers, deformed hands, garbled or misspelled text, random "
           "logos, watermarks, nudity, low-resolution artifacts.")


def generar_conceptos(producto: str, anthropic_key: str, page_text: str = "",
                      ofertas: list[str] | None = None, precio: str = "",
                      mercado: str = "Colombia · español colombiano · pago contraentrega (COD)",
                      evitar: list[str] | None = None, n: int = 10, plantillas_fijas: bool = True) -> list[dict]:
    """Claude inventa N variantes full-prompt (concepto + copy + prompt rico). Devuelve [] si falla.

    `evitar`: titulares/ángulos YA mostrados que NO gustaron → Claude da cosas TOTALMENTE distintas.
    `plantillas_fijas`: si True incluye las 2 plantillas ganadoras de primeras; si False, todo surreal."""
    ofertas = [o for o in (ofertas or []) if o]
    evitar = [e for e in (evitar or []) if e and e.strip()]
    ctx = f"PRODUCTO: {producto}\nMERCADO: {mercado}\n"
    if page_text.strip():
        ctx += f"\nCONTEXTO DE LA PÁGINA DE VENTA (para entender dolor/beneficio real):\n{page_text[:2500]}\n"
    if ofertas:
        ctx += f"\nOFERTAS a incrustar en el precio (úsalas): {', '.join(ofertas)}\n"
    if precio.strip():
        ctx += (f"\nPRECIO: {precio.strip()} — inclúyelo en la línea de precio junto con la oferta y "
                "'Paga al recibir' / 'Pago contraentrega'.\n")
    else:
        ctx += ("\nREGLA ESTRICTA — SIN PRECIO: aunque los 5 EJEMPLOS de arriba muestren precios, TÚ NO "
                "pongas NINGUNA cifra de dinero ($, COP, número de precio, descuento con número) en NINGUNA "
                "parte de la imagen ni en el 'prompt'. El CTA NO debe decir 'VER PRECIO' (usa 'TOCA PARA "
                "VER', 'PEDIR AHORA', 'DESLIZA Y MIRA', 'LO QUIERO', etc.). Si hay una oferta tipo '2x1' o "
                "'envío gratis' SÍ puedes mostrarla (es texto, no cifra de precio), pero jamás un valor.\n")
    if evitar:
        ctx += ("\n🚫 YA SE MOSTRARON estos conceptos y NO gustaron. NO los repitas ni hagas variaciones de "
                "ellos (ni el mismo dolor/escena con otras palabras). Dame ángulos, dolores, mecanismos y "
                "escenas TOTALMENTE DIFERENTES a estos:\n" + "\n".join(f'- "{e}"' for e in evitar[:40]) + "\n")
    if plantillas_fijas:
        pedido = (f"\nInventa las {n} variantes: las 2 PRIMERAS son las plantillas FIJAS (no_compres, "
                  f"capturas) y de la 3 a la {n} surreales con los 6 motores, todas MUY distintas entre sí.")
    else:
        pedido = (f"\nEsta vez IGNORA la regla de las 2 plantillas fijas. Dame {n} conceptos usando SOLO los "
                  "12 arquetipos validados (mínimo 6 distintos), con motores y escenas MUY distintos entre "
                  "sí (y distintos a cualquiera ya mostrado). Ejecución fotográfica SIEMPRE.")
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=16000, system=_SISTEMA,
            tools=[_TOOL], tool_choice={"type": "tool", "name": "entregar_creativos"},
            messages=[{"role": "user", "content": ctx + pedido}],
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


def _recortar_producto(img: "Image.Image", umbral: int = 244) -> "Image.Image":
    """Quita el fondo blanco y deja SOLO el objeto más grande (descarta logos/watermarks sueltos)."""
    import cv2
    import numpy as np
    img = img.convert("RGBA")
    arr = np.array(img)
    fg = (~np.all(arr[:, :, :3] >= umbral, axis=2)).astype(np.uint8)   # 1 = objeto (no blanco)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if n > 1:                                     # 0 = fondo; quédate con el mayor de los demás
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        fg = (labels == big).astype(np.uint8)
    arr[:, :, 3] = fg * 255
    out = Image.fromarray(arr, "RGBA")
    bbox = out.split()[3].getbbox()
    return out.crop(bbox) if bbox else out


def _a_cuadrado(img_path: str) -> None:
    """Regla de la casa: TODO ad sale 1:1. Si una edición de Nano Banana devuelve otro formato
    (el modelo a veces ignora la instrucción), se re-encuadra LOCAL a cuadrado con fondo difuminado
    (estilo IG) — nunca se recorta producto ni texto. $0 y determinista."""
    try:
        from PIL import ImageFilter, ImageEnhance
        im = Image.open(img_path).convert("RGB")
        w, h = im.size
        if w == h:
            return
        lado = max(w, h)
        fondo = im.resize((lado, lado)).filter(ImageFilter.GaussianBlur(42))
        fondo = ImageEnhance.Brightness(fondo).enhance(0.62)
        fondo.paste(im, ((lado - w) // 2, (lado - h) // 2))
        fondo.save(img_path)
    except Exception:  # noqa: BLE001
        pass


def _integrar_producto_ia(ad_path: str, product_image_path: str | None, gemini_key: str,
                          model: str | None = None) -> str | None:
    """2ª pasada: Nano Banana 2 mete el PRODUCTO REAL integrado en la escena (con luz y sombra reales,
    no pegado plano). Mantiene el producto idéntico a la foto.

    Devuelve la ruta si logró meter el producto; None si NO se pudo (bloqueo/cuota/sin foto) — en ese caso
    el ad queda intacto (sin producto), y el que llama debe avisar el fallo."""
    if not (product_image_path and os.path.exists(product_image_path)):
        return None
    buf = ad_path + ".prod.png"
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=gemini_key)
        with open(ad_path, "rb") as f:
            ad_b = f.read()
        prod = _recortar_producto(Image.open(product_image_path))   # producto limpio, sin logos/fondo
        prod.save(buf)
        with open(buf, "rb") as f:
            prod_b = f.read()
        prompt = (
            "Edit the FIRST image (a social-media ad / video screenshot). Take the EXACT product from the SECOND "
            "image and INTEGRATE it into the composition so the viewer instantly understands THIS product is the "
            "solution being shown. FIRST analyze the layout and choose the most natural spot for THIS design: if "
            "the layout has an obviously clean/empty reserved zone (an empty side panel, blank corner or cleared "
            "area), place the product THERE at a size that fills that zone naturally (up to ~30% of the image "
            "width, clearly visible); otherwise place it smaller (~20% of the width) resting on a real flat "
            "surface in the LOWER part of the scene — a table, counter, floor, sink or shelf edge. Always "
            "integrate it with matching lighting, perspective and a soft realistic contact shadow, as if it had "
            "really been photographed there. If this exact product ALREADY appears in the scene, relocate or "
            "refine that single instance instead of adding another — the final image must contain the product "
            "exactly ONCE. STRICT RULES: never place it over a person, face, hands, or over any text, caption, "
            "progress bar or button. Keep the product's shape, colors and label IDENTICAL to the reference — do "
            "NOT redesign it, do NOT add any logo, watermark or extra text on it. Change NOTHING else in the "
            "image: keep all existing captions, the video player, progress bar and the CTA button exactly as "
            "they are. Output only the edited first image, keeping EXACTLY the same 1:1 SQUARE aspect ratio and framing as the first image — do NOT crop, extend or change the canvas.")
        r = client.models.generate_content(
            model=model or _IMG_MODEL,
            contents=[prompt,
                      types.Part.from_bytes(data=ad_b, mime_type="image/png"),
                      types.Part.from_bytes(data=prod_b, mime_type="image/png")])
        for p in ((r.candidates or [None])[0].content.parts if (r.candidates or None) else []):
            if getattr(p, "inline_data", None):
                with open(ad_path, "wb") as f:
                    f.write(p.inline_data.data)
                _a_cuadrado(ad_path)
                return ad_path
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            os.remove(buf)
        except OSError:
            pass
    return None                    # no se pudo integrar → el ad queda intacto (sin producto)


def editar_imagen_ia(img_path: str, instruccion: str, gemini_key: str,
                     errors: list | None = None) -> str | None:
    """Edición DIRIGIDA: aplica la instrucción del usuario a la imagen ya generada (Nano Banana 2),
    cambiando SOLO lo pedido y conservando todo lo demás. Devuelve la ruta o None si no se pudo."""
    if not (instruccion.strip() and gemini_key and os.path.exists(img_path)):
        return None
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=gemini_key)
        with open(img_path, "rb") as f:
            ib = f.read()
        prompt = (
            "Edit this image following the user's instruction EXACTLY. Change ONLY what the instruction "
            "asks and keep EVERYTHING else identical: composition, faces, colors, style, the video-player "
            "chrome, and all existing Spanish text (unless the instruction says to change it). "
            f"User instruction (Spanish): \"{instruccion.strip()}\". "
            "If the instruction adds or modifies Spanish text, render it crisply and spelled EXACTLY. "
            "Output only the edited image, keeping EXACTLY the same aspect ratio and canvas as the "
            "input image (if the input is 1:1 square, the output MUST be 1:1 square).")
        r = client.models.generate_content(
            model=_IMG_MODEL,
            contents=[prompt, types.Part.from_bytes(data=ib, mime_type="image/png")])
        for p in ((r.candidates or [None])[0].content.parts if (r.candidates or None) else []):
            if getattr(p, "inline_data", None):
                with open(img_path, "wb") as f:
                    f.write(p.inline_data.data)
                _a_cuadrado(img_path)
                return img_path
    except Exception as e:  # noqa: BLE001
        if errors is not None:
            errors[:] = [str(e)]
    return None


def generar_ad_fullprompt(variant: dict, out_path: str, *, gemini_key: str,
                          product_image_path: str | None = None, verify: bool = True,
                          max_regen: int = 1, integrar_producto: bool = False,
                          hd: bool = False) -> str | None:
    """Genera el ad (Nano Banana dibuja la escena+texto SIN producto) + verifica ortografía/regenera.
    Por defecto NO mete el producto (queda limpio); si `integrar_producto`, hace la 2ª pasada que lo integra
    en la escena. `hd=False` usa el modelo BORRADOR (~$0.04); `hd=True` el pro (~$0.13) — el flujo genera
    todo en borrador y el botón ✨ HD re-renderiza solo las que Juan va a usar. Devuelve la ruta o None."""
    prompt = variant.get("prompt", "")
    if not prompt:
        return None
    textos = [variant.get("titular", ""), variant.get("apoyo", ""),
              variant.get("boton_cta", ""), variant.get("precio_cta", "")]
    errs: list = []
    got = False
    for intento in range(max_regen + 1):
        p = prompt if intento == 0 else (
            prompt + f" IMPORTANT (retry {intento}): make ABSOLUTELY every letter of the Spanish embedded "
            "text correct, complete and legible; do not misspell or repeat letters.")
        # OJO: NO pasamos el producto como referencia -> el modelo NO lo dibuja; lo pegamos real después.
        img = generar_imagen(p, gemini_key, out_path, product_image_path=None, errors=errs,
                             model=_IMG_MODEL if hd else _IMG_MODEL_DRAFT)
        if not img:
            if not got:
                if errs:         # deja el motivo (tope de gasto, cuota, key...) para el UI
                    variant["error"] = _error_amigable(errs[0])
                return None
            break                # ya hay una imagen previa buena en out_path
        got = True
        if not verify or _verificar_ortografia(out_path, textos, gemini_key)[0]:
            break
    if not got:
        return None
    _a_cuadrado(out_path)
    if integrar_producto:            # 2ª pasada que integra el producto real en la escena
        res = _integrar_producto_ia(out_path, product_image_path, gemini_key,
                                    model=_IMG_MODEL if hd else _IMG_MODEL_DRAFT)
        variant["producto_integrado"] = bool(res)   # False → la UI ofrece reintentar
        return res or out_path                       # si no se pudo, el ad queda limpio (no se pierde)
    return out_path                  # ad LIMPIO sin producto


def generar_ads_fullprompt(variants: list[dict], work_dir: str, *, gemini_key: str,
                           product_image_path: str | None = None,
                           progress: Callable[[str, int], None] | None = None) -> dict:
    """Paso 2 (full-prompt): para los conceptos ELEGIDOS genera el ad completo + verifica/regenera +
    integra el PRODUCTO REAL en la escena (si hay foto). Nunca lanza."""
    def rep(m, p):
        if progress:
            progress(m, int(p))

    os.makedirs(work_dir, exist_ok=True)
    if not gemini_key:
        return {"ok": False, "error": "Falta la API key de Gemini para generar las imágenes."}
    n = len(variants)
    done = [0]
    rep(f"Generando {n} ads completos con Google AI (ortografía + tu producto integrado)...", 8)

    def _one(item):
        i, v = item
        out = os.path.join(work_dir, f"ad_{i:02d}.png")
        try:
            v["imagen"] = generar_ad_fullprompt(v, out, gemini_key=gemini_key,
                                                product_image_path=product_image_path,
                                                integrar_producto=bool(product_image_path))
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
    res = {"ok": len(ok) > 0, "variantes": variants, "n_ok": len(ok), "n_total": n}
    if not ok:   # ninguna salió → sube el motivo real (ej. tope de gasto de Google) al UI
        res["error"] = next((v["error"] for v in variants if v.get("error")),
                            "No se generó ninguna imagen (revisa créditos de Google en ai.studio/spend).")
    return res


def _error_amigable(msg: str) -> str:
    """Traduce el error crudo de Google a algo accionable para Juan."""
    m = (msg or "").lower()
    if "spend" in m or "spending cap" in m:
        return "Se agotó el TOPE DE GASTO mensual de Google. Súbelo en ai.studio/spend y reintenta."
    if "resource_exhausted" in m or "quota" in m or "exceeded" in m:
        return "Sin cuota/créditos de Google ahora. Revisa ai.studio/spend (o reintenta más tarde)."
    if "api key" in m or "api_key" in m or "permission" in m or "401" in m or "403" in m:
        return "Problema con la API key de Google (revísala en 🔑 Claves)."
    if "safety" in m or "blocked" in m or "prohibited" in m:
        return "Google bloqueó ese concepto por políticas. Regenera o cámbialo."
    return "Google no devolvió imagen (reintenta)."


def generar_imagen(prompt: str, gemini_key: str, out_path: str,
                   product_image_path: str | None = None, tries: int = 4,
                   errors: list | None = None, model: str | None = None) -> str | None:
    """Nano Banana convierte el prompt en imagen (usa la foto del producto como referencia si hay).

    Reintenta ante errores transitorios de Google (500 INTERNAL / 503 / rate-limit) con backoff.
    Si `errors` es una lista, guarda ahí el último error crudo (para dar mensaje amigable)."""
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
            resp = client.models.generate_content(model=model or _IMG_MODEL, contents=contents)
            cands = resp.candidates or []
            if not cands:            # bloqueo por políticas: sin candidatos -> mensaje claro, no reintenta
                if errors is not None:
                    errors[:] = [f"blocked/safety: {getattr(resp, 'prompt_feedback', '')}"]
                return None
            for p in (cands[0].content.parts or []):
                if getattr(p, "inline_data", None):
                    with open(out_path, "wb") as f:
                        f.write(p.inline_data.data)
                    return out_path
            return None   # respondió pero sin imagen (bloqueo de contenido) -> no reintenta
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if errors is not None:
                errors[:] = [msg]
            # El tope de gasto mensual NO se arregla reintentando -> falla rápido
            tope = ("spend" in msg.lower()) or ("spending cap" in msg.lower())
            transitorio = (not tope) and any(
                c in msg for c in ("500", "INTERNAL", "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"))
            if transitorio and attempt < tries - 1:
                time.sleep(2.0 * (attempt + 1))   # backoff: 2s, 4s, 6s
                continue
            return None
    return None
