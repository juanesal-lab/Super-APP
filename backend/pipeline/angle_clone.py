"""Clon de ÁNGULO con producto propio.

Toma un creativo GANADOR de otro mercado (que usa un ángulo que también sirve para un
producto nuestro) y lo clona mostrando NUESTRO producto real. Ejemplo: ganador gringo de
"veneno de abeja en cápsulas"; nosotros vendemos la CREMA → clonamos el creativo pero donde
se ve el pote de cápsulas metemos tomas de nuestra crema. El cliente ve el producto real que
le va a llegar, conservando el ángulo/guion (audio) que YA está probado que convierte.

NIVEL REALISTA (este módulo): mezcla clips del ganador + tomas propias en los momentos donde
aparece el producto original, conservando el audio del ganador. (El reemplazo automático
perfecto sobre producto en movimiento es un nivel superior, para después.)

Terreno propio. REUSA `product_swap.py` de Juan (solo lo importa, NO lo modifica):
detect_product_ranges + find_new_clips + swap_product. Aporta soporte de FOTOS y control
manual de momentos. Gemini + FFmpeg (no Anthropic). Degrada sin key.
"""
from __future__ import annotations

import os
import tempfile
from typing import Callable

from .ffmpeg_utils import run, probe
from .narrative import mmss_to_seconds
from .product_swap import detect_product_ranges, find_new_clips, swap_product


def _photo_to_clip(photo: str, seconds: float, out: str) -> str:
    """Convierte una FOTO del producto en un clip de video corto (para poder empalmarlo)."""
    run(["ffmpeg", "-y", "-loop", "1", "-i", photo, "-t", f"{max(0.6, seconds):.2f}",
         "-an", "-vf", "fps=30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", out])
    return out


def _parse_ranges(manual, dur: float) -> list[tuple]:
    """['00:05-00:09', ...] -> [(5.0, 9.0), ...] acotado a la duración del video."""
    out = []
    for r in manual or []:
        try:
            a, b = str(r).split("-", 1)
            s, e = mmss_to_seconds(a), mmss_to_seconds(b)
            if e > s:
                out.append((max(0.0, s), min(dur, e)))
        except (ValueError, TypeError):
            continue
    return out


def clonar_angulo(
    winner_path: str,
    our_videos: list[str] | None = None,
    our_photos: list[str] | None = None,
    *,
    api_key: str | None = None,
    old_desc: str = "",
    our_desc: str = "",
    manual_ranges: list[str] | None = None,
    photo_seconds: float = 2.5,
    out_path: str | None = None,
    work_dir: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Clona el ángulo del ganador mostrando nuestro producto.

    Entrada:
      - winner_path: el video ganador a clonar.
      - our_videos / our_photos: tomas/fotos de NUESTRO producto (al menos una cosa).
      - old_desc: qué producto se ve en el ganador (ayuda a detectarlo). our_desc: el nuestro.
      - manual_ranges: opcional ['mm:ss-mm:ss', ...] para FORZAR dónde va nuestro producto
        (útil cuando la detección automática falla o el auto queda raro).
    Devuelve {"ok":True,"ranges":[(s,e)..],"n_tomas":N,"video":ruta} o {"ok":False,"error":..}.
    """
    def report(m, p):
        if progress:
            progress(m, p)

    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    our_videos = [v for v in (our_videos or []) if v and os.path.exists(v)]
    our_photos = [p for p in (our_photos or []) if p and os.path.exists(p)]
    if not our_videos and not our_photos:
        return {"ok": False, "error": "Sube al menos un video o una foto de tu producto."}
    if not os.path.exists(winner_path):
        return {"ok": False, "error": "No encuentro el video ganador."}

    try:
        dur = probe(winner_path).duration
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"No se pudo leer el video ganador: {e}"}

    work_dir = work_dir or tempfile.mkdtemp(prefix="angleclone_")
    os.makedirs(work_dir, exist_ok=True)
    out_path = out_path or os.path.join(work_dir, "clon_angulo.mp4")

    # 1) Momentos donde aparece el producto VIEJO (manual manda; si no, detección con Gemini)
    ranges = _parse_ranges(manual_ranges, dur)
    if not ranges:
        if not api_key:
            return {"ok": False, "error": "Sin GEMINI_API_KEY no puedo detectar el producto. "
                    "Pásame manual_ranges (ej. ['00:05-00:09'])."}
        report("Detectando dónde aparece el producto del ganador...", 25)
        ranges = detect_product_ranges(api_key, winner_path, old_desc)
    if not ranges:
        return {"ok": False, "error": "No detecté momentos claros del producto en el ganador. "
                "Dame manual_ranges (ej. ['00:03-00:07']) o una mejor descripción (old_desc)."}

    # 2) Nuestras tomas: fotos -> clips + videos -> find_new_clips (reusado)
    report("Preparando las tomas de tu producto...", 55)
    our_clips: list[tuple] = []
    for i, ph in enumerate(our_photos):
        clip = _photo_to_clip(ph, photo_seconds, os.path.join(work_dir, f"photo_{i:02d}.mp4"))
        our_clips.append((clip, 0.0, photo_seconds))
    if our_videos:
        our_clips += find_new_clips(api_key, our_videos, our_desc)
    if not our_clips:
        return {"ok": False, "error": "No pude preparar tomas de tu producto."}

    # 3) Empalmar: nuestras tomas en los momentos del producto, conservando el audio del ganador
    report("Clonando el creativo con tu producto...", 80)
    try:
        swap_product(winner_path, our_clips, ranges, out_path, work_dir)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Error clonando el creativo: {e}"}

    report("Clon de ángulo listo", 100)
    return {"ok": True, "ranges": ranges, "n_tomas": len(our_clips), "video": out_path}


# --- CLI de prueba: python -m backend.pipeline.angle_clone <ganador> --foto X [--rango 00:05-00:09] ---
if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m backend.pipeline.angle_clone <ganador.mp4> "
              "[--video v.mp4]... [--foto f.jpg]... [--rango mm:ss-mm:ss]... "
              "[--old 'desc viejo'] [--nuestro 'desc nuestro'] [--out salida.mp4]")
        raise SystemExit(1)

    winner = sys.argv[1]
    vids, fotos, rangos = [], [], []
    old_d = our_d = out = ""
    args = sys.argv[2:]
    for i, a in enumerate(args):
        if a == "--video" and i + 1 < len(args): vids.append(args[i + 1])
        elif a == "--foto" and i + 1 < len(args): fotos.append(args[i + 1])
        elif a == "--rango" and i + 1 < len(args): rangos.append(args[i + 1])
        elif a == "--old" and i + 1 < len(args): old_d = args[i + 1]
        elif a == "--nuestro" and i + 1 < len(args): our_d = args[i + 1]
        elif a == "--out" and i + 1 < len(args): out = args[i + 1]

    def _p(m, p):
        print(f"[{p:3d}%] {m}", file=sys.stderr)

    res = clonar_angulo(winner, vids or None, fotos or None, old_desc=old_d, our_desc=our_d,
                        manual_ranges=rangos or None, out_path=out or None, progress=_p)
    print(json.dumps(res, ensure_ascii=False, indent=2))
