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


def acelerar(mp3_path: str, words: list[dict] | None, factor: float = 1.12) -> list[dict]:
    """Acelera la locución (Manual Maestro §6: 1.1-1.2× suena más enérgica y retiene mejor en
    short-form) SIN cambiar el tono (atempo) y re-escala los tiempos por palabra para que los
    subtítulos karaoke y el montaje por guion sigan clavados. Devuelve los words re-escalados;
    si algo falla, deja el mp3 y los tiempos como estaban (nunca lanza)."""
    import os
    import subprocess
    if factor <= 1.01 or not os.path.exists(mp3_path):
        return words or []
    tmp = mp3_path + ".spd.mp3"
    try:
        subprocess.run(["ffmpeg", "-y", "-i", mp3_path, "-filter:a", f"atempo={factor:.3f}",
                        "-c:a", "libmp3lame", "-q:a", "3", tmp],
                       capture_output=True, timeout=120, check=True)
        os.replace(tmp, mp3_path)
        return [{**w, "start": round(float(w["start"]) / factor, 3),
                 "end": round(float(w["end"]) / factor, 3)} for w in (words or [])]
    except Exception:  # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass
        return words or []


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
