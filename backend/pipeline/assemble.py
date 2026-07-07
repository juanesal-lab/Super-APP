"""Ensamblado con FFmpeg: recorte al formato elegido, clips, video final y versiones.

Soporta varios formatos de salida (1:1 landing, 9:16 Reels/TikTok, 4:5 feed).
Cada clip se escala para CUBRIR el encuadre y se recorta al centro, luego se
normaliza a un tamano/fps/codec comun para concatenar sin glitches.
"""
from __future__ import annotations

import math
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
DEFAULT_ASPECT = "9:16"

# Cadena de mejora de calidad: limpia ruido/compresion, afina y da un toque de color
ENHANCE_CHAIN = "hqdn3d=1.5:1.5:6:6,unsharp=5:5:0.9:5:5:0.0,eq=contrast=1.04:saturation=1.07"


def dims_for(aspect: str) -> tuple[int, int]:
    return ASPECTS.get(aspect, ASPECTS[DEFAULT_ASPECT])


# Movimiento por plano (medido en 4 ads ganadores reales): NADA queda 100% estático.
# (tasa de zoom por segundo, tope de escala, dirección). El punch (15-23%/s) es el acento
# del plano del producto; el resto es Ken Burns sutil 1.5-3%/s alternando in/out.
_MOTION = {
    "in_suave": (0.020, 1.30, "in"),
    "in_fuerte": (0.060, 1.30, "in"),
    "punch": (0.180, 1.22, "in"),
    "punch_hook": (0.300, 1.15, "in"),   # gancho: 1.0→1.15 en los primeros 0.5s y SOSTIENE
    "out": (0.025, 1.06, "out"),
    "out_lento": (0.030, 1.12, "out"),   # zoom-out lento: arranca en 1.12 y baja hacia 1.0
}


def _motion_chain(motion: str | None, dims: tuple[int, int]) -> str:
    """Ken Burns/punch con zoompan ESTATELESS (zoom en función del nº de frame 'on', no del
    estado previo). OJO: crop NO sirve aquí — sus w/h se evalúan UNA vez, no animan."""
    if not motion or motion not in _MOTION:
        return ""
    w, h = dims
    r, cap, kind = _MOTION[motion]
    rf = r / FPS                                     # tasa por frame
    if kind == "in":
        z = f"min(1+{rf:.6f}*on\\,{cap})"
    else:
        z = f"max({cap}-{rf:.6f}*on\\,1.0)"
    return (f",zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={w}x{h}:fps={FPS}")


