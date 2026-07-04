"""Búsqueda de ads GANADORES en Foreplay (biblioteca de +100M ads) vía su API pública.

Foreplay indexa ads reales de Meta/TikTok con su video descargable, transcripción y cuánto llevan
corriendo (señal de ganador). Aquí: buscar por keyword/idioma/nicho + descargar el video para que el
pipeline lo corte en clips. La key va en .env como FOREPLAY_API_KEY (header 'Authorization').
Regla de oro: se EXCLUYE Colombia (la API no expone país → heurística local _es_colombiano).
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Callable

import requests

_BASE = "https://public.api.foreplay.co"
_UA = {"User-Agent": "Mozilla/5.0"}


def _headers(api_key: str) -> dict:
    return {"Authorization": api_key}


def usage(api_key: str) -> dict:
    """Créditos disponibles: {ok, total, remaining, email} o {ok:False, error}."""
    if not api_key:
        return {"ok": False, "error": "Falta la API key de Foreplay"}
    try:
        r = requests.get(f"{_BASE}/api/usage", headers=_headers(api_key), timeout=20)
        if r.status_code == 401:
            return {"ok": False, "error": "Key de Foreplay inválida"}
        d = (r.json() or {}).get("data") or {}
        return {"ok": True, "total": d.get("total_credits"),
                "remaining": d.get("remaining_credits"),
                "email": (d.get("user") or {}).get("email")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:150]}


def _corriendo(rd) -> tuple[int, str]:
    """De {seconds,minutes,hours,days} (totales) → (días, texto amigable). Señal de ganador."""
    if not isinstance(rd, dict):
        return 0, ""
    d, h = int(rd.get("days") or 0), int(rd.get("hours") or 0)
    if d >= 1:
        return d, f"{d} día{'s' if d != 1 else ''} corriendo"
    if h >= 1:
        return 0, f"{h}h corriendo"
    return 0, "nuevo"


# ── Excluir COLOMBIA (regla de oro: español pero NO Colombia) ─────────────────
# La API de Foreplay NO expone el país del ad/anunciante (solo idioma), así que
# se filtra con heurística LOCAL sobre el texto del ad (sin gastar IA):
# menciones de Colombia, ciudades grandes, moneda COP, precios estilo $59.900,
# teléfonos +57 y dominios .com.co. Case/acento-insensible.
_CO_RX = re.compile(
    r"colombia"                                                    # Colombia / colombiano/a (substring, atrapa dominios tipo 'tiendacolombia')
    r"|\b(bogota|medellin|barranquilla|bucaramanga|cali|cartagena|cucuta)\b"  # ciudades
    r"|\bcop\b"                                                    # moneda (pesos colombianos)
    r"|\+57[\s.\-]?\d"                                             # teléfono +57
    r"|\$\s?\d{1,3}[.,]900\b"                                      # precios típicos COP ($59.900)
    r"|\.com\.co\b"                                                # dominios colombianos
)


def _sin_acentos(s: str) -> str:
    """minúsculas y sin tildes (para matchear 'Bogotá' == 'bogota')."""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(c)).lower()


def _es_colombiano(a: dict) -> bool:
    """True si el ad CRUDO de Foreplay tiene señales colombianas claras en su texto.
    Se corre sobre el ad crudo (antes de _norm_ad) para aprovechar full_transcription."""
    texto = " ".join(str(a.get(k) or "") for k in
                     ("name", "headline", "description", "cta_title",
                      "link_url", "full_transcription"))
    return bool(_CO_RX.search(_sin_acentos(texto)))


def _norm_ad(a: dict) -> dict:
    """Deja solo lo útil para la UI + la descarga."""
    dias, corriendo = _corriendo(a.get("running_duration"))
    return {
        "id": a.get("id") or a.get("ad_id") or "",
        "name": a.get("name") or "",
        "description": (a.get("description") or "")[:300],
        "headline": a.get("headline") or "",
        "video": a.get("video") or "",
        "thumbnail": a.get("thumbnail") or a.get("image") or "",
        "display_format": a.get("display_format") or "",
        "video_duration": a.get("video_duration"),
        "dias": dias,
        "corriendo": corriendo,
        "live": a.get("live"),
        "languages": a.get("languages") or [],
        "niches": a.get("niches") or [],
        "publisher_platform": a.get("publisher_platform") or [],
        "link_url": a.get("link_url") or "",
        "foreplay_url": a.get("foreplay_url") or "",
    }


def buscar_ads(query: str = "", *, api_key: str, live: bool | None = None,
               languages: str = "", niches: str = "", video_only: bool = True,
               running_min_days: int | None = None, video_max_seconds: int | None = None,
               cursor: str = "", limit: int | None = None, order: str = "") -> dict:
    """Busca ads en /api/discovery/ads. Devuelve {ok, ads:[...], cursor, error}.

    `limit`: tamaño de página (el default del API es ~10; acepta hasta 100 — clave para no
    quedarse corto). `order`: "newest" | "oldest" | "longest_running" (ganadores primero)."""
    if not api_key:
        return {"ok": False, "error": "Falta la API key de Foreplay", "ads": []}
    params: dict = {}
    if query.strip():
        params["query"] = query.strip()
    if limit:
        params["limit"] = max(1, min(int(limit), 100))
    if order.strip():
        params["order"] = order.strip()
    if live is not None:
        params["live"] = "true" if live else "false"
    if languages.strip():
        params["languages"] = languages.strip()
    if niches.strip():
        params["niches"] = niches.strip()
    if video_only:
        params["display_format"] = "VIDEO"
    if running_min_days:
        params["running_duration_min_days"] = running_min_days
    if video_max_seconds:
        params["video_duration_max"] = video_max_seconds
    if cursor:
        params["cursor"] = cursor
    try:
        r = requests.get(f"{_BASE}/api/discovery/ads", headers=_headers(api_key),
                         params=params, timeout=30)
        if r.status_code == 401:
            return {"ok": False, "error": "Key de Foreplay inválida", "ads": []}
        if r.status_code == 429:
            return {"ok": False, "error": "Sin créditos de Foreplay o límite de tasa (429)", "ads": []}
        if r.status_code != 200:
            return {"ok": False, "error": f"Foreplay respondió HTTP {r.status_code}", "ads": []}
        body = r.json() or {}
        # regla de oro: excluir Colombia ANTES de normalizar (usa el texto completo del ad)
        ads = [_norm_ad(a) for a in (body.get("data") or []) if not _es_colombiano(a)]
        if video_only:
            ads = [a for a in ads if a.get("video")]
        cur = (body.get("metadata") or {}).get("cursor") or ""
        return {"ok": True, "ads": ads, "cursor": cur}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:150], "ads": []}


_MAX_VIDEO_BYTES = 200 * 1024 * 1024   # tope de 200 MB por video (evita llenar el disco)


def descargar_video(video_url: str, out_path: str, timeout: int = 180) -> str | None:
    """Descarga el MP4 directo de Foreplay (CDN r2.foreplay.co). Devuelve la ruta o None."""
    if not video_url:
        return None
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    try:
        with requests.get(video_url, headers=_UA, timeout=timeout, stream=True,
                          allow_redirects=False) as r:   # no seguir redirects (evita SSRF/exfil)
            if r.status_code != 200:
                return None
            escritos = 0
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        escritos += len(chunk)
                        if escritos > _MAX_VIDEO_BYTES:   # corta si excede el tope
                            break
                        f.write(chunk)
        return out_path if os.path.exists(out_path) and os.path.getsize(out_path) > 2000 else None
    except Exception:  # noqa: BLE001
        return None


def descargar_videos(ads: list[dict], out_dir: str,
                     progress: Callable[[str, int], None] | None = None) -> list[str]:
    """Descarga los videos de una lista de ads. Devuelve las rutas descargadas OK."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    n = len(ads)
    for i, a in enumerate(ads):
        if progress:
            progress(f"Descargando video {i + 1}/{n} de Foreplay...", int(i / max(1, n) * 100))
        p = os.path.join(out_dir, f"fp_{i:02d}.mp4")
        if descargar_video(a.get("video", ""), p):
            paths.append(p)
    return paths
