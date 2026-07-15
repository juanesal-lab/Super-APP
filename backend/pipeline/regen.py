"""Regenerar UNA sola versión de video ya entregada, con un MOTIVO (pedido de Juan 2026-07-04).

El usuario ve las N versiones y, si una no le gusta, la reemplaza SIN rehacer todo el lote —
indicando POR QUÉ: la edición, los clips, el guion, o simplemente "otra distinta". Cada motivo
cambia una palanca del montaje por-guion y re-arma solo esa versión.

Trabaja sobre el ESTADO que `render_versions` guarda en el manifest (`_regen`): el pool de
segmentos (ya enmascarados), las fases, el uso por clip, los ajustes y, por versión, su guion +
voz + orden + topes. Todo JSON-serializable → sobrevive reinicios (persistido en work/<id>).
"""
from __future__ import annotations

import os

from .analyze import Segment, segment_signature
from .assemble import build_variations, dims_for, add_voiceover_and_sfx
from .text_overlay import burn_hook
from . import guion_match

# Motivos que entiende la UI → qué palanca mueve cada uno
MOTIVOS = {
    "edicion":  "misma historia y clips, OTRA edición (efectos, cortes, ritmo, movimiento)",
    "clips":    "mismo guion y voz, CLIPS distintos (reemplaza los que no gustaron)",
    "guion":    "OTRO guion + voz nueva para esta versión (misma info del producto)",
    "otra":     "una versión TOTALMENTE distinta (guion, clips y edición nuevos)",
}


def _seg_from_dict(d: dict) -> Segment:
    return Segment(
        video=d["video"], source_index=int(d.get("source_index", 0)),
        start=float(d["start"]), end=float(d["end"]), score=float(d.get("score", 0.0)),
        local_score=float(d.get("local_score", 0.0)),
        product_visible=bool(d.get("product_visible", False)),
        shows_use=bool(d.get("shows_use", False)), tag=str(d.get("tag", "")),
        is_broll=bool(d.get("is_broll", False)))


