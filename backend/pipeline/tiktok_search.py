"""Buscar creativos en TikTok a partir de una foto + nombre del producto.

Devuelve LINKS REALES de videos de TikTok (vía la API de búsqueda pública de tikwm, sin login).
Si hay foto, Gemini saca las palabras clave; si no, usa el nombre que da el usuario.
El usuario luego elige los links que quiera y los usa (p. ej. pegándolos en la pestaña Descargar).

Nota: tikwm es un servicio de terceros (no oficial de TikTok); puede tener límites o caerse.
Si falla, devolvemos igual el link de BÚSQUEDA de TikTok para abrir a mano (degradación elegante).
"""
from __future__ import annotations

import os
from urllib.parse import quote

import requests

_TIKWM = "https://tikwm.com/api/feed/search"
_MODEL = "gemini-2.5-flash"


def keywords_from_photo(image_path: str | None, nombre: str, api_key: str | None) -> str:
    """Con Gemini visión saca 2-3 palabras clave de la foto para buscar en TikTok. Fallback: el nombre."""
    if not (api_key and image_path and os.path.exists(image_path)):
        return nombre
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        with open(image_path, "rb") as f:
            data = f.read()
        prompt = (
            "Mira esta foto de un producto de dropshipping. Dame SOLO 2 a 4 palabras clave cortas "
            "para BUSCAR videos de ese tipo de producto en TikTok (en español, como las buscaría un "
            f"comprador). El usuario lo llama: \"{nombre}\". Responde ÚNICAMENTE las palabras, en una "
            "sola línea, sin comillas ni explicación.")
        resp = client.models.generate_content(
            model=_MODEL,
            contents=[prompt, types.Part.from_bytes(data=data, mime_type="image/jpeg")])
        kw = (resp.text or "").strip().splitlines()[0].strip().strip('"')[:80]
        return kw or nombre
    except Exception:  # noqa: BLE001
        return nombre


def buscar_tiktok(keywords: str, count: int = 20) -> list[dict]:
    """Devuelve [{url, title, cover}] de videos reales de TikTok para esas palabras clave."""
    out: list[dict] = []
    if not keywords.strip():
        return out
    try:
        r = requests.get(_TIKWM, params={"keywords": keywords, "count": min(max(count, 1), 30)},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        vids = ((r.json() or {}).get("data") or {}).get("videos") or []
        for v in vids[:count]:
            au = (v.get("author") or {}).get("unique_id", "")
            vid = v.get("video_id", "")
            if au and vid:
                out.append({
                    "url": f"https://www.tiktok.com/@{au}/video/{vid}",
                    "title": (v.get("title") or "").strip()[:120],
                    "cover": v.get("cover") or "",
                })
    except Exception:  # noqa: BLE001
        pass
    return out


def buscar(image_path: str | None = None, nombre: str = "", api_key: str | None = None,
           count: int = 20) -> dict:
    """Punto de entrada: foto/nombre -> {ok, keywords, links:[{url,title,cover}], busqueda}."""
    kw = keywords_from_photo(image_path, nombre, api_key) if image_path else (nombre or "")
    kw = (kw or nombre or "").strip()
    links = buscar_tiktok(kw, count)
    return {
        "ok": bool(links),
        "keywords": kw,
        "links": links,
        "busqueda": f"https://www.tiktok.com/search?q={quote(kw)}",   # abrir a mano si algo falla
    }


if __name__ == "__main__":
    import json
    import sys
    kw = sys.argv[1] if len(sys.argv) > 1 else "repelente ultrasónico plagas"
    print(json.dumps(buscar(nombre=kw, count=8), ensure_ascii=False, indent=2))
