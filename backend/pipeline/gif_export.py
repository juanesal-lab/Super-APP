"""Exporta un clip a WebP animado — el "GIF" liviano para landings, igual que video-studio.

La app `~/video-studio` (workflow "landing") hace: MP4 -> extrae frames con ffmpeg a cierto
FPS -> los ensambla con `img2webp` (herramienta oficial de Google, produce WebP animado). Aquí
replicamos ese mismo enfoque, porque el ffmpeg de esta máquina NO trae encoder webp, pero
`img2webp` SÍ está instalado.

100% opcional: si `img2webp` no está, `available()` da False y el pipeline sigue igual (sin GIF).
"""
from __future__ import annotations

import os
import shutil
import tempfile

from .ffmpeg_utils import run

# Preset "media" de video-studio (landing): buen balance calidad/peso para un GIF de web.
_FPS = 20
_Q = 70


def available() -> bool:
    """True si `img2webp` está disponible (si no, se omite el GIF sin romper nada)."""
    return shutil.which("img2webp") is not None


def to_animated_webp(mp4_path: str, out_webp: str, *, fps: int = _FPS, q: int = _Q,
                     max_seconds: float = 3.0, max_dim: int = 720) -> str | None:
    """Convierte un clip .mp4 en WebP animado (loop infinito). Devuelve la ruta o None.

    Acota a `max_seconds` (los GIFs son cortos) y a `max_dim` px de lado (sin agrandar) para
    que el GIF quede liviano. None si no hay img2webp, no existe el clip, o falla algún paso
    (nunca lanza: no rompe el pipeline).
    """
    if not available() or not os.path.exists(mp4_path):
        return None
    frames_dir = tempfile.mkdtemp(prefix="gifframes_",
                                  dir=os.path.dirname(out_webp) or None)
    try:
        # 1) Extraer frames a `fps` (igual que video-studio). `-t` acota la duración; el scale
        #    limita el lado a `max_dim` px SIN agrandar (los clips sueltos son 1:1) -> GIF liviano.
        vf = f"fps={fps},scale='min({max_dim},iw)':-2"
        run(["ffmpeg", "-nostdin", "-y", "-t", f"{max_seconds:.2f}", "-i", mp4_path,
             "-vf", vf, os.path.join(frames_dir, "f_%05d.png")])
        frames = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
        if not frames:
            return None
        frame_ms = max(1, round(1000 / fps))
        # 2) Ensamblar el WebP animado con img2webp (mismos flags que video-studio).
        run(["img2webp", "-loop", "0", "-lossy", "-q", str(q), "-m", "4", "-d", str(frame_ms),
             *[os.path.join(frames_dir, f) for f in frames], "-o", out_webp])
        return out_webp if os.path.exists(out_webp) else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
