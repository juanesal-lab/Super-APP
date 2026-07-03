"""Ensamblado con FFmpeg: recorte al formato elegido, clips, video final y versiones.

Soporta varios formatos de salida (1:1 landing, 9:16 Reels/TikTok, 4:5 feed).
Cada clip se escala para CUBRIR el encuadre y se recorta al centro, luego se
normaliza a un tamano/fps/codec comun para concatenar sin glitches.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor

from .analyze import Segment
from .ffmpeg_utils import run

FPS = 30
_CPU = os.cpu_count() or 4
_SFX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets", "sfx")


def list_sfx() -> list[str]:
    """Efectos de transición disponibles. El usuario puede poner los suyos en assets/sfx/."""
    if not os.path.isdir(_SFX_DIR):
        return []
    out = [os.path.join(_SFX_DIR, f) for f in sorted(os.listdir(_SFX_DIR))
           if f.lower().endswith((".wav", ".mp3", ".m4a", ".aac", ".ogg"))]
    return out


def _gpu_available() -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=20).stdout
        return "h264_videotoolbox" in out
    except Exception:
        return False


GPU = _gpu_available()
# La GPU (VideoToolbox) admite pocas sesiones a la vez; en CPU paralelizamos mas
WORKERS = 3 if GPU else min(8, max(2, _CPU - 2))


def venc() -> list[str]:
    """Codec de video: GPU (VideoToolbox) si esta disponible, si no libx264."""
    if GPU:
        return ["-c:v", "h264_videotoolbox", "-profile:v", "high", "-b:v", "12M"]
    return ["-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "20"]

# Formatos soportados -> (ancho, alto) de trabajo
ASPECTS = {
    "1:1": (1080, 1080),    # landing page
    "9:16": (1080, 1920),   # Reels / TikTok / Stories
    "4:5": (1080, 1350),    # feed vertical Meta
    "16:9": (1920, 1080),   # horizontal
}
DEFAULT_ASPECT = "1:1"

# Cadena de mejora de calidad: limpia ruido/compresion, afina y da un toque de color
ENHANCE_CHAIN = "hqdn3d=1.5:1.5:6:6,unsharp=5:5:0.9:5:5:0.0,eq=contrast=1.04:saturation=1.07"


def dims_for(aspect: str) -> tuple[int, int]:
    return ASPECTS.get(aspect, ASPECTS[DEFAULT_ASPECT])


def _fill_filter(dims: tuple[int, int], enhance: bool = False, fx: bool = False) -> str:
    """Escala para CUBRIR el encuadre y recorta al centro (look nativo de Reels).
    enhance=True agrega limpieza+nitidez+color. fx=True agrega un punch-in zoom."""
    w, h = dims
    chain = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={w}:{h},setsar=1,fps={FPS}"
    )
    if enhance:
        chain += "," + ENHANCE_CHAIN
    if fx:
        chain += (
            f",zoompan=z='min(zoom+0.0012,1.12)':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS}"
        )
    return chain


def render_clip(seg: Segment, out_path: str, dims: tuple[int, int],
                has_audio: bool = True, enhance: bool = False, fx: bool = False) -> str:
    """Renderiza un segmento como clip independiente en el formato pedido."""
    dur = max(0.1, seg.end - seg.start)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{seg.start:.3f}", "-i", seg.video, "-t", f"{dur:.3f}",
        "-vf", _fill_filter(dims, enhance, fx),
        *venc(),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    ]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += [out_path]
    run(cmd)
    return out_path


def _normalized_clip(seg: Segment, out_path: str, dims: tuple[int, int],
                     enhance: bool = False, fx: bool = False) -> str:
    """Clip normalizado SIEMPRE con pista de audio (silencio si la fuente no tiene),
    para que el concat no falle al mezclar clips con y sin audio."""
    dur = max(0.1, seg.end - seg.start)
    cmd_real = [
        "ffmpeg", "-y",
        "-ss", f"{seg.start:.3f}", "-i", seg.video, "-t", f"{dur:.3f}",
        "-vf", _fill_filter(dims, enhance, fx),
        *venc(), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-map", "0:v:0", "-map", "0:a:0?",
        out_path,
    ]
    cmd_silent = [
        "ffmpeg", "-y",
        "-ss", f"{seg.start:.3f}", "-i", seg.video, "-t", f"{dur:.3f}",
        "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", _fill_filter(dims, enhance, fx),
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
        *venc(), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        out_path,
    ]
    try:
        run(cmd_real)
    except Exception:
        run(cmd_silent)
    return out_path


def _ensure_audio(path: str, work_dir: str) -> str:
    """Garantiza que el clip tenga pista de audio (agrega silencio si la fuente no tiene).

    Sin esto, un clip de un video FUENTE sin audio se renderiza con `-an` (sin pista) y rompe
    el concat/acrossfade con "[i:a] matches no streams". Devuelve la ruta lista para concatenar."""
    from .ffmpeg_utils import probe
    info = probe(path)
    if info.has_audio:
        return path
    out = os.path.join(work_dir, "_sil_" + os.path.basename(path))
    dur = max(0.4, info.duration)
    run([
        "ffmpeg", "-y", "-i", path,
        "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        out,
    ])
    return out


def concat_clips(clip_paths: list[str], out_path: str, work_dir: str) -> str:
    """Une clips ya normalizados usando el demuxer concat."""
    clip_paths = [_ensure_audio(p, work_dir) for p in clip_paths]
    list_file = os.path.join(work_dir, f"_concat_{os.path.basename(out_path)}.txt")
    with open(list_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
        *venc(),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        out_path,
    ]
    run(cmd)
    try:
        os.remove(list_file)
    except OSError:
        pass
    return out_path


_TRANSITIONS = ["fade", "slideleft", "wipeup", "circleopen", "slideup"]


def concat_clips_xfade(clip_paths: list[str], out_path: str, work_dir: str,
                       d: float = 0.3) -> str:
    """Une clips con TRANSICIONES (xfade en video + acrossfade en audio)."""
    if len(clip_paths) <= 1:
        return concat_clips(clip_paths, out_path, work_dir)

    from .ffmpeg_utils import probe
    # Todos los clips deben tener pista de audio o el acrossfade falla ("[i:a] matches no streams").
    clip_paths = [_ensure_audio(p, work_dir) for p in clip_paths]
    durs = [max(0.4, probe(p).duration) for p in clip_paths]

    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]
    fc = []
    vlast, alast = "[0:v]", "[0:a]"
    acc = durs[0]
    for i in range(1, len(clip_paths)):
        tr = _TRANSITIONS[(i - 1) % len(_TRANSITIONS)]
        off = max(0.1, acc - d)
        vtag, atag = f"[vx{i}]", f"[ax{i}]"
        fc.append(f"{vlast}[{i}:v]xfade=transition={tr}:duration={d}:offset={off:.3f}{vtag}")
        fc.append(f"{alast}[{i}:a]acrossfade=d={d}{atag}")
        vlast, alast = vtag, atag
        acc = acc + durs[i] - d
    run([
        "ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc),
        "-map", vlast, "-map", alast,
        *venc(), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        out_path,
    ])
    return out_path


def plan_variations(selected: list[Segment], target_seconds: float = 15.0
                    ) -> list[tuple[str, list[int]]]:
    """Decide QUÉ clips (indices de `selected`) usa cada versión, SIN renderizar nada.

    Separado de build_variations para poder saber ANTES qué cortes se usan de verdad
    (así el tapado de textos procesa solo esos). Devuelve [(nombre, [indices]), ...]."""
    n = len(selected)
    NV = 8
    names = ["A_gancho", "B_narrativa", "C_corta", "D_dinamica", "E_inversa", "F_express",
             "G_mixta", "H_alterna"]
    cpv = max(4, min(10, round(target_seconds / 2.2)))   # clips por version
    if n == 0:
        return []

    by_score = sorted(range(n), key=lambda i: selected[i].score, reverse=True)

    def order_version(idxs):
        """Estructura de edición PRO estilo TikTok:
        1) HOOK: la toma más fuerte de una (frena el scroll).
        2) CUERPO: nunca dos tomas seguidas del MISMO video (se siente editado, no pegado),
           empezando por las tomas CORTAS (ritmo rápido al inicio, como los ads que retienen).
        3) PAYOFF: cierra con la mejor toma del producto EN USO (el "remate" antes del CTA)."""
        if not idxs:
            return []
        hook = max(idxs, key=lambda i: selected[i].score)
        rest = [i for i in idxs if i != hook]
        # payoff: mejor toma con el producto en uso/visible (si existe) reservada para el cierre
        payoff = None
        uso = [i for i in rest if selected[i].shows_use or selected[i].product_visible]
        if uso and len(rest) >= 2:
            payoff = max(uso, key=lambda i: (selected[i].shows_use, selected[i].score))
            rest.remove(payoff)
        # cuerpo: cortas primero (ritmo) y alternando la fuente (greedy anti-repetición)
        rest.sort(key=lambda i: (selected[i].duration(), -selected[i].score))
        cuerpo, prev_src, pool = [], selected[hook].source_index, rest[:]
        while pool:
            pick = next((i for i in pool if selected[i].source_index != prev_src), pool[0])
            pool.remove(pick)
            cuerpo.append(pick)
            prev_src = selected[pick].source_index
        return [hook] + cuerpo + ([payoff] if payoff is not None else [])

    # DURACIÓN OBJETIVO con colchón: el montaje debe ALCANZAR (o superar) la voz en off. Antes se
    # elegía por NÚMERO de clips (cpv) y con clips cortos el video quedaba en ~10s con voz de ~20s →
    # el loop repetía TODO el montaje 2-4 veces (queja de Juan). Por DURACIÓN esto no pasa jamás.
    need = float(target_seconds) * 1.15 + 1.0

    if n >= NV * 3:
        # POOL GRANDE: cada version usa clips DISJUNTOS (de videos distintos) -> máxima diversidad
        buckets = [[] for _ in range(NV)]
        for rank, i in enumerate(by_score):
            buckets[rank % NV].append(i)
        usados: set[int] = set()
        version_orders = []
        for vi in range(NV):
            sel, dur = [], 0.0
            for i in buckets[vi]:                      # primero lo del bucket propio (disjunto)
                if i in usados:
                    continue
                sel.append(i); usados.add(i); dur += selected[i].duration()
                if dur >= need:
                    break
            if dur < need:                             # si no alcanza, completa con clips NO usados
                for i in by_score:
                    if i in usados:
                        continue
                    sel.append(i); usados.add(i); dur += selected[i].duration()
                    if dur >= need:
                        break
            if dur < need:                             # pool AGOTADO: se permite reusar clips de OTRAS
                for i in by_score:                     # versiones — NUNCA dentro de la misma versión
                    if i in sel:
                        continue
                    sel.append(i); dur += selected[i].duration()
                    if dur >= need:
                        break
            version_orders.append((names[vi], order_version(sel)))
    else:
        # POCOS CLIPS: (1) el GANCHO (primer clip) ROTA entre los mejores por score -> cada versión
        # abre distinto; (2) el resto se elige priorizando los clips MENOS USADOS por las versiones
        # anteriores -> los CONJUNTOS se solapan lo mínimo posible con un pool chico.
        k_hooks = min(NV, n)
        usage = {i: 0 for i in range(n)}
        version_orders = []
        for vi in range(NV):
            hook = by_score[vi % k_hooks]
            pool = [i for i in range(n) if i != hook]
            pool.sort(key=lambda i: (usage[i], -selected[i].score,
                                     selected[i].source_index, selected[i].start))
            take, dur = [], selected[hook].duration()
            for i in pool:                             # por DURACIÓN, no por número fijo
                if dur >= need:
                    break
                take.append(i); dur += selected[i].duration()
            rest = sorted(take, key=lambda i: (selected[i].source_index, selected[i].start))
            order = [hook] + rest
            for i in order:
                usage[i] += 1
            version_orders.append((names[vi], order))
    return version_orders


def build_variations(selected: list[Segment], work_dir: str,
                     dims: tuple[int, int], enhance: bool = False,
                     fx: bool = False, target_seconds: float = 15.0,
                     version_orders: list[tuple[str, list[int]]] | None = None) -> dict:
    """Crea clips normalizados y arma varias versiones (montajes) del video final.

    `version_orders` (opcional) permite pasar un plan ya calculado con plan_variations
    (los indices refieren a `selected`). Devuelve dict con: clips[], versions[].
    """
    os.makedirs(work_dir, exist_ok=True)
    if version_orders is None:
        version_orders = plan_variations(selected, target_seconds=target_seconds)

    # Renderizar SOLO los clips que de verdad se usan (no todo el pool) -> más rápido
    used_idx = sorted({i for _, order in version_orders for i in order})
    norm_paths: dict[int, str] = {}

    def _mk(i):
        p = os.path.join(work_dir, f"clip_{i:02d}.mp4")
        _normalized_clip(selected[i], p, dims, enhance, fx)
        return i, p

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, p in ex.map(_mk, used_idx):
            norm_paths[i] = p

    out_versions = []
    for name, order in version_orders:
        clip_list = [norm_paths[i] for i in order if i in norm_paths]
        if not clip_list:
            continue
        out_path = os.path.join(work_dir, f"version_{name}.mp4")
        if fx:
            concat_clips_xfade(clip_list, out_path, work_dir)
        else:
            concat_clips(clip_list, out_path, work_dir)
        out_versions.append({
            "name": name,
            "path": out_path,
            "segments": [selected[i].to_dict() for i in order],
        })

    return {"clips": list(norm_paths.values()), "versions": out_versions}


def _dur_flag(audio_path: str) -> list[str]:
    """['-t', dur] con la duración REAL del audio (ffprobe soporta audio puro; probe() no)."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", audio_path], capture_output=True, text=True, timeout=15)
        d = float(out.stdout.strip())
        if d > 0.5:
            return ["-t", f"{d:.2f}"]
    except Exception:  # noqa: BLE001
        pass
    return []


