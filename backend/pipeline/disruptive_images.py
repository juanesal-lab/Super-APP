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

🔒 LAS 2 PRIMERAS VARIANTES SON FIJAS — plantillas PROBADAS (ganadoras reales). NO son surreales: son \
LIMPIAS, creíbles y giran en torno al PRODUCTO y su dolor. Genera SIEMPRE estas 2 de PRIMERO, adaptadas \
al producto (español colombiano), y de la 3 a la 10 sí van surreales con los 6 motores:

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

  (Estas 2 ROMPEN a propósito la regla surreal: son limpias y viven de la CREDIBILIDAD. Pero igual:
   deja la zona del producto VACÍA para pegarlo después, y JAMÁS pongas precio.)

REGLA MADRE: el creativo NO debe PARECER un anuncio. Debe parecer CONTENIDO ORGÁNICO (un video o post que
alguien grabó) que por lo surreal frena el scroll. NADA de "banda de color de anuncio arriba con el titular".

FÓRMULA VISUAL por formato:
- FORMATO VIDEO: es el SCREENSHOT de un VIDEO REAL (TikTok/Reel/YouTube). La ESCENA surreal
  LLENA todo el cuadro; encima va el chrome de video NATIVO — botón de play ▶ translúcido al centro, barra de
  progreso con tiempo ("0:08 / 2:04"), iconitos de volumen/pantalla completa en una esquina. El TITULAR va
  como CAPTION NATIVO: texto blanco grueso con contorno/sombra ENCIMA del video (estilo subtítulo de TikTok),
  NO como banner de anuncio. Se ve como un video que estás mirando, no como publicidad.
- FORMATO SLIDER/QUIZ/CHAT: la escena surreal manda a pantalla completa; el elemento (slider antes/después
  con manija ◄►, pastillas de quiz con cursor-mano, o burbujas de chat de WhatsApp) va integrado y nativo,
  sin verse como plantilla de ad.
- ABAJO (todos): un botón redondeado (amarillo/rojo) con el CTA + cursor-mano a punto de tocar. SIN cifras.

PRODUCTO: NO dibujes NINGÚN frasco/producto en la imagen (el producto REAL del cliente se PEGA aparte
después). Deja LIMPIO y despejado el tercio inferior IZQUIERDO (sin texto ni objetos ahí).

SÚPER CREATIVO — aun en nichos "bonitos" (skincare, belleza): PROHIBIDO foto de stock con un filtro. Lleva la
metáfora al EXTREMO surreal: piel = desierto agrietado con grietas reales, cara = estatua de porcelana
resquebrajándose y cayendo en pedazos, reflejo = versión momia/pasa/anciana, arrugas = mapa de carreteras.
Que dé impresión, risa o "¿qué diablos?", como el hipopótamo del espejo o el bus.

CUMPLIMIENTO Meta: nada de curas absolutas ni % médicos ("ayuda a / apoya el bienestar"). El antes/después o
la transformación se hace SURREAL/metafórico (globo, hipopótamo, momia), NUNCA un split clínico enfermo→sano.
Sin desnudez ni sexo explícito: el shock es por drama y metáfora, no por piel.

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
- UN SOLO párrafo en INGLÉS, fotorrealista. Empieza describiendo que es un "photorealistic square 1:1
  screenshot of an authentic organic social video" (o post) — NO "advertisement". Describe la escena surreal
  a pantalla completa + sujeto + emoción + el chrome nativo (center translucent play button, progress bar
  "0:08 / 2:04", small volume/fullscreen icons) + el titular como caption blanco sobre el video.
- Di EXPLÍCITO: "no product or bottle anywhere in the image, keep the lower-left area clean and empty".
- Los TEXTOS incrustados van LITERALES en español (colombiano, tuteo), entre comillas, CORTOS. SIN precio.
- Termina SIEMPRE con: thick sans-serif fonts, high contrast, render all embedded text crisply and spelled
  exactly as written, looks like an authentic organic social media video screenshot NOT a polished ad. Avoid:
  extra fingers, deformed hands, garbled or misspelled text, random logos, watermarks, nudity, low-res artifacts.

DISTRIBUCIÓN OBLIGATORIA de los 10 (para que NO salgan todos iguales):
- Las variantes 1 y 2 son las 2 PLANTILLAS FIJAS de arriba: la 1 = "no_compres" (contrarian) y la 2 =
  "capturas" (prueba social), adaptadas al producto. Su `formato` es "post_editorial" y su 'prompt'
  describe un POST/imagen editorial LIMPIO (NO screenshot de video con chrome): fondo sobrio, tipografía
  gruesa; contrarian = titular gigante + zona de producto vacía + barra de credibilidad; capturas = zona
  de producto + pila de comentarios estilo Facebook. Español entre comillas, sin precio.
