"""Variar imagen GANADORA.

Jack sube UNA imagen que le funcionó y la app devuelve variaciones que MANTIENEN el
mismo producto y el mismo ÁNGULO de cámara, pero cambian el "tipo" de imagen:
  - estilo    : el mismo producto como distintos formatos de anuncio (UGC, estudio, primer
                plano, flat-lay, lifestyle en uso, antes/después).
  - escenario : el mismo producto en distintos ambientes (casa, en la mano, exterior, baño,
                fondo de color).
  - fondo     : cambios suaves (solo el fondo, la luz o el color) sin reinventar la escena.

Reusa Nano Banana (Google AI, image-to-image) igual que disruptive_images.py.
Barato por defecto (Nano Banana 1). Pedido de Jack (2026-07-06).
"""
import os

_IMG_MODEL_DRAFT = "gemini-2.5-flash-image"     # Nano Banana 1  (~$0.04/imagen)
_IMG_MODEL_PRO = "gemini-3-pro-image-preview"   # Nano Banana 2  (~$0.13/imagen)

# Recetas de variación. Cada `instr` describe SOLO qué cambia; el producto + ángulo se
# preservan en el prompt base (_editar_variacion). `grupo` = estilo | escenario | fondo.
_RECETAS = [
    # ---------- ESTILOS DE ANUNCIO ----------
    {"grupo": "estilo", "nombre": "UGC de celular",
     "instr": "Make it look like a casual real-customer photo shot on a smartphone: natural "
              "window light, everyday hand-held feel, slightly imperfect and authentic (not a "
              "polished studio shot)."},
    {"grupo": "estilo", "nombre": "Estudio profesional",
     "instr": "Make it a clean professional studio product shot: seamless neutral backdrop, soft "
              "diffused softbox lighting, premium high-end e-commerce look."},
    {"grupo": "estilo", "nombre": "Primer plano macro",
     "instr": "Make it an extreme close-up / macro shot that highlights the product's texture and "
              "material detail, shallow depth of field, product filling most of the frame."},
    {"grupo": "estilo", "nombre": "Flat-lay desde arriba",
     "instr": "Make it a top-down flat-lay: the product photographed from directly above on a flat "
              "surface, with a few tasteful complementary props arranged around it."},
    {"grupo": "estilo", "nombre": "Lifestyle en uso",
     "instr": "Show the product being used in a real everyday moment by a person (hands or partial "
              "person), aspirational lifestyle feel, natural light."},
    {"grupo": "estilo", "nombre": "Antes / después",
     "instr": "Compose it as a subtle before/after transformation that suggests the product's "
              "benefit (one side dull/problem, other side improved), keeping the product visible as "
              "the hero. If a before/after does not fit, just show the product with a clear result cue."},
    # ---------- ESCENARIOS / FONDOS ----------
    {"grupo": "escenario", "nombre": "En casa (mesa/cocina)",
     "instr": "Place the product in a cozy home setting: on a wooden kitchen counter or living-room "
              "table, warm domestic ambience, soft natural light."},
    {"grupo": "escenario", "nombre": "En la mano",
     "instr": "Place the product naturally held in a person's hand, realistic skin and grip, clean "
              "softly blurred background."},
    {"grupo": "escenario", "nombre": "Exterior / naturaleza",
     "instr": "Place the product outdoors in natural daylight, with greenery, sky or a natural "
              "surface behind it, fresh airy mood."},
    {"grupo": "escenario", "nombre": "Baño / cuidado personal",
     "instr": "Place the product on a clean bathroom shelf or vanity, spa-like personal-care mood, "
              "soft light and a few subtle bathroom details."},
    {"grupo": "escenario", "nombre": "Fondo de color vibrante",
     "instr": "Put the product against a bold, saturated single-color studio background (modern, "
              "punchy ad look), with a crisp contact shadow."},
    # ---------- SOLO FONDO / COLOR (suave) ----------
    {"grupo": "fondo", "nombre": "Solo fondo blanco limpio",
     "instr": "Keep the exact same composition and framing, only replace the background with a "
              "clean pure-white seamless background."},
    {"grupo": "fondo", "nombre": "Solo luz más cálida",
     "instr": "Keep the exact same composition, only change the lighting to a warmer, golden-hour "
              "tone (do not move or restyle the product)."},
    {"grupo": "fondo", "nombre": "Solo fondo pastel suave",
     "instr": "Keep the exact same composition and framing, only change the background to a soft "
              "pastel gradient (gentle, modern)."},
]


