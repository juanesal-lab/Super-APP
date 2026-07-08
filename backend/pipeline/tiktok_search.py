"""Buscar creativos en TikTok a partir de una foto + nombre del producto.

Devuelve LINKS REALES de videos de TikTok (vía la API pública de tikwm, sin login), pero con
VERIFICACIÓN por IA para que sea SÍ O SÍ el MISMO producto que la foto (mismo tipo Y misma forma:
ej. "veneno de abeja EN CREMA", no en bótox). Prefiere videos SIN texto SOBREPUESTO (subtítulos/captions
que pone el creador, no la etiqueta del producto) y en ESPAÑOL.

Flujo:
  1) Gemini mira la foto → descripción precisa (producto + forma/formato) + keywords en español.
  2) tikwm busca hartos candidatos.
  3) Gemini compara la PORTADA de cada candidato con la foto → ¿mismo producto? ¿español? ¿cuánto texto
     SOBREPUESTO (nada/poco/mucho, ignorando el texto del producto)?
     Se queda solo con los que coinciden, ordenados (sin texto sobrepuesto primero, luego español).
Tarda un poco más, pero acierta. Si no hay foto, busca por el nombre (sin verificación visual).
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests

_TIKWM = "https://tikwm.com/api/feed/search"
_MODEL = "gemini-2.5-flash"
_UA = {"User-Agent": "Mozilla/5.0"}


def _client(api_key):
    from google import genai
    return genai.Client(api_key=api_key)


def analizar_foto(image_path: str, nombre: str, api_key: str,
                  image_paths: list[str] | None = None,
                  landing_text: str = "") -> dict:
    """Gemini: descripción precisa (producto + FORMA) + VARIAS búsquedas (amplía) + desc. Fallback: nombre.

    `image_paths` (opcional): hasta 6 imágenes del MISMO producto (fotos frente/lado/empaque y/o
    FRAMES sacados de un video suyo — p.ej. los 5 mejores frames de mejores_frames) → UNA sola
    llamada a Gemini con todas = ficha más completa.
    `landing_text` (opcional): texto de la página de venta del producto → contexto para el nombre
    EXACTO, beneficios y sinónimos (mejores términos de búsqueda). Firma vieja intacta."""
    paths = [p for p in (image_paths or [image_path])
             if p and os.path.exists(p)][:6]
    if not (api_key and paths):
        return {"keywords": nombre, "variants": _expandir(nombre, []), "desc": nombre}
    try:
        from google.genai import types
        datas = []
        for p in paths:
            with open(p, "rb") as f:
                datas.append(f.read())
        intro = ("Haz un ANÁLISIS VISUAL PROFUNDO de la foto de este producto de dropshipping — como un perito: "
                 if len(datas) == 1 else
                 f"Haz un ANÁLISIS VISUAL PROFUNDO de las {len(datas)} imágenes de este producto de dropshipping "
                 "(son el MISMO producto: fotos desde distintos ángulos y/o frames de un video suyo — combina "
                 "TODO lo que veas en ellas en una sola ficha) — como un perito: ")
        landing_block = ""
        if (landing_text or "").strip():
            landing_block = (
                "INFO DE SU PÁGINA DE VENTA (úsala para el nombre EXACTO, beneficios y sinónimos en "
                "keywords/variants/desc; OJO: si la página describe OTRO producto distinto al de las "
                f"imágenes, ignórala por completo y quédate con lo que VES): \"{landing_text.strip()[:2500]}\". ")
        prompt = (
            intro +
            "(1) qué ES exactamente y su CATEGORÍA (crema, gel, cápsulas, spray, aparato/dispositivo, collar…); "
            "(2) FORMA física exacta (cuadrado, rectangular, redondo, tipo pinza/clamshell, lápiz, pistola, de "
            "mano…) y tamaño aproximado (de bolsillo, de mesa…); (3) COLORES por parte (cuerpo, tapa, botones, "
            "luz); (4) MARCA o TEXTO visible en el producto/empaque (transcríbelo literal si se lee); "
            "(5) RASGOS DISTINTIVOS: bisagra, botón, pantalla, luz (color exacto), cable/puerto, ranura, textura; "
            "(6) CÓMO SE USA (dónde va puesto, qué parte del cuerpo toca); "
            "(7) NO CONFUNDIR CON: 1-3 productos PARECIDOS pero DISTINTOS con los que un buscador se "
            "confundiría (ej. lámpara UV de secar esmalte, masajeador, otro aparato similar). "
            f"El usuario lo llama: \"{nombre}\". " + landing_block + "Devuelve SOLO un JSON:\n"
            '{"keywords":"2-4 palabras CORTAS en español: tipo de producto + para qué sirve (ej. '
            '\'laser hongos uñas\', no solo \'laser\')",'
            '"variants":["7-9 búsquedas CORTAS y VARIADAS (2-4 palabras cada una) para encontrar el MÁXIMO '
            'de videos del MISMO producto. MEZCLA español E INGLÉS (mucho contenido está en inglés). '
            'Incluye: el nombre genérico del producto, su beneficio, y términos AMPLIOS. Ej. para una crema '
            'de veneno de abeja: \'veneno de abeja\', \'bee venom cream\', \'crema quita lunares\', '
            '\'mole removal cream\', \'quitar verrugas\', \'wart remover\', \'skin tag remover\'. '
            'NUNCA frases largas (dan poquísimos resultados)."],'
            '"desc":"FICHA VISUAL compacta (máx 5 líneas) con TODO el análisis: CATEGORÍA | FORMA y tamaño | '
            'COLORES por parte | MARCA/texto visible | RASGOS distintivos | USO | NO CONFUNDIR CON: ... '
            '(esta ficha la usan los jueces visuales para confirmar videos, sé preciso)"}')
        contents = [prompt] + [types.Part.from_bytes(data=d, mime_type="image/jpeg") for d in datas]
        resp = _client(api_key).models.generate_content(model=_MODEL, contents=contents)
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if m:
            d = json.loads(m.group(0))
            kw = str(d.get("keywords", "")).strip() or nombre
            variants = [str(v).strip() for v in (d.get("variants") or []) if str(v).strip()]
            variants = _expandir(kw, variants)
            return {"keywords": kw, "variants": variants,
                    "desc": str(d.get("desc", "")).strip() or nombre}
    except Exception:  # noqa: BLE001
        pass
    return {"keywords": nombre, "variants": _expandir(nombre, []), "desc": nombre}


def _expandir(kw: str, variants: list[str]) -> list[str]:
    """Garantiza HARTAS consultas (amplía) con términos de beneficios/demostración/compra, sin duplicar.
    Más consultas = más candidatos únicos = más chance de llegar a los links pedidos (mismo producto)."""
    kw = (kw or "").strip()
    pal = kw.split()
    # versiones más CORTAS/AMPLIAS de la frase (las cortas devuelven MUCHOS más resultados en tikwm)
    core = " ".join(pal[:3]) if len(pal) > 3 else kw
    base = " ".join(pal[:2]) if len(pal) >= 2 else kw
    # sufijos de demostración/compra sobre el núcleo CORTO (no sobre la frase larga)
    sufijos = ["", "resultados", "antes y después", "reseña", "cómo funciona",
               "review", "opiniones", "testimonio", "comprar"]
    extra = [f"{core} {s}".strip() for s in sufijos] + [base, f"{base} review"]
    out: list[str] = []
    for q in [kw, core] + variants + extra:
        q = (q or "").strip()
        if q and q.lower() not in {x.lower() for x in out}:
            out.append(q)
    return out[:16]


def mejores_frames(video_path: str, n: int = 5, muestreo: int = 24,
                   out_dir: str | None = None) -> list[str]:
    """Del VIDEO del producto saca los N MEJORES frames como JPG para usarlos de referencia MULTI-FRAME.

    Muestrea ~`muestreo` frames repartidos por todo el video (evitando intro/outro), puntúa cada uno
    por NITIDEZ (varianza del Laplaciano de cv2), DESCARTA los casi-negros (brillo medio muy bajo) y
    los borrosos, y devuelve las rutas de los N frames más nítidos y DISTINTOS entre sí (nada de 5
    fotogramas casi idénticos). Más frames de referencia = MUCHO mejor match del MISMO producto.
    Devuelve [] si no se pudo abrir el video o no hubo frames buenos."""
    if not (video_path and os.path.exists(video_path)):
        return []
    try:
        import cv2
    except ImportError:
        return []
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    out_dir = out_dir or os.path.dirname(video_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(video_path))[0]
    cand: list[tuple[float, "object", "object"]] = []   # (nitidez, mini_gris_32x32, frame_bgr)
    try:
        muestreo = max(6, muestreo)
        if total > 1:
            # posiciones repartidas evitando el primer/último 5% (intro/outro suelen ser malas)
            idxs = [int(total * (0.05 + 0.90 * i / (muestreo - 1))) for i in range(muestreo)]
        else:
            idxs = None                                  # sin metadata de frames: leer secuencial
        if idxs is not None:
            for idx in idxs:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, fr = cap.read()
                if not ok or fr is None:
                    continue
                _puntuar_frame(cv2, fr, cand)
        else:
            leidos = 0
            while len(cand) < muestreo * 3 and leidos < 4000:
                ok, fr = cap.read()
                if not ok or fr is None:
                    break
                leidos += 1
                if leidos % 5:                           # 1 de cada 5 fotogramas
                    continue
                _puntuar_frame(cv2, fr, cand)
    finally:
        cap.release()
    if not cand:
        return []
    cand.sort(key=lambda x: x[0], reverse=True)          # más NÍTIDOS primero
    # elige DISTINTOS: descarta el que sea casi igual (mini-gris) a uno ya elegido
    elegidos: list[tuple[float, object, object]] = []
    for tup in cand:
        if any(float(cv2.absdiff(tup[1], e[1]).mean()) < 8 for e in elegidos):
            continue
        elegidos.append(tup)
        if len(elegidos) >= n:
            break
    if len(elegidos) < n:                                # si el filtro dejó menos, completa con los mejores
        ya = {id(e[2]) for e in elegidos}
        for tup in cand:
            if id(tup[2]) not in ya:
                elegidos.append(tup)
            if len(elegidos) >= n:
                break
    out: list[str] = []
    for k, (_, _, fr) in enumerate(elegidos[:n]):
        h, w = fr.shape[:2]
        if w > 1024:
            fr = cv2.resize(fr, (1024, int(h * 1024 / w)))
        p = os.path.join(out_dir, f"{base}_best{k}.jpg")
        if cv2.imwrite(p, fr, [cv2.IMWRITE_JPEG_QUALITY, 90]):
            out.append(p)
    return out


def _puntuar_frame(cv2, fr, cand: list) -> None:
    """Añade (nitidez, mini_gris_32x32, frame) a `cand` si el frame NO es casi-negro ni borroso."""
    gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
    if float(gray.mean()) < 25:                          # casi negro → fuera
        return
    nit = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if nit < 40:                                         # muy borroso → fuera
        return
    cand.append((nit, cv2.resize(gray, (32, 32)), fr))


# Regiones donde el contenido suele estar en español (para priorizar sin gastar visión)
# Regiones hispanas preferidas — SIN Colombia (regla del dueño: excluir Colombia siempre)
_ES_REGIONS = {"MX", "ES", "AR", "PE", "CL", "EC", "VE", "GT", "BO", "DO", "CR",
               "PA", "UY", "PY", "SV", "HN", "NI", "US"}


_VIDEO_ID_RE = re.compile(r"/video/(\d+)")


def norm_tk_id(url_or_id: str) -> str:
    """ID ESTABLE de un video de TikTok, para deduplicar SIN que engañe el @usuario.

    El mismo video sale con handles distintos (vanity vs canónico, o el vendedor cambió de nombre)
    → la URL cambia pero el `video_id` NO. Dedup por este id evita repetir el mismo video.
    Acepta una URL (…/video/123…) o el id pelado; si no reconoce nada, devuelve la cadena tal cual
    (así un id de Foreplay u otra fuente pasa sin romperse)."""
    s = (url_or_id or "").strip()
    m = _VIDEO_ID_RE.search(s)
    if m:
        return m.group(1)
    return s


def _tk_key(c: dict) -> str:
    """Clave de dedup de un candidato de TikTok: su video_id (por `id` si viene, si no del url)."""
    return str(c.get("id") or norm_tk_id(c.get("url", "")))


def buscar_tiktok(keywords: str, count: int = 40, pages: int = 2) -> list[dict]:
    """Videos reales de TikTok con paginación + datos de engagement (views/likes/región/duración)."""
    out: list[dict] = []
    if not keywords.strip():
        return out
    cursor = 0
    try:
        for _ in range(max(1, pages)):
            r = requests.get(_TIKWM, params={"keywords": keywords, "count": 30, "cursor": cursor},
                             headers=_UA, timeout=25)
            data = (r.json() or {}).get("data") or {}
            vids = data.get("videos") or []
            for v in vids:
                au = (v.get("author") or {}).get("unique_id", "")
                vid = v.get("video_id", "")
                if au and vid:
                    out.append({
                        "id": str(vid),                # id ESTABLE del video (dedup sin engaño del @)
                        "url": f"https://www.tiktok.com/@{au}/video/{vid}",
                        "title": (v.get("title") or "").strip()[:120],
                        "cover": v.get("cover") or "",
                        "play": v.get("play") or "",   # mp4 directo (para verificación profunda)
                        "plays": int(v.get("play_count") or 0),
                        "likes": int(v.get("digg_count") or 0),
                        "region": (v.get("region") or "").upper(),
                        "dur": int(v.get("duration") or 0),
                    })
            if not data.get("hasMore") or not vids:
                break
            cursor = data.get("cursor") or (cursor + len(vids))
    except Exception:  # noqa: BLE001
        pass
    return out[:count]


def _posts_cuenta(unique_id: str, count: int = 30) -> list[dict]:
    """Videos recientes de UNA cuenta (tikwm api/user/posts) normalizados IGUAL que buscar_tiktok.

    Palanca de volumen del plan 30/30: los vendedores suben el MISMO producto 10-30 veces →
    explorar la cuenta de un video confirmado destapa el resto de sus creativos."""
    out: list[dict] = []
    if not (unique_id or "").strip():
        return out
    try:
        r = requests.get("https://tikwm.com/api/user/posts",
                         params={"unique_id": unique_id, "count": count},
                         headers=_UA, timeout=25)
        data = (r.json() or {}).get("data") or {}
        for v in data.get("videos") or []:
            au = (v.get("author") or {}).get("unique_id", "") or unique_id
            vid = v.get("video_id", "")
            if au and vid:
                out.append({
                    "id": str(vid),                # id ESTABLE del video (dedup sin engaño del @)
                    "url": f"https://www.tiktok.com/@{au}/video/{vid}",
                    "title": (v.get("title") or "").strip()[:120],
                    "cover": v.get("cover") or "",
                    "play": v.get("play") or "",
                    "plays": int(v.get("play_count") or 0),
                    "likes": int(v.get("digg_count") or 0),
                    "region": (v.get("region") or "").upper(),
                    "dur": int(v.get("duration") or 0),
                })
    except Exception:  # noqa: BLE001
        pass
    return out[:count]


_OVERLAY_SCORE = {"nada": 2, "poco": 1, "mucho": 0}


def _refs(ref_bytes) -> list[bytes]:
    """Normaliza la referencia: bytes sueltos O lista de bytes (multi-foto) → lista (máx 2).
    Los jueces usan MÁXIMO las 2 primeras fotos (tope de costo); todo caller viejo sigue igual."""
    if isinstance(ref_bytes, (list, tuple)):
        return [b for b in ref_bytes if b][:2]
    return [ref_bytes] if ref_bytes else []


def _verificar(cand: dict, ref_bytes, ref_desc: str, api_key: str) -> dict | None:
    """¿El video es SÍ O SÍ el mismo producto (tipo Y forma)? + muestra el producto + español + SIN texto sobrepuesto.
    `ref_bytes`: bytes de la foto de referencia, o LISTA de bytes (multi-foto: usa máx las 2 primeras)."""
    cover = cand.get("cover")
    refs = _refs(ref_bytes)
    if not (cover and refs):
        return None
    try:
        from google.genai import types
        cimg = requests.get(cover, headers=_UA, timeout=15).content
        if not cimg:
            return None
        cand["_cover_bytes"] = cimg   # cache: el 2º juez (Claude) la reusa sin re-descargar
        titulo = (cand.get("title") or "")[:120]
        etiq = ("Foto 1 = el producto de REFERENCIA que quiero" if len(refs) == 1 else
                f"Las primeras {len(refs)} fotos = el MISMO producto de REFERENCIA que quiero, "
                "desde distintos ángulos")
        prompt = (
            f"{etiq} (descripción: \"{ref_desc}\"). "
            f"La ÚLTIMA foto = portada de un video de TikTok (título: \"{titulo}\"). "
            "Tu trabajo es ser un JUEZ MUY ESTRICTO: solo aprobar el EXACTO MISMO producto. "
            "match=true SOLO si la portada muestra el MISMO PRODUCTO físico: misma CATEGORÍA/FORMATO "
            "(crema=crema, gel=gel, cápsulas=cápsulas, aparato=aparato) Y los MISMOS RASGOS DISTINTIVOS de la "
            "ficha (la MISMA forma exacta, los MISMOS colores por parte, el MISMO mecanismo/botón/luz/bisagra). "
            "Otro VENDEDOR con el producto IDÉNTICO (misma forma y rasgos, aunque otra marca/etiqueta) SÍ cuenta. "
            "PERO un producto solo PARECIDO o de la misma familia pero distinto (otra forma, otra presentación, "
            "otro uso, otro beneficio) = match=FALSE. "
            "match=false si: otra categoría/formato (crema vs pastillas/spray/bótox/inyección), otra forma "
            "física, otro propósito, un aparato parecido de OTRO USO (usa el TÍTULO: lámpara de SECAR esmalte ≠ "
            "láser para HONGOS; masajeador ≠ depilador), algo de 'NO CONFUNDIR CON' de la ficha, o si NO se ve "
            "claro el producto. REGLA DE ORO: ante CUALQUIER duda, o si no puedes verificar los rasgos "
            "distintivos → match=FALSE (mejor descartar uno bueno que colar uno malo). "
            "confianza: 'alta' solo si estás MUY seguro (apostarías dinero) que es el mismo producto; 'media' "
            "si es probable pero no confirmaste todos los rasgos; 'baja' si dudoso o la portada no lo deja claro. "
            "TEXTO SOBREPUESTO: distingue el texto AÑADIDO DIGITALMENTE encima del video (subtítulos, "
            "captions, títulos, stickers de texto — lo típico que pone el creador de TikTok) del texto que "
            "es parte REAL de la escena (la etiqueta o empaque del producto, letreros del lugar). SOLO cuenta "
            "el texto sobrepuesto digital; ignora por completo el texto del producto. Reporta texto_overlay = "
            "\"nada\" (sin texto sobrepuesto, o casi imperceptible), \"poco\" (algo de texto pero pequeño/discreto), "
            "o \"mucho\" (subtítulos/títulos grandes que tapan el video). "
            "Responde SOLO JSON: "
            '{"match":true/false,"confianza":"alta"/"media"/"baja","muestra_producto":true/false,'
            '"es":true/false,"texto_overlay":"nada"/"poco"/"mucho"}')
        contents = [prompt] + [types.Part.from_bytes(data=b, mime_type="image/jpeg") for b in refs]
        contents.append(types.Part.from_bytes(data=cimg, mime_type="image/jpeg"))
        resp = _client(api_key).models.generate_content(model=_MODEL, contents=contents)
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not m:
            return None
        d = json.loads(m.group(0))
        ov = str(d.get("texto_overlay", "poco")).strip().lower()
        return {"match": bool(d.get("match")), "muestra": bool(d.get("muestra_producto")),
                "es": bool(d.get("es")), "overlay": _OVERLAY_SCORE.get(ov, 1),
                "confianza": str(d.get("confianza", "media")).strip().lower()}
    except Exception:  # noqa: BLE001
        return None


def _broll_brief_claude(nombre: str, angulo: str, ref_desc: str, anthropic_key: str,
                        landing_text: str = "") -> dict | None:
    """CEREBRO (Claude): saca de la LANDING (fuente de verdad) el ángulo de venta + punto de dolor
    y de ahí las búsquedas de B-ROLL. La landing manda: si viene, el ángulo/dolor se DERIVAN de ella
    (no del texto suelto). Devuelve {"punto_dolor","angulo_resumen","publico","queries"[str]} o None."""
    if not anthropic_key:
        return None
    try:
        from anthropic import Anthropic
        tool = {
            "name": "brief_broll",
            "description": "Brief de B-roll para un anuncio de dropshipping, derivado de la landing.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "punto_dolor": {"type": "string",
                                    "description": "El dolor #1 del comprador según la landing, en 1 frase VISUAL (qué escena lo muestra)"},
                    "angulo_resumen": {"type": "string",
                                       "description": "El ángulo de venta que usa la landing, en 1 frase"},
                    "publico": {"type": "string",
                                "description": "A quién le habla (edad/género/situación) según la landing"},
                    "queries": {"type": "array", "items": {"type": "string"},
                                "description": "6-8 búsquedas cortas (2-4 palabras) para TikTok: ~5 del DOLOR en acción, ~2 del resultado/alivio, ~1 de la situación de uso. Español o inglés, lo que dé más resultados."},
                },
                "required": ["punto_dolor", "queries"],
            },
        }
        if landing_text.strip():
            prompt = (
                f"Esta es la LANDING (página de venta) de un producto de dropshipping llamado "
                f"\"{nombre}\". LÉELA — es la fuente de verdad del ángulo y del dolor:\n\n"
                f"=== LANDING ===\n{landing_text[:2500]}\n=== FIN LANDING ===\n\n"
                + (f"El vendedor además quiere reforzar este ángulo: \"{angulo}\". " if angulo.strip() else "")
                + "De la landing SACA: el ángulo de venta real, a quién le habla y el DOLOR #1 del "
                "comprador. Necesito B-ROLL: escenas que NO muestran el producto pero APOYAN ese "
                "ángulo — sobre todo el PUNTO DE DOLOR en acción (la persona SUFRIENDO la necesidad, "
                "la emoción cruda), y algo del después/alivio. Dame las búsquedas para hallar ese "
                "b-roll en TikTok, amarradas a lo que DICE la landing (no genéricas).")
        else:
            prompt = (
                f"Producto: \"{nombre}\". Ficha: \"{(ref_desc or '')[:400]}\". "
                + (f"Ángulo de venta / punto de dolor que quiere el vendedor: \"{angulo}\". " if angulo.strip() else "")
                + "Necesito B-ROLL para un anuncio de dropshipping: escenas que NO muestran el producto pero "
                "APOYAN su ángulo — sobre todo el PUNTO DE DOLOR en acción (la persona SUFRIENDO la "
                "necesidad, la emoción cruda), y un poco del después/alivio. "
                "Ej. almohadillas para incontinencia → dolor: 'mujer desesperada corriendo al baño', "
                "'sábanas mojadas vergüenza', 'mujer llorando frustrada baño'; resultado: 'mujer durmiendo "
                "tranquila', 'abuela feliz nietos'. Piensa QUÉ ESCENA le duele al comprador de ESTE producto "
                "con ESTE ángulo y dame las búsquedas.")
        client = Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=700,
            tools=[tool], tool_choice={"type": "tool", "name": "brief_broll"},
            messages=[{"role": "user", "content": prompt}])
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use" and b.name == "brief_broll":
                qs = [str(q).strip() for q in (b.input.get("queries") or []) if str(q).strip()]
                if qs:
                    return {"punto_dolor": str(b.input.get("punto_dolor") or ""),
                            "angulo_resumen": str(b.input.get("angulo_resumen") or ""),
                            "publico": str(b.input.get("publico") or ""),
                            "queries": qs[:8]}
    except Exception:  # noqa: BLE001
        pass
    return None


def _juzgar_broll_claude(cands: list[dict], nombre: str, punto_dolor: str,
                         anthropic_key: str) -> dict[int, str] | None:
    """JUEZ (Claude visión, 1 sola llamada): mira las portadas y dice cuáles SÍ son escena de apoyo
    y de qué fase. Devuelve {indice: fase} (fase canónica: problema/resultado/funcionamiento);
    los índices que no aparecen se DESCARTAN. None = fallo técnico (→ no filtrar)."""
    import base64
    if not (anthropic_key and cands):
        return None
    try:
        from anthropic import Anthropic
        covers = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(lambda c: requests.get(c["cover"], headers=_UA, timeout=15).content, c): i
                    for i, c in enumerate(cands) if c.get("cover")}
            for f in as_completed(futs):
                try:
                    b = f.result()
                    if b:
                        covers.append((futs[f], b))
                except Exception:  # noqa: BLE001
                    continue
        covers.sort()
        if not covers:
            return None
        tool = {
            "name": "juzgar_broll",
            "description": "Clasifica cada portada como escena de apoyo (o la descarta).",
            "input_schema": {
                "type": "object",
                "properties": {"escenas": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"i": {"type": "integer"},
                                   "fase": {"type": "string", "enum": ["dolor", "resultado", "uso", "no"]}},
                    "required": ["i", "fase"]}}},
                "required": ["escenas"],
            },
        }
        prompt = (
            f"Busco B-ROLL para un anuncio de \"{nombre}\". El punto de dolor del ángulo: "
            f"\"{punto_dolor or 'la necesidad que resuelve el producto'}\". Te paso {len(covers)} portadas "
            "de TikTok numeradas. Para CADA una dime su fase:\n"
            "- dolor: se VE el punto de dolor en acción (persona sufriendo/frustrada/la situación molesta)\n"
            "- resultado: el después — alivio, tranquilidad, problema resuelto\n"
            "- uso: la situación de uso (sin que el producto protagonice)\n"
            "- no: NO sirve (otra cosa, meme random, texto gigante, gente bailando sin relación)\n"
            "Sé DURO con 'no': b-roll que no cuadre con el ángulo daña el anuncio. Responde TODAS.")
        content: list = [{"type": "text", "text": prompt}]
        for k, (_, b) in enumerate(covers):
            content.append({"type": "text", "text": f"PORTADA {k}:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": _media_type(b),
                                                        "data": base64.b64encode(b).decode()}})
        client = Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=1500,
            tools=[tool], tool_choice={"type": "tool", "name": "juzgar_broll"},
            messages=[{"role": "user", "content": content}])
        canon = {"dolor": "problema", "resultado": "resultado", "uso": "funcionamiento"}
        out: dict[int, str] = {}
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use" and b.name == "juzgar_broll":
                for e in (b.input.get("escenas") or []):
                    try:
                        k, fase = int(e.get("i")), str(e.get("fase", "")).strip().lower()
                    except (TypeError, ValueError):
                        continue
                    if fase in canon and 0 <= k < len(covers):
                        out[covers[k][0]] = canon[fase]
        return out
    except Exception:  # noqa: BLE001
        return None


def _queries_broll(ref_desc: str, nombre: str, api_key: str, landing_text: str = "") -> list[str]:
    """Gemini inventa búsquedas de B-ROLL (escenas de APOYO, no del producto) adaptadas al ÁNGULO del
    producto: para skincare → 'antes y después rostro', 'piel lisa primer plano'; para un gadget →
    'manos usando', 'problema que resuelve'... Devuelve 4-6 consultas cortas.

    Si viene `landing_text`, esa es la fuente de verdad del ángulo (fallback cuando no hay Claude)."""
    try:
        if landing_text.strip():
            prompt = (
                f"Esta es la LANDING de venta del producto \"{nombre}\":\n\"{landing_text[:2000]}\"\n"
                "De la landing saca el DOLOR #1 del comprador y el ángulo de venta. Necesito B-ROLL de "
                "apoyo (escenas que NO muestran el producto, pero apoyan ESE ángulo): el DOLOR en acción, "
                "el resultado/alivio, la situación de uso. Dame 6 búsquedas CORTAS para TikTok (2-4 "
                "palabras, español o inglés) amarradas a lo que dice la landing. "
                "Responde SOLO JSON: {\"broll\":[\"...\"]}")
        else:
            prompt = (
                f"Producto: \"{nombre}\". Ficha: \"{ref_desc[:400]}\". Para armar un anuncio DOPAMÍNICO de este "
                "producto necesito B-ROLL de apoyo (escenas que NO muestran el producto, pero apoyan su ángulo "
                "de venta): el DOLOR en acción, la transformación/resultado, la situación de uso, reacciones. "
                "Dame 6 búsquedas CORTAS para TikTok (2-4 palabras, español o inglés según qué dé más resultados) "
                "de ese b-roll. Ej. crema facial → ['antes despues rostro','piel lisa primer plano','mujer "
                "aplicando crema','skin transformation']. Ej. gadget de limpieza → ['limpieza satisfactoria', "
                "'cleaning asmr','mugre antes despues']. Responde SOLO JSON: {\"broll\":[\"...\"]}")
        resp = _client(api_key).models.generate_content(model=_MODEL, contents=[prompt])
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if m:
            qs = [str(q).strip() for q in (json.loads(m.group(0)).get("broll") or []) if str(q).strip()]
            return qs[:6]
    except Exception:  # noqa: BLE001
        pass
    return []


_FASE_BROLL = {"dolor": "problema", "resultado": "resultado", "uso": "funcionamiento"}


def _verificar_broll_video(cand: dict, punto_dolor: str, angulo: str, api_key: str) -> dict | None:
    """VERIFICACIÓN PROFUNDA de B-roll: baja el video y mira 3 frames de ADENTRO para confirmar que
    el CONTENIDO (no solo la portada) ILUSTRA el punto de dolor / la escena de apoyo del ángulo.

    El juez de portada engaña (una miniatura que 'parece' dolor pero el video es un baile). Aquí se
    mira lo de adentro. Devuelve {"sirve":bool,"fase":str,"confianza":str} o None si no se pudo bajar.
    """
    import tempfile
    play = cand.get("play") or cand.get("video")
    if not (play and api_key):
        return None
    tmp = None
    try:
        import cv2
        from google.genai import types
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        with requests.get(play, headers=_UA, timeout=40, stream=True) as r:
            if r.status_code != 200:
                return None
            escrito = 0
            for chunk in r.iter_content(1 << 16):
                escrito += len(chunk)
                if escrito > 25 * 1024 * 1024:
                    break
                tmp.write(chunk)
        tmp.close()
        cap = cv2.VideoCapture(tmp.name)
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        frames = []
        for f in (0.2, 0.5, 0.8):
            if total > 1:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * f))
            ok, fr = cap.read()
            if ok and fr is not None:
                h, w = fr.shape[:2]
                if w > 480:
                    fr = cv2.resize(fr, (480, int(h * 480 / w)))
                ok2, buf = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 82])
                if ok2:
                    frames.append(buf.tobytes())
        cap.release()
        if not frames:
            return None
        titulo = (cand.get("title") or "")[:120]
        prompt = (
            f"Necesito B-ROLL de apoyo para un anuncio. El punto de dolor / ángulo es: "
            f"\"{punto_dolor or angulo or 'la necesidad que resuelve el producto'}\". "
            f"Te paso FRAMES DE ADENTRO de un video de TikTok (título: \"{titulo}\"). "
            "Eres un JUEZ ESTRICTO: di si el CONTENIDO de este video sirve como b-roll para ESE ángulo.\n"
            "- sirve=true SOLO si en los frames se VE de verdad una escena que apoya el ángulo: el "
            "DOLOR en acción (persona sufriendo/frustrada/la situación molesta), el RESULTADO/alivio, "
            "o la SITUACIÓN DE USO. Debe TENER QUE VER con el dolor del producto.\n"
            "- sirve=false si es otra cosa (baile sin relación, meme random, texto gigante en pantalla, "
            "producto DISTINTO protagonizando, gente hablando a cámara sin mostrar la escena, o no se "
            "entiende). Ante la duda o si el video no muestra CLARO la escena del ángulo → false.\n"
            "- fase: 'dolor' (se ve el sufrimiento/problema), 'resultado' (el después/alivio) o 'uso' "
            "(la situación de uso). Si sirve=false, fase='no'.\n"
            "- confianza: 'alta' si lo viste claro, 'media' si probable, 'baja' si dudoso.\n"
            "- texto_overlay: cuánto TEXTO SOBREPUESTO tiene (subtítulos/carteles grandes que puso el "
            "creador): 'nada', 'poco' o 'mucho'. (Preferimos b-roll LIMPIO, sin texto encima.)\n"
            'Responde SOLO JSON: {"sirve":true/false,"fase":"dolor"/"resultado"/"uso"/"no",'
            '"confianza":"alta"/"media"/"baja","texto_overlay":"nada"/"poco"/"mucho"}')
        contents: list = [prompt]
        for fb in frames:
            contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))
        resp = _client(api_key).models.generate_content(model=_MODEL, contents=contents)
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not m:
            return None
        d = json.loads(m.group(0))
        fase = _FASE_BROLL.get(str(d.get("fase", "")).strip().lower())
        return {"sirve": bool(d.get("sirve")) and fase is not None,
                "fase": fase or "problema",
                "confianza": str(d.get("confianza", "media")).strip().lower(),
                "texto_overlay": str(d.get("texto_overlay", "poco")).strip().lower()}
    except Exception:  # noqa: BLE001
        return None
    finally:
        if tmp is not None:
            try:
                os.remove(tmp.name)
            except OSError:
                pass


def buscar_broll(ref_desc: str, nombre: str, api_key: str, n: int = 10,
                 angulo: str = "", anthropic_key: str | None = None,
                 landing_text: str = "", verificar_contenido: bool = True) -> list[dict]:
    """Busca N escenas de B-ROLL en TikTok amarradas al ÁNGULO/PUNTO DE DOLOR del producto.

    - `landing_text`: la LANDING manda. Si viene, el ángulo/dolor y las búsquedas se DERIVAN de ella
      (fuente de verdad), con Claude o, sin él, con Gemini.
    - `anthropic_key`: Claude piensa las búsquedas Y hace el pre-filtro por portada (barato).
    - `verificar_contenido`: además mira el CONTENIDO de cada candidato (frames de adentro, Gemini)
      para confirmar que el video de verdad ilustra la escena — no solo la portada. Descarta lo que
      el contenido no cuadra y usa la fase confirmada por el contenido.
    """
    brief = _broll_brief_claude(nombre, angulo, ref_desc, anthropic_key, landing_text) if anthropic_key else None
    punto_dolor = (brief or {}).get("punto_dolor", angulo)
    queries = ((brief or {}).get("queries")
               or _queries_broll(ref_desc, nombre, api_key, landing_text)
               or [f"{nombre} antes y después", "satisfying asmr"])
    cands: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(6, len(queries))) as ex:
        for res in ex.map(lambda q: buscar_tiktok(q, count=25, pages=1), queries):
            for c in res:
                cands.setdefault(_tk_key(c), c)   # dedup por video_id (no por url)
    lst = [c for c in cands.values() if 3 <= c.get("dur", 0) <= 90 and c.get("region") != "CO"]
    # más views primero (b-roll viral = más dopamínico) y variedad de autores
    lst.sort(key=lambda c: c.get("plays", 0), reverse=True)
    pre, autores = [], set()
    # pool más grande cuando hay verificación (portada Y/O contenido) para que el filtro tenga de dónde
    hay_filtro = bool(anthropic_key) or verificar_contenido
    for c in lst:
        autor = c["url"].split("@")[1].split("/")[0] if "@" in c["url"] else c["url"]
        if autor in autores:
            continue
        autores.add(autor)
        pre.append(c)
        if len(pre) >= (28 if hay_filtro else n):
            break
    # 1) Pre-filtro barato por PORTADA (Claude visión, 1 llamada): descarta lo obvio y da una fase tentativa
    fases_cover = _juzgar_broll_claude(pre, nombre, punto_dolor, anthropic_key) if anthropic_key else None
    tras_cover = [(i, c) for i, c in enumerate(pre)
                  if fases_cover is None or i in fases_cover]

    # 2) Verificación PROFUNDA por CONTENIDO (Gemini mira frames de adentro): confirma que el video
    #    de verdad ilustra la escena del ángulo. Es lo que pidió Angelo: "que los b-roll realmente
    #    tengan que ver con el video". Si Gemini está caído (None), NO se descarta por eso (se
    #    conserva lo que aprobó la portada) — pero el que el contenido rechaza SÍ se saca.
    out = []
    if verificar_contenido and api_key and tras_cover:
        # solo verificamos los que tienen mp4 descargable; el resto pasa con su fase de portada.
        # TOPE DE COSTO: la verificación profunda baja el mp4 + 1 llamada Gemini por video → se acota
        # a los más virales (pre ya viene ordenado por views) con margen sobre lo que se pedirá (n).
        tope_ver = max(12, min(20, n * 2))
        con_video = [(i, c) for i, c in tras_cover if (c.get("play") or c.get("video"))]
        verificables = con_video[:tope_ver]
        resultados: dict[int, dict | None] = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_verificar_broll_video, c, punto_dolor, angulo, api_key): i
                    for i, c in verificables}
            for f in as_completed(futs):
                try:
                    resultados[futs[f]] = f.result()
                except Exception:  # noqa: BLE001
                    resultados[futs[f]] = None
        for i, c in tras_cover:                            # NO cortar en n: junta todos, luego ordena
            r = resultados.get(i)
            if r is not None and not r["sirve"]:
                continue                                   # el CONTENIDO lo rechazó: fuera
            fase = (r or {}).get("fase") or (fases_cover or {}).get(i, "problema")
            out.append({"url": c["url"], "title": c.get("title", ""), "cover": c.get("cover", ""),
                        "play": c.get("play", ""), "plays": c.get("plays", 0), "tipo": "broll",
                        "fase": fase, "verificado": r is not None and r["sirve"],
                        "texto_overlay": (r or {}).get("texto_overlay", "poco")})
    else:
        for i, c in tras_cover:
            out.append({"url": c["url"], "title": c.get("title", ""), "cover": c.get("cover", ""),
                        "play": c.get("play", ""), "plays": c.get("plays", 0), "tipo": "broll",
                        "fase": (fases_cover or {}).get(i, "problema"), "verificado": False,
                        "texto_overlay": "poco"})
    # ORDEN (pedido de Angelo): (1) SIN texto encima primero (nada<poco<mucho), (2) el DOLOR primero,
    # (3) verificados por contenido antes, (4) más views. Así los b-roll limpios y del dolor van arriba
    # y los con mucho texto solo se usan para rellenar si hace falta.
    _txt = {"nada": 0, "poco": 1, "mucho": 2}
    out.sort(key=lambda x: (_txt.get(x.get("texto_overlay", "poco"), 1),
                            0 if x["fase"] == "problema" else 1,
                            0 if x.get("verificado") else 1,
                            -int(x.get("plays", 0))))
    return out[:n]


def _foreplay_candidatos(queries: list[str], foreplay_key: str | None, max_q: int = 3) -> list[dict]:
    """Candidatos EXTRA desde Foreplay (biblioteca de ads GANADORES con video descargable).

    Se suman al mismo pool y pasan por la MISMA verificación visual (portada + video por dentro).
    El link que se entrega es el mp4 directo (descargable en 📥 Descargar)."""
    if not foreplay_key:
        return []
    try:
        from . import foreplay_search as fps
    except ImportError:
        return []
    out, vistos = [], set()
    for q in queries[:max_q]:
        try:
            r = fps.buscar_ads(q, api_key=foreplay_key, video_only=True)
        except Exception:  # noqa: BLE001
            continue
        if not r.get("ok"):
            continue
        for a in r.get("ads", []):
            vid = a.get("video")
            if not vid or vid in vistos:
                continue
            vistos.add(vid)
            try:
                dur = int(float(a.get("video_duration") or 30))
            except (TypeError, ValueError):
                dur = 30
            out.append({
                "url": vid,                                   # mp4 directo (descargable)
                "title": ((a.get("name") or "") + " · " + (a.get("description") or "")).strip(" ·")[:120],
                "cover": a.get("thumbnail") or "",
                "play": vid,                                  # para la verificación profunda
                "plays": int(a.get("dias") or 0) * 1000,      # días corriendo = señal de GANADOR
                "likes": 0, "region": "", "dur": min(120, max(5, dur)),
                "source": "foreplay",
                "foreplay_url": a.get("foreplay_url") or "",
            })
    return out


def _verificar_video(cand: dict, ref_bytes, ref_desc: str, api_key: str) -> dict | None:
    """VERIFICACIÓN PROFUNDA: baja el video (mp4 de tikwm) y mira 3 frames de ADENTRO.

    Muchos videos del producto no lo muestran en la PORTADA (sale el pie, el antes/después, la cara)
    → el juez de portada los rechazaba aunque el video SÍ era del producto. Aquí se juzga el contenido.
    Con multi-foto usa SOLO la 1ª referencia (los frames ya son varios: tope de costo).
    Devuelve el mismo dict que _verificar, o None si no se pudo."""
    import tempfile
    play = cand.get("play") or cand.get("video")   # tikwm (play) o Foreplay (video): ambos descargables
    refs = _refs(ref_bytes)
    if not (play and api_key and refs):
        return None
    ref_uno = refs[0]
    tmp = None
    try:
        import cv2
        from google.genai import types
        # descarga acotada (los de tikwm pesan poco; tope 25MB por si acaso)
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        # OJO: tikwm redirige al CDN → hay que seguir el redirect (no es un proxy expuesto, es fetch interno)
        with requests.get(play, headers=_UA, timeout=40, stream=True) as r:
            if r.status_code != 200:
                return None
            escrito = 0
            for chunk in r.iter_content(1 << 16):
                escrito += len(chunk)
                if escrito > 25 * 1024 * 1024:
                    break
                tmp.write(chunk)
        tmp.close()
        cap = cv2.VideoCapture(tmp.name)
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        frames = []
        for f in (0.25, 0.5, 0.75):
            if total > 1:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * f))
            ok, fr = cap.read()
            if ok and fr is not None:
                h, w = fr.shape[:2]
                if w > 480:
                    fr = cv2.resize(fr, (480, int(h * 480 / w)))
                ok2, buf = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 82])
                if ok2:
                    frames.append(buf.tobytes())
        cap.release()
        if not frames:
            return None
        titulo = (cand.get("title") or "")[:120]
        prompt = (
            f"Foto 1 = el producto de REFERENCIA que quiero (descripción: \"{ref_desc}\"). "
            f"Las demás fotos son FRAMES DE ADENTRO de un video de TikTok (título: \"{titulo}\"). "
            "Eres un JUEZ MUY ESTRICTO: solo aprobar el EXACTO MISMO producto. "
            "match=true SOLO si en algún frame se ve CLARAMENTE el MISMO producto físico que la referencia: "
            "misma categoría/formato Y los MISMOS RASGOS DISTINTIVOS de la ficha (la MISMA forma exacta, los "
            "MISMOS colores por parte, el MISMO mecanismo/botón/luz/bisagra). Otro vendedor con el producto "
            "IDÉNTICO (misma forma y rasgos) SÍ cuenta, aunque sea otra marca. PERO un producto solo PARECIDO "
            "o de la misma familia pero distinto (otra forma, otra presentación, otro uso) = FALSE. "
            "Aparatos parecidos de OTRO uso (lámpara de secar esmalte ≠ láser para hongos), 'NO CONFUNDIR CON' "
            "de la ficha, o si en NINGÚN frame se ve claro el producto = FALSE. REGLA DE ORO: ante CUALQUIER "
            "duda o si no confirmas los rasgos distintivos → match=FALSE. "
            "confianza: 'alta' solo si estás MUY seguro (viste los rasgos y coinciden); 'media' si probable "
            "pero no confirmaste todo; 'baja' si dudoso. "
            'Responde SOLO JSON: {"match":true/false,"confianza":"alta"/"media"/"baja",'
            '"muestra_producto":true/false,"es":true/false,"texto_overlay":"nada"/"poco"/"mucho"}')
        contents = [prompt, types.Part.from_bytes(data=ref_uno, mime_type="image/jpeg")]
        for fb in frames:
            contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))
        resp = _client(api_key).models.generate_content(model=_MODEL, contents=contents)
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not m:
            return None
        d = json.loads(m.group(0))
        ov = str(d.get("texto_overlay", "poco")).strip().lower()
        return {"match": bool(d.get("match")), "muestra": bool(d.get("muestra_producto")),
                "es": bool(d.get("es")), "overlay": _OVERLAY_SCORE.get(ov, 1),
                "confianza": str(d.get("confianza", "media")).strip().lower()}
    except Exception:  # noqa: BLE001
        return None
    finally:
        if tmp is not None:
            try:
                os.remove(tmp.name)
            except OSError:
                pass


_CLAUDE = "claude-opus-4-8"
_CLAUDE_TOOL = {
    "name": "juzgar",
    "description": "Dice si la portada del TikTok es el MISMO producto que la foto de referencia.",
    "input_schema": {
        "type": "object",
        "properties": {"match": {"type": "boolean", "description": "true SOLO si es el mismo producto (tipo Y forma física)"}},
        "required": ["match"],
    },
}


def _media_type(b: bytes) -> str:
    """Detecta el tipo real de la imagen por sus bytes mágicos (Claude exige el media_type correcto)."""
    if b[:8].startswith(b"\x89PNG"):
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _verificar_claude(cand: dict, ref_bytes, ref_desc: str, anthropic_key: str) -> bool | None:
    """SEGUNDO JUEZ (Claude Opus con visión): ¿la portada es el MISMO producto (tipo + forma física)?
    True=sí, False=no, None=no pudo opinar (fallo técnico → no se descarta por eso).
    `ref_bytes`: bytes o LISTA de bytes (multi-foto: usa máx las 2 primeras como referencia)."""
    import base64
    cover = cand.get("cover")
    refs = _refs(ref_bytes)
    if not (cover and anthropic_key and refs):
        return None
    try:
        cimg = cand.get("_cover_bytes") or requests.get(cover, headers=_UA, timeout=15).content
        if not cimg:
            return None
        titulo = (cand.get("title") or "")[:120]
        etiq = ("Foto 1 = el producto de REFERENCIA que quiero" if len(refs) == 1 else
                f"Las primeras {len(refs)} fotos = el MISMO producto de REFERENCIA que quiero, "
                "desde distintos ángulos")
        prompt = (
            f"{etiq} (descripción: \"{ref_desc}\"). "
            f"La ÚLTIMA foto = portada de un video de TikTok (título: \"{titulo}\"). "
            "Eres un JUEZ MUY ESTRICTO: solo aprobar el EXACTO MISMO producto. Compara FÍSICAMENTE. "
            "match=true SOLO si la PORTADA muestra CLARAMENTE el MISMO producto que la REFERENCIA: mismo tipo "
            "de objeto, la MISMA forma/formato físico exacto (un aparato cuadrado ≠ rectangular ≠ tipo "
            "lápiz/pistola; crema ≠ pastillas ≠ spray) Y los MISMOS rasgos distintivos (colores por parte, "
            "botón/luz/bisagra). Otro vendedor con el producto IDÉNTICO sí cuenta (aunque otra marca), pero un "
            "producto solo PARECIDO o de la misma familia pero distinto = match=false. Aparatos parecidos de "
            "OTRO USO (lámpara de SECAR esmalte ≠ láser para HONGOS; masajeador ≠ depilador) = false; usa el "
            "título para desempatar. Algo de 'NO CONFUNDIR CON' de la ficha = false. "
            "REGLA DE ORO: si es otro producto, otra forma, no se ve claro el producto, no puedes confirmar los "
            "rasgos, o hay CUALQUIER duda → match=false (mejor descartar un bueno que colar un malo). Es UGC: "
            "el producto puede estar en la mano, en ángulo o con otra luz, pero los RASGOS deben coincidir.")
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)
        content = [{"type": "text", "text": prompt}]
        for b in refs + [cimg]:
            content.append({"type": "image", "source": {"type": "base64", "media_type": _media_type(b),
                                                        "data": base64.b64encode(b).decode()}})
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=300,
            tools=[_CLAUDE_TOOL], tool_choice={"type": "tool", "name": "juzgar"},
            messages=[{"role": "user", "content": content}])
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use" and b.name == "juzgar":
                return bool(b.input.get("match"))
    except Exception:  # noqa: BLE001
        return None
    return None


def buscar(image_path: str | None = None, nombre: str = "", api_key: str | None = None,
           count: int = 20, anthropic_key: str | None = None,
           analisis: dict | None = None, foreplay_key: str | None = None,
           image_paths: list[str] | None = None, explorar_cuentas: bool = True,
           landing_text: str = "", solo_confirmados: bool = True,
           rellenar_n: bool = False) -> dict:
    """foto/nombre -> {ok, keywords, links:[{url,title,cover}], busqueda, verificado}.

    Si hay `anthropic_key`, Claude actúa de SEGUNDO juez (doble verificación) sobre lo que Gemini aprobó.
    Si hay `foreplay_key`, también busca en la biblioteca de ads GANADORES de Foreplay (misma verificación).
    `analisis` (opcional): el dict de analizar_foto YA calculado (lo pasa creative_search para que la
    búsqueda combinada TikTok+Foreplay analice la foto UNA sola vez). Sin él, se calcula aquí (igual
    que siempre).
    `image_paths` (opcional): hasta 4 imágenes del MISMO producto (fotos frente/lado/empaque y/o
    FRAMES de un video suyo — fotos primero) → ficha más completa; los jueces usan las 2 primeras
    como referencia. Sin él, todo sigue con `image_path`.
    `explorar_cuentas`: si tras verificar faltan videos para el count, explora las CUENTAS de los
    confirmados (máx 3, tikwm user/posts) — los vendedores suben el mismo producto muchas veces —
    y suma los que el juez de portada confirme (solo portada: tope de costo).
    `landing_text` (opcional): texto de la página de venta → mejor ficha y términos (cero llamadas
    extra: va dentro de la misma llamada de analizar_foto).
    `rellenar_n` (flujo "buscar creativos"): rellena hasta `count` usando SOLO matches CONFIRMADOS
    de confianza ALTA o MEDIA (tier 1 y 2) — NUNCA confianza baja ni "solo por título". El juez NO
    se afloja: para llegar al count se agranda el POOL de candidatos (más términos multilingües, más
    páginas), no se bajan los estándares. Si hay menos de `count` matches verdaderos, devuelve MENOS
    honestamente. Cada link lleva `tier`/`confianza` y `verificado_producto=True`. Default False =
    comportamiento estricto de siempre para otros llamadores."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ref_bytes = None
    ref_desc = nombre
    queries = _expandir(nombre, [])
    paths = [p for p in (image_paths or [image_path]) if p and os.path.exists(p)][:6]
    if paths:
        info = analisis or analizar_foto(paths[0], nombre, api_key, image_paths=paths,
                                         landing_text=landing_text)
        ref_desc = info["desc"]
        queries = info.get("variants") or [info["keywords"]]
        refs: list[bytes] = []
        for p in paths[:2]:            # jueces: máximo 2 fotos de referencia (tope de costo)
            try:
                with open(p, "rb") as f:
                    refs.append(f.read())
            except Exception:  # noqa: BLE001
                pass
        ref_bytes = refs or None       # lista: _verificar/_verificar_claude la aceptan tal cual
    queries = [q for q in queries if q][:16] or [(nombre or "").strip()]
    kw = queries[0]

    # AMPLIAR: MUCHAS consultas (producto + beneficios/compra) × varias páginas → muchísimos candidatos.
    # En PARALELO para que buscar en 10 términos × 3 páginas no se demore.
    cands: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(lambda q: buscar_tiktok(q, count=60, pages=4), queries):
            for c in res:
                cands.setdefault(_tk_key(c), c)   # dedup por video_id (no por url: el @ engaña)
    # + FOREPLAY: ads GANADORES ya probados (video descargable) al MISMO pool y con la MISMA verificación
    for c in _foreplay_candidatos(queries, foreplay_key):
        cands.setdefault(_tk_key(c), c)
    cand_list = list(cands.values())
    # EXCLUIR COLOMBIA (regla del dueño) + descartar duraciones raras (fuera de 4-120s)
    filtered = [c for c in cand_list if 4 <= c.get("dur", 0) <= 120 and c.get("region") != "CO"]
    cand_list = filtered or [c for c in cand_list if c.get("region") != "CO"] or cand_list
    # PRE-ORDENA: región hispana (sin CO) + más views (virales) primero
    cand_list.sort(key=lambda c: (1 if c.get("region") in _ES_REGIONS else 0, c.get("plays", 0)),
                   reverse=True)

    verificado = False
    if ref_bytes and api_key and cand_list:
        verificado = True
        # RELEVANCIA POR TÍTULO antes de gastar visión: los videos del PRODUCTO real (vendedores de
        # TikTok Shop) casi siempre nombran el producto en el título/hashtags, mientras los virales de
        # salones/clínicas dominan por views. Sin esto, el pool a verificar se llenaba de virales
        # equivocados y los videos buenos NUNCA llegaban a verificarse (causa del "solo 1 de 30").
        terms: set[str] = set()
        for q in queries:
            terms.update(w for w in q.lower().split() if len(w) >= 4)
        terms.update(w.strip(".,;:()\"'") for w in ref_desc.lower().split() if len(w) >= 5)

        def _title_score(c) -> int:
            t = (c.get("title") or "").lower()
            return sum(1 for w in terms if w and w in t)
        cand_list.sort(key=lambda c: (_title_score(c),
                                      1 if c.get("region") in _ES_REGIONS else 0,
                                      c.get("plays", 0)), reverse=True)
        # Verifica MUCHOS más (escalado a lo que pide el usuario): como el filtro estricto de "mismo
        # producto" descarta hartos, hay que revisar un pool grande para LLEGAR al count pedido.
        pool_n = min(len(cand_list), max(150, count * 8))
        pool = cand_list[:pool_n]             # los más RELEVANTES primero (título > hispano > views)
        # ── VERIFICACIÓN EXACTA: por CONTENIDO del video, no por portada ─────────────────────
        # 1) PORTADA = pre-filtro BARATO. NO confirma sola (engaña: antes/después, cara, pie): solo
        #    PRIORIZA a cuáles vale la pena bajar el video para juzgarlo por dentro.
        cover_res: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = {ex.submit(_verificar, c, ref_bytes, ref_desc, api_key): c for c in pool}
            for fut in as_completed(futs):
                v = fut.result()
                if v:
                    cover_res[id(futs[fut])] = v
        _CONF = {"alta": 2, "media": 1, "baja": 0}

        def _prio(c):
            v = cover_res.get(id(c)) or {}
            return (1 if v.get("match") else 0, _CONF.get(v.get("confianza"), 0),
                    _title_score(c), c.get("plays", 0))

        def _confirmar_contenido(cands):
            """DEEP: baja el video y lo juzga por DENTRO. EXACTO = match + confianza NO baja.
            SIEMPRE (también con `rellenar_n`) se DESCARTA la confianza baja: el flujo "buscar
            creativos" solo devuelve el MISMO producto confirmado (alta/media), nunca match=false ni
            baja. Cada match queda etiquetado con `_conf` (alta/media) para el tier."""
            out = []
            cands = [c for c in cands if (c.get("play") or c.get("video"))]
            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(_verificar_video, c, ref_bytes, ref_desc, api_key): c for c in cands}
                for fut in as_completed(futs):
                    v = fut.result()
                    if v and v.get("match") and v.get("confianza") != "baja":
                        c = futs[fut]
                        c["_conf"] = v.get("confianza")
                        c["_rank"] = (_CONF.get(v.get("confianza"), 0), v.get("muestra", False),
                                      v.get("overlay", 1), v.get("es", False), c.get("plays", 0))
                        out.append(c)
            return out

        # a DEEP: portada aprobó O título fuerte (la portada a veces no muestra el producto), por prioridad.
        a_deep = [c for c in pool if (c.get("play") or c.get("video")) and
                  ((cover_res.get(id(c)) or {}).get("match") or _title_score(c) >= 2)]
        a_deep.sort(key=_prio, reverse=True)
        a_deep = a_deep[:min(len(a_deep), max(60, count * 4))]   # presupuesto de descargas (pool amplio)
        matches = _confirmar_contenido(a_deep)
        matches.sort(key=lambda c: c.get("_rank", ()), reverse=True)

        # 2) DOBLE JUEZ: Claude VETA (2º juez estricto) lo confirmado por contenido. False = fuera;
        #    True o None (fallo técnico) = se queda (ya pasó el filtro ESTRICTO de contenido).
        if anthropic_key and matches:
            res_cl: dict[int, object] = {}
            with ThreadPoolExecutor(max_workers=5) as ex:
                cf = {ex.submit(_verificar_claude, c, ref_bytes, ref_desc, anthropic_key): c for c in matches}
                for fut in as_completed(cf):
                    res_cl[id(cf[fut])] = fut.result()
            matches = [c for c in matches if res_cl.get(id(c)) is not False]

        # 3) CUENTAS VENDEDORAS: si faltan, explora las cuentas de los confirmados y DEEP-verifica sus
        #    posts con el MISMO filtro exacto (no solo portada) para que no se cuele nada.
        if explorar_cuentas and matches and len(matches) < count:
            vistos_urls = {_tk_key(c) for c in cand_list} | {_tk_key(c) for c in matches}
            cuentas: list[str] = []
            for c in matches:
                u = c.get("url", "")
                if "/@" in u:
                    uid = u.split("/@", 1)[1].split("/", 1)[0]
                    if uid and uid not in cuentas:
                        cuentas.append(uid)
                if len(cuentas) >= 3:
                    break
            extra_cands: list[dict] = []
            if cuentas:
                with ThreadPoolExecutor(max_workers=3) as ex:
                    for res in ex.map(lambda u: _posts_cuenta(u, count=30), cuentas):
                        for c in res:
                            if (_tk_key(c) not in vistos_urls and c.get("region") != "CO"
                                    and 4 <= c.get("dur", 0) <= 120 and c.get("play")):
                                vistos_urls.add(_tk_key(c))
                                extra_cands.append(c)
            extra_cands.sort(key=lambda c: _title_score(c), reverse=True)
            de_cuentas = _confirmar_contenido(extra_cands[:max(20, count * 2)])
            de_cuentas.sort(key=lambda c: c.get("_rank", ()), reverse=True)
            matches.extend(de_cuentas)

        if rellenar_n:
            # TIERED (flujo "buscar creativos"): SOLO matches confirmados de confianza ALTA (tier 1)
            # o MEDIA (tier 2). Se DESCARTA tier 3 (confianza baja / solo-título): el usuario exige
            # literalmente el MISMO producto. Ordena tier 1 antes que 2 y baja a tier 2 solo para
            # llegar al count. Si no hay suficientes, devuelve MENOS (honesto). Jamás match=false.
            confirmados_t = []
            for c in matches:
                conf = c.get("_conf") or "media"
                tier = 1 if conf == "alta" else (2 if conf == "media" else 3)
                if tier > 2:                           # baja/solo-título: FUERA (no es seguro que sea igual)
                    continue
                c["tier"] = tier
                c["confianza"] = conf
                c["verificado_producto"] = True        # tier 1/2 = MISMO producto confirmado
                confirmados_t.append(c)
            confirmados_t.sort(key=lambda c: (c.get("tier", 2),) + tuple(-v for v in c.get("_rank", ())))
            links = confirmados_t[:count]
        else:
            for c in matches:
                c["verificado_producto"] = True       # pasó verificación EXACTA (contenido + juez estricto)
            links = matches[:count]
            # SIN relleno en modo exacto: NO se completa con no-verificados (los "nada que ver"). El llamador
            # puede pedir el relleno viejo con solo_confirmados=False (siempre etiquetado como no verificado).
            if not solo_confirmados and len(links) < count:
                vistos = {l["url"] for l in links}
                extra = [dict(c, verificado_producto=False) for c in cand_list if c["url"] not in vistos]
                links = (links + extra)[:count]
    else:
        links = cand_list[:count]

    n_conf = sum(1 for c in links if c.get("verificado_producto"))
    for c in links:
        c.pop("_rank", None)
        c.pop("_deep", None)
        c.pop("_cuenta", None)
        c.pop("_conf", None)          # interno (tier ya calculado)
        c.setdefault("source", "tiktok")
        c.pop("_cover_bytes", None)   # bytes: no serializan a JSON

    # HONESTIDAD (plan 30/30): si no se llegó al count con confirmados, decirlo CLARO, con las
    # búsquedas que se probaron, y pedir datos para ampliar (nunca inflar con no-confirmados).
    mensaje = ""
    if verificado and n_conf < count:
        mensaje = (f"Encontré {n_conf} confirmados con estas búsquedas: "
                   f"[{', '.join(queries[:6])}]. "
                   "Dame la marca, un hashtag o el país para ampliar.")

    # B-ROLL de apoyo (escenas adaptadas al ángulo, para un video más dopamínico) — manual:
    # se muestran aparte y el usuario elige cuáles usar.
    broll = []
    if api_key or anthropic_key:
        try:
            broll = buscar_broll(ref_desc, nombre or kw, api_key, n=10,
                                 anthropic_key=anthropic_key)
        except Exception:  # noqa: BLE001
            broll = []
    return {"ok": bool(links), "keywords": kw, "links": links, "verificado": verificado,
            "n_confirmados": n_conf, "broll": broll, "mensaje_busqueda": mensaje,
            "busqueda": f"https://www.tiktok.com/search?q={quote(kw)}"}


if __name__ == "__main__":
    import sys
    print(json.dumps(buscar(nombre=sys.argv[1] if len(sys.argv) > 1 else "faja colombiana", count=6),
                     ensure_ascii=False, indent=2))