def add_voiceover(video_path: str, vo_path: str, out_path: str) -> str:
    """Pone la voz en off como audio (reemplaza el original). La duracion final = la de la voz.

    PROHIBIDO el loop: antes, si la voz era más larga que el video, el video ENTERO se repetía desde
    el inicio (los mismos cortes salían 2-4 veces — queja de Juan). Ahora, si falta video, se sostiene
    el ÚLTIMO frame (tpad clone) los segundos que falten. El montaje además ya se arma por DURACIÓN."""
    vo_dur = _dur_flag(vo_path)   # corte EXACTO al final de la voz
    run([
        "ffmpeg", "-y", "-i", video_path, "-i", vo_path,
        "-vf", "tpad=stop_mode=clone:stop_duration=60",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest", *vo_dur,
        *venc(),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ])
    return out_path


def blur_caption(in_path: str, out_path: str, position: str = "abajo") -> str:
    """Tapa con desenfoque una franja del video (donde el proveedor puso textos/captions).
    position: 'abajo' | 'arriba' | 'ambos'."""
    bands = []  # (y_frac, h_frac)
    if position in ("abajo", "ambos"):
        bands.append((0.80, 0.20))
    if position in ("arriba", "ambos"):
        bands.append((0.0, 0.16))
    if not bands:
        return in_path

    splits = len(bands) + 1
    fc = [f"[0:v]split={splits}[base]" + "".join(f"[c{i}]" for i in range(len(bands)))]
    for i, (yf, hf) in enumerate(bands):
        fc.append(f"[c{i}]crop=iw:ih*{hf}:0:ih*{yf},boxblur=24:4[b{i}]")
    last = "[base]"
    for i, (yf, hf) in enumerate(bands):
        tag = "[v]" if i == len(bands) - 1 else f"[t{i}]"
        fc.append(f"{last}[b{i}]overlay=0:main_h*{yf}{tag}")
        last = f"[t{i}]"
    run([
        "ffmpeg", "-y", "-i", in_path,
        "-filter_complex", ";".join(fc),
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "copy",
        out_path,
    ])
    return out_path