def _repartir(tipos, n):
    """Elige hasta `n` recetas repartidas en round-robin entre los `tipos` pedidos (variedad)."""
    porg = {}
    for r in _RECETAS:
        porg.setdefault(r["grupo"], []).append(r)
    orden = [t for t in tipos if t in porg] or list(porg)
    sel, used = [], set()
    while len(sel) < n:
        avanzo = False
        for g in orden:
            cand = next((r for r in porg[g] if id(r) not in used), None)
            if cand:
                sel.append(cand)
                used.add(id(cand))
                avanzo = True
                if len(sel) >= n:
                    break
        if not avanzo:        # se agotaron las recetas de los grupos pedidos
            break
    return sel


def _normalizar_png(src_path, out_dir):
    """Convierte la imagen subida (jpg/webp/png) a un PNG limpio para mandarla a Gemini."""
    from PIL import Image
    dst = os.path.join(out_dir, "winner_src.png")
    with Image.open(src_path) as im:
        im.convert("RGB").save(dst, "PNG")
    return dst


def _editar_variacion(src_png_bytes, dst, instruccion, key, model, product_desc=""):
    """Una variación: image-to-image conservando producto + ángulo, cambiando lo que dice `instruccion`."""
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        desc = f" The product is: {product_desc.strip()}." if product_desc.strip() else ""
        prompt = (
            "You are given a product advertising photo. Create a NEW variation of it for a "
            "different ad. You MUST keep the EXACT SAME product — identical shape, proportions, "
            "colors, materials and label/branding — and keep the SAME camera angle and product "
            f"orientation as the input.{desc} "
            f"The variation to apply: {instruccion} "
            "Hard rules: do NOT redesign, recolor, resize or relabel the product; do NOT add any "
            "text, caption, watermark or logo anywhere; keep it fully PHOTOREALISTIC (a real "
            "photograph, never CGI, 3D render or illustration); no extra fingers or deformed hands. "
            "Output ONLY the image, in the SAME vertical aspect ratio and framing as the input "
            "(do not crop, extend or add borders).")
        r = client.models.generate_content(
            model=model,
            contents=[prompt, types.Part.from_bytes(data=src_png_bytes, mime_type="image/png")])
        for p in ((r.candidates or [None])[0].content.parts if (r.candidates or None) else []):
            if getattr(p, "inline_data", None):
                with open(dst, "wb") as f:
                    f.write(p.inline_data.data)
                return dst
    except Exception:  # noqa: BLE001
        pass
    return None


def variar_imagen(src_path, out_dir, gemini_key, tipos=("estilo", "escenario", "fondo"),
                  n=6, pro=False, product_desc="", progress=None):
    """Genera `n` variaciones de `src_path`. Devuelve {ok, variantes:[{estilo,grupo,imagen,ok,error}]}."""
    if not (src_path and os.path.exists(src_path)):
        return {"ok": False, "error": "No llegó la imagen", "variantes": []}
    if not gemini_key:
        return {"ok": False, "error": "Falta la clave de Google (Gemini)", "variantes": []}
    os.makedirs(out_dir, exist_ok=True)
    try:
        src_png = _normalizar_png(src_path, out_dir)
        with open(src_png, "rb") as f:
            src_bytes = f.read()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"No pude leer la imagen: {e}", "variantes": []}

    sel = _repartir(tuple(tipos), max(1, int(n)))
    model = _IMG_MODEL_PRO if pro else _IMG_MODEL_DRAFT
    variantes = []
    total = len(sel)
    for i, rec in enumerate(sel):
        if progress:
            progress(f"Variación {i + 1}/{total}: {rec['nombre']}", int(i * 100 / max(1, total)))
        dst = os.path.join(out_dir, f"var_{i:02d}.png")
        img = _editar_variacion(src_bytes, dst, rec["instr"], gemini_key, model, product_desc)
        variantes.append({"estilo": rec["nombre"], "grupo": rec["grupo"], "imagen": img,
                          "ok": bool(img),
                          "error": None if img else "Google no devolvió imagen (reintenta o revisa créditos)"})
    if progress:
        progress("Listo", 100)
    return {"ok": any(v["ok"] for v in variantes), "variantes": variantes,
            "modelo": "pro" if pro else "rapida"}
