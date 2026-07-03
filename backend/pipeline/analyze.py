"""Analisis de calidad de video por ventanas cortas + seleccion de sub-segmentos.

Idea: muestreamos frames varias veces por segundo y calculamos por cada uno:
  - nitidez (varianza del Laplaciano)  -> penaliza desenfoque / borroso
  - brillo (luminancia media)          -> penaliza muy oscuro / quemado
  - movimiento (diff vs frame previo)  -> detecta cortes de camara y exceso de shake
Con eso armamos una linea de tiempo de "calidad" y extraemos los tramos buenos,
recortando solo la parte buena de cada escena (ej. los 1.5s utiles de 2s).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, asdict

import cv2
import numpy as np

from .ffmpeg_utils import VideoInfo


# Parametros de seleccion (segundos)
MIN_CLIP = 0.8
MAX_CLIP = 3.0          # requisito del usuario: clips < 3s
SAMPLES_PER_SEC = 6     # resolucion temporal del analisis
# Margenes para no mostrar frames de la escena vecina (cortes limpios)
START_MARGIN = 0.12     # recorta el inicio (lo mas importante: evita el "pedazo de antes")
END_MARGIN = 0.08       # recorta el final


def detect_scene_cuts(path: str, threshold: float = 0.30) -> list[float]:
    """Tiempos (s) PRECISOS de cambio de escena usando el detector de FFmpeg."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-i", path, "-filter:v",
             f"select='gt(scene,{threshold})',metadata=print:file=-",
             "-an", "-f", "null", "-"],
            capture_output=True, text=True, timeout=180,
        )
    except Exception:
        return []
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return sorted({float(t) for t in re.findall(r"pts_time:([0-9.]+)", out)})


@dataclass
class Segment:
    video: str          # ruta del video origen
    source_index: int   # indice del video en el lote
    start: float
    end: float
    score: float        # 0..100, score final combinado
    local_score: float = 0.0      # calidad tecnica local (nitidez/luz)
    product_visible: bool = False  # Gemini: se ve el producto
    shows_use: bool = False        # Gemini: muestra como se usa / funciona
    tag: str = ""                  # Gemini: etiqueta corta de la escena
    def duration(self) -> float:
        return self.end - self.start
    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = round(self.duration(), 2)
        return d


def segment_signatures(seg: "Segment", fracs=(0.2, 0.5, 0.8)) -> list:
    """VARIAS firmas perceptuales (aHash 8x8) por segmento — al inicio, medio y final.

    Con una sola firma (frame medio) dos tomas de la MISMA escena en archivos/tiempos distintos no se
    detectaban como duplicadas (causa de que los cortes se repitieran entre versiones cuando los
    creativos del proveedor comparten metraje). Con 3 firmas, basta que UNA coincida para marcarlas."""
    sigs = []
    cap = cv2.VideoCapture(seg.video)
    if not cap.isOpened():
        return sigs
    for f in fracs:
        cap.set(cv2.CAP_PROP_POS_MSEC, (seg.start + (seg.end - seg.start) * f) * 1000.0)
        ok, frame = cap.read()
        if ok and frame is not None:
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, (8, 8)).astype(np.float32)
            sigs.append((g > g.mean()).flatten())
    cap.release()
    return sigs


def segment_signature(seg: "Segment"):
    """Firma perceptual (aHash 8x8) del frame medio, para detectar duplicados visuales."""
    cap = cv2.VideoCapture(seg.video)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, (seg.start + seg.end) / 2.0 * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (8, 8)).astype(np.float32)
    return (g > g.mean()).flatten()


def sig_distance(a, b) -> int:
    """Distancia de Hamming entre dos firmas (0 = identicas, 64 = opuestas)."""
    return int(np.count_nonzero(a != b))


