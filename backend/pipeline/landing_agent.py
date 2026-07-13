"""Motor CREAR LANDINGS: arma la página ENTERA en automático y la publica en Shopify.

Flujo (pedido de Jack, el dueño):
  1. `generar_landing()` — Claude (claude-opus-4-8) escribe TODO el copy llenando la estructura
     VALIDADA de sus páginas reales (anexos de assets/landing-templates/*.md: 16 bloques el
     advertorial, 11 la landing), Nano Banana genera las imágenes con la FOTO REAL del producto
     como referencia, y se ensambla un PREVIEW HTML autocontenido (se sirve por /api/file).
  2. Jack APRUEBA en el preview (gate obligatorio — jamás se publica sin su clic).
  3. `publicar_en_shopify()` — sube las imágenes a Files (CDN) y crea SOLO recursos nuevos cm-*
     (sections/cm-*.liquid + templates/page.cm-*.json) vía shopify_admin. Nunca edita lo existente.

REGLAS INNEGOCIABLES (bakeadas acá, no solo en el prompt):
  - PRECIO y OFERTA: los EXACTOS que escribió Jack. El copy de Claude pasa por un limpiador que
    borra cualquier cifra de dinero/descuento que no venga del precio/oferta dados.
  - SIN personas inventadas: cero expertos con nombre, cero reviews falsas. La autoridad es
    framing genérico y los testimonios/reviews salen como PLACEHOLDERS [[EDITAR: ...]].
  - Salud policy-safe (sin curas milagro) y producto SIEMPRE con las fotos reales de Jack.

VÍA DE PUBLICACIÓN (decisión técnica): theme asset (section + template JSON) como vía principal
porque los scopes del token del módulo (write_themes/write_files, ver README-LANDINGS.md) la
GARANTIZAN; crear la página vía REST (/pages.json) requiere el scope `write_content` que el
README no pide, así que la página se intenta como best-effort y, si el token no alcanza, se
devuelven instrucciones honestas para crearla a mano (2 clics en el admin).
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import shutil
import time
import urllib.parse
from typing import Callable

import requests

from .disruptive_images import generar_imagen, _IMG_MODEL_DRAFT
from .ia_errors import error_amigable

_CLAUDE = "claude-opus-4-8"

# Placeholder estándar que Jack rellena con SU prueba social real (regla: nada inventado).
_PH = "[[EDITAR: {que}]]"


def _ph(que: str) -> str:
    return _PH.format(que=que)


# ───────────────────────── cierres de calidad por aspecto (Nano Banana) ─────────────────────────
# Fotografía real creíble (doctrina de disruptive_images) — el advertorial NO lleva texto dentro.
_CIERRE_FOTO = (" Photorealistic, natural phone-camera lighting, believable real everyday person "
                "and setting (NOT studio, NOT CGI). Avoid: any text or letters in the image, "
                "deformed hands, watermarks, random logos, low-resolution artifacts.")
# Infográfico de beneficio (landing): acá el texto SÍ va dentro (corto, exacto, entre comillas).
_CIERRE_INFO = (" Clean modern e-commerce benefit infographic, soft gradient background, the real "
                "product as the hero, bold legible typography, high contrast. Avoid: misspelled "
                "words, extra paragraphs, watermarks, deformed product, clutter.")
_ASPECTS = {"2:3": "Vertical 2:3 aspect ratio.", "4:5": "Vertical 4:5 aspect ratio.",
            "1:1": "Square 1:1 aspect ratio.", "16:9": "Horizontal 16:9 aspect ratio."}


def _cierre(aspect: str, info: bool = False) -> str:
    return " " + _ASPECTS.get(aspect, _ASPECTS["1:1"]) + (_CIERRE_INFO if info else _CIERRE_FOTO)


# ───────────────────────── limpiador de cifras inventadas ─────────────────────────

def _limpiar_cifras(texto: str, permitidas: list[str], avisos: list[str] | None = None) -> str:
    """Borra del copy cualquier cifra de dinero ($) o descuento (% off / ahorra $X) que NO esté
    contenida en el precio/oferta EXACTOS que dio Jack. '100% natural' se respeta (no es descuento)."""
    if not texto:
        return texto
    permitido = " ".join(p or "" for p in permitidas).lower()

    def _ok(frag: str) -> bool:
        f = re.sub(r"\s+", "", frag.lower())
        return bool(f) and f in re.sub(r"\s+", "", permitido)

    out = texto
    tocado = False
    # $ 79.900 / $79,900 / COP 79.900
    for m in re.findall(r"(?:\$|COP\s?)\s?[\d][\d.,]*", out):
        if not _ok(m):
            out = out.replace(m, "")
            tocado = True
    # -50% / 50% OFF / 50% de descuento / ahorra 30.000
    for m in re.findall(r"-?\d{1,3}\s?%\s?(?:off|dcto|de\s+descuento|descuento)", out, re.I):
        if not _ok(m):
            out = out.replace(m, "")
            tocado = True
    for m in re.findall(r"ahorr\w+\s+(?:\$?\s?[\d][\d.,]*)", out, re.I):
        if not _ok(m):
            out = out.replace(m, "")
            tocado = True
    if tocado and avisos is not None:
        avisos.append("Se borró del copy una cifra de precio/descuento que la IA inventó "
                      "(regla: solo el precio y la oferta EXACTOS que escribiste).")
    return re.sub(r"[ \t]{2,}", " ", out).strip()


# ───────────────────────── Claude: el copy por bloque (1 llamada grande) ─────────────────────────

_SISTEMA = """Eres el mejor copywriter de respuesta directa para dropshipping en Colombia \
(pago contraentrega). Llenas una ESTRUCTURA VALIDADA que ya vende — jamás inventas otra estructura. \
Español colombiano de MARKETING (no traducción literal).

