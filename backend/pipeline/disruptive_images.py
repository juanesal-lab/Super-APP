"""Generador de ADS DISRUPTIVOS de imagen.

Anthropic (Claude) = cerebro creativo: inventa 10 conceptos disruptivos + prompts siguiendo el estilo
de Juan (skill ads-disruptivos-imagen). Google AI (Nano Banana / gemini-2.5-flash-image) = generación
visual: convierte cada prompt en una imagen. Metes CUALQUIER producto -> 10 creativos listos.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

_CLAUDE = "claude-opus-4-8"
_IMG_MODEL = "gemini-2.5-flash-image"   # Nano Banana

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
