"""
editor.py — Motor de edición PRO v2 (autocontenido, integrable a cualquier app).

Implementa las reglas destiladas de ads ganadores reales (edicion-pro-reglas.md
de cortador-clips, 2026-07-03):
  · Transiciones: SOLO dissolve 0.17s (~80%) + corte casi-duro 0.034s (1 de cada 5
    y el último plano). Cero whips/flashes/slides.
  · Movimiento: nada 100% estático. Ciclo Ken Burns (in_suave 2%/s cap 1.30 →
    out_lento 3%/s 1.12→1.0 → in_suave → out 2.5%/s 1.06→1.0). Acentos:
    punch 18%/s cap 1.22 (máx 1-2, producto/oferta) y punch_hook 30%/s cap 1.15 (beat 1).
  · Color: hqdn3d 1.5:1.5:6:6 + unsharp 0.9 + eq contrast 1.04 / saturation 1.07.
  · Voz: loudnorm I=-18:TP=-1.5:LRA=8 (rango dinámico pro), entra a 0.25s (nunca frame 0).
  · SFX: sutiles (−14dB), ~50% de los cortes, arrancan 150ms ANTES del corte, jamás el
    mismo sample 2 veces seguidas. Protagonista (−2dB): caja registradora en la oferta.
    En DOLOR no hay SFX. (Presupuesto duro: 1 cada 1.8s.)
  · Subtítulos: karaoke por GRUPOS de 2-4 palabras con tiempos REALES por palabra,
    Poppins ExtraBold, stroke negro grueso, palabra activa amarilla y 12% más grande.

API principal:
    build(outdir, workdir, audio_path, beats, plan, clips_map, words, log=print)
      beats: [{n,t0,t1,dur,seg_start,seg_end,texto}]      (tiempos de la voz, fijos)
      plan:  [{beat,clip,in,caption,fase,punch,razon}]     (fase: hook|dolor|solucion|prueba|precio|cta)
      clips_map: {"01": Path(...), ...}
      words: [{"w","start","end"}]  (timestamps por palabra de whisper)
    → genera corte-base.mp4, corte-base-SUBS.mp4, subtitulos.srt en outdir.
"""
import json, random, re, subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ASSETS = BASE / "assets"

# ------------------------------------------------------------------ config PRO
W, H, FPS = 1080, 1920, 30
XFADE_D, XFADE_D_HARD = 0.17, 0.034          # dissolve / corte casi-duro
VOICE_LEAD = 0.25                             # la voz nunca entra en frame 0
ENHANCE = "hqdn3d=1.5:1.5:6:6,unsharp=5:5:0.9:5:5:0.0,eq=contrast=1.04:saturation=1.07"
SUBS_Y_CENTER = 0.62                          # centro vertical de subtítulos (0.62 Meta / 0.80 TikTok)
SFX_DB_SUTIL, SFX_DB_PROTA = -14, -2
SFX_PRE_MS = 150                              # el whoosh arranca antes del corte

# --- cama musical (receta destilada de pro_mix / ads reales — no tocar números) ---
MUSICA_VOL = 0.22          # cama bajo la voz (~−13 dB antes del ducking)
MUSICA_VOL_SIN_VOZ = 0.30  # donde no hay voz en off la cama vive un pelín más arriba
MUSICA_DUCK = "sidechaincompress=threshold=0.02:ratio=4:attack=25:release=400"  # −3..−5dB al hablar
MUSICA_FADE_OUT = 1.5      # s de fade-out final: la música JAMÁS se corta en seco

# --- subtítulos: estilos y plataforma ---
ESTILOS_SUBS = {"karaoke", "caja", "minimal"}
PLATAFORMA_Y = {"meta": 0.62, "tiktok": 0.80}  # centro vertical de subs por plataforma

# movimiento: (tasa por segundo, tope, modo)
MOTION = {
    "in_suave":   (0.02, 1.30, "in"),
    "in_fuerte":  (0.06, 1.30, "in"),
    "punch":      (0.18, 1.22, "in"),
    "punch_hook": (0.30, 1.15, "in"),
    "out":        (0.025, 1.06, "out"),
    "out_lento":  (0.03, 1.12, "out"),
}
CICLO = ["in_suave", "out_lento", "in_suave", "out"]

