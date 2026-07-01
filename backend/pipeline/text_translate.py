"""Traducir el TEXTO EN PANTALLA de un video ganador a español colombiano.

Muchos ads (sobre todo gringos) llevan texto quemado en el video
("This fixed my back pain", "Before / After", "Link in bio"...). Hoy
`text_detect.py` (de Juan) solo lo TAPA con blur (queda un borrón). Este módulo va
más allá y NO reemplaza a ese: es una alternativa "traducir" en vez de "tapar":

  1. LEE el texto en pantalla con Gemini (multimodal) + su posición y tiempos.
  2. Lo TRADUCE a español colombiano natural.
  3. TAPA el original con un rectángulo del color de fondo que combine.
  4. Escribe el texto traducido encima (Pillow → PNG → overlay de FFmpeg).

Así el creativo queda 100% en español (no solo la voz). Terreno propio: NO toca
`text_detect.py`. Reusa el patrón de fuentes de `text_overlay.py`, Gemini (como
narrative.py) y `ffmpeg_utils`. Gemini + FFmpeg (no Anthropic). Degrada sin key.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .ffmpeg_utils import run, probe

_MODEL = "gemini-2.5-flash"

# Poppins (marca de la app) primero; luego fallback multiplataforma
_ASSETS_FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets", "fonts")
_FONTS = [
    os.path.join(_ASSETS_FONTS, "Poppins-ExtraBold.ttf"),
    os.path.join(_ASSETS_FONTS, "Poppins-Bold.ttf"),
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

_UPLOAD_TIMEOUT = 120
_POLL_EVERY = 2


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in _FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _prompt(duration: float) -> str:
    dur = f"{int(duration // 60):02d}:{int(duration % 60):02d}"
    return (
        "Eres un experto en localización de anuncios. Te doy un video-anuncio que dura "
        f"{dur}. Encuentra TODO el TEXTO QUEMADO EN PANTALLA (captions, títulos, "
        "'before/after', 'link in bio', ofertas, etc.). NO transcribas el audio, solo el "
        "texto VISIBLE. Para cada bloque de texto devuelve su traducción al ESPAÑOL "
        "COLOMBIANO natural (adáptalo a marketing, no literal), su posición y sus tiempos.\n"
        "Devuelve SOLO un JSON válido (array), sin texto extra, con esta forma:\n"
        '[{"texto":"This fixed my back pain","es_colombia":"Esto me quitó el dolor de espalda",'
        '"x":0.1,"y":0.8,"w":0.8,"h":0.08,"inicio":"00:01","fin":"00:04",'
        '"fondo":"#000000","texto_color":"#FFFFFF"}, ...]\n'
        "Reglas:\n"
        "- x,y,w,h en FRACCIÓN del ancho/alto del video (0..1); x,y = esquina superior izquierda "
        "de la caja del texto. Sé generoso con la caja para tapar bien el original.\n"
        "- fondo: color con el que taparías el original para que combine (hex). Si el texto está "
        "sobre fondo claro usa uno claro; si oscuro, oscuro. texto_color: color legible encima.\n"
        "- inicio/fin en mm:ss (cuándo aparece y desaparece ese texto).\n"
        "- Si NO hay texto quemado, devuelve []."
    )


def _parse_array(text: str) -> list[dict] | None:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def _mmss(v) -> float:
    try:
        parts = str(v).strip().split(":")
        if len(parts) > 3 or not parts:
            return 0.0
        return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))
    except (ValueError, TypeError):
        return 0.0


def _hex(c: str, default: tuple) -> tuple:
    """'#RRGGBB' -> (r,g,b). Robusto: si viene mal, usa default."""
    try:
        s = str(c).lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except (ValueError, TypeError):
        pass
    return default


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    """Parte el texto en líneas que quepan en max_w px."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def _render_solid(box_w: int, box_h: int, bg: tuple, out_png: str) -> None:
    """PNG de relleno SÓLIDO (modo 'tapar': cubre el texto sin escribir nada encima)."""
    box_w, box_h = max(8, box_w), max(8, box_h)
    Image.new("RGBA", (box_w, box_h), bg + (255,)).save(out_png)


