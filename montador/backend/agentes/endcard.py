"""
endcard.py — Agente end-card CTA del Montador (receta validada en
research/MEJORAS-FUTURAS.md #4 y research/prototipos/endcard-muestra.png).

Genera un PNG 1080x1920 COMPLETO (con fondo incluido) que el editor quema como
overlay full-frame con fade-in de 0.25s sobre los últimos ~1.8s del video:
  · Fondo: último frame del video difuminado (GaussianBlur 30) + velo negro 62%.
  · Precio ancla (el MAYOR encontrado en los captions) tachado en gris.
  · Precio oferta (el MENOR) GIGANTE amarillo #FFDE00 con stroke negro grueso.
  · Línea COD blanca ("Paga al recibir · Envío GRATIS", según los captions).
  · Botón pill amarillo "PIDE LA TUYA" con texto negro y sombra sutil.

Contrato (lo llama editor.build cuando opts={"endcard": True}):
    generar(outdir, workdir, beats, plan, video_base) -> str | None
Devuelve la ruta de outdir/"endcard.png" o None si no hay datos suficientes
(ningún precio en los captions) o ante CUALQUIER problema. Jamás lanza.
"""
import re
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent   # raíz del repo
ASSETS = BASE / "assets"

# ------------------------------------------------------------------ diseño
W, H = 1080, 1920
AMARILLO = (255, 222, 0)        # #FFDE00 (mismo amarillo de los subtítulos karaoke)
BLANCO = (255, 255, 255)
NEGRO = (0, 0, 0)
GRIS_ANCLA = (201, 201, 201)    # gris del precio tachado en la muestra

BLUR_FONDO = 30                 # GaussianBlur del último frame (receta validada)
VELO_NEGRO = 0.62               # Image.blend(fondo, negro, 0.62) — muestra validada

# centros verticales (fracción de H) — calcados de endcard-muestra.png
Y_ANCLA, Y_OFERTA, Y_COD, Y_BOTON = 0.35, 0.45, 0.57, 0.64

SZ_ANCLA, SZ_OFERTA, SZ_COD, SZ_BOTON = 76, 190, 60, 68
STROKE_OFERTA = 12              # stroke negro grueso del precio gigante
TEXTO_BOTON = "PIDE LA TUYA"

# ------------------------------------------------------------------ precios
# Regex robusto para montos colombianos en los captions:
#   · "$139.900", "$ 280.000", "$139,900", "$139900"  (símbolo $ delante)
#   · "139.900 pesos", "139,900 pesos", "139900 COP"  (unidad detrás)
# Acepta punto O coma como separador de miles (los captions de whisper a veces
# salen con coma); un número "pelado" sin $ ni pesos/COP NO cuenta (evita falsos
# positivos tipo "50 y 100 micrones" o "3 centímetros").
_PRECIO_RE = re.compile(
    r"\$\s*(\d{1,3}(?:[.,]\d{3})+|\d{4,})"
    r"|(\d{1,3}(?:[.,]\d{3})+|\d{4,})\s*(?:pesos|cop)\b",
    re.IGNORECASE)

_COD_RE = re.compile(r"contra\s*entrega|paga[sr]?\s+al\s+recibir", re.IGNORECASE)
_ENVIO_RE = re.compile(r"env[ií]o\s+gratis", re.IGNORECASE)


def _montos_en_captions(plan):
    """Extrae los montos (int, en pesos) que aparecen en los captions del plan."""
    montos = []
    for p in plan:
        for m in _PRECIO_RE.finditer(str(p.get("caption") or "")):
            crudo = m.group(1) or m.group(2)
            try:
                valor = int(re.sub(r"[.,]", "", crudo))
            except ValueError:
                continue
            if valor >= 1000:           # un precio COD real jamás baja de $1.000
                montos.append(valor)
    return sorted(set(montos))


def _formato_cop(valor):
    """139900 → '$139.900' (formato colombiano con puntos de miles)."""
    return "$" + f"{valor:,}".replace(",", ".")


def _linea_cod(plan):
    """Arma la línea COD según lo que digan los captions; con default del negocio."""
    texto = " ".join(str(p.get("caption") or "") for p in plan)
    partes = []
    if _COD_RE.search(texto):
        partes.append("Paga al recibir")
    if _ENVIO_RE.search(texto):
        partes.append("Envío GRATIS")
    if not partes:                      # default del negocio (COD Colombia)
        partes = ["Paga al recibir", "Envío GRATIS"]
    return "  ·  ".join(partes)


# ------------------------------------------------------------------ fondo
def _ultimo_frame(video_base, workdir):
    """Extrae el último frame del video (ffmpeg -sseof). Devuelve Path o None."""
    destino = Path(workdir) / "endcard_bg.jpg"
    for sseof in ("-0.3", "-1.0", "-3.0"):
        destino.unlink(missing_ok=True)
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-sseof", sseof,
             "-i", str(video_base), "-frames:v", "1", "-update", "1",
             "-q:v", "2", str(destino)],
            capture_output=True, text=True)
        if r.returncode == 0 and destino.exists() and destino.stat().st_size > 0:
            return destino
    return None


