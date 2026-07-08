"""B-ROLL de verdad desde BANCOS DE VIDEO (stock), no de TikTok.

TikTok search (tikwm) devuelve memes/comedia/anuncios completos → basura para b-roll. Los bancos
de stock (Pexels, Pixabay) tienen clips LIMPIOS, etiquetados y descargables de escenas reales
("mujer estresada", "limpiando cocina", "antes/después piel"…) → esto SÍ sirve como b-roll de apoyo.

Ambas APIs son GRATIS (key gratis e instantánea). Devuelve candidatos con el MISMO shape que usa
tiktok_search.buscar_broll (url/cover/play/dur/region/plays/source) para enchufarse sin fricción.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import requests

_UA = {"User-Agent": "Mozilla/5.0"}
_PEXELS = "https://api.pexels.com/videos/search"
_PIXABAY = "https://pixabay.com/api/videos/"


def _pick_pexels_mp4(video_files: list[dict]) -> tuple[str, int, int]:
    """Elige el mejor mp4 de Pexels: prefiere VERTICAL y resolución media (720-1080 de ancho)."""
    mejor, score_mejor = None, -1
    for vf in video_files or []:
        link = vf.get("link")
        if not link or "mp4" not in (vf.get("file_type") or "video/mp4"):
            continue
        w, h = int(vf.get("width") or 0), int(vf.get("height") or 0)
        vertical = 1 if h >= w else 0
        # cercanía a 1080 de ancho (ni gigante ni diminuto)
        cerca = -abs((max(w, h) if vertical else w) - 1080)
        score = vertical * 100000 + cerca
        if score > score_mejor:
            mejor, score_mejor = (link, w, h), score
    return mejor or ("", 0, 0)


def _buscar_pexels(query: str, key: str, per_page: int = 12) -> list[dict]:
    out = []
    try:
        r = requests.get(_PEXELS, headers={"Authorization": key, **_UA},
                         params={"query": query, "per_page": per_page, "orientation": "portrait"},
                         timeout=20)
        if r.status_code != 200:
            return []
        for v in (r.json().get("videos") or []):
            link, w, h = _pick_pexels_mp4(v.get("video_files"))
            if not link:
                continue
            dur = int(v.get("duration") or 0)
            out.append({
                "video_id": f"pexels_{v.get('id')}",
                "url": v.get("url") or link,          # página o el propio mp4
                "cover": v.get("image") or "",         # miniatura
                "play": link,                          # mp4 directo (preview inline + descarga + verificación)
                "dur": max(1, min(120, dur)),
                "plays": 0, "region": "", "likes": 0,
                "title": (query + " · Pexels")[:120],
                "source": "pexels",
            })
    except Exception:  # noqa: BLE001
        return out
    return out


def _buscar_pixabay(query: str, key: str, per_page: int = 12) -> list[dict]:
    out = []
    try:
        r = requests.get(_PIXABAY, headers=_UA,
                         params={"key": key, "q": query, "per_page": max(3, min(50, per_page)),
                                 "safesearch": "true"},
                         timeout=20)
        if r.status_code != 200:
            return []
        for hit in (r.json().get("hits") or []):
            vids = hit.get("videos") or {}
            v = vids.get("medium") or vids.get("large") or vids.get("small") or {}
            link = v.get("url")
            if not link:
                continue
            dur = int(hit.get("duration") or 0)
            out.append({
                "video_id": f"pixabay_{hit.get('id')}",
                "url": hit.get("pageURL") or link,
                "cover": (vids.get("large") or vids.get("medium") or {}).get("thumbnail") or "",
                "play": link,
                "dur": max(1, min(120, dur)),
                "plays": int(hit.get("views") or 0), "region": "", "likes": 0,
                "title": ((hit.get("tags") or query) + " · Pixabay")[:120],
                "source": "pixabay",
            })
    except Exception:  # noqa: BLE001
        return out
    return out


def buscar_stock(queries: list[str], *, pexels_key: str | None = None,
                 pixabay_key: str | None = None, n: int = 12,
                 min_dur: int = 2, max_dur: int = 45) -> list[dict]:
    """Busca B-ROLL de stock (Pexels + Pixabay) para varias queries EN PARALELO. Dedup por id,
    filtra por duración usable, variedad. Devuelve candidatos (shape de buscar_broll). [] si no hay keys."""
    if not (pexels_key or pixabay_key):
        return []
    tareas = []
    for q in queries[:8]:
        if pexels_key:
            tareas.append((_buscar_pexels, q, pexels_key))
        if pixabay_key:
            tareas.append((_buscar_pixabay, q, pixabay_key))
    if not tareas:
        return []
    cands: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(tareas))) as ex:
        for res in ex.map(lambda t: t[0](t[1], t[2]), tareas):
            for c in res:
                if min_dur <= c.get("dur", 0) <= max_dur:
                    cands.setdefault(c["video_id"], c)
    # más "vistas" primero (Pixabay trae views; Pexels 0) y luego variedad
    return sorted(cands.values(), key=lambda c: -int(c.get("plays", 0)))[:max(n * 3, 24)]