def blur_boxes(in_path: str, out_path: str, boxes: list[dict]) -> str:
    """Tapa con desenfoque cajas especificas {x,y,w,h} (fracciones) del frame."""
    boxes = [b for b in (boxes or []) if b.get("w", 0) > 0 and b.get("h", 0) > 0][:6]
    if not boxes:
        return in_path
    n = len(boxes)
    fc = [f"[0:v]split={n + 1}[base]" + "".join(f"[c{i}]" for i in range(n))]
    for i, b in enumerate(boxes):
        fc.append(
            f"[c{i}]crop=iw*{b['w']:.4f}:ih*{b['h']:.4f}:iw*{b['x']:.4f}:ih*{b['y']:.4f},"
            f"boxblur=26:5[bb{i}]")
    last = "[base]"
    for i, b in enumerate(boxes):
        tag = "[v]" if i == n - 1 else f"[t{i}]"
        fc.append(f"{last}[bb{i}]overlay=main_w*{b['x']:.4f}:main_h*{b['y']:.4f}{tag}")
        last = f"[t{i}]"
    run([
        "ffmpeg", "-y", "-i", in_path, "-filter_complex", ";".join(fc),
        "-map", "[v]", "-map", "0:a?",
        *venc(), "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "copy",
        out_path,
    ])
    return out_path