REGLAS INNEGOCIABLES (romper una = respuesta inservible):
1. PROHIBIDO escribir cifras de dinero, precios, descuentos o "ahorros" ($, COP, %, "antes/ahora"). \
El sistema inserta el precio y la oferta EXACTOS del dueño donde van. Si necesitas hablar del costo \
del problema, hazlo CUALITATIVO ("una fortuna", "lo que vale un tratamiento de spa").
2. PROHIBIDO inventar personas: cero expertos con nombre o credenciales, cero testimonios o reseñas \
(el sistema pone placeholders que el dueño llena con reseñas reales). La autoridad se escribe con \
framing genérico ("dermatólogos en Colombia coinciden en...", sin nombre).
3. Salud policy-safe: nada de curas milagro, "elimina el dolor para siempre", promesas médicas \
absolutas. Beneficios realistas, expectativa honesta (la honestidad vende).
4. Si te dieron la OFERTA exacta (ej. "2x1 + envío gratis"), úsala LITERAL donde la estructura la pida."""

_TOOL_ADV = {
    "name": "entregar_advertorial",
    "description": "El copy del advertorial, bloque por bloque, siguiendo la estructura validada.",
    "input_schema": {
        "type": "object",
        "properties": {
            "categoria": {"type": "string", "description": "Categoría editorial corta (ej: Belleza & Cuidado de la piel)"},
            "headline": {"type": "string", "description": "Fórmula: Por qué [expertos] en Colombia están recomendando [producto/ingrediente] en vez de [alternativa cara] — y cómo está cambiando [rutina] después de los [edad]"},
            "subgancho": {"type": "string", "description": "Conspirativo: Lo que [industria] nunca te contó..."},
            "agitacion": {"type": "string", "description": "Empatía: Si tienes más de X, ya conoces la frustración... (2-4 frases)"},
            "problema_raiz": {"type": "string", "description": "El problema de fondo + costo del dolor CUALITATIVO (sin cifras $)"},
            "solucion_origen": {"type": "string", "description": "La solución y su origen con anclaje de prestigio"},
            "comparativa": {"type": "array", "minItems": 2, "maxItems": 3, "items": {
                "type": "object", "properties": {
                    "alternativa": {"type": "string"}, "contra": {"type": "string"}, "pro": {"type": "string"}},
                "required": ["alternativa", "contra", "pro"]},
                "description": "2-3 alternativas: ❌ contra de la alternativa vs ✔ pro del producto"},
            "mecanismo": {"type": "string", "description": "Ciencia simplificada creíble + metáfora + expectativa honesta"},
            "autoridad": {"type": "string", "description": "Framing genérico de expertos SIN nombres ni credenciales inventadas"},
            "proceso": {"type": "array", "minItems": 3, "maxItems": 4, "items": {
                "type": "object", "properties": {"etapa": {"type": "string"}, "texto": {"type": "string"}},
                "required": ["etapa", "texto"]},
                "description": "Etapas: Día 1-3 → Semana 2-3 → Mes 1+"},
            "cta_justificacion": {"type": "string", "description": "Justificación de la oferta (ej: uno para usar, otro de respaldo) SIN cifras"},
            "urgencia": {"type": "string", "description": "Urgencia honesta (⏳ la oferta termina hoy)"},
            "faq": {"type": "array", "minItems": 5, "maxItems": 6, "items": {
                "type": "object", "properties": {"p": {"type": "string"}, "r": {"type": "string"}},
                "required": ["p", "r"]},
                "description": "5-6 objeciones reales con respuesta"},
            "imagenes": {"type": "object", "description": "Escenas FOTOGRAFIABLES (sin texto en la imagen)",
                "properties": {
                    "hero": {"type": "string"}, "uso": {"type": "string"}, "lifestyle": {"type": "string"},
                    "antes_despues": {"type": "string", "description": "Cambio SUTIL y realista, misma persona (policy-safe)"},
                    "detalle": {"type": "string"}, "pack": {"type": "string"}},
                "required": ["hero", "uso", "lifestyle", "antes_despues", "detalle", "pack"]},
        },
        "required": ["categoria", "headline", "subgancho", "agitacion", "problema_raiz", "solucion_origen",
                      "comparativa", "mecanismo", "autoridad", "proceso", "cta_justificacion", "urgencia",
                      "faq", "imagenes"],
    },
}

_TOOL_LANDING = {
    "name": "entregar_landing",
    "description": "El copy de la landing corta y visual, bloque por bloque.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titulo_hero": {"type": "string", "description": "MAYÚSCULAS+emoji: [PRODUCTO] [OFERTA LITERAL si la hay] | [Beneficio] en [plazo] [emoji]. SIN precio."},
            "subtitulo": {"type": "string", "description": "1 línea de apoyo bajo el título"},
            "anti_imitaciones": {"type": "string", "description": "Aviso anti-imitaciones (⚠️ cuidado con copias...)"},
            "urgencia": {"type": "string", "description": "Urgencia corta para repetir entre bloques (🚨 MENOS DE 3 UNIDADES 🚨 estilo)"},
            "beneficios": {"type": "array", "minItems": 5, "maxItems": 7, "items": {
                "type": "object", "properties": {
                    "icono": {"type": "string", "description": "1 emoji"},
                    "frase": {"type": "string", "description": "Frase corta del beneficio (máx 8 palabras, para ir DENTRO del infográfico)"},
                    "escena": {"type": "string", "description": "Escena visual del infográfico (producto + contexto del beneficio)"}},
                "required": ["icono", "frase", "escena"]},
                "description": "5-7 beneficios → cada uno es un INFOGRÁFICO"},
            "cta_texto": {"type": "string", "description": "Texto del botón CTA (ej: 🛒 PEDIR AHORA — PAGA AL RECIBIR). SIN precio."},
            "hero_escena": {"type": "string", "description": "Escena de la imagen hero (producto protagonista)"},
            "pack_escena": {"type": "string", "description": "Escena de la imagen del pack de la oferta"},
        },
        "required": ["titulo_hero", "subtitulo", "anti_imitaciones", "urgencia", "beneficios",
                      "cta_texto", "hero_escena", "pack_escena"],
    },
}


def _copy_claude(tipo: str, product_desc: str, page_text: str, precio: str, oferta: str,
                 anthropic_key: str) -> dict:
    """1 llamada grande a Claude → dict con el copy por bloque (tool_use forzado = JSON válido).
    Lanza RuntimeError con mensaje honesto (motor real nombrado) si Claude no responde."""
    adv = str(tipo).lower().startswith("advert")
    ctx = f"PRODUCTO: {product_desc}\nMERCADO: Colombia · español colombiano · pago contraentrega (COD)\n"
    if (page_text or "").strip():
        ctx += f"\nCONTEXTO REAL DE LA PÁGINA DEL PRODUCTO (dolor/beneficio/uso reales):\n{page_text[:2500]}\n"
    if (oferta or "").strip():
        ctx += f"\nOFERTA EXACTA del dueño (úsala LITERAL donde la estructura la pida): {oferta.strip()}\n"
    ctx += ("\nRECUERDA: cero cifras de dinero/descuento (el sistema pone el precio), cero personas "
            "inventadas, salud policy-safe.\n")
    if adv:
        ctx += ("\nEscribe el ADVERTORIAL completo (artículo editorial largo, NO parece anuncio hasta "
                "el CTA, la oferta llega TARDE). Tercera persona periodística; el 'tú' solo para "
                "nombrar el dolor. Cifras específicas NO monetarias (días, edades) > adjetivos.")
    else:
        ctx += ("\nEscribe la LANDING corta y visual (venta directa, MAYÚSCULAS+emojis, ritmo rápido). "
                "Los beneficios son INFOGRÁFICOS: frase corta y potente por beneficio.")
    tool = _TOOL_ADV if adv else _TOOL_LANDING
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key, timeout=180.0, max_retries=1)
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=16000, system=_SISTEMA,
            tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": ctx}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool["name"]:
                return dict(block.input)
        raise RuntimeError("Claude respondió sin el copy estructurado")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("El copy no se pudo escribir — " + error_amigable(e, "Claude")) from e


# ───────────────────────── imágenes (plan por sección + best-effort) ─────────────────────────

def _optimizar(src: str, dst: str) -> str:
    """Optimiza el peso ANTES de subir a Shopify (regla del módulo): máx 1400px, JPEG q82."""
    try:
        from PIL import Image
        im = Image.open(src).convert("RGB")
        w, h = im.size
        if max(w, h) > 1400:
            sc = 1400.0 / max(w, h)
            im = im.resize((int(w * sc), int(h * sc)))
        im.save(dst, "JPEG", quality=82, optimize=True)
        return dst
    except Exception:  # noqa: BLE001
        try:
            shutil.copy(src, dst)
        except Exception:  # noqa: BLE001
            return src
        return dst


def _plan_imagenes(tipo: str, copy: dict, producto: str) -> list[dict]:
    """El plan de imágenes por sección según la plantilla (advertorial: 5-6 de apoyo /
    landing: hero + infográficos + pack). Cada item: {slot, prompt, aspect, info}."""
    if str(tipo).lower().startswith("advert"):
        esc = copy.get("imagenes") or {}
        base = f" Producto: {producto}."
        return [
            {"slot": "hero", "aspect": "4:5", "info": False,
             "prompt": (esc.get("hero") or f"Persona del público objetivo usando {producto} en un contexto real y cotidiano.") + base},
            {"slot": "uso", "aspect": "4:5", "info": False,
             "prompt": (esc.get("uso") or f"Primer plano de las manos aplicando/usando {producto}.") + base},
            {"slot": "lifestyle", "aspect": "4:5", "info": False,
             "prompt": (esc.get("lifestyle") or f"Escena lifestyle creíble con {producto} integrado en la rutina diaria.") + base},
            {"slot": "antes_despues", "aspect": "1:1", "info": False,
             "prompt": (esc.get("antes_despues") or "Comparación antes/después SUTIL y realista, misma persona, cambio conservador.") + base},
            {"slot": "detalle", "aspect": "1:1", "info": False,
             "prompt": (esc.get("detalle") or f"Detalle macro del producto {producto}, textura y empaque reales.") + base},
            {"slot": "pack", "aspect": "4:5", "info": False,
             "prompt": (esc.get("pack") or f"El pack de la oferta de {producto} sobre fondo limpio.") + base},
        ]
    plan = [{"slot": "hero", "aspect": "2:3", "info": False,
             "prompt": (copy.get("hero_escena") or f"{producto} protagonista, foto de producto premium.")
                       + f" Producto: {producto}."}]
    for i, b in enumerate((copy.get("beneficios") or [])[:7]):
        frase = (b.get("frase") or "").strip()
        plan.append({"slot": f"beneficio_{i + 1}", "aspect": "1:1", "info": True,
                     "prompt": (f"Infográfico de beneficio para e-commerce. Escena: "
                                f"{b.get('escena') or frase}. Ícono grande {b.get('icono') or '✅'} y el "
                                f'texto EXACTO en español, bien escrito y legible: "{frase}".')})
    plan.append({"slot": "pack", "aspect": "2:3", "info": False,
                 "prompt": (copy.get("pack_escena") or f"El pack de la oferta de {producto}, fondo limpio.")
                           + f" Producto: {producto}."})
    return plan


def _generar_imagenes(plan: list[dict], fotos: list[str], gemini_key: str, work_dir: str,
                      avisos: list[str], progress: Callable | None = None) -> list[dict]:
    """Genera cada imagen del plan con Nano Banana (draft, barato) usando la foto REAL del producto
    como referencia. Si una falla → esa sección usa la foto original (best-effort, avisando)."""
    out: list[dict] = []
    fotos = [f for f in (fotos or []) if f and os.path.exists(f)]
    n = max(1, len(plan))
    for i, item in enumerate(plan):
        if progress:
            progress(f"Generando imagen {i + 1}/{n} ({item['slot']})…", 35 + int(50 * i / n))
        raw = os.path.join(work_dir, f"img_{item['slot']}_raw.png")
        ref = fotos[i % len(fotos)] if fotos else None
        errs: list = []
        ok_path = None
        if (gemini_key or "").strip():
            ok_path = generar_imagen(item["prompt"], gemini_key, raw, product_image_path=ref,
                                     errors=errs, model=_IMG_MODEL_DRAFT,
                                     cierre=_cierre(item["aspect"], item["info"]))
        if not ok_path:
            # Degradación HONESTA: se usa la foto original de Jack y se avisa el motivo real.
            motivo = error_amigable(errs[0], "Gemini") if errs else \
                ("Falta la API key de Gemini en 🔑 Claves." if not (gemini_key or "").strip()
                 else "Gemini no devolvió imagen.")
            avisos.append(f"Imagen '{item['slot']}' no se pudo generar ({motivo}) — se usó tu foto original del producto.")
            if not ref:
                continue  # sin foto de respaldo no hay nada que mostrar en esa sección
            ok_path = ref
        final = _optimizar(ok_path, os.path.join(work_dir, f"img_{item['slot']}.jpg"))
        src = "/api/file?path=" + urllib.parse.quote(os.path.abspath(final))
        out.append({"slot": item["slot"], "path": os.path.abspath(final), "aspect": item["aspect"],
                    "src": src, "generada": ok_path != ref})
    return out


# ───────────────────────── ensamblado del HTML (preview autocontenido) ─────────────────────────

def _e(t: str) -> str:
    return _html.escape((t or "").strip())


def _img_tag(imgs: list[dict], slot: str, alt: str = "") -> str:
    for im in imgs:
        if im["slot"] == slot:
            return f'<img src="{im["src"]}" alt="{_e(alt or slot)}" loading="lazy">'
    return ""


_CSS_ADV = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Georgia,'Times New Roman',serif;color:#1c1c1c;background:#fff;line-height:1.65}
.cmwrap{max-width:680px;margin:0 auto;padding:20px 18px 60px}
img{max-width:100%;border-radius:10px;display:block;margin:18px auto}
.kicker{font-family:Arial,sans-serif;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#b3261e;font-weight:bold}
h1{font-size:30px;line-height:1.25;margin:10px 0 8px}
.sub{font-size:18px;color:#444;font-style:italic;margin-bottom:8px}
.meta{font-family:Arial,sans-serif;font-size:12.5px;color:#777;border-bottom:1px solid #e5e5e5;padding-bottom:12px;margin-bottom:18px}
h2{font-size:22px;margin:28px 0 10px}
p{margin:12px 0;font-size:17px}
table{width:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:14.5px;margin:16px 0}
td,th{border:1px solid #e2e2e2;padding:10px;vertical-align:top}
th{background:#faf7f2;text-align:left}
.si{color:#1c7c3c;font-weight:bold}.no{color:#b3261e;font-weight:bold}
.autoridad{background:#faf7f2;border-left:4px solid #c9a227;padding:14px 16px;font-style:italic;margin:18px 0}
.etapa{display:flex;gap:12px;margin:12px 0;font-family:Arial,sans-serif}
.etapa b{white-space:nowrap;color:#b3261e}
.ph{background:#fff8e1;border:2px dashed #e0a800;border-radius:10px;padding:14px;font-family:Arial,sans-serif;font-size:14px;color:#7a5c00;margin:10px 0}
.cta{background:#1c7c3c;color:#fff;text-align:center;border-radius:12px;padding:22px;margin:24px 0;font-family:Arial,sans-serif}
.cta .precio{font-size:30px;font-weight:800;margin:6px 0}
.cta .oferta{font-size:19px;font-weight:700;background:#fff;color:#1c7c3c;display:inline-block;border-radius:999px;padding:5px 16px;margin:6px 0}
.btn{display:inline-block;background:#ffb300;color:#1c1c1c;font-weight:800;font-size:18px;border-radius:999px;padding:14px 30px;text-decoration:none;margin-top:10px}
.garantia{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;font-family:Arial,sans-serif;font-size:14px;margin:14px 0}
.garantia span{background:#f4f4f4;border-radius:999px;padding:7px 14px}
.urgencia{font-family:Arial,sans-serif;text-align:center;color:#b3261e;font-weight:800;font-size:17px;margin:16px 0}
.faq{font-family:Arial,sans-serif;margin:14px 0}
.faq b{display:block;margin-top:12px}
@media(max-width:480px){h1{font-size:25px}p{font-size:16px}}
"""

