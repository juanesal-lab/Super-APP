"""Wrappers ligeros sobre ffmpeg / ffprobe."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


class FFmpegError(RuntimeError):
    pass


def run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Ejecuta un comando y lanza FFmpegError si falla."""
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise FFmpegError(
            f"Comando fallo ({proc.returncode}): {' '.join(cmd[:6])}...\n{proc.stderr[-1500:]}"
        )
    return proc


@dataclass
class VideoInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def probe(path: str) -> VideoInfo:
    """Devuelve metadatos del video usando ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    proc = run(cmd, timeout=60)
    data = json.loads(proc.stdout)

    v_stream = None
    has_audio = False
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and v_stream is None:
            v_stream = s
        if s.get("codec_type") == "audio":
            has_audio = True

    if v_stream is None:
        raise FFmpegError(f"No se encontro stream de video en {path}")

    # fps puede venir como "30000/1001"
    fps_raw = v_stream.get("avg_frame_rate") or v_stream.get("r_frame_rate") or "0/1"
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    if fps <= 0:
        fps = 30.0  # fallback razonable

    duration = float(data.get("format", {}).get("duration", 0) or 0)
    if duration <= 0:
        duration = float(v_stream.get("duration", 0) or 0)

    return VideoInfo(
        path=path,
        duration=duration,
        width=int(v_stream.get("width", 0)),
        height=int(v_stream.get("height", 0)),
        fps=fps,
        has_audio=has_audio,
    )


def normalize_loudness(in_path: str, out_path: str, target_lufs: float = -14.0) -> str:
    """Normaliza el loudness del audio a `target_lufs` (por defecto -14 LUFS, estándar
    TikTok/Reels/Meta). Solo re-encodea el AUDIO (video -c:v copy → barato y sin pérdida);
    single-pass loudnorm es suficiente para ads cortos. Si el video no tiene audio o algo
    falla, devuelve `in_path` sin tocar (best-effort, nunca rompe el job)."""
    try:
        if not probe(in_path).has_audio:
            return in_path
        run([
            "ffmpeg", "-y", "-i", in_path,
            "-c:v", "copy",
            "-af", f"loudnorm=I={target_lufs:g}:TP=-1.5:LRA=11",
            "-c:a", "aac", "-b:a", "192k",
            out_path,
        ])
        return out_path
    except Exception:  # noqa: BLE001
        return in_path
