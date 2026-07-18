"""Descarga videos de TikTok (y otros) desde links, con yt-dlp — para el Montador.

Autocontenido: NO importa nada de la app principal ni del pipeline del Montador (respeta que
el Montador sea independiente). yt-dlp se usa por subprocess (binario global de homebrew), así que
funciona aunque no esté en el venv del Montador. Si yt-dlp no está, `disponible()` da False y no rompe.

Pegado del descargador de la app principal (backend/pipeline/downloader.py) para tener el mismo
comportamiento probado: 2º intento con --impersonate chrome (anti-bot) y descarga en paralelo.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

_TIMEOUT = 300      # s por video
_MAX_PARALELO = 5   # cuántos bajar a la vez


def disponible() -> bool:
    return shutil.which("yt-dlp") is not None


def _limpiar(urls: list[str]) -> list[str]:
    """Solo http(s), sin duplicados, conservando el orden."""
    seen, out = set(), []
    for u in urls:
        u = (u or "").strip()
        if u.startswith(("http://", "https://")) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _bajar_uno(url: str, out_tpl: str) -> tuple[bool, str | None, str]:
    """Baja UN video. (ok, ruta, error). Reintenta con --impersonate si falla."""
    # PREFERIR H.264 (avc1): TikTok ofrece h264 y h265 (bytevc1) del mismo video; el <video> de
    # Chrome/Mac NO decodifica H.265 → el preview saldría en negro. H.264 lo reproduce siempre.
    # Si solo hay H.265, cae a mp4/lo que haya (se baja igual; ffmpeg lo monta sin problema).
    fmt = "b[vcodec^=h264]/b[vcodec^=avc1]/bv*[vcodec^=h264]+ba/mp4/b[ext=mp4]/bv*+ba/b"
    base = ["yt-dlp", "--no-playlist", "--no-warnings", "-q", "-N", "4", "--no-part",
            "-f", fmt, "--merge-output-format", "mp4", "-o", out_tpl]
    last = ""
    for extra in ([], ["--impersonate", "chrome"]):
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


def bajar_urls(urls: list[str], out_dir: str) -> list[dict]:
    """Baja cada URL a `out_dir`. Devuelve [{url, ok, path, filename, error}]. Nunca lanza."""
    if not disponible():
        return [{"url": u, "ok": False, "path": None, "filename": "",
                 "error": "yt-dlp no está instalado (brew install yt-dlp)"} for u in urls]
    os.makedirs(out_dir, exist_ok=True)
    clean = _limpiar(urls)
    n = len(clean)
    if n == 0:
        return []
    results: list[dict | None] = [None] * n

    def _task(i: int, url: str) -> tuple[int, dict]:
        out_tpl = os.path.join(out_dir, f"dl_{i:03d}.%(ext)s")
        ok, path, err = _bajar_uno(url, out_tpl)
        return i, {"url": url, "ok": ok, "path": path,
                   "filename": os.path.basename(path) if path else "", "error": err}

    with ThreadPoolExecutor(max_workers=min(_MAX_PARALELO, n)) as ex:
        futs = [ex.submit(_task, i, u) for i, u in enumerate(clean)]
        for f in as_completed(futs):
            i, res = f.result()
            results[i] = res
    return [r for r in results if r is not None]
