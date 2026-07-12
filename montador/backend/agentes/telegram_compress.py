"""🤖 Agente telegram: comprime los videos finales a <48MB para que quepan por el bot.

El Bot API de Telegram rechaza subidas de más de 50MB, así que los ads largos
(p. ej. 99s a 1080p ≈ 113MB) solo llegaban como mensaje de texto. Este agente
transcodifica el video a 720x1280 (vertical) con bitrate calculado según la
duración para caer justo bajo el límite, sin tocar el archivo original.

Receta: H.264 libx264 preset fast, +movflags +faststart (streaming en el chat),
escala 720x1280 y audio AAC 128k. El bitrate de video se calcula como
TARGET_MB*8192/duración (kbits/s) menos los 128k del audio, aplicado con
-b:v/-maxrate/-bufsize. Si aun así el resultado supera los 48MB (raro),
reintenta UNA sola vez con bitrate*0.8.

Contrato: preparar() NUNCA lanza excepción; ante cualquier fallo devuelve la
lista original y deja registro en el log del proyecto.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

LIMITE_MB = 48.0     # tope duro: por debajo del límite de 50MB del Bot API (con margen)
TARGET_MB = 45.0     # objetivo al transcodificar (margen extra por overhead del contenedor)
AUDIO_KBPS = 128     # audio AAC reservado
MIN_VIDEO_KBPS = 150 # piso de bitrate para videos larguísimos (mejor algo que nada)
TIMEOUT_S = 900      # 15 min máximo por pasada de ffmpeg: jamás colgar el pipeline
# Escala vertical 720x1280: si el aspecto no es 9:16 exacto, encoge sin deformar y
# rellena con negro para entregar siempre 720x1280 (mitad de bitrate necesario vs 1080).
_FILTRO_ESCALA = ("scale=720:1280:force_original_aspect_ratio=decrease,"
                  "pad=720:1280:-1:-1,setsar=1")


def _mb(path: Path) -> float:
    """Tamaño en MB (misma convención que notify.py: bytes/1_000_000)."""
    return path.stat().st_size / 1_000_000


def _duracion(path: Path) -> float | None:
    """Duración en segundos vía ffprobe, o None si no se pudo leer."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60)
        dur = float(r.stdout.strip())
        return dur if dur > 0 else None
    except Exception:  # noqa: BLE001
        return None


def _transcodificar(orig: Path, destino_tmp: Path, video_kbps: int) -> bool:
    """Una pasada de ffmpeg a 720x1280 con el bitrate dado. True si salió bien."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(orig),
           "-vf", _FILTRO_ESCALA,
           "-c:v", "libx264", "-preset", "fast",
           "-b:v", f"{video_kbps}k", "-maxrate", f"{video_kbps}k",
           "-bufsize", f"{video_kbps * 2}k",
           "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k",
           "-movflags", "+faststart",
           str(destino_tmp)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
        return r.returncode == 0 and destino_tmp.exists() and destino_tmp.stat().st_size > 0
    except Exception:  # noqa: BLE001
        return False


def _limpiar(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def _preparar_uno(pdir: Path, rel: str, log) -> str:
    """Procesa UN video. Devuelve la ruta relativa a mandar (la -tg.mp4 o la original)."""
    orig = pdir / "resultado" / rel
    if not orig.exists():
        log(f"🤖 Agente telegram: no encontré {rel} — lo dejo tal cual")
        return rel

    mb_orig = _mb(orig)
    if mb_orig <= LIMITE_MB:
        log(f"🤖 Agente telegram: {rel} pesa {mb_orig:.0f}MB (≤{LIMITE_MB:.0f}MB) — va directo")
        return rel

    rel_p = Path(rel)
    rel_tg = str(rel_p.parent / f"{rel_p.stem}-tg.mp4")
    destino = pdir / "resultado" / rel_tg

    # Caché: si el -tg.mp4 ya existe, es más nuevo que el original y cabe, no recomprimir.
    if (destino.exists() and destino.stat().st_mtime > orig.stat().st_mtime
            and _mb(destino) <= LIMITE_MB):
        log(f"🤖 Agente telegram: {rel_tg} ya estaba listo ({_mb(destino):.0f}MB, caché) — no recomprimo")
        return rel_tg

    dur = _duracion(orig)
    if dur is None:
        log(f"🤖 Agente telegram: no pude leer la duración de {rel} — mando el original")
        return rel

    # Bitrate objetivo: TARGET_MB*8192/dur kbits/s totales, menos los 128k del audio.
    video_kbps = max(int(TARGET_MB * 8192 / dur) - AUDIO_KBPS, MIN_VIDEO_KBPS)

    # Transcodificar a un temporal y renombrar al final: un archivo a medias
    # jamás debe quedar como -tg.mp4 (envenenaría la caché).
    tmp = destino.with_name(f".{destino.stem}.tmp.mp4")
    _limpiar(tmp)

    log(f"🤖 Agente telegram: {rel} pesa {mb_orig:.0f}MB (> {LIMITE_MB:.0f}MB) — comprimiendo a 720p…")
    intentos = 0
    for kbps in (video_kbps, int(video_kbps * 0.8)):
        intentos += 1
        if not _transcodificar(orig, tmp, kbps):
            log(f"🤖 Agente telegram: ffmpeg falló con {rel} — mando el original")
            _limpiar(tmp)
            return rel
        if _mb(tmp) <= LIMITE_MB:
            break
        if intentos == 1:
            log(f"🤖 Agente telegram: salió de {_mb(tmp):.0f}MB, reintento con bitrate*0.8…")
    else:
        log(f"🤖 Agente telegram: ni con el reintento bajó de {LIMITE_MB:.0f}MB "
            f"({_mb(tmp):.0f}MB) — mando el original")
        _limpiar(tmp)
        return rel

    os.replace(tmp, destino)
    log(f"🤖 Agente telegram: {mb_orig:.0f}MB → {_mb(destino):.0f}MB (720p)")
    return rel_tg


def preparar(pdir, rel_paths: list[str], log=print) -> list[str]:
    """pdir = carpeta del proyecto. rel_paths = rutas relativas a pdir/'resultado'.
    Para cada video: si pesa <=48MB lo deja igual; si pesa más, lo transcodifica a
    pdir/'resultado'/<stem>-tg.mp4 (<48MB) y devuelve esa ruta relativa en su lugar.
    Con caché: si el -tg.mp4 ya existe y es más nuevo que el original, no recomprime.
    NUNCA lanza excepción: ante cualquier fallo devuelve la lista original y loguea."""
    try:
        pdir = Path(pdir)
        salida = []
        for rel in rel_paths:
            try:
                salida.append(_preparar_uno(pdir, rel, log))
            except Exception as ex:  # noqa: BLE001
                try:
                    log(f"🤖 Agente telegram falló con {rel} ({ex}) — mando el original")
                except Exception:  # noqa: BLE001
                    pass
                salida.append(rel)
        return salida
    except Exception as ex:  # noqa: BLE001
        try:
            log(f"🤖 Agente telegram falló ({ex}) — mando los originales")
        except Exception:  # noqa: BLE001
            pass
        return list(rel_paths)