_CSS_LANDING = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'Segoe UI',Arial,sans-serif;color:#181818;background:#fff;line-height:1.5}
.cmwrap{max-width:560px;margin:0 auto;padding:14px 14px 60px;text-align:center}
img{max-width:100%;border-radius:14px;display:block;margin:14px auto}
h1{font-size:26px;line-height:1.2;margin:12px 0 6px;text-transform:uppercase}
.sub{font-size:16px;color:#555;margin-bottom:10px}
.precio{background:linear-gradient(135deg,#ff5722,#e53935);color:#fff;border-radius:14px;padding:16px;margin:14px 0}
.precio .valor{font-size:34px;font-weight:900}
.precio .oferta{display:inline-block;background:#ffeb3b;color:#b3261e;font-weight:900;border-radius:999px;padding:5px 16px;font-size:17px;margin-top:6px}
.badge{display:inline-block;background:#fff3e0;color:#e65100;border:1.5px solid #ffb74d;border-radius:999px;padding:7px 14px;font-weight:800;font-size:14px;margin:8px 4px}
.urgencia{background:#b3261e;color:#fff;font-weight:900;font-size:16px;border-radius:10px;padding:10px;margin:14px 0;letter-spacing:.5px}
.envio{background:#e8f5e9;color:#1b5e20;font-weight:800;border-radius:10px;padding:10px;margin:14px 0;font-size:15px}
.ph{background:#fff8e1;border:2px dashed #e0a800;border-radius:10px;padding:12px;font-size:13.5px;color:#7a5c00;margin:10px 0;text-align:left}
.video{border:2px dashed #bbb;border-radius:14px;padding:34px 12px;color:#888;font-weight:700;margin:14px 0}
.btn{display:block;background:linear-gradient(135deg,#ff9800,#ff5722);color:#fff;font-weight:900;font-size:19px;border-radius:999px;padding:16px;text-decoration:none;margin:16px 0;box-shadow:0 6px 18px rgba(255,87,34,.35)}
.benef h3{font-size:19px;margin:16px 0 2px}
h2{font-size:21px;margin:22px 0 6px;text-transform:uppercase}
@media(max-width:480px){h1{font-size:22px}}
"""


def _bloque_precio(precio: str, oferta: str) -> tuple[str, str]:
    """(html_precio, html_oferta_pill) — EXACTOS como los escribió Jack, cero cifras derivadas."""
    p = _e(precio)
    o = _e(oferta)
    return (f'<div class="valor">{p}</div>' if p else "",
            f'<div class="oferta">🎁 {o}</div>' if o else "")


def _html_advertorial(c: dict, precio: str, oferta: str, imgs: list[dict], producto: str) -> tuple[str, str]:
    """(css, body) del advertorial — los 16 bloques EN ORDEN (data-bloque para auditar)."""
    hoy = time.strftime("%d/%m/%Y")
    p_val, p_off = _bloque_precio(precio, oferta)
    comp_rows = "".join(
        f"<tr><td><span class='no'>❌</span> <b>{_e(r.get('alternativa'))}</b>: {_e(r.get('contra'))}</td>"
        f"<td><span class='si'>✔</span> {_e(r.get('pro'))}</td></tr>"
        for r in (c.get("comparativa") or []))
    etapas = "".join(f"<div class='etapa'><b>{_e(r.get('etapa'))}</b><span>{_e(r.get('texto'))}</span></div>"
                     for r in (c.get("proceso") or []))
    faq = "".join(f"<b>❓ {_e(r.get('p'))}</b><span>{_e(r.get('r'))}</span>" for r in (c.get("faq") or []))
    testi_ph = "".join(
        f"<div class='ph'>💬 {_e(_ph('pega aquí una reseña REAL de tu cliente'))} — "
        f"<i>{_e(_ph('nombre y ciudad reales'))}</i></div>" for _ in range(2))
    reviews_ph = ("<div class='ph'>⭐ " + _e(_ph("tu métrica real, ej: 4.8★ basado en tus ventas")) + "</div>"
                  + "".join(f"<div class='ph'>💬 {_e(_ph('reseña real ' + str(i + 1) + ' (nombre, ciudad)'))}</div>"
                            for i in range(3)))
    body = f"""<div class="cmwrap">
<div data-bloque="01-headline"><span class="kicker">Informe especial · {_e(c.get('categoria'))}</span>
<h1>{_e(c.get('headline'))}</h1></div>
<div data-bloque="02-subgancho" class="sub">{_e(c.get('subgancho'))}</div>
<div data-bloque="03-meta" class="meta">{_e(c.get('categoria'))} · Actualizado {hoy}</div>
{_img_tag(imgs, 'hero', producto)}
<div data-bloque="04-agitacion"><p>{_e(c.get('agitacion'))}</p></div>
<div data-bloque="05-problema"><p>{_e(c.get('problema_raiz'))}</p></div>
{_img_tag(imgs, 'lifestyle', producto)}
<div data-bloque="06-solucion"><h2>El giro que nadie esperaba</h2><p>{_e(c.get('solucion_origen'))}</p></div>
<div data-bloque="07-comparativa"><h2>Método tradicional vs. {_e(producto)}</h2>
<table><tr><th>Lo de siempre ❌</th><th>{_e(producto)} ✔</th></tr>{comp_rows}</table></div>
<div data-bloque="08-mecanismo"><h2>Así funciona</h2><p>{_e(c.get('mecanismo'))}</p></div>
{_img_tag(imgs, 'uso', producto)}
<div data-bloque="09-autoridad" class="autoridad">{_e(c.get('autoridad'))}</div>
<div data-bloque="10-proceso"><h2>Qué esperar, semana a semana</h2>{etapas}</div>
{_img_tag(imgs, 'antes_despues', producto)}
<div data-bloque="11-testimonios"><h2>Lo que cuentan quienes ya lo usan</h2>{testi_ph}</div>
{_img_tag(imgs, 'detalle', producto)}
<div data-bloque="12-cta" class="cta"><div>Hoy con oferta por tiempo limitado ↓</div>
{p_val}{p_off}<p style="margin:8px 0">{_e(c.get('cta_justificacion'))}</p>
<a class="btn" href="#comprar">🛒 PEDIR AHORA — PAGA AL RECIBIR</a></div>
{_img_tag(imgs, 'pack', producto)}
<div data-bloque="13-garantia" class="garantia"><span>🛡️ Garantía 30 días</span><span>🚚 Envío gratis</span>
<span>✅ {_e(oferta) if (oferta or '').strip() else 'Pago contraentrega'}</span></div>
<div data-bloque="14-urgencia" class="urgencia">⏳ {_e(c.get('urgencia'))}</div>
<div data-bloque="15-faq" class="faq"><h2>Preguntas frecuentes</h2>{faq}</div>
<div data-bloque="16-reviews"><h2>Opiniones</h2>{reviews_ph}</div>
</div>"""
    return _CSS_ADV, body


def _html_landing(c: dict, precio: str, oferta: str, imgs: list[dict], producto: str) -> tuple[str, str]:
    """(css, body) de la landing — los 11 bloques EN ORDEN (data-bloque para auditar)."""
    p_val, p_off = _bloque_precio(precio, oferta)
    urg = f"<div class='urgencia'>🚨 {_e(c.get('urgencia'))} 🚨</div>"
    envio = "<div class='envio'>ENVÍO GRATIS 🚚 · PAGAS AL RECIBIR 📦</div>"
    benefs = ""
    for i, b in enumerate((c.get("beneficios") or [])[:7]):
        benefs += (f"<div class='benef'><h3>{_e(b.get('icono'))} {_e(b.get('frase'))}</h3>"
                   f"{_img_tag(imgs, f'beneficio_{i + 1}', b.get('frase'))}</div>")
        if i == 2:
            benefs += urg  # urgencia repetida ENTRE bloques (patrón de las páginas reales)
    body = f"""<div class="cmwrap">
<div data-bloque="01-hero">{_img_tag(imgs, 'hero', producto)}<h1>{_e(c.get('titulo_hero'))}</h1>
<div class="sub">{_e(c.get('subtitulo'))}</div></div>
<div data-bloque="02-precio" class="precio">{p_val}{p_off}</div>
<a class="btn" href="#comprar">{_e(c.get('cta_texto')) or '🛒 PEDIR AHORA — PAGA AL RECIBIR'}</a>
<div data-bloque="03-prueba-social" class="ph">🔥 {_e(_ph('tu prueba social real en vivo, ej: N personas viendo esto / última compra hace X min'))}</div>
<div data-bloque="04-anti-imitaciones"><span class="badge">⚠️ {_e(c.get('anti_imitaciones'))}</span></div>
<div data-bloque="05-metrica" class="ph">⭐ {_e(_ph('tu métrica real de clientes satisfechos'))}</div>
<div data-bloque="06-video" class="video">▶️ Míralo en acción — {_e(_ph('pega aquí tu video (opcional)'))}</div>
<div data-bloque="07-oferta" class="precio"><h2 style="margin:0">OFERTA</h2>{p_off or p_val}{p_val if p_off else ''}
<a class="btn" style="background:#fff;color:#e53935" href="#comprar">{_e(c.get('cta_texto')) or 'LO QUIERO'}</a></div>
<div data-bloque="08-urgencia">{urg}</div>
<div data-bloque="09-beneficios"><h2>Por qué lo vas a amar</h2>{benefs}</div>
<div data-bloque="10-envio">{envio}{_img_tag(imgs, 'pack', producto)}{envio}</div>
<div data-bloque="11-cta-final">{urg}<a class="btn" href="#comprar" id="comprar">{_e(c.get('cta_texto')) or '🛒 PEDIR AHORA — PAGA AL RECIBIR'}</a></div>
</div>"""
    return _CSS_LANDING, body


def _wrap_preview(css: str, body: str, titulo: str) -> str:
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_e(titulo)}</title><style>{css}</style></head><body>{body}</body></html>")


# ───────────────────────── el motor: generar_landing ─────────────────────────

def generar_landing(tipo: str, product_desc: str, page_text: str, precio: str, oferta: str,
                    fotos: list[str], gemini_key: str, anthropic_key: str, work_dir: str,
                    progress: Callable | None = None) -> dict:
    """Arma la página ENTERA: copy (Claude) + imágenes (Nano Banana draft, foto real como
    referencia, best-effort) + preview HTML autocontenido en work_dir. Devuelve el manifest
    {ok, preview_html, copy, imagenes, avisos, ...}. El preview se sirve por /api/file."""
    tipo = "advertorial" if str(tipo).lower().startswith("advert") else "landing"
    os.makedirs(work_dir, exist_ok=True)
    avisos: list[str] = []
    if not (anthropic_key or "").strip():
        return {"ok": False, "error": "Falta la API key de Claude (ANTHROPIC_API_KEY) en 🔑 Claves — "
                                       "es la que escribe el copy de la landing."}
    if not (precio or "").strip():
        return {"ok": False, "error": "Escribe el precio EXACTO (se usa tal cual, jamás se inventa)."}

    # (a) Claude escribe TODO el copy llenando la plantilla (1 llamada grande, JSON por bloque)
    if progress:
        progress("Claude está escribiendo el copy con tu estructura validada…", 8)
    try:
        copy = _copy_claude(tipo, product_desc, page_text or "", precio, oferta, anthropic_key)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    # Blindaje: cualquier cifra de dinero/descuento inventada se borra del copy (regla de oro)
    permitidas = [precio or "", oferta or ""]
    for k, v in list(copy.items()):
        if isinstance(v, str):
            copy[k] = _limpiar_cifras(v, permitidas, avisos)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    for kk, vv in list(item.items()):
                        if isinstance(vv, str):
                            item[kk] = _limpiar_cifras(vv, permitidas, avisos)

    # (b) plan de imágenes por sección → Nano Banana draft con la foto real; si falla → foto original
    if progress:
        progress("Generando las imágenes de la página…", 30)
    plan = _plan_imagenes(tipo, copy, product_desc.split("\n")[0][:80] or "el producto")
    imgs = _generar_imagenes(plan, fotos, gemini_key, work_dir, avisos, progress)
    if not imgs:
        avisos.append("La página quedó SIN imágenes (no se pudo generar ninguna y no había foto de "
                      "respaldo). Puedes regenerar o subir fotos y volver a intentar.")

    # (c) preview HTML autocontenido (estilos inline, mobile-first)
    if progress:
        progress("Ensamblando el preview de la página…", 90)
    producto_corto = (product_desc or "").split("\n")[0][:80] or "Producto"
    if tipo == "advertorial":
        css, body = _html_advertorial(copy, precio, oferta, imgs, producto_corto)
        titulo = copy.get("headline") or producto_corto
    else:
        css, body = _html_landing(copy, precio, oferta, imgs, producto_corto)
        titulo = copy.get("titulo_hero") or producto_corto
    preview = os.path.join(work_dir, "preview.html")
    with open(preview, "w", encoding="utf-8") as f:
        f.write(_wrap_preview(css, body, titulo))

    if progress:
        progress("Preview listo — revísalo y aprueba para subir a Shopify.", 100)
    # (d) manifest — lo que el endpoint guarda en el job y usa publicar_en_shopify
    return {"ok": True, "tipo": tipo, "producto": producto_corto, "titulo": titulo,
            "precio": precio, "oferta": oferta, "preview_html": os.path.abspath(preview),
            "css": css, "body_html": body, "copy": copy,
            "imagenes": imgs, "avisos": avisos}


# ───────────────────────── publicación en Shopify (solo recursos nuevos cm-*) ─────────────────────────

def _escapar_liquid(texto: str) -> str:
    """Evita que el HTML generado se interprete como Liquid dentro de la section."""
    return (texto or "").replace("{{", "&#123;&#123;").replace("{%", "&#123;%")


def _url_cdn(domain: str, token: str, file_id: str, intentos: int = 4) -> str:
    """La URL del CDN puede tardar unos segundos tras fileCreate — se consulta con reintentos."""
    from . import shopify_admin as sh
    gql = f"https://{(domain or '').strip().replace('https://', '').strip('/')}/admin/api/{sh._API_VER}/graphql.json"
    q = {"query": "query($id:ID!){node(id:$id){... on MediaImage{image{url}}}}",
         "variables": {"id": file_id}}
    for i in range(intentos):
        try:
            r = requests.post(gql, headers=sh._headers(token), json=q, timeout=20)
            url = ((((r.json() or {}).get("data") or {}).get("node") or {}).get("image") or {}).get("url") or ""
            if url:
                return url
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.5 * (i + 1))
    return ""


def publicar_en_shopify(manifest: dict, domain: str, token: str, theme_id, tipo: str,
                        producto: str) -> dict:
    """Sube las imágenes a Files (CDN) y crea la landing como recursos NUEVOS cm-* en el tema:
    sections/cm-*.liquid (el HTML completo con estilos) + templates/page.cm-*.json que la
    referencia. Best-effort adicional: crear la página (/pages.json) apuntando a esa plantilla;
    si el token no tiene el scope write_content, se devuelven instrucciones honestas.

    Por qué esta vía: los scopes del módulo (write_themes/write_files) GARANTIZAN el theme asset;
    la página REST exige write_content, que el README del módulo no pide → solo best-effort."""
    from . import shopify_admin as sh
    if not (domain or "").strip() or not (token or "").strip():
        return {"ok": False, "error": "Faltan las credenciales de Shopify en 🔑 Claves "
                                       "(dominio + Admin API token) — no se publicó nada."}
    if not manifest or not manifest.get("ok"):
        return {"ok": False, "error": "No hay una landing generada y aprobable para publicar."}
    avisos: list[str] = list(manifest.get("avisos") or [])

    v = sh.validar(domain, token)
    if not v.get("ok"):
        return {"ok": False, "error": v.get("error", "Shopify rechazó las credenciales")}
    t = sh.tema_publicado(domain, token, theme_id)
    if not t.get("ok"):
        return {"ok": False, "error": t.get("error", "No pude detectar el tema publicado")}
    tid = t["id"]

    # 1) imágenes → Shopify Files (CDN). Si UNA falla, se aborta (honesto: nada de páginas rotas).
    body = manifest.get("body_html") or ""
    for im in (manifest.get("imagenes") or []):
        up = sh.subir_imagen_files(domain, token, im["path"], alt=f"{producto} — {im['slot']}")
        if not up.get("ok"):
            return {"ok": False, "error": f"No se pudo subir la imagen '{im['slot']}' a Shopify: "
                                           f"{up.get('error', '')}"}
        url = up.get("url") or (_url_cdn(domain, token, up.get("id") or "") if up.get("id") else "")
        if not url:
            return {"ok": False, "error": f"Shopify no devolvió la URL CDN de la imagen '{im['slot']}' "
                                           "(reintenta en unos segundos)."}
        body = body.replace(im["src"], url)

    # 2) section liquid (HTML completo con estilos) + template JSON que la referencia — SOLO cm-*
    nombre = sh.nombre_unico(tipo, producto)
    liquid = ("<style>" + (manifest.get("css") or "") + "</style>\n"
              + _escapar_liquid(body) + "\n"
              + "{% schema %}\n"
              + json.dumps({"name": f"CM {tipo} {producto}"[:25],
                            "settings": [], "presets": [{"name": nombre[:25]}]},
                           ensure_ascii=False, indent=2)
              + "\n{% endschema %}\n")
    r1 = sh.crear_asset(domain, token, tid, f"sections/{nombre}.liquid", liquid)
    if not r1.get("ok"):
        return {"ok": False, "error": r1.get("error", "No se pudo crear la section")}
    template = json.dumps({"sections": {"main": {"type": nombre}}, "order": ["main"]},
                          ensure_ascii=False, indent=2)
    r2 = sh.crear_asset(domain, token, tid, f"templates/page.{nombre}.json", template)
    if not r2.get("ok"):
        return {"ok": False, "error": r2.get("error", "No se pudo crear la plantilla de página")}

    dom_limpio = (domain or "").strip().replace("https://", "").strip("/")
    out = {"ok": True, "template": nombre, "tema": t.get("nombre", ""),
           "url_admin": f"https://{dom_limpio}/admin/themes/{tid}/editor",
           "url_pagina": "", "avisos": avisos}

    # 3) best-effort: crear la PÁGINA nueva que usa la plantilla (requiere scope write_content)
    try:
        rp = requests.post(f"{sh._base(domain)}/pages.json", headers=sh._headers(token),
                           json={"page": {"title": manifest.get("titulo") or producto,
                                           "template_suffix": nombre, "body_html": ""}}, timeout=30)
        if rp.status_code in (200, 201):
            page = (rp.json() or {}).get("page") or {}
            out["url_pagina"] = f"https://{dom_limpio}/pages/{page.get('handle', '')}"
            out["url_admin"] = f"https://{dom_limpio}/admin/pages/{page.get('id', '')}"
        else:
            avisos.append("La plantilla quedó creada, pero el token no pudo crear la página "
                          f"(HTTP {rp.status_code} — suele faltar el scope write_content). "
                          "Créala a mano: Admin → Tienda online → Páginas → Agregar página → "
                          f"en 'Plantilla' elige '{nombre}'.")
    except Exception as e:  # noqa: BLE001
        avisos.append(f"La plantilla quedó creada; la página hay que crearla a mano "
                      f"(no se pudo vía API: {str(e)[:100]}). Admin → Páginas → Agregar página → "
                      f"plantilla '{nombre}'.")
    return out