SFX_FAMILIAS = {
    "swoosh":  ["swoosh.wav", "whoosh.wav", "whoosh_fast.wav"],
    "sparkle": ["sparkle.wav"],
    "cash":    ["cash_register.mp3"],
    "pop":     ["notification_pop.mp3", "click.wav"],
}
# por fase: (familia_en_el_corte_de_entrada | None, protagonista_bool)
SFX_POR_FASE = {
    "hook":     ("swoosh", False),
    "dolor":    (None, False),
    "solucion": ("sparkle", True),
    "prueba":   ("pop", False),
    "deseo":    ("sparkle", False),
    "precio":   ("cash", True),
    "cta":      ("swoosh", False),
}

def _run(cmd):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True)

# ------------------------------------------------------------------ encuadre
def _probe_wh(path, _cache={}):
    key = str(path)
    if key not in _cache:
        r = _run(["ffprobe","-v","error","-select_streams","v:0",
                  "-show_entries","stream=width,height","-of","csv=p=0",path])
        try:
            w, h = [int(x) for x in r.stdout.strip().split(",")[:2]]
        except Exception:
            w, h = 1080, 1920
        _cache[key] = (w, h)
    return _cache[key]

# receta rescate (research/MEJORAS-FUTURAS.md): denoise ANTES de escalar, lanczos,
# deband + cas (nada de halos) para fuentes <900px de ancho.
_RESCATE_POST = "deband=1thr=0.012:2thr=0.012:3thr=0.012:range=16,cas=0.8,eq=contrast=1.04:saturation=1.07"

def _vf_encuadre(w, h):
    """Prefijo de encuadre+color según la fuente (reglas validadas en research/):
    · AR > 0.68 → BLUR-PAD: fondo = mismo clip fill+gblur oscurecido, frente contain
      (el crop duro mutila los clips horizontales — verificado con frames).
    · ancho < 900 → MODO RESCATE (denoise a resolución nativa + lanczos + deband + cas).
    · ambos → rescate + blur-pad combinados. · resto → camino actual (idéntico a antes).
    """
    ar = (w / h) if h else 0.5625
    horizontal = ar > 0.68
    lowres = 0 < w < 900
    if horizontal and lowres:
        return ("hqdn3d=4:3:12:12,split=2[bg0][fg0];"
                f"[bg0]scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},"
                "gblur=sigma=50:steps=2,eq=brightness=-0.06:saturation=0.85[bg];"
                f"[fg0]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2," + _RESCATE_POST)
    if horizontal:
        return ("split=2[bg0][fg0];"
                f"[bg0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                "gblur=sigma=50:steps=2,eq=brightness=-0.06:saturation=0.85[bg];"
                f"[fg0]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{ENHANCE}")
    if lowres:
        return (f"hqdn3d=4:3:12:12,scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={W}:{H}," + _RESCATE_POST)
    return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{ENHANCE}"

