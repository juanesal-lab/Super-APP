"""Voz en off con ElevenLabs (text-to-speech)."""
from __future__ import annotations

import base64
import json
import os
import urllib.request

# Voces elegidas por el usuario (ElevenLabs voice library)
VOICES = {
    "kate": {"id": "qWWAqFomnJ99VwQLREfT", "label": "Kate"},
    "juan_carlos": {"id": "G4IAP30yc6c1gK0csDfu", "label": "Juan Carlos"},
}
_MODEL = "eleven_multilingual_v2"   # soporta espanol


def voice_id_for(key: str) -> str:
    v = VOICES.get(key)
    return v["id"] if v else key  # permite pasar un voice_id directo


def synthesize(api_key: str, text: str, voice_key: str, out_path: str) -> str:
    """Genera el audio de la voz en off (mp3). Lanza excepcion si falla."""
    if not api_key:
        raise RuntimeError("Falta la API key de ElevenLabs")
    vid = voice_id_for(voice_key)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    body = json.dumps({
        "text": text,
        "model_id": _MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.25},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"ElevenLabs error {e.code}: {detail}")
    with open(out_path, "wb") as f:
        f.write(audio)
    return out_path


def _words_from_chars(alignment: dict) -> list[dict]:
    chars = alignment.get("characters", [])
    st = alignment.get("character_start_times_seconds", [])
    et = alignment.get("character_end_times_seconds", [])
    words, cur, cs, ce = [], "", None, None
    for ch, s, e in zip(chars, st, et):
        if ch.strip() == "":
            if cur:
                words.append({"word": cur, "start": cs, "end": ce}); cur = ""
            continue
        if not cur:
            cs = s
        cur += ch; ce = e
    if cur:
        words.append({"word": cur, "start": cs, "end": ce})
    return words


def synthesize_with_timestamps(api_key: str, text: str, voice_key: str,
                               out_path: str) -> list[dict]:
    """Genera la voz Y devuelve los tiempos por palabra [{'word','start','end'}]."""
    if not api_key:
        raise RuntimeError("Falta la API key de ElevenLabs")
    vid = voice_id_for(voice_key)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/with-timestamps"
    body = json.dumps({
        "text": text, "model_id": _MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.25},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"ElevenLabs error {e.code}: {detail}")
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(data["audio_base64"]))
    return _words_from_chars(data.get("alignment") or {})


def music(api_key: str, prompt: str, out_path: str, length_ms: int = 18000) -> str:
    """Genera musica de fondo (mp3) con ElevenLabs Music a partir de una descripcion."""
    if not api_key:
        raise RuntimeError("Falta la API key de ElevenLabs")
    body = json.dumps({
        "prompt": prompt,
        "music_length_ms": int(max(10000, min(60000, length_ms))),
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/music", data=body, method="POST",
        headers={"xi-api-key": api_key, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"ElevenLabs Music error {e.code}: {detail}")
    with open(out_path, "wb") as f:
        f.write(audio)
    return out_path


def sound_effect(api_key: str, description: str, out_path: str,
                 duration: float | None = None) -> str:
    """Genera un efecto de sonido (mp3) con ElevenLabs a partir de una descripcion."""
    if not api_key:
        raise RuntimeError("Falta la API key de ElevenLabs")
    payload = {"text": description, "prompt_influence": 0.4}
    if duration:
        payload["duration_seconds"] = max(0.5, min(8.0, float(duration)))
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/sound-generation", data=body, method="POST",
        headers={"xi-api-key": api_key, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"ElevenLabs SFX error {e.code}: {detail}")
    with open(out_path, "wb") as f:
        f.write(audio)
    return out_path
