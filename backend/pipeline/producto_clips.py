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
from .ffmpeg_utils import run, probe
from .hook_gen import fetch_page_text
from .orchestrator import process_job
from .scripts import generate_scripts
from . import voiceover

_MODEL = "gemini-2.5-flash"

# 4 géneros de música; la IA elige el que mejor pega con el producto
_GENEROS = {
    "energico": "música urbana/trap energética con beat marcado, moderna y viral para TikTok, instrumental",
    "alegre": "música pop alegre, animada y pegajosa, positiva, instrumental",
    "emotivo": "música cinematográfica emotiva y cálida, inspiradora, con piano y cuerdas, instrumental",
    "elegante": "música elegante y premium, deep house/lo-fi suave y sofisticada, instrumental",
}


def _elegir_genero(desc: str, gemini_key: str | None) -> str:
    """La IA elige 1 de 4 géneros según el producto. Fallback: energico."""
    if not (gemini_key and (desc or "").strip()):
        return "energico"
    try:
        from google import genai
        client = genai.Client(api_key=gemini_key)
        r = client.models.generate_content(
            model=_MODEL,
            contents=[f"Producto: {desc}. Para un anuncio de TikTok, ¿qué música pega MEJOR? "
                      "Responde SOLO una palabra: energico, alegre, emotivo o elegante."])
        g = (r.text or "").strip().lower()
        for k in _GENEROS:
            if k in g:
                return k
    except Exception:  # noqa: BLE001
        pass
    return "energico"


def _tiene_audio(path: str) -> bool:
    try:
        return any(getattr(s, "codec_type", "") == "audio" for s in (probe(path).streams or []))
    except Exception:  # noqa: BLE001
        return False


def _generar_musica(work_dir: str, *, eleven_key: str | None, genero: str,
                    report) -> str | None:
    """Genera 1 pista de música del género elegido (ElevenLabs Music). None si falla o no hay key."""
    if not eleven_key:
        return None
    music_path = os.path.join(work_dir, "musica.mp3")
    try:
        report(f"Poniendo música ({genero})...", 90)
        voiceover.music(eleven_key, _GENEROS.get(genero, _GENEROS["energico"]), music_path,
                        length_ms=30000)
    except Exception:  # noqa: BLE001
        return None
    return music_path if os.path.exists(music_path) else None


def _mezclar_musica(versions: list[dict], music_path: str, *, bajar_volumen: bool) -> None:
    """Mezcla la música en cada versión (bajando el volumen de los clips). Modifica
    versions[i]['path'] en el sitio. Si una versión falla, se deja igual (sin música)."""
    clip_vol = "0.12" if bajar_volumen else "0.55"
    for v in versions:
        p = v.get("path")
        if not p or not os.path.exists(p):
            continue
        try:
            vdur = probe(p).duration
        except Exception:  # noqa: BLE001
            continue
        out = p[:-4] + "_mus.mp4" if p.endswith(".mp4") else p + "_mus.mp4"
        if _tiene_audio(p):
            fc = (f"[0:a]volume={clip_vol}[c];[1:a]volume=0.8[m];"
                  "[c][m]amix=inputs=2:duration=first:normalize=0[mix];"
                  "[mix]loudnorm=I=-16:TP=-1.5:LRA=11[a]")
        else:
            fc = "[1:a]volume=0.8,loudnorm=I=-16:TP=-1.5:LRA=11[a]"
        try:
            run(["ffmpeg", "-y", "-i", p, "-stream_loop", "-1", "-i", music_path,
                 "-filter_complex", fc, "-map", "0:v:0", "-map", "[a]",
                 "-t", f"{vdur:.2f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", out])
            v["path"] = out
        except Exception:  # noqa: BLE001
            continue