def _laplacian_var(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _brightness_score(mean_lum: float) -> float:
    """1.0 en luminancia ideal (~110), cae hacia oscuro/quemado."""
    ideal = 110.0
    return float(max(0.0, 1.0 - abs(mean_lum - ideal) / ideal))


def analyze_video(info: VideoInfo, source_index: int,
                  max_clip: float = MAX_CLIP) -> list[Segment]:
    """Devuelve sub-segmentos candidatos ordenados por aparicion (cada uno <= max_clip)."""
    cap = cv2.VideoCapture(info.path)
    if not cap.isOpened():
        return []

    fps = info.fps if info.fps > 0 else 30.0
    step = max(1, int(round(fps / SAMPLES_PER_SEC)))

    times: list[float] = []
    sharp: list[float] = []
    bright: list[float] = []
    motion: list[float] = []

    prev_small = None
    idx = 0
    while True:
        ret = cap.grab()
        if not ret:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok and frame is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                times.append(idx / fps)
                sharp.append(_laplacian_var(gray))
                bright.append(float(gray.mean()))
                small = cv2.resize(gray, (64, 64))
                if prev_small is None:
                    motion.append(0.0)
                else:
                    motion.append(float(np.abs(small.astype(np.int16) - prev_small).mean()))
                prev_small = small
        idx += 1
    cap.release()

    n = len(times)
    if n < 3:
        return []

    sharp_a = np.array(sharp)
    bright_a = np.array(bright)
    motion_a = np.array(motion)

    # Normalizar nitidez relativa dentro de este video (robusto a percentiles)
    lo, hi = np.percentile(sharp_a, 10), np.percentile(sharp_a, 90)
    if hi - lo < 1e-6:
        sharp_norm = np.zeros(n)
    else:
        sharp_norm = np.clip((sharp_a - lo) / (hi - lo), 0, 1)

    bright_norm = np.array([_brightness_score(b) for b in bright_a])

    # Cortes de escena: detector PRECISO de FFmpeg (autoritativo) + picos de movimiento
    times_a = np.array(times)
    scene_cuts: set[int] = set()
    for ct in detect_scene_cuts(info.path):
        scene_cuts.add(int(np.argmin(np.abs(times_a - ct))))
    mot_thr = np.percentile(motion_a, 95) * 0.9 + 12.0
    scene_cuts |= set(i for i in range(n) if motion_a[i] > mot_thr)

    # Penalizacion por exceso de movimiento (shake/blur), pero algo de movimiento es bueno
    mot_med = np.median(motion_a) + 1e-6
    excess = np.clip((motion_a - 3 * mot_med) / (6 * mot_med), 0, 1)

    # Score final por muestra (0..100)
    score = (0.6 * sharp_norm + 0.4 * bright_norm - 0.25 * excess)
    # Suavizar para evitar saltos de un solo frame
    k = 3
    kernel = np.ones(k) / k
    score = np.convolve(score, kernel, mode="same")
    score = np.clip(score, 0, 1) * 100.0

    segs = _extract_segments(info, source_index, np.array(times), score, scene_cuts, max_clip)
    for s in segs:
        s.local_score = s.score
    return segs


def _extract_segments(
    info: VideoInfo,
    source_index: int,
    times: np.ndarray,
    score: np.ndarray,
    scene_cuts: set[int],
    max_clip: float = MAX_CLIP,
) -> list[Segment]:
    """Extrae tramos contiguos por encima del umbral, sin cruzar cortes de escena,
    recortando a <= max_clip y quedandose con la mejor ventana interna."""
    n = len(times)
    # Umbral dinamico: por encima de la mediana y de un piso absoluto
    thr = max(float(np.percentile(score, 55)), 35.0)
    good = score >= thr

    segments: list[Segment] = []
    i = 0
    while i < n:
        if not good[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and good[j + 1] and (j + 1) not in scene_cuts:
            j += 1
        start_t = float(times[i])
        end_t = float(times[j]) + (1.0 / SAMPLES_PER_SEC)
        seg_score = float(score[i:j + 1].mean())
        _split_and_add(info, source_index, times, score, i, j, start_t, end_t, segments, max_clip)
        i = j + 1

    return segments


def _apply_margins(s: float, e: float, total: float) -> tuple[float, float]:
    """Recorta los bordes para no mostrar frames de la escena vecina."""
    e = min(e, total)
    s2 = s + START_MARGIN
    e2 = e - END_MARGIN
    if e2 - s2 >= MIN_CLIP:
        return s2, e2
    # Tramo corto: prioriza recortar el inicio (que es donde se ve el mal corte)
    s2 = s + min(START_MARGIN, max(0.0, (e - s) - MIN_CLIP))
    return s2, e


def _split_and_add(info, source_index, times, score, i, j, start_t, end_t, out,
                   max_clip: float = MAX_CLIP):
    """Emite un segmento (<= max_clip) con bordes limpios (margenes de seguridad)."""
    dur = end_t - start_t
    if dur < MIN_CLIP + START_MARGIN:
        return
    if dur <= max_clip:
        s, e, sc = start_t, min(end_t, info.duration), float(score[i:j + 1].mean())
    else:
        # Ventana deslizante para el mejor bloque de max_clip dentro del tramo largo
        win = max(1, int(max_clip * SAMPLES_PER_SEC))
        best_k, best_val = i, -1.0
        for k in range(i, max(i + 1, j - win + 2)):
            val = float(score[k:k + win].mean())
            if val > best_val:
                best_val, best_k = val, k
        s, e, sc = float(times[best_k]), min(float(times[best_k]) + max_clip, info.duration), best_val

    s, e = _apply_margins(s, e, info.duration)
    if e - s < MIN_CLIP:
        return
    out.append(Segment(info.path, source_index, round(s, 2), round(e, 2), round(sc, 1)))