- De la 3 a la 10 (8 variantes) van SURREALES con los 6 motores. FORMATOS: MÁXIMO 4 en "video"; el resto
  REPARTIDO entre "slider" (antes/después con manija ◄►), "quiz" (fila de pastillas con cursor-mano),
  "chat" (WhatsApp) y "cursor" (dedo sobre un botón). Usa AL MENOS 4 formatos distintos. Pon el `formato`
  EXACTO como una de esas palabras. Cada concepto un motor DISTINTO (no repitas el mismo dos veces).
- SURREAL OBLIGATORIO: de la 3 a la 10, MÍNIMO 6 deben ser SURREALES/absurdos de verdad — metáfora física
  IMPOSIBLE (piel = desierto agrietado, cara = estatua que se rompe, reflejo = hipopótamo/momia, persona
  que se desinfla como globo). "Alguien preocupado mirándose al espejo" NO cuenta: súbelo a surreal o cámbialo.

Devuelve EXACTAMENTE 10 variantes (1-2 = plantillas fijas, 3-10 = surreales), al nivel de los 5 ejemplos
(hipopótamo, bus, cemento, globo, momia)."""

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
                        "formato": {"type": "string", "description": "formato falso-interactivo EXACTO: 'video' | 'slider' | 'quiz' | 'chat' | 'cursor'. Máx 4 'video'; varía el resto."},
                        "mecanismo": {"type": "string", "description": "el motor psicológico: personificación | metáfora | consecuencia absurda | escena social | reflejo surreal | reacción extrema. DISTINTO por concepto."},
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
                                 "solucion_visual", "titular", "prompt"],
                },
            }
        },
        "required": ["variantes"],
    },
}

# Cola de calidad que se pega al final de cada prompt de imagen.
_CIERRE = (" Thick bold sans-serif fonts, high contrast, 1:1 perfectly SQUARE aspect ratio, looks like an authentic "
           "organic social-media video screenshot (NOT a polished advertisement), render all embedded text "
           "crisply and spelled EXACTLY as written. Avoid: extra fingers, deformed hands, garbled or "
           "misspelled text, random logos, watermarks, nudity, low-resolution artifacts.")


# ── ADVERTORIAL (formato NOTICIA VIRAL) — pedido de Juan 2026-07-04 ────────────────────────
# Imagen que parece un ARTÍCULO/noticia viral: foto lifestyle real del producto EN USO arriba +
# recuadro circular con el producto en mano + barra negra abajo con etiqueta tipo "VIRAL" y un
# titular blanco en mayúsculas con UNA frase resaltada en amarillo entre comillas.
_SISTEMA_ADV = """Eres DIRECTOR DE ARTE de ADVERTORIALS (publirreportajes) para dropshipping en \
Colombia (pago contraentrega). Tu formato NO es un anuncio: es una imagen que PARECE una NOTICIA \
VIRAL / artículo de revista digital, para que la gente baje la guardia y lea. El texto va \
incrustado y bien escrito (el generador lo dibuja).

⭐ EL MOLDE EXACTO (una imagen vertical 4:5 que parece captura de una nota viral):
- ARRIBA (≈78% del alto): una FOTO LIFESTYLE fotorrealista y CREÍBLE — una persona REAL del \
público objetivo USANDO/LLEVANDO el producto en un entorno cotidiano real (la entrada de su casa, \
la calle, un parque, la cocina, la oficina), luz natural, look de foto de celular, NADA de estudio. \
La persona se ve feliz/relajada/natural. El PRODUCTO se ve CLARO en uso.
- RECUADRO CIRCULAR en una esquina superior (borde blanco grueso): un plano héroe del producto \
sostenido en la mano (o primer plano limpio del producto). Es el clásico "inset" de las notas virales.
- ABAJO (≈22%): una BARRA NEGRA sólida. Centrada, una etiquetita blanca (rectángulo o texto entre \
líneas finas) con una palabra tipo "VIRAL" / "TENDENCIA" / "RECOMENDADO" en mayúsculas. Debajo, el \
TITULAR en mayúsculas, sans-serif CONDENSADA y GRUESA, blanco, 2-3 líneas, con UNA frase resaltada \
en AMARILLO y entre comillas simples (lo más emocional/coloquial).

