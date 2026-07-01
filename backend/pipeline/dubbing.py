"""Doblaje (dubbing) de video con ElevenLabs: traduce el audio a otro idioma
manteniendo el tono de voz. Es asíncrono: se crea el trabajo y se sondea hasta terminar."""
from __future__ import annotations

import os
import time

import requests

_BASE = "https://api.elevenlabs.io/v1/dubbing"

# Idiomas soportados (código: nombre)
LANGS = {
    "es": "Español", "en": "Inglés", "pt": "Portugués", "fr": "Francés",
    "it": "Italiano", "de": "Alemán", "hi": "Hindi", "ja": "Japonés",
}


def create_dubbing(api_key: str, file_path: str, target_lang: str,
                   source_lang: str = "auto") -> str:
    data = {"target_lang": target_lang}
    if source_lang and source_lang != "auto":
        data["source_lang"] = source_lang
    with open(file_path, "rb") as f:
        r = requests.post(_BASE, headers={"xi-api-key": api_key}, data=data,
                          files={"file": (os.path.basename(file_path), f, "video/mp4")},
                          timeout=180)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs Dubbing {r.status_code}: {r.text[:300]}")
    return r.json()["dubbing_id"]


def dubbing_status(api_key: str, dubbing_id: str) -> dict:
    r = requests.get(f"{_BASE}/{dubbing_id}", headers={"xi-api-key": api_key}, timeout=60)
    return r.json() if r.status_code < 400 else {"status": "error", "detail": r.text[:200]}


def download_dubbed(api_key: str, dubbing_id: str, target_lang: str, out_path: str) -> str:
    r = requests.get(f"{_BASE}/{dubbing_id}/audio/{target_lang}",
                     headers={"xi-api-key": api_key}, timeout=600)
    if r.status_code >= 400:
        raise RuntimeError(f"Descarga del doblaje {r.status_code}: {r.text[:200]}")
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def dub_video(api_key: str, file_path: str, target_lang: str, out_path: str,
              source_lang: str = "auto", progress=None, timeout: int = 900) -> str:
    """Crea el doblaje, espera a que termine y descarga el video doblado."""
    if not api_key:
        raise RuntimeError("Falta la API key de ElevenLabs")
    did = create_dubbing(api_key, file_path, target_lang, source_lang)
    waited = 0
    while waited < timeout:
        st = dubbing_status(api_key, did)
        status = st.get("status")
        if status == "dubbed":
            return download_dubbed(api_key, did, target_lang, out_path)
        if status in ("failed", "error"):
            raise RuntimeError("El doblaje falló: " + str(st.get("error") or st.get("detail") or ""))
        if progress:
            progress(f"Doblando el video... (esto tarda unos minutos)")
        time.sleep(8)
        waited += 8
    raise RuntimeError("El doblaje tardó demasiado (timeout)")