def _guiones_y_narraciones(work_dir: str, *, eleven_key: str | None, gemini_key: str | None,
                           desc: str, page_text: str, target_seconds: float, voz: str,
                           n_guiones: int, n_versiones: int,
                           report) -> tuple[list[dict], list[tuple]] | None:
    """PASO 1 del flujo "primero el guion": guiones con Gemini (reglas de oro: sin precio +
    CTA exacto) → narración colombiana (ElevenLabs con tiempos por palabra). El montaje se
    hace DESPUÉS, guiado por estas frases (guion_match dentro de render_versions).

    Devuelve (guiones, narraciones=[(mp3, words, texto)]) o None si no se pudo."""
    if not eleven_key:
        return None
    n = n_versiones if not n_guiones else max(1, min(int(n_guiones), n_versiones))
    report("Escribiendo los guiones de la voz en off...", 32)
    guiones = generate_scripts(gemini_key, desc, page_text, target_seconds, n=n)
    if not guiones:
        return None

    from concurrent.futures import ThreadPoolExecutor
    report(f"Narrando {len(guiones)} guion(es) con la voz colombiana...", 34)

    def _tts(item):
        i, g = item
        mp3 = os.path.join(work_dir, f"vo_{i}.mp3")
        try:
            words = voiceover.synthesize_with_timestamps(eleven_key, g["texto"], voz, mp3)
            return (mp3, words, g["texto"])
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=min(4, len(guiones))) as ex:
        narraciones = [r for r in ex.map(_tts, list(enumerate(guiones))) if r]
    if not narraciones:
        return None
    return guiones, narraciones


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
                     archivos_locales: list[str] | None = None,
                     product_url: str = "", image_path: str | None = None,
                     product_desc: str = "", settings: dict | None = None,
                     gemini_key: str | None = None, eleven_key: str | None = None,
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
    import os as _os
    paths += [p for p in (archivos_locales or []) if p and _os.path.exists(p)]  # 📁 de Descargas
    n_fail = sum(1 for d in dl if not d.get("ok"))
    if not paths:
        return {"ok": False,
                "error": "No se pudo descargar ningún video de esos links. "
                         "Revisa que sean públicos y estén bien copiados.",
                "descargas": dl}

    # 2 · Entender el producto (link + imagen) (28→32%)
    report("Analizando tu producto (imagen + página)...", 30)
    desc = describir_producto(product_url, image_path, gemini_key, fallback=product_desc)

    # 2.5 · GUION PRIMERO (flujo de Juan): guiones + narración ANTES del montaje → el render
    #       monta por guion (guion_match elige el clip que ilustra cada frase) y quema voz,
    #       subtítulos y mezcla pro ADENTRO. La música también se genera antes por lo mismo.
    out_dir = os.path.join(work_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    music_path, genero = None, None
    if settings.get("musica", True):
        genero = _elegir_genero(desc, gemini_key)
        music_path = _generar_musica(out_dir, eleven_key=eleven_key, genero=genero,
                                     report=report)
    guiones, narraciones, version_vos = None, None, None
    if settings.get("voz_en_off"):
        page_text = ""
        if (product_url or "").strip():
            try:
                page_text = fetch_page_text(product_url.strip(), max_chars=2500)
            except Exception:  # noqa: BLE001
                page_text = ""
        gn = _guiones_y_narraciones(
            out_dir, eleven_key=eleven_key, gemini_key=gemini_key, desc=desc,
            page_text=page_text, target_seconds=float(settings.get("target_seconds", 15.0)),
            voz=settings.get("voz", "juan_carlos"),
            n_guiones=int(settings.get("vo_guiones", 0) or 0), n_versiones=8, report=report)
        if gn:
            guiones, narraciones = gn
            # una voz por versión (cicladas si hay menos guiones que versiones)
            version_vos = [(narraciones[i % len(narraciones)][0],
                            narraciones[i % len(narraciones)][1]) for i in range(8)]

    # 3 · Crear los clips (montaje por guion si hay voz), reusa el pipeline principal
    report("Creando clips a partir de los ganadores...", 36)
    from .assemble import list_sfx
    result = process_job(
        paths, out_dir,
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
        version_vos=version_vos,
        sfx_paths=list_sfx() if version_vos else None,
        music_path=music_path if version_vos else None,
        captions=bool(settings.get("subtitulos", True)) and bool(version_vos),
        caption_style=settings.get("caption_style", "hormozi"),
        caption_size=settings.get("caption_size", "mediano"),
        gemini_key=gemini_key,
        progress=lambda m, p: report(m, 36 + p * 0.62),
    )

    if isinstance(result, dict) and result.get("ok") and result.get("versions"):
        if genero:
            result["genero_musica"] = genero
        if version_vos:
            result["voz_en_off"] = True
            result["guiones_vo"] = [g.get("texto", "") for g in (guiones or [])]
            result["caption_style"] = settings.get("caption_style", "hormozi")
            for i, v in enumerate(result["versions"]):   # el guion de cada versión, para la UI
                _, _, texto = narraciones[i % len(narraciones)]
                v["guion"] = texto
        elif music_path:
            # Sin voz en off (o si falló la narración): comportamiento de antes (música sola)
            _mezclar_musica(result["versions"], music_path,
                            bajar_volumen=bool(settings.get("bajar_volumen", True)))

    if isinstance(result, dict):
        result["producto_desc"] = desc
        result["descargados"] = len(paths)
        result["fallidos"] = n_fail
    return result
