"""momentos.py — Agente 🤖: detector de mejores in-points antes de que Claude decida.

Porta el prototipo validado en research/prototipos/inpoint_detect.py (ver también
research/MEJORAS-FUTURAS.md, sección 5). La idea NO es reemplazar a Claude sino
darle mejores opciones: proponer candidatos locales baratos y extraer los frames AHÍ
(en vez de en las fracciones fijas 15/45/80%). Claude sigue teniendo la última palabra.

Método (2 sondas ffprobe a fps=5 sobre frames reducidos a 192px, EN PARALELO,
~1-3s por clip):
  1. MOVIMIENTO: tblend=all_mode=difference + signalstats → YAVG = energía de cambio.
  2. CONTENIDO + ESCENAS: signalstats → YAVG (brillo) + YHIGH ("hay algo visible")
     + scene_score en el mismo paso (select=gte(scene,-1)) para sembrar arranques
     de plano sin una tercera decodificación.
Dos ajustes de rendimiento vs el prototipo (que usaba 3 sondas seriales a full-res y
con clips largos de 1080p se pasaba del presupuesto de 5s, sobre todo con el Mac
cargado): sondas en paralelo y scale=192 antes de analizar. Validado contra el
prototipo full-res en los 4 clips de prueba: mismos candidatos salvo desvíos menores
(un pick ±0.6s, un pick alterno igual de bueno) y la alarma de Clip_04 dispara igual.

Score de cada candidato = movimiento medio en la ventana siguiente (1.5s ≈ un beat)
menos castigos por: arrancar sin contenido visible (YHIGH bajo vs p95 del propio clip),
negro casi absoluto, quemado, arrancar EN plena transición (movimiento en t0 > p75)
o caer a <1.5s del final.

LÍMITE HONESTO (documentado por el investigador): en animaciones oscuras con fades
(caso Clip_04) los picos de movimiento SON los fades y ningún método ciego acierta
solo. La señal de alarma: si TODOS los candidatos salen con 'contenido' bajo (<40),
este módulo devuelve None y el pipeline cae a las fracciones fijas para que Claude
decida viendo los frames. Por eso este agente solo PROPONE, nunca decide.
"""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

FPS_SONDA = 5.0        # fps de muestreo de las sondas
ANCHO_SONDA = 192      # px: analizar frames reducidos (~3x más rápido, mismos scores)
VENTANA = 1.5          # s de ventana de evaluación (≈ un beat)
SCENE_TH = 0.20        # umbral de escena SOBRE EL STREAM A 5FPS (equivale al 0.30 a
                       # full-fps del prototipo: calibrado contra los mismos clips —
                       # a 5fps los scores salen más bajos; las semillas extra no
                       # dañan porque la puntuación las filtra)
TIMEOUT_SONDA = 4.5    # s máximo por sonda (van en paralelo → tope ~4.7s por clip)
CONTENIDO_MIN = 40.0   # YHIGH mínimo: si TODOS los candidatos quedan debajo → None


# ---------------------------------------------------------------- sondas ffprobe
def _ruta_filtro(path):
    """Escapa la ruta para el filtro movie= de lavfi (comillas simples estilo ffmpeg)."""
    return "'" + str(path).replace("\\", "\\\\").replace("'", "'\\''") + "'"


def _sonda_movimiento(path):
    """[(t, YAVG del difference)] = energía de cambio frame a frame a 5fps."""
    cmd = ["ffprobe", "-v", "error", "-f", "lavfi",
           "-i", f"movie={_ruta_filtro(path)},fps={FPS_SONDA:g},scale={ANCHO_SONDA}:-2,"
                 "tblend=all_mode=difference,signalstats",
           "-show_entries", "frame=pts_time:frame_tags=lavfi.signalstats.YAVG",
           "-of", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SONDA)
    frames = json.loads(r.stdout or '{"frames":[]}').get("frames", [])
    out = []
    for f in frames:
        try:
            out.append((float(f["pts_time"]), float(f["tags"]["lavfi.signalstats.YAVG"])))
        except (KeyError, ValueError):
            continue
    return out


