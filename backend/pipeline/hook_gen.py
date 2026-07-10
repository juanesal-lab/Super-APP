"""Generacion automatica del texto de gancho con Gemini.

Combina: descripcion del producto + contenido de la pagina (si se da el link) +
un frame del producto -> Gemini escribe un gancho corto e impactante en espanol.
"""
from __future__ import annotations

import os
import re
import urllib.request

import cv2

from .analyze import Segment

_MODEL = "gemini-2.5-flash"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def fetch_page_text(url: str, max_chars: int = 3000) -> str:
    """Descarga la pagina y extrae el texto util (titulo, meta, JSON-LD, cuerpo)."""
    url = (url or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        html = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
    except Exception:
        return ""

    parts: list[str] = []
    patterns = [
        r"<title[^>]*>(.*?)</title>",
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I | re.S)
        if m:
            parts.append(m.group(1))
    # JSON-LD (suele traer nombre/descripcion/precio del producto)
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.I | re.S):
        parts.append(block[:800])
    # Cuerpo sin etiquetas como respaldo
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body)
    parts.append(body[:1500])

    text = " ".join(p.strip() for p in parts if p and p.strip())
    return text[:max_chars]


def _frame_bytes(seg: Segment) -> bytes | None:
    cap = cv2.VideoCapture(seg.video)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, (seg.start + seg.end) / 2.0 * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    h, w = frame.shape[:2]
    if max(h, w) > 640:
        sc = 640.0 / max(h, w)
        frame = cv2.resize(frame, (int(w * sc), int(h * sc)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None


# Intención del overlay por etapa del embudo (asset funnel-tofu-mofu-bofu-2026.md): TOFU frena el
# scroll con curiosidad/dolor, MOFU aporta prueba/mecanismo, BOFU empuja con oferta/urgencia.
_STAGE_HOOK = {
    "TOFU": ("ETAPA TOFU (público FRÍO): el overlay debe CURIOSEAR o nombrar el DOLOR para frenar "
             "el scroll de un desconocido — mecánicas CURIOSIDAD/SECRETO, DOLOR EXACTO, "
             "CONTRARIO/ADVERTENCIA o PARA EL SCROLL. PROHIBIDO oferta, precio, urgencia o "
             "'pagas al recibir' (espantan al frío). Ej: 'NADIE TE DICE ESTO'."),
    "MOFU": ("ETAPA MOFU (público TIBIO): el overlay debe dar PRUEBA o MECANISMO — mecánicas "
             "ANTES/DESPUES o PRUEBA, DATO IMPACTANTE, ERROR. Ej: 'MIRA LA DIFERENCIA', "
             "'4.8★ 12.000 RESEÑAS'. Sin oferta dura."),
    "BOFU": ("ETAPA BOFU (público CALIENTE): el overlay debe empujar la COMPRA con OFERTA o "
             "URGENCIA/escasez o reversión de riesgo. Ej: '2X1 SOLO HOY', 'PAGA AL RECIBIR', "
             "'ANTES DE QUE SE AGOTE' (sin cifras de dinero)."),
}


def generate_hook(api_key: str | None, product_desc: str = "",
                  page_text: str = "", sample_seg: Segment | None = None,
                  stage: str | None = None) -> str:
    """Devuelve un gancho corto e impactante, o '' si no se pudo.

    `stage` (opcional): 'TOFU'/'MOFU'/'BOFU' — sesga la INTENCIÓN del overlay a la etapa del
    embudo (curiosidad/problema, prueba/mecanismo, oferta/urgencia). Sin stage → como siempre."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return ""
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
    except Exception:
        return ""

    info = ""
    if product_desc.strip():
        info += f"\nProducto: {product_desc.strip()}"
    if page_text.strip():
        info += f"\nInfo de la pagina de venta: {page_text.strip()[:2500]}"

    prompt = (
        "Eres un copywriter experto en anuncios de dropshipping para LATAM (Colombia/Ecuador). "
        "Con base en el producto y su pagina (y el frame que te muestro), escribe UN solo gancho de "
        "TEXTO para incrustar en el PRIMER segundo de un video de TikTok/Reels.\n"
        "PASO 1 — elige la MECANICA que mejor calza con este producto (son los ganchos que mas venden "
        "y mas duran en US/UK/DE/FR, adaptados a LATAM):\n"
        "- DOLOR EXACTO: nombra el problema puntual del comprador ('¿CANSADO DE [problema]?').\n"
        "- CURIOSIDAD/SECRETO: 'NADIE TE DIJO ESTO', 'LO QUE NADIE TE CUENTA DE [X]'.\n"
        "- CONTRARIO/ADVERTENCIA: 'NO COMPRES [categoria] SIN VER ESTO', 'DEJA DE [habito]'.\n"
        "- ERROR: 'LO ESTAS HACIENDO MAL', 'EL ERROR QUE TE CUESTA [consecuencia]'.\n"
        "- ANTES/DESPUES o PRUEBA: 'DIA 1 VS DIA 30', 'LO USE 14 DIAS'.\n"
        "- DATO IMPACTANTE: '[objeto] ESTA MAS SUCIO QUE [comparacion]'.\n"
        "- PARA EL SCROLL: 'PARA. MIRA ESTO', para producto con demo visual fuerte.\n"
        "PASO 2 — llena la mecanica con el DOLOR o DESEO EXACTO del producto (sacado de la pagina), "
        "nunca generico. Debe nombrar el problema/beneficio concreto de ESTE producto.\n"
        "REGLAS DURAS: en espanol LATAM natural (tu/vos, como un amigo, nada corporativo); MAXIMO 6 "
        "palabras; en MAYUSCULAS; sin comillas, hashtags ni emojis; PROHIBIDO el precio o cifras de "
        "dinero. PROHIBIDAS las muletillas de IA/relleno (si aparece una, reescribe): 'INCREIBLE', "
        "'NO LO VAS A CREER' (solo), 'DESCUBRE EL SECRETO', 'REVOLUCIONARIO', 'CAMBIA TU VIDA', "
        "'EL MEJOR DEL MUNDO', 'IMPERDIBLE', 'ATENCION', 'MIRA ESTO' (solo, sin decir el problema). "
        "Que se entienda al instante y de ganas de seguir viendo.\n"
        + (("PASO 3 — AJUSTA LA INTENCIÓN A LA ETAPA DEL EMBUDO: " + _STAGE_HOOK[stage] + "\n")
           if stage in _STAGE_HOOK else "")
        + "Devuelve SOLO el texto del gancho (una linea)." + info
    )

    contents = [prompt]
    if sample_seg is not None:
        fb = _frame_bytes(sample_seg)
        if fb:
            contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))

    try:
        resp = client.models.generate_content(model=_MODEL, contents=contents)
        hook = (resp.text or "").strip().splitlines()[0] if resp.text else ""
        hook = hook.strip().strip('"').strip("'").strip()
        return hook[:50].upper()
    except Exception:
        return ""


def generate_hooks_for_versions(api_key: str | None, product_desc: str,
                                versiones: list[dict]) -> list[str]:
    """UN hook de texto (pastilla arriba, 0-3s) POR versión, COHERENTE con lo que dice cada una.

    `versiones`: lista de {"name": str, "guion": str} (el guion es lo que dice la voz de esa
    versión; puede venir vacío en el flujo sin voz → el hook se basa en el producto + ángulo).
    Devuelve una lista de hooks alineada a `versiones` (mismo largo/orden). Si la IA no responde,
    devuelve '' en esa posición (el caller pone un fallback honesto, nunca inventa cifras).

    Una sola llamada a Gemini (JSON array) para las N versiones → barato. Regla de Jack: SIN
    precios/cifras en el gancho, español, corto, coherente con el video."""
    n = len(versiones)
    if n == 0:
        return []
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return [""] * n
    bloques = []
    for i, v in enumerate(versiones):
        g = (v.get("guion") or "").strip()
        g = (g[:280] + "…") if len(g) > 280 else g
        bloques.append(f'{i}) ángulo "{v.get("name", "")}": '
                       + (f'lo que dice: "{g}"' if g else "(sin voz — básate en el producto)"))
    prompt = (
        "Eres copywriter de ads de dropshipping para LATAM (Colombia). Para CADA versión de un "
        f"anuncio del producto: {product_desc.strip() or '(producto)'}\n"
        "escribe UN hook de texto para los PRIMEROS 3 SEGUNDOS (va como pastilla arriba del video).\n"
        "REGLAS: español, MAYÚSCULAS, máximo 6 palabras, sin comillas/hashtags/emojis, "
        "NADA de precios ni cifras de dinero (ej: nada de '$', '2x1', '50%'). El hook debe ser "
        "COHERENTE con lo que dice/muestra ESA versión (curiosidad, problema→solución o deseo).\n"
        "Versiones:\n" + "\n".join(bloques) + "\n\n"
        f"Devuelve SOLO un JSON array de {n} strings, en el MISMO orden (uno por versión)."
    )
    texto = ""
    try:
        from . import gemini_fast
        texto = gemini_fast.generate(api_key, [prompt]) or ""
    except Exception:
        texto = ""
    if not texto:
        try:
            from google import genai
            resp = genai.Client(api_key=api_key).models.generate_content(
                model=_MODEL, contents=[prompt])
            texto = resp.text or ""
        except Exception:
            return [""] * n
    # parsear el JSON array (viene entre ```json ... ``` a veces)
    import json
    m = re.search(r"\[.*\]", texto, re.S)
    hooks: list[str] = []
    if m:
        try:
            arr = json.loads(m.group(0))
            hooks = [str(x).strip().strip('"').strip("'").strip()[:50].upper() for x in arr]
        except Exception:
            hooks = []
    if len(hooks) < n:                    # respaldo: reparte lo que haya, rellena con ''
        hooks += [""] * (n - len(hooks))
    return hooks[:n]
