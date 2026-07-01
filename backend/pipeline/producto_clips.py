"""Flujo 'Producto → Clips' (semi-auto): de links de ganadores + tu producto, a clips en una pasada.

El usuario pega 2-3 links de creativos GANADORES (que él encontró) + el link y/o la imagen de SU
producto. La app:
  1) descarga los ganadores (yt-dlp),
  2) entiende el producto (Gemini lee la imagen + el texto de la página),
  3) crea los clips priorizando lo que muestra el producto (reusa process_job).

Sin scraping frágil de TikTok: la búsqueda la hace el humano (que juzga mejor), la máquina hace
todo el trabajo tedioso. Devuelve el MISMO shape que process_job (versions + clips) para que el
frontend lo pinte con renderResults.
"""
from __future__ import annotations

import os
from typing import Callable

from .downloader import download_urls
from .hook_gen import fetch_page_text
from .orchestrator import process_job

_MODEL = "gemini-2.5-flash"


def describir_producto(product_url: str, image_path: str | None, gemini_key: str | None,
                       fallback: str = "") -> str:
    """product_desc corto leyendo la página (link) + la imagen (Gemini vision).

    Graceful: si no hay key o falla, usa el `fallback` del usuario o el texto de la página."""
    page_text = ""
    if (product_url or "").strip():
        try:
            page_text = fetch_page_text(product_url.strip(), max_chars=2000)
        except Exception:  # noqa: BLE001
            page_text = ""

    base = (fallback or "").strip() or page_text[:180].strip()
    has_image = bool(image_path and os.path.exists(image_path))
    # Sin nada que "mirar" (ni imagen ni página), no dejamos que Gemini invente un producto:
    # devolvemos tal cual lo que escribió el usuario (o vacío).
    if not gemini_key or (not has_image and not page_text.strip()):
        return base
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=gemini_key)
    except Exception:  # noqa: BLE001
        return base

    prompt = (
        "Eres experto en dropshipping LATAM. Con la imagen del producto y/o el texto de su página, "
        "describe en UNA frase corta (máx 12 palabras, español) QUÉ es el producto y su beneficio "
        "principal — para que otra IA priorice los clips donde el producto se ve y se usa. "
        "Devuelve SOLO la frase, sin comillas ni emojis."
    )
    if (fallback or "").strip():
        prompt += f"\nPista del usuario: {fallback.strip()}"
    if page_text.strip():
        prompt += f"\nPágina: {page_text.strip()[:1500]}"

    contents = [prompt]
    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, "rb") as f:
                fb = f.read()
            mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
            contents.append(types.Part.from_bytes(data=fb, mime_type=mime))
        except Exception:  # noqa: BLE001
            pass
    try:
        resp = client.models.generate_content(model=_MODEL, contents=contents)
        desc = (resp.text or "").strip().strip('"').strip()
        return (desc or base)[:200]
    except Exception:  # noqa: BLE001
        return base


def producto_a_clips(winner_urls: list[str], work_dir: str, *,
                     product_url: str = "", image_path: str | None = None,
                     product_desc: str = "", settings: dict | None = None,
                     gemini_key: str | None = None,
                     progress: Callable[[str, int], None] | None = None) -> dict:
    """Descarga los ganadores → entiende el producto → crea los clips. Nunca lanza."""
    settings = settings or {}

    def report(m, p):
        if progress:
            progress(m, int(p))

    # 1 · Descargar los creativos ganadores (0→28%)
    report("Descargando creativos ganadores...", 3)
    src_dir = os.path.join(work_dir, "src")
    dl = download_urls(winner_urls, src_dir,
                       progress=lambda m, p: report(m, 3 + p * 0.25))
    paths = [d["path"] for d in dl if d.get("ok") and d.get("path")]
    n_fail = sum(1 for d in dl if not d.get("ok"))
    if not paths:
        return {"ok": False,
                "error": "No se pudo descargar ningún video de esos links. "
                         "Revisa que sean públicos y estén bien copiados.",
                "descargas": dl}

    # 2 · Entender el producto (link + imagen) (28→32%)
    report("Analizando tu producto (imagen + página)...", 30)
    desc = describir_producto(product_url, image_path, gemini_key, fallback=product_desc)

    # 3 · Crear los clips (32→100%), reusa el pipeline principal
    report("Creando clips a partir de los ganadores...", 32)
    result = process_job(
        paths, os.path.join(work_dir, "out"),
        target_seconds=float(settings.get("target_seconds", 15.0)),
        max_clip_seconds=float(settings.get("max_clip", 3.0)),
        use_gemini=bool(settings.get("use_gemini", True)),
        product_desc=desc,
        aspect=settings.get("aspect", "9:16"),
        auto_hook=bool(settings.get("auto_hook", False)),
        page_url=product_url or "",
        enhance=bool(settings.get("enhance", False)),
        effects=bool(settings.get("effects", False)),
        blur_captions=bool(settings.get("blur_captions", True)),
        text_mode=settings.get("text_mode", "tapar"),
        gemini_key=gemini_key,
        progress=lambda m, p: report(m, 32 + p * 0.66),
    )

    if isinstance(result, dict):
        result["producto_desc"] = desc
        result["descargados"] = len(paths)
        result["fallidos"] = n_fail
    return result