REGLA MADRE: debe parecer CONTENIDO EDITORIAL / NOTICIA, jamás un anuncio con banda de colores. El \
titular es PERIODÍSTICO/CHISMOSO, no publicitario: "por qué todos están comprando…", "esto se volvió \
viral y la gente no para de…", "lo que nadie te dijo sobre…", "dermatólogos recomiendan…".

TITULARES (español colombiano, MAYÚSCULAS, gancho de nota viral). Cada uno con una frase 'destacado' \
para pintar en amarillo entre comillas. Ej. (producto=tenis): titular "ESTOS TENIS SE VOLVIERON \
VIRALES Y LA GENTE NO DEJA DE USARLOS POR LO 'CÓMODOS QUE SON'", destacado "CÓMODOS QUE SON".

PROHIBIDO el PRECIO y cualquier cifra de dinero. Ofertas tipo 2x1 / envío gratis SÍ se pueden \
mencionar como texto (no cifra). Cumplimiento Meta: nada de curas absolutas ni % médicos; \
antes/después SOLO por lifestyle creíble, jamás clínico.

Cada 'prompt' que entregues:
- UN SOLO párrafo en INGLÉS, fotorrealista. Empieza: "photorealistic vertical 4:5 image that looks \
like a screenshot of a VIRAL NEWS ARTICLE (not an advertisement)". Describe la escena lifestyle real \
con el producto EN USO + el recuadro circular con el producto en mano en la esquina superior + la \
barra negra inferior con la etiqueta y el titular.
- Di EXPLÍCITO qué texto va: la etiqueta (ej. "VIRAL"), el titular COMPLETO en español entre comillas, \
y cuál frase va en AMARILLO. Textos LITERALES, cortos, bien escritos.
- El producto se renderiza a partir de la foto de referencia del cliente (respeta forma/color/logo).
- Termina SIEMPRE con: photorealistic, natural phone-camera lighting, believable real person, bottom \
black bar with bold condensed uppercase white headline and one phrase in bright yellow, small "VIRAL" \
style label, circular product inset with white border top corner, render all Spanish text crisply and \
spelled EXACTLY. Avoid: extra fingers, deformed hands, garbled or misspelled text, studio look, \
watermarks, nudity, low-resolution artifacts.