# ------------------------------------------------------------------ dibujo
def _fuente(sz, extra=True):
    """Poppins ExtraBold/Bold con fallback (mismo criterio que editor._font)."""
    from PIL import ImageFont
    rutas = [ASSETS / "fonts" / ("Poppins-ExtraBold.ttf" if extra else "Poppins-Bold.ttf"),
             ASSETS / "fonts" / "Poppins-Bold.ttf",
             Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")]
    for ruta in rutas:
        try:
            return ImageFont.truetype(str(ruta), sz)
        except Exception:
            continue
    return ImageFont.load_default()


def _fuente_que_quepa(texto, sz, max_ancho, extra=True, stroke=0):
    """Baja el tamaño hasta que el texto quepa en max_ancho (precios largos)."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    while sz > 24:
        f = _fuente(sz, extra)
        bb = d.textbbox((0, 0), texto, font=f, stroke_width=stroke)
        if bb[2] - bb[0] <= max_ancho:
            return f
        sz -= 8
    return _fuente(sz, extra)


def _sombra_texto(img, xy, texto, fuente, stroke, radio, alfa, dy):
    """Sombra suave: el mismo texto en negro, desplazado y con blur, debajo."""
    from PIL import Image, ImageDraw, ImageFilter
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(capa).text((xy[0], xy[1] + dy), texto, font=fuente,
                              fill=(0, 0, 0, alfa), stroke_width=stroke,
                              stroke_fill=(0, 0, 0, alfa), anchor="mm")
    img.alpha_composite(capa.filter(ImageFilter.GaussianBlur(radio)))


def _componer(fondo, ancla_txt, oferta_txt, cod_txt):
    """Compone el end-card 1080x1920 sobre el fondo ya difuminado/oscurecido."""
    from PIL import Image, ImageDraw, ImageFilter
    img = fondo.convert("RGBA")
    d = ImageDraw.Draw(img)
    cx = W // 2

    # --- precio ancla tachado (solo si hay 2 montos distintos) ---
    if ancla_txt:
        f = _fuente_que_quepa(ancla_txt, SZ_ANCLA, W - 240)
        y = int(H * Y_ANCLA)
        _sombra_texto(img, (cx, y), ancla_txt, f, 0, 6, 110, 4)
        d = ImageDraw.Draw(img)
        d.text((cx, y), ancla_txt, font=f, fill=GRIS_ANCLA, anchor="mm")
        bb = d.textbbox((cx, y), ancla_txt, font=f, anchor="mm")
        grosor = max(6, f.size // 9)
        d.line([(bb[0] - 18, y), (bb[2] + 18, y)], fill=GRIS_ANCLA, width=grosor)

    # --- precio oferta GIGANTE amarillo con stroke negro ---
    f = _fuente_que_quepa(oferta_txt, SZ_OFERTA, W - 120, stroke=STROKE_OFERTA)
    y = int(H * Y_OFERTA)
    _sombra_texto(img, (cx, y), oferta_txt, f, STROKE_OFERTA, 16, 150, 12)
    d = ImageDraw.Draw(img)
    d.text((cx, y), oferta_txt, font=f, fill=AMARILLO, anchor="mm",
           stroke_width=STROKE_OFERTA, stroke_fill=NEGRO)

    # --- línea COD blanca ---
    f = _fuente_que_quepa(cod_txt, SZ_COD, W - 120)
    y = int(H * Y_COD)
    _sombra_texto(img, (cx, y), cod_txt, f, 0, 8, 130, 5)
    d = ImageDraw.Draw(img)
    d.text((cx, y), cod_txt, font=f, fill=BLANCO, anchor="mm")

    # --- botón pill amarillo con sombra sutil (rect negro +8/+14, blur 12) ---
    f = _fuente_que_quepa(TEXTO_BOTON, SZ_BOTON, W - 420)
    y = int(H * Y_BOTON)
    bb = d.textbbox((cx, y), TEXTO_BOTON, font=f, anchor="mm")
    pad_x, pad_y = 100, 34
    caja = (bb[0] - pad_x, bb[1] - pad_y, bb[2] + pad_x, bb[3] + pad_y)
    radio = (caja[3] - caja[1]) // 2                      # pill: radio = mitad del alto
    sombra = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle(
        (caja[0] + 8, caja[1] + 14, caja[2] + 8, caja[3] + 14),
        radius=radio, fill=(0, 0, 0, 150))
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(caja, radius=radio, fill=AMARILLO)
    d.text((cx, y), TEXTO_BOTON, font=f, fill=NEGRO, anchor="mm")

    return img.convert("RGB")


# ------------------------------------------------------------------ API
def generar(outdir, workdir, beats, plan, video_base):
    """Genera el end-card 1080x1920 y devuelve la ruta del PNG (str), o None si
    no hay datos suficientes (p.ej. ningún precio en los captions). Nunca lanza:
    ante cualquier problema devuelve None."""
    try:
        return _generar(Path(outdir), Path(workdir), list(plan or []), video_base)
    except Exception:
        return None


def _generar(outdir, workdir, plan, video_base):
    montos = _montos_en_captions(plan)
    if not montos:                       # sin precio no hay end-card
        return None
    if len(montos) >= 2:
        ancla_txt = "ANTES " + _formato_cop(montos[-1])   # el mayor, tachado
        oferta = montos[0]                                # el menor, gigante
    else:
        ancla_txt, oferta = None, montos[0]

    frame = _ultimo_frame(video_base, workdir)
    if frame is None:
        return None

    from PIL import Image, ImageFilter, ImageOps
    fondo = ImageOps.fit(Image.open(frame).convert("RGB"), (W, H),
                         Image.Resampling.LANCZOS)
    fondo = fondo.filter(ImageFilter.GaussianBlur(BLUR_FONDO))
    fondo = Image.blend(fondo, Image.new("RGB", (W, H), NEGRO), VELO_NEGRO)

    img = _componer(fondo, ancla_txt, _formato_cop(oferta), _linea_cod(plan))
    destino = outdir / "endcard.png"
    outdir.mkdir(parents=True, exist_ok=True)
    img.save(destino)
    return str(destino)
