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


def analizar_foto(image_path: str, nombre: str, api_key: str) -> dict:
    """Gemini: descripción precisa (producto + FORMA) + VARIAS búsquedas (amplía) + desc. Fallback: nombre."""
    if not (api_key and image_path and os.path.exists(image_path)):
        return {"keywords": nombre, "variants": _expandir(nombre, []), "desc": nombre}
    try:
        from google.genai import types
        with open(image_path, "rb") as f:
            data = f.read()
        prompt = (
            "Haz un ANÁLISIS VISUAL PROFUNDO de la foto de este producto de dropshipping — como un perito: "
            "(1) qué ES exactamente y su CATEGORÍA (crema, gel, cápsulas, spray, aparato/dispositivo, collar…); "
            "(2) FORMA física exacta (cuadrado, rectangular, redondo, tipo pinza/clamshell, lápiz, pistola, de "
            "mano…) y tamaño aproximado (de bolsillo, de mesa…); (3) COLORES por parte (cuerpo, tapa, botones, "
            "luz); (4) MARCA o TEXTO visible en el producto/empaque (transcríbelo literal si se lee); "
            "(5) RASGOS DISTINTIVOS: bisagra, botón, pantalla, luz (color exacto), cable/puerto, ranura, textura; "
            "(6) CÓMO SE USA (dónde va puesto, qué parte del cuerpo toca); "
            "(7) NO CONFUNDIR CON: 1-3 productos PARECIDOS pero DISTINTOS con los que un buscador se "
            "confundiría (ej. lámpara UV de secar esmalte, masajeador, otro aparato similar). "
            f"El usuario lo llama: \"{nombre}\". Devuelve SOLO un JSON:\n"
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
        resp = _client(api_key).models.generate_content(
            model=_MODEL, contents=[prompt, types.Part.from_bytes(data=data, mime_type="image/jpeg")])
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
    return out[:10]


# Regiones donde el contenido suele estar en español (para priorizar sin gastar visión)
# Regiones hispanas preferidas — SIN Colombia (regla del dueño: excluir Colombia siempre)
_ES_REGIONS = {"MX", "ES", "AR", "PE", "CL", "EC", "VE", "GT", "BO", "DO", "CR",
               "PA", "UY", "PY", "SV", "HN", "NI", "US"}


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


_OVERLAY_SCORE = {"nada": 2, "poco": 1, "mucho": 0}


def _verificar(cand: dict, ref_bytes: bytes, ref_desc: str, api_key: str) -> dict | None:
    """¿El video es SÍ O SÍ el mismo producto (tipo Y forma)? + muestra el producto + español + SIN texto sobrepuesto."""
    cover = cand.get("cover")
    if not cover:
        return None
    try:
        from google.genai import types
        cimg = requests.get(cover, headers=_UA, timeout=15).content
        if not cimg:
            return None
        cand["_cover_bytes"] = cimg   # cache: el 2º juez (Claude) la reusa sin re-descargar
        titulo = (cand.get("title") or "")[:120]
        prompt = (
            f"Foto 1 = el producto de REFERENCIA que quiero (descripción: \"{ref_desc}\"). "
            f"Foto 2 = portada de un video de TikTok (título: \"{titulo}\"). "
            "match=true si la Foto 2 muestra el MISMO PRODUCTO en lo que IMPORTA: la MISMA CATEGORÍA/FORMATO "
            "(crema=crema, gel=gel, cápsulas=cápsulas, aparato=aparato) Y el MISMO PROPÓSITO/beneficio que la "
            "Foto 1 (ej. crema de veneno de abeja para lunares/verrugas). NO exijas la misma MARCA/etiqueta/"
            "envase: OTRO vendedor con el MISMO producto (misma categoría + mismo propósito) SÍ cuenta "
            "(match=true) — así encontramos más creativos del mismo producto. "
            "match=false si es OTRA categoría/formato (crema vs pastillas/spray/bótox/inyección), otro "
            "propósito, u otro tipo de producto. Si es un APARATO/dispositivo, además debe tener la MISMA "
            "FORMA física (cuadrado vs lápiz/pistola = false). OJO con aparatos PARECIDOS pero de OTRO USO: "
            "usa el TÍTULO para desempatar (ej. lámpara de SECAR esmalte/gel ≠ láser para HONGOS; masajeador "
            "≠ depilador) → si el título indica otro uso, match=false. Si la ficha trae 'NO CONFUNDIR CON' y "
            "el producto del video parece UNO DE ESOS → match=false. Compara también los rasgos distintivos "
            "de la ficha (forma, colores, bisagra/botón/luz). Si no se ve el producto o hay duda de "
            "categoría/propósito → match=false. "
            "TEXTO SOBREPUESTO: distingue el texto AÑADIDO DIGITALMENTE encima del video (subtítulos, "
            "captions, títulos, stickers de texto — lo típico que pone el creador de TikTok) del texto que "
            "es parte REAL de la escena (la etiqueta o empaque del producto, letreros del lugar). SOLO cuenta "
            "el texto sobrepuesto digital; ignora por completo el texto del producto. Reporta texto_overlay = "
            "\"nada\" (sin texto sobrepuesto, o casi imperceptible), \"poco\" (algo de texto pero pequeño/discreto), "
            "o \"mucho\" (subtítulos/títulos grandes que tapan el video). "
            "Responde SOLO JSON: "
            '{"match":true/false,"muestra_producto":true/false,"es":true/false,"texto_overlay":"nada"/"poco"/"mucho"}')
        resp = _client(api_key).models.generate_content(
            model=_MODEL,
            contents=[prompt,
                      types.Part.from_bytes(data=ref_bytes, mime_type="image/jpeg"),
                      types.Part.from_bytes(data=cimg, mime_type="image/jpeg")])
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not m:
            return None
        d = json.loads(m.group(0))
        ov = str(d.get("texto_overlay", "poco")).strip().lower()
        return {"match": bool(d.get("match")), "muestra": bool(d.get("muestra_producto")),
                "es": bool(d.get("es")), "overlay": _OVERLAY_SCORE.get(ov, 1)}
    except Exception:  # noqa: BLE001
        return None


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


def _verificar_video(cand: dict, ref_bytes: bytes, ref_desc: str, api_key: str) -> dict | None:
    """VERIFICACIÓN PROFUNDA: baja el video (mp4 de tikwm) y mira 3 frames de ADENTRO.

    Muchos videos del producto no lo muestran en la PORTADA (sale el pie, el antes/después, la cara)
    → el juez de portada los rechazaba aunque el video SÍ era del producto. Aquí se juzga el contenido.
    Devuelve el mismo dict que _verificar, o None si no se pudo."""
    import tempfile
    play = cand.get("play")
    if not (play and api_key):
        return None
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
            "match=true si en ALGÚN frame se ve el MISMO producto: misma categoría/formato, mismo propósito "
            "y (si es aparato) la MISMA FORMA física y los RASGOS de la ficha (colores, bisagra/botón/luz). "
            "No exijas la misma marca. Aparatos parecidos de OTRO uso (lámpara de secar esmalte ≠ láser "
            "para hongos) → false. Si la ficha trae 'NO CONFUNDIR CON' y lo del video parece uno de esos → "
            "false. Si en ningún frame se ve el producto o hay duda → false. "
            'Responde SOLO JSON: {"match":true/false,"muestra_producto":true/false,"es":true/false,'
            '"texto_overlay":"nada"/"poco"/"mucho"}')
        contents = [prompt, types.Part.from_bytes(data=ref_bytes, mime_type="image/jpeg")]
        for fb in frames:
            contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))
        resp = _client(api_key).models.generate_content(model=_MODEL, contents=contents)
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not m:
            return None
        d = json.loads(m.group(0))
        ov = str(d.get("texto_overlay", "poco")).strip().lower()
        return {"match": bool(d.get("match")), "muestra": bool(d.get("muestra_producto")),
                "es": bool(d.get("es")), "overlay": _OVERLAY_SCORE.get(ov, 1)}
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