Devuelve EXACTAMENTE {n} advertorials, TODOS distintos entre sí (ángulo, escena, persona, entorno, \
titular)."""

_TOOL_ADV = {
    "name": "entregar_advertorials",
    "description": "Entrega las variantes de imagen ADVERTORIAL (noticia viral).",
    "input_schema": {
        "type": "object",
        "properties": {
            "variantes": {
                "type": "array",
                "description": "Advertorials, cada uno con ángulo/escena/titular DISTINTO.",
                "items": {
                    "type": "object",
                    "properties": {
                        "angulo": {"type": "string", "description": "el ángulo/tema de la 'nota' (corto)"},
                        "kicker": {"type": "string", "description": "etiqueta de la barra: VIRAL | TENDENCIA | RECOMENDADO | LO NUEVO"},
                        "titular": {"type": "string", "description": "titular de la nota (español, MAYÚSCULAS, periodístico)"},
                        "destacado": {"type": "string", "description": "la frase del titular que va en AMARILLO (entre comillas)"},
                        "escena": {"type": "string", "description": "la foto lifestyle: quién, dónde, cómo usa el producto"},
                        "por_que": {"type": "string", "description": "por qué frena el scroll y da credibilidad"},
                        "prompt": {"type": "string", "description": "prompt de imagen en inglés (ver instrucciones)"},
                    },
                    "required": ["angulo", "kicker", "titular", "destacado", "escena", "prompt"],
                },
            }
        },
        "required": ["variantes"],
    },
}

# Cierre de calidad del advertorial (4:5 vertical, no cuadrado).
_CIERRE_ADV = (" Photorealistic vertical 4:5 aspect ratio, natural phone-camera lighting, believable "
               "real everyday person and setting (NOT studio, NOT a polished ad). Bottom solid black "
               "bar with a bold CONDENSED uppercase white headline (2-3 lines) and ONE phrase in bright "
               "yellow inside single quotes; a small white 'VIRAL'-style label above it between thin "
               "lines. A circular product inset with a thick white border in a top corner. Render ALL "
               "Spanish text crisply and spelled EXACTLY as written. Avoid: extra fingers, deformed "
               "hands, garbled or misspelled text, studio look, random logos, watermarks, nudity, "
               "low-resolution artifacts.")


def generar_conceptos(producto: str, anthropic_key: str, page_text: str = "",
                      ofertas: list[str] | None = None, precio: str = "",
                      mercado: str = "Colombia · español colombiano · pago contraentrega (COD)",
                      evitar: list[str] | None = None, n: int = 10, plantillas_fijas: bool = True,
                      tipo: str = "disruptivo") -> list[dict]:
    """Claude inventa N variantes full-prompt (concepto + copy + prompt rico). Devuelve [] si falla.

    `evitar`: titulares/ángulos YA mostrados que NO gustaron → Claude da cosas TOTALMENTE distintas.
    `plantillas_fijas`: si True incluye las 2 plantillas ganadoras de primeras; si False, todo surreal.
    `tipo`: "disruptivo" (surreal, default) | "advertorial" (noticia viral con producto en uso)."""
    ofertas = [o for o in (ofertas or []) if o]
    evitar = [e for e in (evitar or []) if e and e.strip()]
    adv = str(tipo).lower().startswith("advert")
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
    if adv:
        pedido = (f"\nDame {n} ADVERTORIALS (noticia viral) para este producto, TODOS distintos entre "
                  "sí (ángulo, escena, persona, entorno, titular). Español colombiano.")
    elif plantillas_fijas:
        pedido = (f"\nInventa las {n} variantes: las 2 PRIMERAS son las plantillas FIJAS (no_compres, "
                  f"capturas) y de la 3 a la {n} surreales con los 6 motores, todas MUY distintas entre sí.")
    else:
        pedido = (f"\nEsta vez IGNORA la regla de las 2 plantillas fijas. Dame {n} conceptos TODOS surreales "
                  "y arriesgados, con mecanismos y escenas MUY distintos entre sí (y distintos a cualquiera "
                  "ya mostrado).")
    sistema = (_SISTEMA_ADV.replace("{n}", str(n)) if adv else _SISTEMA)
    tool = _TOOL_ADV if adv else _TOOL
    tool_name = tool["name"]
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=16000, system=sistema,
            tools=[tool], tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": ctx + pedido}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                variantes = list(block.input.get("variantes", []))
                if adv:
                    for v in variantes:      # marca el formato para la generación
                        v["formato"] = "advertorial"
                        v["apoyo"] = v.get("destacado", "")   # el destacado también se verifica
                return variantes
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
    es_adv = variant.get("formato") == "advertorial"
    textos = [variant.get("titular", ""), variant.get("apoyo", ""),
              variant.get("boton_cta", ""), variant.get("precio_cta", "")]
    errs: list = []
    got = False
    for intento in range(max_regen + 1):
        p = prompt if intento == 0 else (
            prompt + f" IMPORTANT (retry {intento}): make ABSOLUTELY every letter of the Spanish embedded "
            "text correct, complete and legible; do not misspell or repeat letters.")
        # ADVERTORIAL: el producto va EN la escena (persona usándolo + recuadro) → se pasa la foto
        # real como referencia y se usa el cierre 4:5. DISRUPTIVO: escena SIN producto (se pega luego).
        img = generar_imagen(p, gemini_key, out_path,
                             product_image_path=product_image_path if es_adv else None,
                             errors=errs, model=_IMG_MODEL if hd else _IMG_MODEL_DRAFT,
                             cierre=_CIERRE_ADV if es_adv else _CIERRE)
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
    if es_adv:
        variant["producto_integrado"] = True     # el producto ya va renderizado en la escena
        return out_path                           # advertorial es 4:5: NO se fuerza a cuadrado
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
                   errors: list | None = None, model: str | None = None,
                   cierre: str | None = None) -> str | None:
    """Nano Banana convierte el prompt en imagen (usa la foto del producto como referencia si hay).

    Reintenta ante errores transitorios de Google (500 INTERNAL / 503 / rate-limit) con backoff.
    Si `errors` es una lista, guarda ahí el último error crudo (para dar mensaje amigable).
    `cierre`: cola de calidad (por defecto la cuadrada 1:1; el advertorial pasa la 4:5)."""
    import time
    from google import genai
    from google.genai import types
    cola = cierre if cierre is not None else _CIERRE
    client = genai.Client(api_key=gemini_key)
    if product_image_path and os.path.exists(product_image_path):
        with open(product_image_path, "rb") as f:
            pb = f.read()
        mime = "image/png" if product_image_path.lower().endswith(".png") else "image/jpeg"
        contents = ["Use the product shown in this reference image (respect its exact shape, color and "
                    "label) placed into the following scene. " + prompt + cola,
                    types.Part.from_bytes(data=pb, mime_type=mime)]
    else:
        contents = [prompt + cola]

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
