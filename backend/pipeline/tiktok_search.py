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
            "Mira la foto de este producto de dropshipping. Identifica el producto EXACTO y sobre todo "
            "su FORMA/FORMATO (crema, gel, cápsulas, spray, aparato, collar, etc.). "
            f"El usuario lo llama: \"{nombre}\". Devuelve SOLO un JSON:\n"
            '{"keywords":"3-5 palabras en español, INCLUYENDO la forma",'
            '"variants":["4 búsquedas DISTINTAS en español para encontrar videos que MUESTREN este '
            'MISMO producto y sus BENEFICIOS/resultados/demostración (todas con la forma; ej. añade '
            '\'resultados\', \'antes y después\', \'cómo funciona\', \'reseña\')"],'
            '"desc":"una línea: qué es, en qué forma/formato viene, y para qué sirve"}')
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
    """Garantiza VARIAS consultas (amplía) con términos de beneficios/demostración, sin duplicar."""
    kw = (kw or "").strip()
    extra = [kw, f"{kw} resultados", f"{kw} antes y después", f"{kw} reseña", f"{kw} cómo funciona"]
    out: list[str] = []
    for q in [kw] + variants + extra:
        q = (q or "").strip()
        if q and q.lower() not in {x.lower() for x in out}:
            out.append(q)
    return out[:5]


# Regiones donde el contenido suele estar en español (para priorizar sin gastar visión)
_ES_REGIONS = {"CO", "MX", "ES", "AR", "PE", "CL", "EC", "VE", "GT", "BO", "DO", "CR",
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
        titulo = (cand.get("title") or "")[:120]
        prompt = (
            f"Foto 1 = producto de REFERENCIA que quiero: \"{ref_desc}\". "
            f"Foto 2 = portada de un video de TikTok (título: \"{titulo}\"). "
            "Sé MUY ESTRICTO: match=true SOLO si la Foto 2 muestra INEQUÍVOCAMENTE el MISMO tipo de "
            "producto Y en la MISMA FORMA/FORMATO que la Foto 1 (ej: si la referencia es CREMA, un "
            "bótox/inyección/pastilla/otra cosa NO cuenta). Si la portada no deja ver claro el producto, "
            "o hay duda, o es otro producto → match=false. "
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


def buscar(image_path: str | None = None, nombre: str = "", api_key: str | None = None,
           count: int = 20) -> dict:
    """foto/nombre -> {ok, keywords, links:[{url,title,cover}], busqueda, verificado}."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ref_bytes = None
    ref_desc = nombre
    queries = _expandir(nombre, [])
    if image_path and os.path.exists(image_path):
        info = analizar_foto(image_path, nombre, api_key)
        ref_desc = info["desc"]
        queries = info.get("variants") or [info["keywords"]]
        try:
            with open(image_path, "rb") as f:
                ref_bytes = f.read()
        except Exception:  # noqa: BLE001
            ref_bytes = None
    queries = [q for q in queries if q][:5] or [(nombre or "").strip()]
    kw = queries[0]

    # AMPLIAR: varias consultas (producto + beneficios) × varias páginas → muchos candidatos únicos
    cands: dict[str, dict] = {}
    for q in queries:
        for c in buscar_tiktok(q, count=40, pages=2):
            cands.setdefault(c["url"], c)
    cand_list = list(cands.values())
    # descarta duraciones raras (fuera de 4-120s) y PRE-ORDENA: región hispana + más views (virales) primero
    filtered = [c for c in cand_list if 4 <= c.get("dur", 0) <= 120]
    cand_list = filtered or cand_list
    cand_list.sort(key=lambda c: (1 if c.get("region") in _ES_REGIONS else 0, c.get("plays", 0)),
                   reverse=True)

    verificado = False
    if ref_bytes and api_key and cand_list:
        verificado = True
        pool = cand_list[:28]                 # verifica los MEJORES (hispanos + virales) primero
        matches: list[dict] = []
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_verificar, c, ref_bytes, ref_desc, api_key): c for c in pool}
            for fut in as_completed(futs):
                v = fut.result()
                if v and v.get("match"):
                    c = futs[fut]
                    # muestra producto → SIN texto sobrepuesto (2 nada > 1 poco > 0 mucho) → español → más views
                    c["_rank"] = (v.get("muestra", False), v.get("overlay", 1),
                                  v.get("es", False), c.get("plays", 0))
                    matches.append(c)
        # muestra el producto → sin texto sobrepuesto → español → más views
        matches.sort(key=lambda c: c.get("_rank", ()), reverse=True)
        links = matches[:count]
        if len(links) < min(3, count):       # si quedaron muy pocos, completa con candidatos
            extra = [c for c in cand_list if c["url"] not in {l["url"] for l in links}]
            links = (links + extra)[:count]
    else:
        links = cand_list[:count]

    for c in links:
        c.pop("_rank", None)
    return {"ok": bool(links), "keywords": kw, "links": links, "verificado": verificado,
            "busqueda": f"https://www.tiktok.com/search?q={quote(kw)}"}


if __name__ == "__main__":
    import sys
    print(json.dumps(buscar(nombre=sys.argv[1] if len(sys.argv) > 1 else "faja colombiana", count=6),
                     ensure_ascii=False, indent=2))