def _verificar_claude(cand: dict, ref_bytes: bytes, ref_desc: str, anthropic_key: str) -> bool | None:
    """SEGUNDO JUEZ (Claude Opus con visión): ¿la portada es el MISMO producto (tipo + forma física)?
    True=sí, False=no, None=no pudo opinar (fallo técnico → no se descarta por eso)."""
    import base64
    cover = cand.get("cover")
    if not (cover and anthropic_key and ref_bytes):
        return None
    try:
        cimg = cand.get("_cover_bytes") or requests.get(cover, headers=_UA, timeout=15).content
        if not cimg:
            return None
        titulo = (cand.get("title") or "")[:120]
        prompt = (
            f"Foto 1 = el producto de REFERENCIA que quiero (descripción: \"{ref_desc}\"). "
            f"Foto 2 = portada de un video de TikTok (título: \"{titulo}\"). "
            "Compara FÍSICAMENTE los dos. ¿La Foto 2 muestra CLARAMENTE el MISMO producto que la Foto 1 — "
            "mismo tipo de objeto y la MISMA forma/formato físico (un aparato cuadrado ≠ rectangular ≠ tipo "
            "lápiz/pistola; una crema ≠ pastillas ≠ spray)? NO exijas la misma marca/etiqueta: otro vendedor "
            "con el MISMO producto sí cuenta. OJO con aparatos parecidos de OTRO USO: usa el título para "
            "desempatar (lámpara de SECAR esmalte ≠ láser para HONGOS) → otro uso = match=false. Si la ficha "
            "trae 'NO CONFUNDIR CON' y lo del video parece uno de esos → match=false. "
            "Si es otro producto, otra forma, no se ve claro "
            "el producto en la portada, o hay CUALQUIER duda → match=false. Sé ESTRICTO pero justo (es UGC: "
            "puede estar en la mano, en ángulo o con otra luz).")
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key)
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=300,
            tools=[_CLAUDE_TOOL], tool_choice={"type": "tool", "name": "juzgar"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {"type": "base64", "media_type": _media_type(ref_bytes),
                                             "data": base64.b64encode(ref_bytes).decode()}},
                {"type": "image", "source": {"type": "base64", "media_type": _media_type(cimg),
                                             "data": base64.b64encode(cimg).decode()}},
            ]}])
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use" and b.name == "juzgar":
                return bool(b.input.get("match"))
    except Exception:  # noqa: BLE001
        return None
    return None


