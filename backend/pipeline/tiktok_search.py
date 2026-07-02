"""Buscar creativos en TikTok a partir de una foto + nombre del producto.

Devuelve LINKS REALES de videos de TikTok (vía la API pública de tikwm, sin login), pero con
VERIFICACIÓN por IA para que sea SÍ O SÍ el MISMO producto que la foto (mismo tipo Y misma forma:
ej. "veneno de abeja EN CREMA", no en bótox). Prefiere videos en ESPAÑOL y con POCO texto en pantalla.

Flujo:
  1) Gemini mira la foto → descripción precisa (producto + forma/formato) + keywords en español.
  2) tikwm busca hartos candidatos.
  3) Gemini compara la PORTADA de cada candidato con la foto → ¿mismo producto? ¿español? ¿poco texto?
     Se queda solo con los que coinciden, ordenados (español + poco texto primero).
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
    """Gemini: descripción precisa (producto + FORMA) + keywords en español. Fallback: el nombre."""
    base = {"keywords": nombre, "desc": nombre}
    if not (api_key and image_path and os.path.exists(image_path)):
        return base
    try:
        from google.genai import types
        with open(image_path, "rb") as f:
            data = f.read()
        prompt = (
            "Mira la foto de este producto de dropshipping. Identifica el producto EXACTO y sobre todo "
            "su FORMA/FORMATO (crema, gel, cápsulas, spray, aparato, collar, etc.). "
            f"El usuario lo llama: \"{nombre}\". Devuelve SOLO un JSON: "
            '{"keywords":"3-5 palabras en español para buscarlo en TikTok, INCLUYENDO la forma",'
            '"desc":"una línea: qué es y en qué forma/formato viene"}')
        resp = _client(api_key).models.generate_content(
            model=_MODEL, contents=[prompt, types.Part.from_bytes(data=data, mime_type="image/jpeg")])
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if m:
            d = json.loads(m.group(0))
            kw = str(d.get("keywords", "")).strip()
            return {"keywords": kw or nombre, "desc": str(d.get("desc", "")).strip() or nombre}
    except Exception:  # noqa: BLE001
        pass
    return base


def buscar_tiktok(keywords: str, count: int = 20) -> list[dict]:
    """Devuelve [{url, title, cover}] de videos reales de TikTok para esas palabras clave."""
    out: list[dict] = []
    if not keywords.strip():
        return out
    try:
        r = requests.get(_TIKWM, params={"keywords": keywords, "count": min(max(count, 1), 30)},
                         headers=_UA, timeout=25)
        vids = ((r.json() or {}).get("data") or {}).get("videos") or []
        for v in vids[:count]:
            au = (v.get("author") or {}).get("unique_id", "")
            vid = v.get("video_id", "")
            if au and vid:
                out.append({"url": f"https://www.tiktok.com/@{au}/video/{vid}",
                            "title": (v.get("title") or "").strip()[:120],
                            "cover": v.get("cover") or ""})
    except Exception:  # noqa: BLE001
        pass
    return out


def _verificar(cand: dict, ref_bytes: bytes, ref_desc: str, api_key: str) -> dict | None:
    """¿La portada del candidato es EL MISMO producto (tipo Y forma) que la foto? + español + poco texto."""
    cover = cand.get("cover")
    if not cover:
        return None
    try:
        from google.genai import types
        cimg = requests.get(cover, headers=_UA, timeout=15).content
        if not cimg:
            return None
        prompt = (
            f"Foto 1 = producto de REFERENCIA que quiero: \"{ref_desc}\". "
            "Foto 2 = portada de un video de TikTok. "
            "¿La Foto 2 muestra EXACTAMENTE el mismo TIPO de producto Y en la misma FORMA/FORMATO que la "
            "Foto 1? (ej: si la referencia es una CREMA, un bótox/inyección NO cuenta). Sé estricto. "
            "Además, ¿el texto/idioma del video parece ESPAÑOL? ¿tiene POCO texto sobrepuesto en pantalla? "
            'Responde SOLO JSON: {"match":true/false,"es":true/false,"poco_texto":true/false}')
        resp = _client(api_key).models.generate_content(
            model=_MODEL,
            contents=[prompt,
                      types.Part.from_bytes(data=ref_bytes, mime_type="image/jpeg"),
                      types.Part.from_bytes(data=cimg, mime_type="image/jpeg")])
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not m:
            return None
        d = json.loads(m.group(0))
        return {"match": bool(d.get("match")), "es": bool(d.get("es")),
                "poco_texto": bool(d.get("poco_texto"))}
    except Exception:  # noqa: BLE001
        return None


def buscar(image_path: str | None = None, nombre: str = "", api_key: str | None = None,
           count: int = 20) -> dict:
    """foto/nombre -> {ok, keywords, links:[{url,title,cover}], busqueda, verificado}."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ref_bytes = None
    ref_desc = nombre
    if image_path and os.path.exists(image_path):
        info = analizar_foto(image_path, nombre, api_key)
        kw, ref_desc = info["keywords"], info["desc"]
        try:
            with open(image_path, "rb") as f:
                ref_bytes = f.read()
        except Exception:  # noqa: BLE001
            ref_bytes = None
    else:
        kw = (nombre or "").strip()
    kw = (kw or nombre or "").strip()

    # Traemos MÁS candidatos para poder filtrar y quedarnos con los que coincidan
    cands = buscar_tiktok(kw, min(30, max(count * 2, 15)))
    verificado = False

    if ref_bytes and api_key and cands:
        verificado = True
        matches: list[dict] = []
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_verificar, c, ref_bytes, ref_desc, api_key): c for c in cands}
            for fut in as_completed(futs):
                v = fut.result()
                if v and v.get("match"):
                    c = futs[fut]
                    c["_es"], c["_poco"] = v.get("es", False), v.get("poco_texto", False)
                    matches.append(c)
        # español + poco texto primero
        matches.sort(key=lambda c: (c.get("_es", False), c.get("_poco", False)), reverse=True)
        links = matches[:count]
        # si la verificación dejó muy pocos, completamos con candidatos sin verificar (mejor algo que nada)
        if len(links) < min(3, count):
            extra = [c for c in cands if c not in links]
            links = (links + extra)[:count]
    else:
        links = cands[:count]

    for c in links:
        c.pop("_es", None); c.pop("_poco", None)
    return {"ok": bool(links), "keywords": kw, "links": links, "verificado": verificado,
            "busqueda": f"https://www.tiktok.com/search?q={quote(kw)}"}


if __name__ == "__main__":
    import sys
    print(json.dumps(buscar(nombre=sys.argv[1] if len(sys.argv) > 1 else "faja colombiana", count=6),
                     ensure_ascii=False, indent=2))