def regenerar_version(estado: dict, name: str, motivo: str, *,
                      gemini_key: str | None = None, eleven_key: str | None = None,
                      voz: str = "juan_carlos",
                      progress=None) -> dict | None:
    """Rehace la versión `name` según `motivo`. Devuelve el dict de la versión (path nuevo,
    n_clips, voiceover, cut_times, ...) o None si no se pudo. Muta `estado` (usage, versión)
    para que el llamador lo re-persista."""
    def rep(m, p):
        if progress:
            progress(m, p)

    vers = estado.get("versions", {}).get(name)
    if not vers:
        return None
    motivo = motivo if motivo in MOTIVOS else "otra"
    s = estado.get("settings", {})
    selected = [_seg_from_dict(d) for d in estado.get("selected", [])]
    if not selected:
        return None
    fases = {int(k): v for k, v in estado.get("fases", {}).items()}
    usage = {int(k): v for k, v in estado.get("usage", {}).items()}
    work_dir = estado["work_dir"]
    dims = dims_for(s.get("aspect", "9:16"))
    fx = bool(s.get("effects"))
    # bump de intento → el seed cambia (otra edición) y los archivos no se pisan
    intento = int(vers.get("regen", 0)) + 1
    vers["regen"] = intento
    seed = intento % 3 + (1 if motivo in ("edicion", "otra") else 0)

    # ── 1) guion + voz: se rehacen solo si el motivo lo pide ────────────────────────────
    frases = vers.get("frases") or []
    vo_path = vers.get("vo_path")
    words = vers.get("words") or []
    # HONESTO (auditoría 2026-07-06): si el motivo es "guion" y la IA o la voz FALLAN, NO se
    # re-monta el guion VIEJO marcado como "regenerado" — se falla con el porqué. Con motivo
    # "otra" el guion es best-effort (los clips y la edición sí se renuevan igual).
    if motivo == "guion" and not eleven_key:
        raise RuntimeError("Para regenerar el guion necesito la API key de ElevenLabs "
                           "(narra la voz nueva) — configúrala en 🔑 Claves.")
    if motivo in ("guion", "otra") and eleven_key:
        rep("Escribiendo otro guion…", 15)
        from .scripts import generate_scripts
        from . import voiceover
        evitar_ang = [vers.get("guion", "")]  # no repetir el mismo texto
        try:
            gs = generate_scripts(gemini_key, s.get("product_desc", ""), s.get("page_text", ""),
                                  float(s.get("target_seconds", 20.0)), n=3)
        except Exception as e:  # noqa: BLE001
            if motivo == "guion":
                raise RuntimeError(f"No pude escribir otro guion — {e}")
            gs = []
        nuevo = next((g for g in gs if g.get("texto") and g["texto"] not in evitar_ang), None)
        if nuevo is None and motivo == "guion":
            raise RuntimeError("La IA no entregó un guion distinto al actual — reintenta.")
        if nuevo:
            mp3 = os.path.join(work_dir, f"vo_regen_{name}_{intento}.mp3")
            try:
                rep("Narrando el nuevo guion…", 35)
                w = voiceover.synthesize_with_timestamps(eleven_key, nuevo["texto"], voz, mp3)
                w = voiceover.acelerar(mp3, w, factor=1.12)
                vo_path, words = mp3, w
                vers["guion"] = nuevo["texto"]
                fr = guion_match.frases_de_vo(w, voiceover_dur(mp3))
                guion_match.etiquetar_frases([fr], gemini_key, s.get("product_desc", ""))
                frases = fr
                vers["frases"] = fr
                vers["words"] = w
                vers["vo_path"] = mp3
            except Exception as e:  # noqa: BLE001
                if motivo == "guion":
                    raise RuntimeError(f"La voz del guion nuevo falló (ElevenLabs) — {e}")
                # motivo "otra": sigue con la voz anterior (clips y edición sí cambian)

    # ── 2) plan de montaje ──────────────────────────────────────────────────────────────
    rep("Eligiendo los clips…", 55)
    firmas: dict[int, object] = {}
    if motivo in ("clips", "otra"):
        for i in fases:                              # firmas para el guard de "mismo look"
            try:
                firmas[i] = segment_signature(selected[i])
            except Exception:  # noqa: BLE001
                pass

    order = vers.get("order") or []
    caps = vers.get("caps") or []
    if motivo in ("clips", "guion", "otra") and frases:
        evitar = set(vers.get("order") or []) if motivo == "clips" else set()
        # afinidad guion↔clip por contenido (mismo extra del render normal); None si no hay key/tags
        af = guion_match.afinidad_guion_clips([frases], selected, fases, gemini_key,
                                              s.get("product_desc", ""))
        broll_idx = {i for i in fases if getattr(selected[i], "is_broll", False)}
        plan = guion_match.plan_montaje(
            selected, fases, frases, usage,
            version_i=int(vers.get("version_i", 0)), n_versiones=int(estado.get("n_versiones", 8)),
            hook_srcs=set(), max_usos=99, firmas=firmas, evitar=evitar,
            afinidad=(af[0] if af else None), broll_idx=broll_idx, mismatch_duro=True)
        if plan:
            order, caps = plan
            vers["order"], vers["caps"] = order, caps
            for i in order:
                usage[i] = usage.get(i, 0) + 1
    if not order:
        return None

    # ── 3) armar el montaje de ESTA versión ─────────────────────────────────────────────
    rep("Armando el montaje…", 68)
    built = build_variations(selected, work_dir, dims, enhance=bool(s.get("enhance")),
                             fx=fx, version_orders=[(f"{name}_r{intento}", order)],
                             version_caps={f"{name}_r{intento}": caps}, seed=seed)
    if not built["versions"]:
        return None
    v = built["versions"][0]

    # ── 4) gancho + voz + SFX + captions (mismo pipeline del render normal) ──────────────
    hook = (vers.get("hook") or "").strip()
    if hook:
        ho = v["path"].replace(".mp4", "_hook.mp4")
        v["path"], _ = burn_hook(v["path"], ho, work_dir, hook, s.get("hook_pos", "arriba"))

    if vo_path and os.path.exists(vo_path):
        rep("Voz, música y efectos…", 84)
        phases_mix = [{"etiqueta": str(f.get("fase", "")).upper(),
                       "inicio_s": f["inicio"], "fin_s": f["fin"]} for f in frases]
        vo_out = v["path"].replace(".mp4", "_vo.mp4")
        # SOUND DESIGN CON INTENCIÓN igual que el render principal (riser→producto, cash→CTA):
        # sin esto la versión regenerada sonaba distinta (plan viejo) a las del lote.
        from .assemble import sound_design_events
        from .ffmpeg_utils import probe as _probe
        sd_events = None
        try:
            vo_d = _probe(vo_path).duration
            if vo_d and vo_d > 1.0:
                sd_events = sound_design_events(v.get("segments") or [], vo_d,
                                                vo_dur=vo_d, cut_times=list(v.get("cut_times") or []))
        except Exception:  # noqa: BLE001
            sd_events = None
        try:
            add_voiceover_and_sfx(v["path"], vo_path, vo_out,
                                  sfx_paths=estado.get("sfx_paths") or None,
                                  cut_times=list(v.get("cut_times") or []),
                                  music_path=estado.get("music_path"), phases=phases_mix,
                                  sfx_events=sd_events)
            v["path"] = vo_out
            v["voiceover"] = True
        except Exception:  # noqa: BLE001
            v["voiceover"] = False
        if s.get("captions") and words:
            rep("Subtítulos…", 92)
            try:
                from .caption_styles import burn_word_captions, set_destino
                set_destino(s.get("destino", "tiktok"))
                co = v["path"].replace(".mp4", "_cap.mp4")
                np = burn_word_captions(v["path"], words, work_dir, co,
                                        style=s.get("caption_style", "hormozi"),
                                        cap_size=s.get("caption_size", "mediano"))
                v["path"] = np
                v["captions"] = True
            except Exception:  # noqa: BLE001
                pass

    rep("Listo", 100)
    return {
        "name": name, "path": v["path"], "filename": os.path.basename(v["path"]),
        "n_clips": len(order), "voiceover": v.get("voiceover", False),
        "guion": vers.get("guion", ""), "regenerado": True, "motivo": motivo,
    }


def voiceover_dur(mp3: str) -> float:
    import subprocess
    try:
        o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", mp3], capture_output=True, text=True, timeout=15)
        return float(o.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0