def buscar(image_path: str | None = None, nombre: str = "", api_key: str | None = None,
           count: int = 20, anthropic_key: str | None = None,
           foreplay_key: str | None = None,
           analisis: dict | None = None) -> dict:
    """foto/nombre -> {ok, keywords, links:[{url,title,cover}], busqueda, verificado}.

    Si hay `anthropic_key`, Claude actúa de SEGUNDO juez (doble verificación) sobre lo que Gemini aprobó.
    Si hay `foreplay_key`, también busca en la biblioteca de ads GANADORES de Foreplay (misma verificación).
    `analisis` (opcional): el dict de analizar_foto YA calculado (lo pasa creative_search para que la
    búsqueda combinada TikTok+Foreplay analice la foto UNA sola vez). Sin él, se calcula aquí (igual
    que siempre)."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ref_bytes = None
    ref_desc = nombre
    queries = _expandir(nombre, [])
    if image_path and os.path.exists(image_path):
        info = analisis or analizar_foto(image_path, nombre, api_key)
        ref_desc = info["desc"]
        queries = info.get("variants") or [info["keywords"]]
        try:
            with open(image_path, "rb") as f:
                ref_bytes = f.read()
        except Exception:  # noqa: BLE001
            ref_bytes = None
    queries = [q for q in queries if q][:10] or [(nombre or "").strip()]
    kw = queries[0]

    # AMPLIAR: MUCHAS consultas (producto + beneficios/compra) × varias páginas → muchísimos candidatos.
    # En PARALELO para que buscar en 10 términos × 3 páginas no se demore.
    cands: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(lambda q: buscar_tiktok(q, count=60, pages=3), queries):
            for c in res:
                cands.setdefault(c["url"], c)
    # + FOREPLAY: ads GANADORES ya probados (video descargable) al MISMO pool y con la MISMA verificación
    for c in _foreplay_candidatos(queries, foreplay_key):
        cands.setdefault(c["url"], c)
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
        pool_n = min(len(cand_list), max(60, count * 4))
        pool = cand_list[:pool_n]             # los más RELEVANTES primero (título > hispano > views)
        matches: list[dict] = []
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = {ex.submit(_verificar, c, ref_bytes, ref_desc, api_key): c for c in pool}
            for fut in as_completed(futs):
                v = fut.result()
                if v and v.get("match"):
                    c = futs[fut]
                    # muestra producto → SIN texto sobrepuesto (2 nada > 1 poco > 0 mucho) → español → más views
                    c["_rank"] = (v.get("muestra", False), v.get("overlay", 1),
                                  v.get("es", False), c.get("plays", 0))
                    matches.append(c)
        # VERIFICACIÓN PROFUNDA (2ª pasada): la portada muchas veces NO muestra el producto (sale el
        # pie, el antes/después, la cara) → falsos rechazos. Para los candidatos con TÍTULO prometedor
        # que la portada no confirmó, se baja el video y se juzgan 3 frames de ADENTRO.
        if len(matches) < count:
            ya = {c["url"] for c in matches}
            pendientes = [c for c in pool if c["url"] not in ya and c.get("play") and _title_score(c) >= 2]
            pendientes = pendientes[:12]      # tope: 12 descargas (costo/tiempo acotado)
            if pendientes:
                with ThreadPoolExecutor(max_workers=4) as ex:
                    futs = {ex.submit(_verificar_video, c, ref_bytes, ref_desc, api_key): c
                            for c in pendientes}
                    for fut in as_completed(futs):
                        v = fut.result()
                        if v and v.get("match"):
                            c = futs[fut]
                            c["_deep"] = True   # confirmado mirando el video por DENTRO (no re-juzgar portada)
                            c["_rank"] = (v.get("muestra", False), v.get("overlay", 1),
                                          v.get("es", False), c.get("plays", 0))
                            matches.append(c)

        # muestra el producto → sin texto sobrepuesto → español → más views
        matches.sort(key=lambda c: c.get("_rank", ()), reverse=True)

        # DOBLE JUEZ: Claude confirma los que Gemini aprobó (solo los mejores, para no gastar de más).
        # Solo quedan "confirmados" los que AMBOS dan como el mismo producto; si Claude falla
        # técnicamente (None), el veredicto de Gemini se respeta.
        if anthropic_key and matches:
            deep = [c for c in matches if c.get("_deep")]          # confirmados por CONTENIDO: no re-juzgar portada
            por_juzgar = [c for c in matches if not c.get("_deep")][:20]
            resto = [c for c in matches if not c.get("_deep")][20:]
            confirmados, rechazados = [], []
            with ThreadPoolExecutor(max_workers=5) as ex:
                cf = {ex.submit(_verificar_claude, c, ref_bytes, ref_desc, anthropic_key): c
                      for c in por_juzgar}
                for fut in as_completed(cf):
                    r, c = fut.result(), cf[fut]
                    (rechazados if r is False else confirmados).append(c)
            matches = sorted(confirmados + deep, key=lambda c: c.get("_rank", ()), reverse=True) + resto

        for c in matches:
            c["verificado_producto"] = True       # pasó la verificación visual (uno o ambos jueces)
        links = matches[:count]
        # Completa hasta `count` con candidatos NO verificados pero SIEMPRE marcados como tales — la UI
        # los separa en "⚠️ revísalos tú" (nunca más mezclar en silencio: fue la causa de que salieran
        # clínicas/productos equivocados como si fueran buenos).
        if len(links) < count:
            vistos = {l["url"] for l in links}
            extra = [dict(c, verificado_producto=False) for c in cand_list if c["url"] not in vistos]
            links = (links + extra)[:count]
    else:
        links = cand_list[:count]

    n_conf = sum(1 for c in links if c.get("verificado_producto"))
    for c in links:
        c.pop("_rank", None)
        c.pop("_deep", None)
        c.setdefault("source", "tiktok")
        c.pop("_cover_bytes", None)   # bytes: no serializan a JSON
    return {"ok": bool(links), "keywords": kw, "links": links, "verificado": verificado,
            "n_confirmados": n_conf,
            "busqueda": f"https://www.tiktok.com/search?q={quote(kw)}"}


if __name__ == "__main__":
    import sys
    print(json.dumps(buscar(nombre=sys.argv[1] if len(sys.argv) > 1 else "faja colombiana", count=6),
                     ensure_ascii=False, indent=2))
