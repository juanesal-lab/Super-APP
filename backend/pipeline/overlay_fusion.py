"""Composición FUSIONADA de capas de post-proceso en UNA sola pasada de ffmpeg.

PERF (medido por el agente de perf): la cadena banner → end-card → hook eran 3 RE-ENCODES
GPU completos por versión (~67s del lote de 8). Banner y hook son overlays de PNG; la
end-card es un CONCAT (cambia la duración). El hook (pastilla 0-3s arriba) tiene que quedar
SEPARADO porque es la frontera de `v['_prehook']` (base CON banner+end-card pero SIN hook,
para re-aplicar otro hook sin duplicar capas — /api/reaplicar-hook).

Por eso fusionamos las DOS capas que rodean esa frontera: **banner (overlay) + end-card
(concat) en una sola pasada**. El resultado ES la base pre-hook. Semántica idéntica a hacer
banner y luego end-card por separado:
  - el banner se superpone sobre la porción [0..D] del video (con su enable temporal),
  - la end-card se anexa como frames nuevos [D..D+dur] (nunca los toca el banner ni el hook).

Solo se usa cuando banner Y end-card están AMBOS activos (2+ capas). Con una sola de las dos,
el runner llama al camino de siempre (add_offer_banner / append_end_card) — cero riesgo.
Los textos, posiciones, la y-fracción que elige la IA y la duración de la card son IDÉNTICOS
a los de las funciones originales (reusa render_banner/safe_top_y y _card_clip_cached).
"""
from __future__ import annotations

import os

from .assemble import venc
from .end_card import _card_clip_cached
from .ffmpeg_utils import probe, run
from .offer_banner import render_banner, safe_top_y


def _banner_enable(start: float, dur: float) -> str | None:
    """Condición `enable` del overlay del banner — MISMA lógica que add_offer_banner.

    None = sin enable (overlay todo el video)."""
    if start and start > 0:
        if dur and dur > 0:
            return f"between(t,{float(start):.2f},{float(start) + float(dur):.2f})"
        return f"gte(t,{float(start):.2f})"
    if dur and dur > 0:
        return f"lt(t,{float(dur):.2f})"
    return None


def compose_banner_endcard(video_path: str, out_path: str, work_dir: str, *,
                           banner_line1: str = "ENVÍO GRATIS · PAGAS AL RECIBIR",
                           banner_line2: str = "OFERTA 2X1",
                           banner_start: float = 0.0, banner_dur: float = 0.0,
                           gemini_key: str | None = None,
                           ec_line1: str = "PAGAS AL RECIBIR",
                           ec_line2: str = "ENVÍO GRATIS A TODA COLOMBIA",
                           ec_cta: str = "PIDE EL TUYO AQUÍ 👇",
                           ec_dur: float = 1.5) -> str:
    """Banner (overlay PNG con enable temporal) + end-card (concat al final) en UNA pasada.

    Devuelve out_path, o el original si algo falla (best-effort, igual que las funciones
    que fusiona). El banner queda DEBAJO (se dibuja primero) y la card se anexa después:
    layer order y duración final (D + ec_dur) idénticos a hacerlo en dos pasadas."""
    try:
        info = probe(video_path)
        W, H, fps = info.width, info.height, (info.fps or 30.0)

        # 1) PNG del banner (misma y-fracción que elige la IA; sin key = piso seguro, $0)
        y = safe_top_y(video_path, gemini_key)
        png = os.path.join(work_dir, os.path.basename(out_path) + ".fus_banner.png")
        render_banner(W, H, y_frac=y, line1=banner_line1, line2=banner_line2).save(png)

        # 2) CLIP de la end-card (cacheado por WxH/fps/dur/textos — idéntico a append_end_card)
        clip = _card_clip_cached(work_dir, W, H, float(fps), float(ec_dur),
                                 ec_line1, ec_line2, ec_cta)

        # 3) filtro único: overlay del banner sobre [0..D] → normaliza fps/sar → concat con la card
        cond = _banner_enable(banner_start, banner_dur)
        ov = f"[0:v][1:v]overlay=0:0:enable='{cond}'[vb];" if cond else "[0:v][1:v]overlay=0:0[vb];"
        vf = ov + (f"[vb]fps={fps:.3f},setsar=1[v0];[2:v]fps={fps:.3f},setsar=1[v1];")
        if info.has_audio:
            fc = (vf + "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
                       "[2:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
                       "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")
            maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac"]
        else:
            fc = vf + "[v0][v1]concat=n=2:v=1:a=0[v]"
            maps = ["-map", "[v]", "-an"]
        run(["ffmpeg", "-y", "-i", video_path, "-i", png, "-i", clip,
             "-filter_complex", fc, *maps, *venc(),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path])
        return out_path
    except Exception:  # noqa: BLE001
        return video_path