def blur_boxes_timed(in_path: str, out_path: str, timed_boxes: list[dict],
                     window: float = 0.9) -> str:
    """Tapa cada caja {x,y,w,h,t} SOLO durante [t-window, t+window] (sigue el caption)."""
    boxes = [b for b in (timed_boxes or []) if b.get("w", 0) > 0 and b.get("h", 0) > 0][:24]
    if not boxes:
        return in_path
    n = len(boxes)
    fc = [f"[0:v]split={n + 1}[base]" + "".join(f"[c{i}]" for i in range(n))]
    for i, b in enumerate(boxes):
        fc.append(
            f"[c{i}]crop=iw*{b['w']:.4f}:ih*{b['h']:.4f}:iw*{b['x']:.4f}:ih*{b['y']:.4f},"
            f"boxblur=28:6[bb{i}]")
    last = "[base]"
    for i, b in enumerate(boxes):
        t0 = max(0.0, float(b.get("t", 0)) - window)
        t1 = float(b.get("t", 0)) + window
        tag = "[v]" if i == n - 1 else f"[t{i}]"
        fc.append(f"{last}[bb{i}]overlay=main_w*{b['x']:.4f}:main_h*{b['y']:.4f}:"
                  f"enable='between(t,{t0:.2f},{t1:.2f})'{tag}")
        last = f"[t{i}]"
    run([
        "ffmpeg", "-y", "-i", in_path, "-filter_complex", ";".join(fc),
        "-map", "[v]", "-map", "0:a?",
        *venc(), "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "copy",
        out_path,
    ])
    return out_path