def _fill_filter(dims: tuple[int, int], enhance: bool = False, fx: bool = False,
                 motion: str | None = None) -> str:
    """Escala para CUBRIR el encuadre y recorta al centro (look nativo de Reels).
    enhance=True agrega limpieza+nitidez+color. motion agrega Ken Burns/punch por plano
    (fx=True sin motion explícito equivale al Ken Burns suave de antes)."""
    w, h = dims
    chain = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={w}:{h},setsar=1,fps={FPS}"
    )
    if enhance:
        chain += "," + ENHANCE_CHAIN
    if motion is None and fx:
        motion = "in_suave"
    chain += _motion_chain(motion, dims)
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
                     enhance: bool = False, fx: bool = False,
                     motion: str | None = None, max_dur: float | None = None) -> str:
    """Clip normalizado SIEMPRE con pista de audio (silencio si la fuente no tiene),
    para que el concat no falle al mezclar clips con y sin audio.
    max_dur recorta el plano al tope de su slot (curva de ritmo pro: ningún plano >2.2s)."""
    dur = max(0.1, seg.end - seg.start)
    if max_dur:
        dur = min(dur, max_dur)
    cmd_real = [
        "ffmpeg", "-y",
        "-ss", f"{seg.start:.3f}", "-i", seg.video, "-t", f"{dur:.3f}",
        "-vf", _fill_filter(dims, enhance, fx, motion),
        *venc(), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-map", "0:v:0", "-map", "0:a:0?",
        out_path,
    ]
    cmd_silent = [
        "ffmpeg", "-y",
        "-ss", f"{seg.start:.3f}", "-i", seg.video, "-t", f"{dur:.3f}",
        "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", _fill_filter(dims, enhance, fx, motion),
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


# Medido en 4 ads ganadores reales: el 70-85% de las transiciones son DISSOLVES de 4-6 frames
# (0.13-0.20s) — el pegamento que unifica clips de cámaras/luces distintas — y solo 1 de cada
# ~5 es corte (casi) duro, reservado al plano de impacto. CERO slides/wipes/circles (PowerPoint).
_XFADE_D = 0.17          # dissolve estándar (5 frames a 30fps)
_XFADE_D_HARD = 0.034    # "corte duro" (1 frame de mezcla: evita el salto entre fuentes)


def _video_stream_dur(path: str) -> float:
    """Duración del STREAM de video (no del contenedor: el contenedor toma el máximo de
    video/audio y esconde streams de video cortos — causa real de un congelón de 24s)."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v",
                              "-show_entries", "stream=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=20)
        return float((out.stdout or "").strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return 0.0


def concat_clips_xfade(clip_paths: list[str], out_path: str, work_dir: str,
                       d: float = _XFADE_D,
                       cut_times_out: list[float] | None = None,
                       hard_shift: int = 0) -> str:
    """Une clips estilo ads ganadores: dissolve corto por defecto + corte duro selectivo
    (1 de cada ~5 y en la entrada del último plano = el payoff/impacto).
    Si `cut_times_out` es una lista, deja ahí los tiempos reales de cada transición.

    BLINDAJE (bug real 2026-07-04: el stream de video de un clip terminaba antes que su audio
    → la cadena xfade se SECABA a mitad del montaje → tpad clonaba el último frame 24s):
    - los offsets se calculan con la duración del STREAM DE VIDEO real (no del contenedor);
    - cada rama de video lleva un colchón tpad (si a un clip le faltan frames, sostiene su
      último frame ese instante en vez de matar la cadena entera);
    - el audio de cada clip se recorta a su video (atrim) y el render se limita a la duración
      planeada (-t) para que el colchón no alargue el final."""
    if len(clip_paths) <= 1:
        return concat_clips(clip_paths, out_path, work_dir)

    from .ffmpeg_utils import probe
    # Todos los clips deben tener pista de audio o el acrossfade falla ("[i:a] matches no streams").
    clip_paths = [_ensure_audio(p, work_dir) for p in clip_paths]
    durs = []
    for p in clip_paths:
        dv = _video_stream_dur(p)
        if dv <= 0.05:
            dv = probe(p).duration
        durs.append(max(0.4, dv))

    n_b = len(clip_paths) - 1
    # payoff + 1 de cada ~5 (hard_shift mueve el patrón al regenerar "otra edición")
    hard = {n_b - 1} | {i for i in range(n_b) if i % 5 == (2 + hard_shift) % 5}

    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]
    fc = []
    for i, dv in enumerate(durs):    # colchón de video + audio recortado al video
        fc.append(f"[{i}:v]tpad=stop_mode=clone:stop_duration=3[vp{i}]")
        fc.append(f"[{i}:a]atrim=0:{dv:.3f}[at{i}]")
    vlast, alast = "[vp0]", "[at0]"
    acc = durs[0]
    for i in range(1, len(clip_paths)):
        dd = _XFADE_D_HARD if (i - 1) in hard else d
        off = max(0.1, acc - dd)
        if cut_times_out is not None:
            cut_times_out.append(round(off + dd / 2, 3))
        vtag, atag = f"[vx{i}]", f"[ax{i}]"
        fc.append(f"{vlast}[vp{i}]xfade=transition=fade:duration={dd}:offset={off:.3f}{vtag}")
        fc.append(f"{alast}[at{i}]acrossfade=d={dd}{atag}")
        vlast, alast = vtag, atag
        acc = acc + durs[i] - dd
    run([
        "ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc),
        "-map", vlast, "-map", alast, "-t", f"{acc:.3f}",
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

    def _fase_arco(i):
        """Fase narrativa del clip para el ARCO de ecommerce que convierte:
        0 = problema (ni producto ni uso) → 1 = solución/uso (shows_use) → 2 = producto."""
        if selected[i].shows_use:
            return 1
        if selected[i].product_visible:
            return 2
        return 0

    def order_version(idxs):
        """Estructura de edición PRO estilo TikTok:
        1) HOOK: la toma más fuerte de una (frena el scroll).
        2) ARCO NARRATIVO (si los flags de Gemini distinguen fases): problema → solución/uso
           → producto, cronológico DENTRO de cada fase — la historia que convierte en ecommerce.
        3) Fallback (todos los clips de la misma fase, p. ej. sin Gemini): cuerpo anti-repetición
           de fuente + payoff con la mejor toma del producto EN USO (comportamiento de siempre)."""
        if not idxs:
            return []
        hook = max(idxs, key=lambda i: selected[i].score)
        rest = [i for i in idxs if i != hook]
        # ARCO problema→solución→producto cuando hay al menos 2 fases distintas en el cuerpo
        if len({_fase_arco(i) for i in rest}) >= 2:
            return [hook] + sorted(rest, key=lambda i: (_fase_arco(i),
                                                        selected[i].source_index,
                                                        selected[i].start))
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
                sel.append(i); usados.add(i); dur += min(selected[i].duration(), 1.7)
                if dur >= need:
                    break
            if dur < need:                             # si no alcanza, completa con clips NO usados
                for i in by_score:
                    if i in usados:
                        continue
                    sel.append(i); usados.add(i); dur += min(selected[i].duration(), 1.7)
                    if dur >= need:
                        break
            if dur < need:                             # pool AGOTADO: se permite reusar clips de OTRAS
                for i in by_score:                     # versiones — NUNCA dentro de la misma versión
                    if i in sel:
                        continue
                    sel.append(i); dur += min(selected[i].duration(), 1.7)
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
            take, dur = [], min(selected[hook].duration(), 1.6)
            for i in pool:                             # por DURACIÓN, no por número fijo
                if dur >= need:
                    break
                take.append(i); dur += min(selected[i].duration(), 1.7)
            # ARCO narrativo problema→solución/uso→producto, cronológico DENTRO de cada fase.
            # Con una sola fase (p. ej. sin Gemini todos son "problema") la clave de fase es
            # constante → queda el cronológico de siempre (comportamiento viejo intacto).
            rest = sorted(take, key=lambda i: (_fase_arco(i),
                                               selected[i].source_index, selected[i].start))
            order = [hook] + rest
            for i in order:
                usage[i] += 1
            version_orders.append((names[vi], order))
    return version_orders


def build_variations(selected: list[Segment], work_dir: str,
                     dims: tuple[int, int], enhance: bool = False,
                     fx: bool = False, target_seconds: float = 15.0,
                     version_orders: list[tuple[str, list[int]]] | None = None,
                     version_caps: dict[str, list[float]] | None = None,
                     seed: int = 0) -> dict:
    """Crea clips normalizados y arma varias versiones (montajes) del video final.

    `version_orders` (opcional) permite pasar un plan ya calculado con plan_variations
    (los indices refieren a `selected`). `version_caps` (opcional, por nombre de versión)
    fija la duración de CADA slot — es el montaje guiado por guion (guion_match): la
    duración viene de las frases de la voz. Devuelve dict con: clips[], versions[].
    """
    os.makedirs(work_dir, exist_ok=True)
    if version_orders is None:
        version_orders = plan_variations(selected, target_seconds=target_seconds)
    version_caps = version_caps or {}

    # CURVA DE RITMO PRO (medida en 4 ads ganadores): ancla ≤1.6s → ráfaga 0.9s → crucero ≤1.7s
    # → cierre/CTA calmado ≤2.2s. Movimiento ALTERNADO POR POSICIÓN (técnica CapCut 2026):
    # gancho = punch-in rápido y notorio (1.0→1.15 en 0.5s, sostiene); slots pares = zoom-in
    # lento; impares = zoom-out lento (1.12→1.0); payoff = punch (con fx). Antes todos los
    # clips llevaban el mismo zoompan lento y el montaje se sentía plano.
    # Con guion (caps): la DURACIÓN la mandan las frases de la voz; el movimiento sigue la curva.
    def _slot_plan(order: list[int], caps: list[float] | None) -> list[tuple[int, float, str]]:
        n = len(order)
        n_b = n - 1
        hard = {n_b - 1} | {k for k in range(n_b) if k % 5 == (2 + seed) % 5}   # espejo del concat
        # alternado por POSICIÓN (técnica CapCut: pares zoom-in, impares zoom-out) y el
        # `seed` de Juan lo ROTA al regenerar una versión suelta (otro look, mismo montaje)
        ciclo = ("in_suave", "out_lento", "in_suave", "out")
        plan = []
        for slot, i in enumerate(order):
            alt = ciclo[(slot + seed) % len(ciclo)]
            if slot == 0:
                cap, motion = 1.6, ("punch_hook" if fx else "in_suave")
            elif slot <= 2 and n >= 6:
                cap, motion = 0.9, alt                 # ráfaga del hook (planos cortos)
            elif slot == n - 1:
                cap, motion = 2.2, ("punch" if fx else "in_suave")   # payoff = acento
            elif slot >= n - 3:
                cap, motion = 2.2, alt                 # CTA calmado: que la oferta se lea
            else:
                cap, motion = 1.7, alt
            if caps and slot < len(caps):
                # el guion manda la duración + compensación del overlap del dissolve
                # (xfade CONSUME dd por transición; sin esto la voz se desincroniza del plano)
                cap = caps[slot]
                if slot < n - 1:
                    cap += _XFADE_D_HARD if slot in hard else _XFADE_D
            plan.append((i, round(cap, 3), motion))
        return plan

    # Renderizar SOLO las combinaciones (clip, tope, movimiento) que de verdad se usan;
    # el dict dedup evita renderizar dos veces la misma combinación entre versiones.
    slot_plans = {name: _slot_plan(order, version_caps.get(name)) for name, order in version_orders}
    combos = sorted({c for plan in slot_plans.values() for c in plan})
    norm_paths: dict[tuple, str] = {}

    def _mk(combo):
        i, cap, motion = combo
        p = os.path.join(work_dir, f"clip_{i:02d}_{int(cap * 1000):04d}_{motion}.mp4")
        _normalized_clip(selected[i], p, dims, enhance, fx, motion=motion, max_dur=cap)
        return combo, p

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for combo, p in ex.map(_mk, combos):
            norm_paths[combo] = p

    out_versions = []
    for name, order in version_orders:
        clip_list = [norm_paths[c] for c in slot_plans[name] if c in norm_paths]
        if not clip_list:
            continue
        out_path = os.path.join(work_dir, f"version_{name}.mp4")
        # SIEMPRE dissolve corto (el pegamento pro del mashup) — antes solo con fx, y con
        # transiciones tipo PowerPoint que se veían amateur.
        cuts: list[float] = []
        concat_clips_xfade(clip_list, out_path, work_dir, cut_times_out=cuts, hard_shift=seed)
        # VERIFICACIÓN anti-congelón: si el stream de video murió antes que el audio (cadena
        # xfade seca), se reconstruye con cortes duros (demuxer, robusto) — jamás entregar un
        # montaje que congele media pantalla.
        try:
            from .ffmpeg_utils import probe as _probe
            if _video_stream_dur(out_path) + 0.5 < _probe(out_path).duration:
                concat_clips(clip_list, out_path + ".hc.mp4", work_dir)
                os.replace(out_path + ".hc.mp4", out_path)
                cuts, _acc = [], 0.0
                for c in slot_plans[name][:-1]:
                    _acc += min(selected[c[0]].duration(), c[1])
                    cuts.append(round(_acc, 3))
        except Exception:  # noqa: BLE001
            pass
        out_versions.append({
            "name": name,
            "path": out_path,
            "segments": [selected[i].to_dict() for i in order],
            "cut_times": cuts,      # tiempos REALES de transición (para alinear los SFX)
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
        # 48k estéreo SIEMPRE: el mp3 de ElevenLabs viene a 44.1k mono y si esto luego se
        # concatena con clips normalizados (48k), el demuxer concat ralentiza/desafina el audio.
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
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


# ─────────────────────────── SOUND DESIGN CON INTENCIÓN ───────────────────────────
# Reglas del estudio CapCut 2026 + ads ecommerce: cada SFX cae donde la HISTORIA lo pide
# (riser→revelación del producto, cash en el CTA...), no rotado al azar en cada corte.
_SD_MUSIC_VOL = 0.16      # música bajo el sound design: voz 1.0 > SFX 0.4-0.7 > música 0.16


def _sd_sfx(*names: str) -> str | None:
    """Primera ruta existente en assets/sfx/ entre los nombres dados (None si ninguno)."""
    for n in names:
        p = os.path.join(_SFX_DIR, n)
        if os.path.exists(p):
            return p
    return None


def sound_design_events(segments: list[dict], total_dur: float,
                        vo_dur: float | None = None,
                        cut_times: list[float] | None = None
                        ) -> list[tuple[float, str, float]]:
    """Plan de SFX CON INTENCIÓN. Devuelve [(t_inicio_segundos, ruta_sfx, volumen_lineal)].

    Reglas (estudio de técnicas CapCut 2026 + estructura de ads ecommerce):
    1. RISER que TERMINA exactamente en el corte donde entra el PRIMER clip con
       product_visible=True + impact/bass_drop justo EN ese corte (máx 1 riser + 1 golpe).
    2. Whoosh/swoosh ROTADOS (3 variantes) en los demás cortes a volumen moderado (~0.5);
       con más de 6 cortes, solo en cortes alternos (que no sature).
    3. Pop/click suave en t≈0.15s (acompaña el gancho/texto inicial).
    4. cash_register bajito (~0.4) al ARRANCAR el CTA: con voz = últimos ~5.5s de la
       narración (la frase obligatoria "por tu compra hoy..."); sin voz = últimos 4s.
    5. Ding/sparkle suave (máx 1) en el corte de la PRUEBA: primer clip con shows_use=True
       DESPUÉS del clip del producto.
    6. Jerarquía: voz 1.0 > SFX puntuales 0.4-0.7 > música 0.16 — nunca tapar la voz.

    `segments` = v["segments"] (dicts con duration/product_visible/shows_use).
    `cut_times` (opcional) = tiempos REALES de corte; si no viene, se acumulan los
    `duration` de segments (igual que _cut_times del orchestrator)."""
    from .pro_mix import _dur_audio
    events: list[tuple[float, str, float]] = []
    segs = [dict(s or {}) for s in (segments or [])]
    if total_dur <= 1.0:
        return events
    if cut_times is None:
        cut_times, acc = [], 0.0
        for sg in segs[:-1]:
            acc += float(sg.get("duration", 0) or 0)
            cut_times.append(round(acc, 3))
    cut_times = list(cut_times)
    cuts = [t for t in cut_times if 0.3 < t < total_dur - 0.3]
    ocupados: list[float] = []          # cortes ya cubiertos por un acento (sin whoosh encima)

    # 3) pop de arranque con el gancho/texto inicial
    pop = _sd_sfx("pop.wav", "click.wav", "notification_pop.mp3")
    if pop:
        events.append((0.15, pop, 0.5))

    # 1) riser → revelación del producto + impact/bass EN el corte (máximo 1 + 1)
    j = next((k for k, sg in enumerate(segs) if sg.get("product_visible")), None)
    t_prod = None
    if j is not None and 0 < j <= len(cut_times):
        t_prod = float(cut_times[j - 1])
    if t_prod and 0.8 < t_prod < total_dur - 0.4:
        golpe = _sd_sfx("impact.wav", "bass_drop.wav", "boom.wav")
        if golpe:
            events.append((round(t_prod, 3), golpe, 0.7))
        for rname in ("riser.wav", "riser_fast.wav"):   # el riser COMPLETO termina EN el corte
            rp = _sd_sfx(rname)
            rd = _dur_audio(rp) if rp else 0.0
            if rp and 0.3 < rd <= t_prod - 0.05:
                events.append((round(t_prod - rd, 3), rp, 0.55))
                break
        ocupados.append(t_prod)

    # 5) ding/sparkle suave en la PRUEBA (shows_use DESPUÉS del producto, máx 1)
    if j is not None:
        k = next((m for m in range(j + 1, len(segs)) if segs[m].get("shows_use")), None)
        if k is not None and k <= len(cut_times):
            t_uso = float(cut_times[k - 1])
            if 0.5 < t_uso < total_dur - 0.4 and all(abs(t_uso - s) > 0.6 for s in ocupados):
                brillo = _sd_sfx("ding.wav", "sparkle.wav")
                if brillo:
                    events.append((round(t_uso, 3), brillo, 0.45))
                    ocupados.append(t_uso)

    # 4) caja registradora bajita al ARRANCAR el CTA (es una firma, no un golpe)
    t_cta = (vo_dur - 5.5) if vo_dur else (total_dur - 4.0)
    cash = _sd_sfx("cash_register.mp3")
    if cash and 1.0 < t_cta < total_dur - 0.5:
        events.append((round(t_cta, 3), cash, 0.4))
        ocupados.append(t_cta)

    # 2) whoosh/swoosh rotados en los DEMÁS cortes (alternos si hay más de 6 cortes)
    whooshes = [p for p in (_sd_sfx("whoosh.wav"), _sd_sfx("whoosh_fast.wav"),
                            _sd_sfx("swoosh.wav")) if p]
    otros = [t for t in cuts if all(abs(t - s) > 0.6 for s in ocupados)]
    if len(cuts) > 6:
        otros = otros[::2]
    for nw, t in enumerate(otros):
        if whooshes:   # arranca 150ms antes para que el pico aterrice EN el corte
            events.append((round(max(0.0, t - 0.15), 3), whooshes[nw % len(whooshes)], 0.5))

    events.sort(key=lambda e: e[0])
    return events


def _sd_eventos(sfx_events: list[tuple[float, str, float]]) -> list[dict]:
    """Convierte los eventos (t, ruta, volumen lineal) al formato de pro_mix (dB)."""
    return [{"t": max(0.0, float(t)), "path": p,
             "db": 20.0 * math.log10(min(1.0, max(0.05, float(v)))), "pre_ms": 0}
            for t, p, v in (sfx_events or []) if p and os.path.exists(p)]


def add_music_sfx(video_path: str, out_path: str, music_path: str | None = None,
                  sfx_paths: list[str] | None = None, cut_times: list[float] | None = None,
                  phases: list[dict] | None = None,
                  sfx_events: list[tuple[float, str, float]] | None = None) -> str:
    """MEZCLA PRO sin voz en off (Cortar clips): el audio del clip manda, la música se agacha
    debajo de él (ducking) con fade-out final, y los SFX van SUTILES solo en ~50% de los cortes
    (whoosh 150ms antes del corte). Master −18 LUFS. Devuelve la ruta o el original si no aplica.

    `sfx_events` (opcional): colocación EXACTA [(t, ruta, volumen)] de sound_design_events —
    si viene, manda ELLA (sound design con intención); si no, el plan viejo (retrocompatible)."""
    from .pro_mix import plan_sfx, filtros_mezcla, cadena_final
    sfx_paths = [p for p in (sfx_paths or []) if p and os.path.exists(p)]
    has_music = bool(music_path and os.path.exists(music_path))
    if not has_music and not sfx_paths and not sfx_events:
        return video_path
    from .ffmpeg_utils import probe
    try:
        vdur = probe(video_path).duration
    except Exception:  # noqa: BLE001
        return video_path
    if sfx_events is not None:
        eventos = _sd_eventos(sfx_events)
    else:
        eventos = plan_sfx([t for t in (cut_times or []) if t > 0.2], vdur, sfx_paths, phases=phases)
    if not has_music and not eventos:
        return video_path
    inputs = ["-i", video_path]
    fc, idx = [], 1
    clip_label = None
    if _has_audio_stream(video_path):
        fc.append("[0:a]volume=1.0[clip]")
        clip_label = "[clip]"
    music_index = None
    if has_music:
        inputs += ["-i", music_path]
        music_index = idx; idx += 1
    extra, fc2, mix = filtros_mezcla(vo_label=None, clip_label=clip_label, music_index=music_index,
                                     sfx_eventos=eventos, input_offset=idx, dur_total=vdur,
                                     con_voz=False,
                                     music_vol=_SD_MUSIC_VOL if sfx_events is not None else None)
    if not mix:
        return video_path
    inputs += extra
    fc += fc2
    fc.append(cadena_final(mix))
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "0:v:0", "-map", "[a]",
         "-t", f"{vdur:.2f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-ac", "2", "-movflags", "+faststart", out_path])
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
                          music_path: str | None = None,
                          phases: list[dict] | None = None,
                          sfx_events: list[tuple[float, str, float]] | None = None,
                          caption_pngs: list[tuple[str, float, float]] | None = None,
                          out_45: str | None = None) -> str:
    """Voz en off + MEZCLA PRO (pro_mix, reglas de 4 ads ganadores reales):
    música 13dB bajo la voz + ducking al hablar + fade-out final; SFX SUTILES solo en ~50% de
    los cortes (whoosh 150ms ANTES del corte) + 1 'brillo' protagonista en el momento del
    producto; master −18 LUFS. Antes: whoosh a 0.8 en CADA corte + música plana (sonaba amateur).

    `sfx_events` (opcional): colocación EXACTA [(t, ruta, volumen)] de sound_design_events —
    si viene, manda ELLA (riser→producto, cash→CTA...); si no, plan viejo (retrocompatible).
    `caption_pngs` (opcional): [(png_fullframe, inicio_s, fin_s)] de caption_styles.caption_events —
    los subtítulos se queman AQUÍ MISMO (overlay en el mismo filter_complex) = una pasada de
    re-encode menos por versión. Los tiempos van en la línea de tiempo de la VOZ (la misma del
    video final: el video se estira/acolcha a la voz ANTES de los overlays, así que quedan
    idénticos a quemarlos después).
    `out_45` (opcional): además del master, escribe en UNA MISMA pasada el cut 4:5 para Meta
    (crop central, mismo audio). Todo retrocompatible: sin estos params, comportamiento de siempre."""
    from .pro_mix import plan_sfx, filtros_mezcla, cadena_final, _dur_audio
    sfx_paths = [p for p in (sfx_paths or []) if p and os.path.exists(p)]
    has_music = bool(music_path and os.path.exists(music_path))
    vo_dur_s = _dur_audio(vo_path)
    caption_pngs = [(p, s, e) for p, s, e in (caption_pngs or []) if p and os.path.exists(p)]
    if sfx_events is not None:
        eventos = _sd_eventos(sfx_events)
    else:
        eventos = plan_sfx([t for t in (cut_times or []) if t > 0.2], vo_dur_s or 20.0,
                           sfx_paths, phases=phases)
    if not eventos and not has_music and not caption_pngs and not out_45:
        return add_voiceover(video_path, vo_path, out_path)

    # SIN loop de video: si la voz es más larga, se sostiene el último frame (tpad clone).
    # (El loop repetía TODO el montaje desde el inicio → cortes duplicados. Queja de Juan.)
    # ANTI-CONGELÓN: si el montaje quedó hasta 8% más corto que la voz (overlap de dissolves,
    # colitas), se ESTIRA el video imperceptiblemente (setpts) — el audio del montaje no se usa.
    try:
        from .ffmpeg_utils import probe as _probe
        vdur_montaje = _probe(video_path).duration
    except Exception:  # noqa: BLE001
        vdur_montaje = 0.0
    stretch = ""
    if vo_dur_s and vdur_montaje and 1.0 < (vo_dur_s / vdur_montaje) <= 1.08:
        stretch = f"setpts=PTS*{vo_dur_s / vdur_montaje:.5f},"
    inputs = ["-i", video_path, "-i", vo_path]
    fc = [f"[0:v]{stretch}tpad=stop_mode=clone:stop_duration=60[v]", "[1:a]volume=1.0[vo]"]
    idx = 2
    music_index = None
    if has_music:
        inputs += ["-i", music_path]
        music_index = idx; idx += 1
    if eventos or has_music:
        extra, fc2, mix = filtros_mezcla(vo_label="[vo]", clip_label=None, music_index=music_index,
                                         sfx_eventos=eventos, input_offset=idx,
                                         dur_total=vo_dur_s or 20.0, con_voz=True,
                                         music_vol=_SD_MUSIC_VOL if sfx_events is not None else None)
        inputs += extra
        fc += fc2
        fc.append(cadena_final(mix))
        alabel = "[a]"
    else:
        # solo captions/45 sin SFX ni música: el audio queda como en add_voiceover (sin loudnorm)
        alabel = "[vo]"

    # Subtítulos EN LA MISMA pasada (overlays con enable=between sobre la línea de tiempo final)
    vlabel = "[v]"
    n_in = len(inputs) // 2                     # todos los inputs son pares "-i ruta"
    for k, (png, st, en) in enumerate(caption_pngs):
        inputs += ["-i", png]
        tag = f"[vcap{k}]"
        fc.append(f"{vlabel}[{n_in}:v]overlay=0:0:enable='between(t,{st:.2f},{en:.2f})'{tag}")
        vlabel = tag
        n_in += 1

    vo_dur = _dur_flag(vo_path)   # corte EXACTO al final de la voz
    a_enc = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    if out_45:
        # master + cut 4:5 para Meta en UNA pasada (split del video final + crop central)
        fc.append(f"{vlabel}split=2[vmain][v45p]")
        fc.append("[v45p]crop=iw:iw*5/4:0:(ih-iw*5/4)/2,setsar=1[v45]")
        fc.append(f"{alabel}asplit=2[amain][a45]")
        run([
            "ffmpeg", "-y", *inputs,
            "-filter_complex", ";".join(fc),
            "-map", "[vmain]", "-map", "[amain]", "-shortest", *vo_dur,
            *venc(), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            # -ar 48000 OBLIGATORIO: loudnorm sube el sample rate interno a 192k si no se fija
            *a_enc, out_path,
            "-map", "[v45]", "-map", "[a45]", "-shortest", *vo_dur,
            *venc(), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            *a_enc, out_45,
        ])
        return out_path
    run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(fc),
        "-map", vlabel, "-map", alabel, "-shortest", *vo_dur,
        *venc(),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        # -ar 48000 OBLIGATORIO: loudnorm sube el sample rate interno a 192k si no se fija
        *a_enc,
        out_path,
    ])
    return out_path


def export_resolution(src_path: str, out_path: str, width: int) -> str:
    """Re-escala un montaje al ancho pedido para descarga, conservando el formato.
    Recipe de maxima compatibilidad (QuickTime/Apple/Meta/TikTok): H.264 High,
    yuv420p, faststart (moov al inicio) y AAC. Escribe a .tmp y renombra (atomico).
    GPU (VideoToolbox) si hay: el preset medium de libx264 tardaba ~4x el largo del video
    (83s para un montaje de 21s en 1080) y en 2K/4K eran MINUTOS con el navegador mudo."""
    tmp = out_path + f".{uuid.uuid4().hex[:8]}.tmp.mp4"
    if GPU:
        # bitrate alto para que el escalado no pierda calidad (4K necesita mas que 1080)
        vcodec = ["-c:v", "h264_videotoolbox", "-profile:v", "high",
                  "-b:v", "35M" if width >= 2160 else ("22M" if width >= 1440 else "14M")]
    else:
        vcodec = ["-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "19"]
    cmd = [
        "ffmpeg", "-y", "-i", src_path,
        "-vf", f"scale={width}:-2:flags=lanczos,setsar=1,format=yuv420p",
        *vcodec,
        "-movflags", "+faststart",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        tmp,
    ]
    run(cmd)
    os.replace(tmp, out_path)  # renombrado atomico: nunca se sirve un archivo a medias
    return out_path
