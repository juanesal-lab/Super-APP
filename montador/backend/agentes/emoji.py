"""Agente EMOJI — emojis a color en los subtítulos karaoke (lista blanca).

Renderiza emojis con la fuente Apple Color Emoji de macOS
(/System/Library/Fonts/Apple Color Emoji.ttc). Es una fuente BITMAP con
"strikes" fijos: solo acepta size ∈ {20, 26, 32, 40, 48, 52, 64, 96, 160};
cualquier otro tamaño lanza "invalid pixel size". La receta validada
(ver research/MEJORAS-FUTURAS.md, sección 3) es:

  1. renderizar a 160 px (el strike más grande) con embedded_color=True,
  2. recortar al bbox real del glifo,
  3. reescalar con LANCZOS al alto pedido (ancho proporcional).

LISTA BLANCA obligatoria: Pillow NO hace shaping de secuencias — los emojis
con tono de piel (💪🏽 → cuadro de color suelto), las banderas (🇨🇴 no sale)
y las secuencias ZWJ salen ROTOS. Solo se aceptan emojis simples verificados
a ojo en el grid de prueba. ❤️ y ⚠️ llevan variation selector (U+FE0F): se
normaliza la entrada para aceptar ambas formas (con y sin FE0F).

Contrato (lo llama backend/editor.py vía backend.agentes.cargar("emoji")):
    emoji_png(ch, alto) -> PIL.Image RGBA de altura `alto` px.
    Lanza ValueError si ch no está en LISTA_BLANCA o no se puede renderizar.

Nada pesado corre al importar: la fuente y los renders se cachean lazy.
"""
from functools import lru_cache

RUTA_FUENTE = "/System/Library/Fonts/Apple Color Emoji.ttc"
STRIKE = 160          # strike bitmap más grande de la fuente (máxima nitidez)
FE0F = "\ufe0f"  # variation selector-16 (presentación emoji)

# Emojis simples VERIFICADOS a ojo en el grid (alto=83, fondo a cuadros y gris):
# todos salen nítidos, completos y con transparencia limpia. NO agregar tonos de
# piel, banderas ni secuencias ZWJ — salen rotos (Pillow no hace shaping).
LISTA_BLANCA = {
    # caras / reacciones
    "😱", "😴", "😍", "🤯", "🤩", "😭", "🥵",
    # energía / énfasis
    "🔥", "✨", "💥", "⚡", "🚀", "💤",
    # checks / avisos
    "✅", "❌", "⚠️",
    # dinero / compra / envío
    "💰", "💸", "🤑", "🚚", "📦", "🛒", "🎁",
    # gestos / cuerpo (base sin tono de piel)
    "👇", "💪", "🙌",
    # hogar / producto
    "❤️", "🧸", "🏠", "🌙", "⭐", "⏰", "🎯",
}


def _normalizar(ch: str) -> str:
    """Forma canónica de la entrada: sin espacios ni variation selectors.

    Así "❤" (U+2764) y "❤️" (U+2764 U+FE0F) cuentan como el MISMO emoji,
    igual que ⚠/⚠️. Apple Color Emoji dibuja idéntico con o sin FE0F
    (verificado: mismo bbox en ambas formas).
    """
    return (ch or "").strip().replace(FE0F, "")


# Lista blanca normalizada (sin FE0F) para comparar entradas.
_BLANCA_NORM = frozenset(_normalizar(e) for e in LISTA_BLANCA)


@lru_cache(maxsize=1)
def _fuente():
    """Carga (una sola vez) Apple Color Emoji en su strike de 160 px."""
    from PIL import ImageFont
    return ImageFont.truetype(RUTA_FUENTE, STRIKE)


@lru_cache(maxsize=128)
def _render_base(ch_norm: str):
    """Render maestro del emoji a 160 px, recortado a su bbox real (RGBA).

    Se cachea por emoji normalizado: el reescalado por `alto` es barato,
    lo caro (rasterizar el glifo bitmap) se hace una sola vez.
    """
    from PIL import Image, ImageDraw
    lienzo = STRIKE * 2 + 40  # margen holgado: ningún glifo se sale
    img = Image.new("RGBA", (lienzo, lienzo), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((lienzo // 2, lienzo // 2), ch_norm, font=_fuente(),
           embedded_color=True, anchor="mm")
    bbox = img.getbbox()
    if bbox is None:
        raise ValueError(f"el emoji {ch_norm!r} no produjo ningún pixel")
    return img.crop(bbox)


def emoji_png(ch: str, alto: int):
    """Devuelve PIL.Image RGBA del emoji `ch` con altura `alto` px (ancho proporcional).
    Lanza ValueError si ch no está en LISTA_BLANCA o no se puede renderizar."""
    from PIL import Image
    ch_norm = _normalizar(ch)
    if ch_norm not in _BLANCA_NORM:
        raise ValueError(f"emoji fuera de la lista blanca: {ch!r}")
    if not isinstance(alto, int) or alto <= 0:
        raise ValueError(f"alto inválido: {alto!r} (debe ser entero > 0)")
    try:
        base = _render_base(ch_norm)
    except ValueError:
        raise
    except Exception as e:  # fuente ausente, Pillow raro… → contrato: ValueError
        raise ValueError(f"no se pudo renderizar {ch!r}: {e}") from e
    ancho = max(1, round(base.width * alto / base.height))
    return base.resize((ancho, alto), Image.LANCZOS)