def _has_audio_stream(path: str) -> bool:
    try:
        import subprocess as _sp
        r = _sp.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                     "stream=index", "-of", "csv=p=0", path],
                    capture_output=True, text=True, timeout=20)
        return bool((r.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return False


def add_music_sfx(video_path: str, out_path: str, music_path: str | None = None,
                  sfx_paths: list[str] | None = None, cut_times: list[float] | None = None) -> str:
    """MÚSICA de fondo (baja) + SFX en cada corte, CONSERVANDO el audio del clip (para Cortar clips
    sin voz en off). Varía el SFX por corte (rota la librería). Devuelve la ruta o el original si no aplica."""
    sfx_paths = [p for p in (sfx_paths or []) if p and os.path.exists(p)]
    cut_times = [t for t in (cut_times or []) if t > 0.2][:10]
    has_music = bool(music_path and os.path.exists(music_path))
    has_sfx = bool(sfx_paths and cut_times)
    if not has_music and not has_sfx:
        return video_path
    from .ffmpeg_utils import probe
    try:
        vdur = probe(video_path).duration
    except Exception:  # noqa: BLE001
        return video_path
    inputs = ["-i", video_path]
    fc, mix, idx = [], [], 1
    if _has_audio_stream(video_path):
        fc.append("[0:a]volume=1.0[clip]"); mix.append("[clip]")
    if has_music:
        inputs += ["-stream_loop", "-1", "-i", music_path]
        fc.append(f"[{idx}:a]volume=0.20[mus]"); mix.append("[mus]"); idx += 1
    if has_sfx:
        import random as _rnd
        seq = sfx_paths[:]; _rnd.shuffle(seq)   # variar los SFX (no siempre el mismo)
        for k, t in enumerate(cut_times):
            inputs += ["-i", seq[k % len(seq)]]
            ms = int(t * 1000)
            fc.append(f"[{idx}:a]adelay={ms}|{ms},volume=0.85[sf{k}]"); mix.append(f"[sf{k}]"); idx += 1
    if not mix:
        return video_path
    fc.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0,dynaudnorm=f=200[a]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "0:v:0", "-map", "[a]",
         "-t", f"{vdur:.2f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         out_path])
    return out_path


def punch_pace(video_path: str, out_path: str, target_max: float = 22.0,
               max_speed: float = 1.35) -> str:
    """Acelera un pelín (video + audio EN SYNC) si el creativo dura más que target_max, para un
    pacing 'punchy' tipo TikTok ganador (retiene más). Tope max_speed para que la voz no suene
    atropellada. Debe correr AL FINAL (con todo ya quemado) para que subtítulos/audio queden en sync.
    Devuelve out_path o el original si no aplica."""
    from .ffmpeg_utils import probe
    try:
        dur = probe(video_path).duration
    except Exception:  # noqa: BLE001
        return video_path
    if dur <= target_max + 0.5:
        return video_path
    speed = min(max_speed, dur / target_max)
    if speed <= 1.03:
        return video_path
    try:
        if _has_audio_stream(video_path):
            run(["ffmpeg", "-y", "-i", video_path,
                 "-filter_complex", f"[0:v]setpts=PTS/{speed:.4f}[v];[0:a]atempo={speed:.4f}[a]",
                 "-map", "[v]", "-map", "[a]", *venc(), "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", out_path])
        else:
            run(["ffmpeg", "-y", "-i", video_path, "-filter:v", f"setpts=PTS/{speed:.4f}",
                 *venc(), "-movflags", "+faststart", out_path])
        return out_path
    except Exception:  # noqa: BLE001
        return video_path


def add_voiceover_and_sfx(video_path: str, vo_path: str, out_path: str,
                          sfx_paths: list[str] | None = None,
                          cut_times: list[float] | None = None,
                          music_path: str | None = None) -> str:
    """Voz en off + efectos REALES en transiciones (alternados) + musica de fondo."""
    cut_times = [t for t in (cut_times or []) if t > 0.2][:8]
    sfx_paths = [p for p in (sfx_paths or []) if p and os.path.exists(p)]
    has_sfx = bool(sfx_paths and cut_times)
    has_music = bool(music_path and os.path.exists(music_path))
    if not has_sfx and not has_music:
        return add_voiceover(video_path, vo_path, out_path)

    # SIN loop de video: si la voz es más larga, se sostiene el último frame (tpad clone).
    # (El loop repetía TODO el montaje desde el inicio → cortes duplicados. Queja de Juan.)
    inputs = ["-i", video_path, "-i", vo_path]
    fc = ["[0:v]tpad=stop_mode=clone:stop_duration=60[v]", "[1:a]volume=1.0[vo]"]
    mix_labels = ["[vo]"]
    idx = 2

    if has_sfx:
        # asignar un efecto a cada transición: BARAJADOS por render (variedad — queja de Juan:
        # "no siempre el mismo efecto"), y nunca el mismo dos veces seguidas.
        import random as _rnd
        seq = sfx_paths[:]
        _rnd.shuffle(seq)
        assign = [seq[i % len(seq)] for i in range(len(cut_times))]
        in_index = {}
        for p in assign:
            if p not in in_index:
                inputs += ["-i", p]
                in_index[p] = idx
                idx += 1
        from collections import Counter
        counts = Counter(assign)
        for p, ii in in_index.items():
            fc.append(f"[{ii}:a]asplit={counts[p]}" + "".join(f"[s{ii}_{k}]" for k in range(counts[p])))
        ptr = {p: 0 for p in in_index}
        for i, (t, p) in enumerate(zip(cut_times, assign)):
            ii = in_index[p]; k = ptr[p]; ptr[p] += 1
            ms = int(t * 1000)
            fc.append(f"[s{ii}_{k}]adelay={ms}|{ms},volume=0.8[w{i}]")
            mix_labels.append(f"[w{i}]")

    if has_music:
        inputs += ["-i", music_path]
        m_idx = idx; idx += 1
        fc.append(f"[{m_idx}:a]aloop=loop=-1:size=2000000000,volume=0.16[mus]")
        mix_labels.append("[mus]")

    fc.append("".join(mix_labels) + f"amix=inputs={len(mix_labels)}:normalize=0:duration=first[a]")
    vo_dur = _dur_flag(vo_path)   # corte EXACTO al final de la voz
    run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(fc),
        "-map", "[v]", "-map", "[a]", "-shortest", *vo_dur,
        *venc(),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ])
    return out_path


def export_resolution(src_path: str, out_path: str, width: int) -> str:
    """Re-escala un montaje al ancho pedido para descarga, conservando el formato.
    Recipe de maxima compatibilidad (QuickTime/Apple/Meta/TikTok): H.264 High,
    yuv420p, faststart (moov al inicio) y AAC. Escribe a .tmp y renombra (atomico)."""
    tmp = out_path + f".{uuid.uuid4().hex[:8]}.tmp.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", src_path,
        "-vf", f"scale={width}:-2:flags=lanczos,setsar=1,format=yuv420p",
        "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "19",
        "-movflags", "+faststart",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        tmp,
    ]
    run(cmd)
    os.replace(tmp, out_path)  # renombrado atomico: nunca se sirve un archivo a medias
    return out_path
