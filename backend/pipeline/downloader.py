"""Descarga automática de videos desde links (TikTok, Instagram, YouTube, etc.) con yt-dlp.

Pegas una lista de URLs y las baja a una carpeta, listas para usar como fuente de clips.
Reintenta con --impersonate si la descarga normal falla (anti-bot), como el descargador de jack.

100% opcional: si `yt-dlp` no está instalado, `available()` da False y no rompe nada.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from typing import Callable

_TIMEOUT = 300  # s por video


def available() -> bool:
    return shutil.which("yt-dlp") is not None


def _clean_urls(raw: list[str]) -> list[str]:
    """Filtra a http(s) y quita duplicados conservando el orden."""
    seen, out = set(), []
    for u in raw:
        u = (u or "").strip()
        if u.startswith(("http://", "https://")) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _download_one(url: str, out_tpl: str) -> tuple[bool, str | None, str]:
    """Baja UN video. Devuelve (ok, ruta, error). Reintenta con --impersonate si falla."""
    base = ["yt-dlp", "--no-playlist", "--no-warnings", "-q",
            "-f", "mp4/bv*+ba/b", "--merge-output-format", "mp4", "-o", out_tpl]
    last = ""
    for extra in ([], ["--impersonate", "chrome"]):   # 2º intento con impersonate (anti-bot)
        try:
            subprocess.run(base + extra + [url], check=True, capture_output=True,
                           text=True, timeout=_TIMEOUT)
            found = sorted(glob.glob(out_tpl.replace("%(ext)s", "*")))
            if found:
                return True, found[0], ""
            last = "descargó pero no se encontró el archivo"
        except subprocess.CalledProcessError as e:
            last = (e.stderr or "").strip().splitlines()[-1] if e.stderr else "falló yt-dlp"
        except subprocess.TimeoutExpired:
            last = "tardó demasiado (timeout)"
        except Exception as e:  # noqa: BLE001
            last = str(e)
    return False, None, last


def download_urls(urls: list[str], out_dir: str,
                  progress: Callable[[str, int], None] | None = None) -> list[dict]:
    """Baja cada URL a `out_dir`. Devuelve [{url, ok, path, filename, error}].

    `path` es la ruta del .mp4 descargado (o None si falló). Nunca lanza.
    """
    def report(m, p):
        if progress:
            progress(m, p)

    if not available():
        return [{"url": u, "ok": False, "path": None, "filename": "",
                 "error": "yt-dlp no está instalado"} for u in urls]

    os.makedirs(out_dir, exist_ok=True)
    clean = _clean_urls(urls)
    results = []
    for i, url in enumerate(clean):
        report(f"Descargando video {i + 1}/{len(clean)}...", int(5 + (i / max(1, len(clean))) * 90))
        out_tpl = os.path.join(out_dir, f"dl_{i:03d}.%(ext)s")
        ok, path, err = _download_one(url, out_tpl)
        results.append({
            "url": url, "ok": ok, "path": path,
            "filename": os.path.basename(path) if path else "",
            "error": err,
        })
    report("Descarga terminada", 100)
    return results