def _region_color_rgb(cap, t_sec, x, y, w, h, default_rgb):
    """Muestrea el color MEDIANO real de la zona del video (para que el relleno sólido combine).

    Devuelve (r,g,b). Si no se puede leer, usa `default_rgb`. La mediana ignora el texto
    (minoría de píxeles), así que da el color del fondo detrás del texto.
    """
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(t_sec)) * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            return default_rgb
        Hf, Wf = frame.shape[:2]
        x0, y0 = max(0, min(int(x), Wf - 1)), max(0, min(int(y), Hf - 1))
        x1, y1 = max(x0 + 1, min(int(x + w), Wf)), max(y0 + 1, min(int(y + h), Hf))
        med = np.median(frame[y0:y1, x0:x1].reshape(-1, 3), axis=0)   # BGR
        return (int(med[2]), int(med[1]), int(med[0]))                # -> RGB
    except Exception:
        return default_rgb


def _render_block(text: str, box_w: int, box_h: int, bg: tuple, fg: tuple, out_png: str) -> None:
    """Dibuja un PNG del tamaño de la caja: fondo relleno + texto traducido centrado y ajustado."""
    # Quitar emojis que Poppins no tiene (salían como cuadrito □)
    text = re.sub("[\U0001F000-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF"
                  "\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF\U0000FE0F\U00002190-\U000021FF]",
                  "", text or "").strip()
    box_w, box_h = max(8, box_w), max(8, box_h)
    img = Image.new("RGBA", (box_w, box_h), bg + (255,))
    draw = ImageDraw.Draw(img)
    # Buscar el tamaño de fuente más grande que quepa (alto y ancho)
    size = max(10, int(box_h * 0.8))
    pad = max(4, int(box_w * 0.03))
    while size >= 10:
        font = _font(size)
        lines = _wrap(draw, text, font, box_w - 2 * pad)
        line_h = (font.getbbox("Ag")[3] - font.getbbox("Ag")[1]) + 4
        total_h = line_h * len(lines)
        widest = max((draw.textlength(ln, font=font) for ln in lines), default=0)
        if total_h <= box_h - 2 * pad and widest <= box_w - 2 * pad:
            break
        size -= 2
    y = (box_h - total_h) // 2
    for ln in lines:
        w = draw.textlength(ln, font=font)
        draw.text(((box_w - w) // 2, y), ln, font=font, fill=fg + (255,))
        y += line_h
    img.save(out_png)


def _upload_video(client, path: str, progress):
    """Sube el video a Gemini y espera a que esté ACTIVE (como en narrative.py)."""
    f = client.files.upload(file=path)
    waited = 0
    while waited < _UPLOAD_TIMEOUT:
        state = str(getattr(f, "state", "") or "")
        if "ACTIVE" in state:
            return f
        if "FAILED" in state:
            return None
        if progress:
            progress("Gemini está procesando el video...", 25)
        time.sleep(_POLL_EVERY); waited += _POLL_EVERY
        f = client.files.get(name=f.name)
    return f if "ACTIVE" in str(getattr(f, "state", "") or "") else None


def traducir_texto_pantalla(
    video_path: str, *,
    api_key: str | None = None,
    out_path: str | None = None,
    progress: Callable[[str, int], None] | None = None,
    modo: str = "traducir",   # "traducir" (reescribe en es-CO) | "tapar" (relleno sólido)
) -> dict:
    """Lee el texto en pantalla y lo reemplaza sobre el video (traducido o tapado sólido).

    Gemini DETECTA el texto quemado (entiende texto vs caras/casas, a diferencia de EAST).
    `modo="traducir"` reescribe en español colombiano; `modo="tapar"` lo cubre con un relleno
    sólido (mismo detector inteligente, solo cambia lo que se pinta en la caja).

    Devuelve {"ok":True,"bloques":[...],"video":ruta}  (video = el mismo si no hay texto),
    o {"ok":False,"error":...}. Nunca lanza (para no romper el pipeline).
    """
    def report(m, p):
        if progress:
            progress(m, p)

    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {"ok": False, "error": "Falta la API key de Gemini."}
    try:
        info = probe(video_path)
        W, H, dur = info.width, info.height, info.duration
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"No se pudo leer el video: {e}"}

    out_path = out_path or os.path.splitext(video_path)[0] + "_es.mp4"
    work = out_path + ".d"
    os.makedirs(work, exist_ok=True)

    # 1) Detectar + traducir el texto en pantalla (una llamada a Gemini)
    uploaded = None
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        report("Subiendo el video a Gemini...", 10)
        uploaded = _upload_video(client, video_path, progress)
        if uploaded is None:
            return {"ok": False, "error": "Gemini no pudo procesar el video."}
        report("Leyendo y traduciendo el texto en pantalla...", 45)
        current = client.files.get(name=uploaded.name)
        resp = client.models.generate_content(model=_MODEL, contents=[current, _prompt(dur)])
        bloques = _parse_array(resp.text or "") or []
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Error leyendo el texto: {e}"}
    finally:
        if uploaded is not None:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    if not bloques:
        report("No hay texto en pantalla que traducir", 100)
        return {"ok": True, "bloques": [], "video": video_path}

    # 2) Renderizar un PNG por bloque (fondo que tapa + texto traducido)
    report(f"Traduciendo {len(bloques)} bloque(s) de texto en pantalla...", 70)
    inputs, filt, last = ["-i", video_path], [], "[0:v]"
    cap_s = cv2.VideoCapture(video_path) if modo == "tapar" else None   # para muestrear color real
    n = 0
    for b in bloques:
        es = str(b.get("es_colombia", "")).strip()
        if modo == "traducir" and not es:   # en "tapar" cubrimos aunque no haya traducción
            continue
        bw, bh = int(float(b.get("w", 0.5)) * W), int(float(b.get("h", 0.1)) * H)
        bx, by = int(float(b.get("x", 0)) * W), int(float(b.get("y", 0)) * H)
        # Margen de seguridad GENEROSO: la caja debe tapar el original ENTERO (Gemini estima la
        # caja justa y el texto real suele ser más alto/ancho). Sin esto se asoman bordes.
        mx, my = int(bw * 0.14) + 18, int(bh * 0.6) + 20
        bx, by = max(0, bx - mx), max(0, by - my)
        bw, bh = min(W - bx, bw + 2 * mx), min(H - by, bh + 2 * my)
        bg = _hex(b.get("fondo"), (255, 255, 255))
        fg = _hex(b.get("texto_color"), (0, 0, 0))
        png = os.path.join(work, f"b{n}.png")
        if modo == "tapar":
            # color REAL de la zona (mediana) para que el relleno sólido combine con el fondo
            fill = _region_color_rgb(cap_s, _mmss(b.get("inicio", 0)), bx, by, bw, bh, bg)
            _render_solid(bw, bh, fill, png)
        else:
            _render_block(es, bw, bh, bg, fg, png)  # reescribe la traducción
        inputs += ["-i", png]
        s, e = _mmss(b.get("inicio", 0)), _mmss(b.get("fin", dur))
        if e <= s:
            e = dur
        tag = f"[v{n}]"
        filt.append(f"{last}[{n + 1}:v]overlay={bx}:{by}:enable='between(t,{s:.2f},{e:.2f})'{tag}")
        last = tag
        n += 1
    if cap_s is not None:
        cap_s.release()

    if n == 0:
        return {"ok": True, "bloques": [], "video": video_path}

    # 3) Aplicar todos los overlays sobre el video (audio intacto)
    report("Montando el texto traducido sobre el video...", 90)
    try:
        run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt),
             "-map", last, "-map", "0:a?", "-c:a", "copy",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Error montando el texto: {e}", "bloques": bloques}

    report("Texto en pantalla traducido", 100)
    return {"ok": True, "bloques": bloques, "video": out_path}


# --- CLI de prueba: python -m backend.pipeline.text_translate <video> ---
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m backend.pipeline.text_translate <video.mp4> [salida.mp4]")
        raise SystemExit(1)

    def _p(m, p):
        print(f"[{p:3d}%] {m}", file=sys.stderr)

    res = traducir_texto_pantalla(
        sys.argv[1], out_path=sys.argv[2] if len(sys.argv) > 2 else None, progress=_p)
    print(json.dumps({k: v for k, v in res.items() if k != "bloques"}, ensure_ascii=False, indent=2))
    for b in res.get("bloques", []):
        print(f'  · "{b.get("texto","")}"  →  "{b.get("es_colombia","")}"  '
              f'@({b.get("x")},{b.get("y")}) {b.get("inicio")}-{b.get("fin")}')