def _sonda_contenido(path):
    """[(t, YAVG, YHIGH, scene_score)] a 5fps: brillo, 'hay contenido visible' y
    score de escena, todo en UNA decodificación (select=gte(scene,-1) deja pasar
    todos los frames pero obliga a calcular el scene_score)."""
    cmd = ["ffprobe", "-v", "error", "-f", "lavfi",
           "-i", f"movie={_ruta_filtro(path)},fps={FPS_SONDA:g},scale={ANCHO_SONDA}:-2,"
                 "select=gte(scene\\,-1),signalstats",
           "-show_entries", "frame=pts_time:frame_tags=lavfi.signalstats.YAVG,"
                            "lavfi.signalstats.YHIGH,lavfi.scene_score",
           "-of", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SONDA)
    frames = json.loads(r.stdout or '{"frames":[]}').get("frames", [])
    out = []
    for f in frames:
        try:
            tags = f["tags"]
            out.append((float(f["pts_time"]),
                        float(tags["lavfi.signalstats.YAVG"]),
                        float(tags["lavfi.signalstats.YHIGH"]),
                        float(tags.get("lavfi.scene_score", 0.0))))
        except (KeyError, ValueError):
            continue
    return out


def _sondear(path):
    """Corre las 2 sondas EN PARALELO (cada una con timeout) para no pasar de ~5s/clip.
    Devuelve (mov, bri, escenas): bri = [(t, YAVG, YHIGH)], escenas = [t de corte]."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_mov = pool.submit(_sonda_movimiento, path)
        f_con = pool.submit(_sonda_contenido, path)
        mov = f_mov.result()          # si truena/expira, propaga → candidatos() → None
        con = f_con.result()
    bri = [(t, ya, yh) for t, ya, yh, _ in con]
    escenas = [t for t, _, _, sc in con if sc > SCENE_TH]
    return mov, bri, escenas


# ---------------------------------------------------------------- puntuación
def _puntuar(mov, bri, escenas, dur_util):
    """Puntúa cada semilla (inicio, arranques de escena, picos de movimiento).
    Devuelve [(score, t0, contenido)] por score desc — lógica portada tal cual
    del prototipo validado."""

    def mov_ventana(t0):
        vals = [y for t, y in mov if t0 + 0.2 <= t < t0 + VENTANA]
        return sum(vals) / len(vals) if vals else 0.0

    def mov_en(t0):
        vals = [y for t, y in mov if abs(t - t0) <= 0.25]
        return max(vals) if vals else 0.0

    def brillo_en(t0):
        vals = [y for t, y, _ in bri if abs(t - t0) <= 0.4]
        return sum(vals) / len(vals) if vals else 128.0

    def contenido_en(t0):
        """min de YHIGH en los primeros 0.6s: si cae, el plano arranca vacío/en fade."""
        vals = [yh for t, _, yh in bri if t0 <= t <= t0 + 0.6]
        return min(vals) if vals else 128.0

    ys = sorted(yh for _, _, yh in bri)
    # referencia de 'contenido visible': p95 del propio clip (en clips de animación
    # el 75-90% de los frames son gaps oscuros → p75/p90 no sirven de referencia)
    yh_p95 = ys[int(len(ys) * 0.95)] if ys else 128.0
    ms = sorted(y for _, y in mov)
    m_p75 = ms[int(len(ms) * 0.75)] if ms else 10.0   # p75 de movimiento del clip

    # semillas: inicio, arranques de escena (+0.2s de colchón) y picos locales de movimiento
    semillas = {0.0}
    for t in escenas:
        semillas.add(round(t + 0.2, 2))
    for i in range(1, len(mov) - 1):
        t, y = mov[i]
        if y > mov[i - 1][1] and y >= mov[i + 1][1] and y > 4.0:
            semillas.add(round(max(0.0, t - 0.3), 2))  # arrancar justo antes del pico

    scored = []
    for t0 in sorted(semillas):
        if t0 > dur_util - VENTANA:                    # no caer al final sin material
            continue
        m = mov_ventana(t0)
        b = brillo_en(t0)
        yh = contenido_en(t0)
        pen = 0.0
        # castigo por arrancar sin contenido visible (gap/fade de animaciones, negro)
        umbral = max(0.45 * yh_p95, 26.0)
        if yh < umbral:
            pen += 12.0 * (umbral - yh) / umbral
        if b < 24: pen += 6.0                          # negro casi absoluto: fuera
        if b > 225: pen += 4.0                         # quemado
        # castigo por arrancar EN plena transición/movimiento brusco
        m0 = mov_en(t0)
        if m0 > m_p75:
            pen += 0.5 * (m0 - m_p75)
        scored.append((m - pen, t0, yh))
    scored.sort(reverse=True)
    return scored


# ---------------------------------------------------------------- selección
def _alarma_sin_contenido(scored, n):
    """True si los top-N candidatos (de-dup a >1.2s, como devolvía el prototipo)
    arrancan TODOS sin contenido visible (YHIGH < 40) → animación oscura con fades
    (caso Clip_04): el detector no es confiable y debe decidir Claude."""
    top = []
    for _s, t0, yh in scored:                          # ya vienen por score desc
        if all(abs(t0 - t) > 1.2 for t, _ in top):
            top.append((t0, yh))
        if len(top) >= n:
            break
    return bool(top) and all(yh < CONTENIDO_MIN for _t, yh in top)


def _seleccionar(scored, dur, n):
    """Aplica las reglas del contrato: 3-5 candidatos en [0.1, dur-0.5], separados
    al menos dur/8, con al menos uno del primer tercio (ahí suele estar el gancho)."""
    sep = dur / 8.0
    t_min, t_max = 0.1, dur - 0.5
    primer_tercio = dur / 3.0

    # candidatos clampeados al rango del contrato, mejores primero, sin duplicados
    pool, vistos = [], set()
    for _s, t0, _yh in scored:                         # ya vienen por score desc
        t = round(min(max(t0, t_min), t_max), 2)
        if t not in vistos:
            vistos.add(t)
            pool.append(t)

    elegidos = []
    # 1) asegurar el gancho: el mejor candidato del primer tercio entra primero
    for t in pool:
        if t <= primer_tercio:
            elegidos.append(t)
            break
    # 2) greedy por score respetando la separación mínima
    for t in pool:
        if len(elegidos) >= n:
            break
        if all(abs(t - e) >= sep for e in elegidos):
            elegidos.append(t)
    # 3) si el detector no juntó 3, rellenar con fracciones fijas compatibles
    if len(elegidos) < 3:
        for fr in (0.15, 0.45, 0.80, 0.30, 0.62):
            t = round(min(max(dur * fr, t_min), t_max), 2)
            if all(abs(t - e) >= sep for e in elegidos):
                elegidos.append(t)
            if len(elegidos) >= 3:
                break
    if len(elegidos) < 3:
        return None
    return sorted(float(t) for t in elegidos[:n])


# ---------------------------------------------------------------- API del agente
def candidatos(clip_path, dur: float) -> list[float] | None:
    """Devuelve 3-5 timestamps (segundos, floats) de los mejores instantes del clip,
    ordenados cronológicamente, o None si el análisis no es confiable (el pipeline
    entonces usa fracciones fijas). Máximo ~5s de cómputo por clip. Nunca lanza."""
    try:
        dur = float(dur)
        if dur < 1.2:                                  # muy corto para 3 cortes útiles
            return None
        mov, bri, escenas = _sondear(str(clip_path))
        if len(mov) < 5 or len(bri) < 5:               # sondas vacías/rotas → no confiable
            return None
        # dur útil: el mínimo entre lo que dice el pipeline y lo que midió la sonda
        dur_util = min(dur, mov[-1][0])
        scored = _puntuar(mov, bri, escenas, dur_util)
        if not scored:
            return None
        # ALARMA (límite documentado): si los mejores candidatos arrancan TODOS sin
        # contenido visible (animación oscura con fades, caso Clip_04) el detector no
        # es confiable → None, y que Claude decida viendo los frames de las fracciones.
        n = 3 if dur < 8 else (4 if dur <= 30 else 5)   # cuántos proponer (contrato: 3-5)
        if _alarma_sin_contenido(scored, n):
            return None
        return _seleccionar(scored, dur, n)
    except Exception:
        return None