# ------------------------------------------------------------------ movimiento
def _motion_vf(kind):
    rate, cap, mode = MOTION[kind]
    rf = rate / FPS
    if mode == "in":
        z = f"min(1+{rf:.6f}*on,{cap})"
    else:
        z = f"max({cap}-{rf:.6f}*on,1.0)"
    return (f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={W}x{H}:fps={FPS}")

def asignar_movimiento(plan):
    """punch_hook al beat 1; 'punch' donde el plan lo pida (máx 2); ciclo en el resto."""
    out, punches, ci = [], 0, 0
    for i, p in enumerate(plan):
        if i == 0:
            out.append("punch_hook")
        elif p.get("punch") and punches < 2:
            out.append("punch"); punches += 1
        else:
            out.append(CICLO[ci % len(CICLO)]); ci += 1
    return out

# ------------------------------------------------------------------ timeline
def _transiciones(n, seed=0):
    """Duración de la transición DESPUÉS de cada beat i (n-1 transiciones)."""
    dur = []
    for i in range(n - 1):
        hard = (i % 5 == (2 + seed) % 5) or (i == n - 2)  # 1/5 + entrada del último plano
        dur.append(XFADE_D_HARD if hard else XFADE_D)
    return dur

def render_segmentos(beats, plan, movs, clips_map, trans, workdir, log, encuadre=True):
    """Renderiza cada beat con color+movimiento.

    La transición ARRANCA en la frontera del beat (como cortador-clips), así que
    cada segmento intermedio lleva cola extra = duración de su transición + 1 frame
    de margen (media frame no existe: un corte casi-duro de 0.034s sin cola completa
    deja a xfade sin material y colapsa la cadena — bug real cazado en pruebas).
    """
    segs = []
    for i, (b, p) in enumerate(zip(beats, plan)):
        d_out = (trans[i] + 1.0/FPS) if i < len(trans) else 0.0
        lead = VOICE_LEAD if i == 0 else 0.0
        ss = max(0.0, p["in"])
        dur = b["dur"] + d_out + lead
        seg = workdir / f"v2_seg_{b['n']:02d}.mp4"
        if encuadre:   # 🤖 agente encuadre: blur-pad horizontales + rescate <900px
            sw, sh = _probe_wh(clips_map[p["clip"]])
            prefijo = _vf_encuadre(sw, sh)
        else:          # camino clásico: crop duro siempre
            prefijo = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{ENHANCE}"
        # tpad clona el último frame si el CLIP FUENTE es más corto que el beat+colas:
        # sin esto el segmento sale corto y la cadena xfade trunca el video EN SILENCIO
        # (bug real: clon de ganador con 6 clips → video muerto a los 10.6s).
        # OJO: tpad debe ir ANTES de zoompan — después de zoompan NO rellena (probado);
        # además así el Ken Burns sigue moviéndose sobre el frame clonado (se ve natural).
        vf = (f"{prefijo},tpad=stop_mode=clone:stop_duration=30,"
              f"{_motion_vf(movs[i])},setsar=1,format=yuv420p")
        cmd = ["ffmpeg","-y","-loglevel","error","-ss",ss,"-i",clips_map[p["clip"]],
               "-t",dur,"-vf",vf,"-an","-c:v","libx264","-preset","medium",
               "-crf","18","-r",FPS,seg]
        r = _run(cmd)
        if r.returncode != 0 or not seg.exists():
            # blindaje: un reintento único (a veces ffmpeg tropieza con un frame raro)
            log(f"⚠️  ffmpeg falló en el corte {b['n']}; reintentando una vez…")
            seg.unlink(missing_ok=True)
            r = _run(cmd)
        if r.returncode != 0 or not seg.exists():
            raise RuntimeError(f"render seg {b['n']}: {r.stderr[-300:]}")
        segs.append(seg)
        log(f"🎞️  Corte {b['n']}/{len(beats)} (clip {p['clip']}, {movs[i]})")
    return segs

def unir_con_dissolves(segs, beats, trans, workdir):
    """Encadena xfade fade que ARRANCA en cada frontera de beat (la voz manda el corte)."""
    if len(segs) == 1:
        out = workdir / "v2_video.mp4"
        _run(["ffmpeg","-y","-loglevel","error","-i",segs[0],"-c","copy",out])
        return out
    inputs = []
    for s in segs:
        inputs += ["-i", s]
    fc, prev = [], "[0:v]"
    acum = VOICE_LEAD + beats[0]["dur"]          # frontera del beat 1 en la línea de tiempo
    for i in range(1, len(segs)):
        d = trans[i-1]
        nxt = f"[x{i}]"
        fc.append(f"{prev}[{i}:v]xfade=transition=fade:duration={d:.3f}:offset={acum:.3f}{nxt}")
        prev = nxt
        acum += beats[i]["dur"]
    out = workdir / "v2_video.mp4"
    r = _run(["ffmpeg","-y","-loglevel","error"] + inputs +
             ["-filter_complex", ";".join(fc), "-map", prev,
              "-c:v","libx264","-preset","medium","-crf","18","-r",FPS,out])
    if r.returncode != 0:
        raise RuntimeError(f"xfade chain: {r.stderr[-400:]}")
    return out

# ------------------------------------------------------------------ audio
def mezclar_audio(video, audio_path, beats, plan, outdir, workdir, log, musica_path=None):
    """Voz con loudnorm −18 LUFS + lead 0.25s + SFX sutiles según fase.

    Si hay música (musica_path): cama a 0.22 bajo la voz (0.30 sería sin voz — en
    Montador siempre hay voz en off), ducking con sidechaincompress usando la voz
    como llave, hot-start al 100% de su nivel en t=0 (sin fade-in) y fade-out de
    1.5s al final. Receta destilada de ads reales (pro_mix de cortador-clips).
    Sin música, el código corre IDÉNTICO al de siempre."""
    sfx_events = []   # (path, t_video, dB)
    ultimo = {}
    presupuesto = max(1, int((VOICE_LEAD + beats[-1]["t1"]) / 1.8))
    rnd = random.Random(7)
    for i, (b, p) in enumerate(zip(beats, plan)):
        if len(sfx_events) >= presupuesto:
            break
        fase = (p.get("fase") or "").lower()
        familia, prota = SFX_POR_FASE.get(fase, ("swoosh", False))
        if familia is None:                      # en DOLOR no se celebra
            continue
        if not prota and i % 2 == 1:             # sutiles: ~50% de los cortes
            continue
        cands = [s for s in SFX_FAMILIAS[familia] if (ASSETS/"sfx"/s).exists()
                 and s != ultimo.get(familia)]
        if not cands:
            continue
        s = rnd.choice(cands); ultimo[familia] = s
        t = max(0.0, VOICE_LEAD + b["t0"] - SFX_PRE_MS/1000.0)
        db = SFX_DB_PROTA if prota else SFX_DB_SUTIL
        sfx_events.append((ASSETS/"sfx"/s, t, db))
    log(f"🔊 Voz a −18 LUFS + {len(sfx_events)} SFX sutiles")

    # Paso previo: loudnorm a WAV aparte. (Meterlo en el grafo junto al mux de video
    # rompe los timestamps → el AAC sale en silencio digital. Bug real cazado en pruebas.)
    voz_norm = workdir / "voz_norm.wav"
    r = _run(["ffmpeg","-y","-loglevel","error","-i",audio_path,
              "-af","loudnorm=I=-18:TP=-1.5:LRA=8","-ar","44100","-ac","1",voz_norm])
    if r.returncode != 0:
        raise RuntimeError(f"loudnorm voz: {r.stderr[-300:]}")

    total = VOICE_LEAD + beats[-1]["t1"]
    delay = int(VOICE_LEAD*1000)
    inputs = ["-i", video, "-i", voz_norm]
    fc, sfx_base = [], 2
    if musica_path:
        # Cama musical: hot-start al 100% de su nivel en t=0 (sin fade-in), loop si la
        # pista es más corta que el video, volumen 0.22 bajo la voz y fade-out 1.5s.
        # La voz se parte en dos: una copia va a la mezcla, la otra es la LLAVE del
        # ducking (sidechaincompress agacha la cama −3..−5dB cuando la voz habla).
        inputs += ["-i", Path(musica_path)]
        fade_st = max(0.0, total - MUSICA_FADE_OUT)
        fc.append(f"[1:a]adelay={delay}|{delay},asplit=2[voz][vozkey]")
        fc.append(f"[2:a]aloop=loop=-1:size=2000000000,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
                  f"volume={MUSICA_VOL},afade=t=out:st={fade_st:.3f}:d={MUSICA_FADE_OUT}[mus0]")
        fc.append(f"[mus0][vozkey]{MUSICA_DUCK}[mus]")
        mix = ["[voz]", "[mus]"]
        sfx_base = 3
        log(f"🎵 Cama musical a {MUSICA_VOL} con ducking sidechain, hot-start y fade-out {MUSICA_FADE_OUT}s")
    else:
        fc.append(f"[1:a]adelay={delay}|{delay}[voz]")
        mix = ["[voz]"]
    for k, (spath, t, db) in enumerate(sfx_events):
        inputs += ["-i", spath]
        fc.append(f"[{k+sfx_base}:a]volume={db}dB,adelay={int(t*1000)}|{int(t*1000)}[s{k}]")
        mix.append(f"[s{k}]")
    # limitador de seguridad: la suma voz+SFX protagonista puede pasar de 0 dB
    fc.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0,alimiter=limit=0.89[aout]")
    base = outdir / "corte-base.mp4"
    r = _run(["ffmpeg","-y","-loglevel","error"] + inputs +
             ["-filter_complex", ";".join(fc),
              "-map","0:v:0","-map","[aout]","-c:v","copy","-c:a","aac","-b:a","192k",
              "-t", f"{total:.3f}", base])
    if r.returncode != 0:
        raise RuntimeError(f"mezcla audio: {r.stderr[-400:]}")
    return base

# ------------------------------------------------------------------ subtítulos v2
def _font(sz, extra=False):
    from PIL import ImageFont
    for p in [ASSETS/"fonts"/("Poppins-ExtraBold.ttf" if extra else "Poppins-Bold.ttf"),
              ASSETS/"fonts"/"Poppins-Bold.ttf",
              Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")]:
        try:
            return ImageFont.truetype(str(p), sz)
        except Exception:
            continue
    return ImageFont.load_default()

def _tiempos_por_palabra(caption_words, seg_words):
    """Asigna a cada palabra del caption un (start,end) real de whisper (mapeo proporcional)."""
    nc, nt = len(caption_words), len(seg_words)
    out = []
    for j in range(nc):
        k = min(nt - 1, round(j * nt / max(1, nc)))
        out.append((seg_words[k]["start"], seg_words[k]["end"]))
    # monotonía
    for j in range(1, nc):
        if out[j][0] < out[j-1][0]:
            out[j] = (out[j-1][0], max(out[j][1], out[j-1][1]))
    return out

YEL, WHITE, BLK = (255,222,0), (255,255,255), (0,0,0)
CH = 300                                      # alto del lienzo de cada cuadro de subtítulo

def _dibujar_grupo(cwords, g, activa, estilo, F, FA, STROKE, emoji_img=None):
    """Dibuja UN cuadro del grupo de palabras según el estilo.
    · karaoke: palabra activa amarilla y 12% más grande (comportamiento de siempre).
    · caja:    palabra activa con caja amarilla redondeada detrás y texto negro (Hormozi).
    · minimal: todo blanco, sin palabra activa (activa=None), mismos grupos.
    """
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, CH), (0,0,0,0))
    d = ImageDraw.Draw(img)
    # layout centrado (en karaoke la palabra activa es más grande)
    ws = [(cwords[k], FA if (estilo == "karaoke" and k == activa) else F) for k in g]
    widths = [d.textbbox((0,0), t, font=f, stroke_width=STROKE)[2] for t, f in ws]
    total = sum(widths) + 22 * (len(ws)-1)
    if emoji_img is not None:                      # agente emoji: reservar sitio al final
        total += emoji_img.width + 18
    x = (W - total) // 2
    for (t, f), wd, k in zip(ws, widths, g):
        yy = CH//2 - (f.getbbox("Ag")[3])//2
        if estilo == "caja" and k == activa:
            bb = d.textbbox((x, yy), t, font=f)
            pad = 16
            d.rounded_rectangle((bb[0]-pad, bb[1]-pad, bb[2]+pad, bb[3]+pad),
                                radius=14, fill=YEL)
            d.text((x, yy), t, font=f, fill=BLK)
        else:
            act = (estilo == "karaoke" and k == activa)
            d.text((x, yy), t, font=f, fill=(YEL if act else WHITE),
                   stroke_width=STROKE, stroke_fill=BLK)
        x += wd + 22
    if emoji_img is not None:
        img.alpha_composite(emoji_img.convert("RGBA"),
                            (x - 4, CH//2 - emoji_img.height//2))
    return img

def karaoke(video_base, beats, plan, words, outdir, workdir, log,
            estilo="karaoke", y_center=SUBS_Y_CENTER, opts=None):
    """Subtítulos por GRUPOS de 2-4 palabras con tiempos REALES por palabra, Poppins.
    estilo: karaoke | caja | minimal (ver _dibujar_grupo). y_center: 0.62 Meta / 0.80 TikTok."""
    opts = opts or {}
    SZ = 72
    F, FA = _font(SZ, extra=True), _font(int(SZ*1.12), extra=True)
    STROKE = SZ // 8
    y_top = int(H * y_center) - CH // 2
    subsdir = workdir / "subs_v2"; subsdir.mkdir(exist_ok=True)
    for f in subsdir.glob("*.png"): f.unlink()

    # 🤖 agente emoji (opcional): emoji del beat al final de cada grupo
    mod_emoji = None
    if opts.get("emojis"):
        from backend.agentes import cargar
        mod_emoji = cargar("emoji")
        if mod_emoji is None:
            log("🤖 Agente emoji marcado pero el módulo no está — sigo sin emojis")
    _emoji_cache = {}
    def _emoji_de(p):
        if mod_emoji is None:
            return None
        ch = (p.get("emoji") or "").strip()
        if not ch:
            return None
        if ch not in _emoji_cache:
            try:
                _emoji_cache[ch] = mod_emoji.emoji_png(ch, int(SZ * 1.15))
            except Exception:
                _emoji_cache[ch] = None
        return _emoji_cache[ch]

    overlays = []   # (png, t_on, t_off)
    idx = 0
    for b, p in zip(beats, plan):
        cwords = p["caption"].split()
        if not cwords:
            continue
        seg_words = [w for w in words if b["seg_start"] - 0.05 <= w["start"] < b["seg_end"] + 0.05]
        if len(seg_words) < 2:
            # sin tiempos de whisper (o un solo timestamp): repartir uniforme dentro del
            # segmento — si todas las palabras comparten tiempo, los cuadros karaoke se
            # encienden a la vez y el texto sale encimado (caso borde cazado en pruebas)
            n = len(cwords)
            paso = max(0.001, (b["seg_end"] - b["seg_start"]) / max(1, n))
            seg_words = [{"start": b["seg_start"] + i * paso,
                          "end": b["seg_start"] + (i + 1) * paso} for i in range(n)]
        tiempos = _tiempos_por_palabra(cwords, seg_words)
        # grupos de 2-4 palabras (corta en 3-4)
        grupos, g = [], []
        for j, w in enumerate(cwords):
            g.append(j)
            if len(g) >= (4 if len(cwords) - j - 1 != 1 else 3):
                grupos.append(g); g = []
        if g: grupos.append(g)
        for gi, g in enumerate(grupos):
            g_on = tiempos[g[0]][0]
            g_off = tiempos[grupos[gi+1][0]][0] if gi+1 < len(grupos) else b["seg_end"]
            emoji_img = _emoji_de(p)
            if estilo == "minimal":               # un solo cuadro por grupo, sin karaoke
                img = _dibujar_grupo(cwords, g, None, estilo, F, FA, STROKE, emoji_img)
                png = subsdir / f"k_{idx:04d}.png"; img.save(png); idx += 1
                overlays.append((png, VOICE_LEAD + g_on, VOICE_LEAD + max(g_off, g_on + 0.12)))
                continue
            for j in g:                           # una imagen por palabra activa
                img = _dibujar_grupo(cwords, g, j, estilo, F, FA, STROKE, emoji_img)
                png = subsdir / f"k_{idx:04d}.png"; img.save(png); idx += 1
                w_on = max(g_on, tiempos[j][0])
                w_off = tiempos[j][1] if j != g[-1] else g_off
                overlays.append((png, VOICE_LEAD + w_on, VOICE_LEAD + max(w_off, w_on + 0.12)))
    log(f"💬 Subtítulos '{estilo}' (centro {y_center:.2f}): {idx} cuadros, grupos de 2-4 palabras, tiempos reales")

    inputs = ["-i", video_base]
    for png, _, _ in overlays:
        inputs += ["-i", png]
    fc, prev = [], "[0:v]"
    for i, (png, on, off) in enumerate(overlays):
        nxt = f"[v{i}]"
        fc.append(f"{prev}[{i+1}:v]overlay=x=(W-w)/2:y={y_top}:enable='between(t,{on:.3f},{off:.3f})'{nxt}")
        prev = nxt
    outp = outdir / "corte-base-SUBS.mp4"
    total = VOICE_LEAD + beats[-1]["t1"]
    r = _run(["ffmpeg","-y","-loglevel","error"] + inputs +
             ["-filter_complex", ";".join(fc), "-map", prev, "-map", "0:a:0",
              "-c:v","libx264","-preset","medium","-crf","19","-pix_fmt","yuv420p",
              "-r", FPS, "-c:a","copy", "-t", f"{total:.3f}", outp])
    if r.returncode != 0:
        raise RuntimeError(f"karaoke overlay: {r.stderr[-400:]}")
    # SRT (por frase, con el lead)
    def ts(x):
        h=int(x//3600); m=int((x%3600)//60); s=x%60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
    with open(outdir / "subtitulos.srt", "w") as f:
        for i, (b, p) in enumerate(zip(beats, plan), 1):
            f.write(f"{i}\n{ts(VOICE_LEAD+b['seg_start'])} --> {ts(VOICE_LEAD+b['seg_end'])}\n{p['caption']}\n\n")
    return outp

# ------------------------------------------------------------------ overlays extra
def aplicar_overlays_extra(video_path, items, workdir):
    """Quema overlays PNG de agentes sobre el video (end-card, hook-banner…).
    items: [(png_path, t_on, t_off, y, fade_in_s)] — y en px desde arriba (0 = pegado).
    Reemplaza el archivo original. Un solo pase de ffmpeg para todos."""
    items = [(p, a, b, y, f) for (p, a, b, y, f) in items if p and Path(p).exists()]
    if not items:
        return video_path
    video_path = Path(video_path)

    def _nframes(p):
        r = _run(["ffprobe","-v","error","-count_frames","-select_streams","v:0",
                  "-show_entries","stream=nb_read_frames","-of","csv=p=0",p])
        try:
            return max(1, int(r.stdout.strip()))
        except Exception:
            return 1

    r = _run(["ffprobe","-v","error","-show_entries","format=duration",
              "-of","default=noprint_wrappers=1:nokey=1",video_path])
    try:
        dur_total = float(r.stdout.strip())
    except Exception:
        dur_total = 0.0

    inputs = ["-i", video_path]
    for (p, _, _, _, _) in items:
        inputs += ["-i", p]
    fc, prev = [], "[0:v]"
    for i, (p, ton, toff, y, fade) in enumerate(items):
        pre = f"[{i+1}:v]"
        # GOTCHA (cazado por el agente hook-banner): un PNG estático es UN frame en t=0;
        # el fade alpha lo agarra transparente y overlay repite ese frame invisible todo
        # el video. Se clona el frame en un stream continuo ANTES del fade. Los APNG
        # animados (nframes>1) pasan tal cual.
        if _nframes(p) == 1:
            pre += "loop=loop=-1:size=1:start=0,"
        pre += "format=rgba"
        if fade and fade > 0:
            pre += f",fade=t=in:st={ton:.3f}:d={fade:.3f}:alpha=1"
        fc.append(pre + f"[o{i}]")
        nxt = f"[v{i}]"
        fc.append(f"{prev}[o{i}]overlay=x=(W-w)/2:y={y}:enable='between(t,{ton:.3f},{toff:.3f})'{nxt}")
        prev = nxt
    tmp = Path(workdir) / ("extra_" + video_path.name)
    cmd = (["ffmpeg","-y","-loglevel","error"] + inputs +
           ["-filter_complex", ";".join(fc), "-map", prev, "-map", "0:a:0",
            "-c:v","libx264","-preset","medium","-crf","19","-pix_fmt","yuv420p",
            "-c:a","copy"] + (["-t", f"{dur_total:.3f}"] if dur_total > 0 else []) + [tmp])
    r = _run(cmd)
    if r.returncode != 0 or not tmp.exists():
        raise RuntimeError(f"overlays extra: {r.stderr[-300:]}")
    tmp.replace(video_path)
    return video_path

# ------------------------------------------------------------------ API
def build(outdir, workdir, audio_path, beats, plan, clips_map, words, log=print, seed=0,
          musica_path=None, estilo_subs="karaoke", plataforma="meta", opts=None):
    """Defaults = comportamiento de siempre (sin música, karaoke, Meta, sin agentes).
    opts (agentes opcionales): {"encuadre":True, "emojis":False, "endcard":False,
    "hookbanner":False, "hookbanner_texto":""} — cada agente vive en backend/agentes/."""
    from backend.agentes import cargar
    opts = opts or {}
    outdir, workdir = Path(outdir), Path(workdir)
    outdir.mkdir(parents=True, exist_ok=True); workdir.mkdir(parents=True, exist_ok=True)
    if estilo_subs not in ESTILOS_SUBS:
        estilo_subs = "karaoke"
    y_center = PLATAFORMA_Y.get(str(plataforma or "meta").lower(), SUBS_Y_CENTER)
    movs = asignar_movimiento(plan)
    trans = _transiciones(len(beats), seed)
    n_hard = sum(1 for d in trans if d == XFADE_D_HARD)
    log(f"🎬 Motor PRO v2: {len(beats)} planos · dissolve 0.17s + {n_hard} cortes casi-duros · "
        f"movimiento {'/'.join(sorted(set(movs)))}")
    segs = render_segmentos(beats, plan, movs, clips_map, trans, workdir, log,
                            encuadre=opts.get("encuadre", True))
    video = unir_con_dissolves(segs, beats, trans, workdir)
    base = mezclar_audio(video, audio_path, beats, plan, outdir, workdir, log,
                         musica_path=musica_path)
    subs = karaoke(base, beats, plan, words, outdir, workdir, log,
                   estilo=estilo_subs, y_center=y_center, opts=opts)

    # 🤖 overlays de agentes (end-card / hook-banner) sobre el video CON subtítulos
    total = VOICE_LEAD + beats[-1]["t1"]
    extra = []
    if opts.get("endcard"):
        mod = cargar("endcard")
        if mod is None:
            log("🤖 Agente end-card marcado pero el módulo no está — sigo sin end-card")
        else:
            try:
                png = mod.generar(outdir=outdir, workdir=workdir, beats=beats, plan=plan,
                                  video_base=base)
                if png:
                    extra.append((png, max(0.0, total - 1.8), total, 0, 0.25))
                    log("🤖 Agente end-card: cierre CTA en los últimos 1.8s")
            except Exception as ex:
                log(f"🤖 Agente end-card falló ({ex}) — sigo sin end-card")
    if opts.get("hookbanner"):
        mod = cargar("hookbanner")
        texto = (opts.get("hookbanner_texto") or "").strip()
        if mod is None:
            log("🤖 Agente hook-banner marcado pero el módulo no está — sigo sin banner")
        elif not texto:
            log("🤖 Agente hook-banner: sin texto del banner — sigo sin banner")
        else:
            try:
                png = mod.generar(texto=texto, workdir=workdir)
                if png:
                    fin = VOICE_LEAD + beats[min(1, len(beats)-1)]["t1"]
                    extra.append((png, 0.0, fin, int(H*0.16), 0.15))
                    log(f"🤖 Agente hook-banner: “{texto}” sobre el gancho")
            except Exception as ex:
                log(f"🤖 Agente hook-banner falló ({ex}) — sigo sin banner")
    if extra:
        aplicar_overlays_extra(subs, extra, workdir)
    return base, subs
