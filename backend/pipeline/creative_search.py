"""Búsqueda COMBINADA de creativos (🎵 TikTok + 📚 Foreplay) a partir de una foto + nombre.

El usuario manda la FOTO del producto y su NOMBRE → se analiza la foto UNA sola vez con Gemini
(`tiktok_search.analizar_foto`: descripción física + términos de búsqueda cortos ES+EN) y esos
términos alimentan LAS DOS fuentes EN PARALELO (no suma tiempo):

  - TikTok: el flujo completo de `tiktok_search.buscar` (candidatos tikwm + verificación por IA de
    que sea el MISMO producto). Excluye Colombia (region != "CO") como siempre.
  - Foreplay: `foreplay_search.buscar_ads` con los 2-4 mejores términos EN ESPAÑOL (Foreplay filtra
    por idioma; Colombia se excluye ADENTRO de buscar_ads con la heurística _es_colombiano — aquí no
    se re-implementa nada de Juan, solo se consume). Se deduplican los ads entre términos y se
    VERIFICA el MISMO producto sobre los thumbnails con el MISMO juez de TikTok (`_verificar`),
    con tope de thumbnails para no disparar el costo. Si un thumbnail no se pudo juzgar (CDN caído,
    sin imagen), el ad queda HONESTAMENTE marcado `verificado_producto=False` (badge "sin verificar"
    en la UI) — nunca se inventa verificación.

Los endpoints viejos (/api/tiktok-search y /api/foreplay-search) NO cambian; esto es aditivo.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import foreplay_search as fp
from .tiktok_search import _expandir, _verificar, analizar_foto, buscar

# tope de thumbnails de Foreplay verificados con Gemini (costo acotado; flash es barato pero no gratis)
_FP_VERIFY_MAX = 24
_FP_TERMS = 3          # cuántos términos de búsqueda se mandan a Foreplay (cada uno gasta créditos)

# ── heurística barata para preferir los términos EN ESPAÑOL (analizar_foto mezcla ES+EN) ──────────
_ES_CHARS = set("áéíóúñü¿¡")
_ES_HINTS = {
    "de", "del", "la", "el", "los", "las", "para", "con", "sin", "que", "como", "crema", "gel",
    "aparato", "dispositivo", "quitar", "eliminar", "alivio", "aliviar", "dolor", "piel", "cara",
    "uñas", "hongos", "masajeador", "limpiador", "corrector", "plantillas", "almohadillas",
    "rodilla", "rodillas", "espalda", "cuello", "pies", "cabello", "pelo", "verrugas", "lunares",
    "manchas", "arrugas", "celulitis", "repelente", "plagas", "cucarachas", "ratones", "mosquitos",
    "adelgazar", "blanqueador", "limpieza", "hogar", "cocina", "bebé", "mascotas", "perro", "gato",
}


def _parece_espanol(term: str) -> bool:
    t = (term or "").lower()
    if any(c in _ES_CHARS for c in t):
        return True
    return any(w in _ES_HINTS for w in t.split())


def _terminos_foreplay(info: dict, max_terms: int = _FP_TERMS) -> list[str]:
    """Los mejores términos para Foreplay: español PRIMERO (la búsqueda filtra idioma español),
    después el resto, sin duplicar. Reusa lo que YA generó analizar_foto (cero llamadas extra)."""
    cands = [str(info.get("keywords") or "").strip()] + \
            [str(v).strip() for v in (info.get("variants") or [])]
    cands = [c for c in cands if c]
    es = [c for c in cands if _parece_espanol(c)]
    resto = [c for c in cands if c not in es]
    out: list[str] = []
    for t in es + resto:
        if t.lower() not in {x.lower() for x in out}:
            out.append(t)
        if len(out) >= max_terms:
            break
    return out


def _buscar_foreplay(info: dict, ref_bytes: bytes | None, foreplay_key: str | None,
                     gemini_key: str | None, count: int = 20,
                     verify_max: int = _FP_VERIFY_MAX) -> dict:
    """Busca en Foreplay con varios términos (paralelo), deduplica y verifica el MISMO producto.
    Devuelve {ok, ads:[...], n_confirmados, verificado, terminos, error?}."""
    if not foreplay_key:
        return {"ok": False, "error": "Falta la API key de Foreplay (ponla en 🔑 Claves)",
                "ads": [], "n_confirmados": 0, "verificado": False, "terminos": []}
    terms = _terminos_foreplay(info)
    if not terms:
        return {"ok": False, "error": "Sin términos de búsqueda", "ads": [],
                "n_confirmados": 0, "verificado": False, "terminos": []}

    # 1) buscar cada término EN PARALELO (idioma español como la pestaña Foreplay; Colombia se
    #    excluye adentro de buscar_ads) y DEDUPLICAR entre términos.
    ads: dict[str, dict] = {}
    errores: list[str] = []
    with ThreadPoolExecutor(max_workers=len(terms)) as ex:
        for r in ex.map(lambda t: fp.buscar_ads(t, api_key=foreplay_key, live=True,
                                                languages="spanish", video_only=True), terms):
            if not r.get("ok"):
                errores.append(r.get("error") or "Error en Foreplay")
                continue
            for a in r.get("ads") or []:
                k = str(a.get("id") or a.get("video") or a.get("foreplay_url") or "")
                if k and k not in ads:
                    ads[k] = a
    ad_list = list(ads.values())
    if not ad_list:
        return {"ok": not errores, "error": (errores[0] if errores else ""), "ads": [],
                "n_confirmados": 0, "verificado": False, "terminos": terms}

    # 2) verificar MISMO producto sobre los thumbnails (mismo juez que TikTok), con tope de costo.
    #    match=True → confirmado; match=False → se descarta; no se pudo juzgar (sin thumbnail /
    #    CDN falló) → queda SIN VERIFICAR (badge), sin inventar nada.
    verificado = bool(ref_bytes and gemini_key)
    if verificado:
        ref_desc = str(info.get("desc") or "")
        pool = ad_list[:verify_max]
        fuera = ad_list[verify_max:]
        confirmados, sin_verificar = [], []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {}
            for a in pool:
                cand = {"cover": a.get("thumbnail") or "",
                        "title": (a.get("name") or a.get("headline") or "")[:120]}
                futs[ex.submit(_verificar, cand, ref_bytes, ref_desc, gemini_key)] = a
            for fut in as_completed(futs):
                v, a = fut.result(), futs[fut]
                if v is None:                      # no se pudo juzgar → honesto: sin verificar
                    a["verificado_producto"] = False
                    sin_verificar.append(a)
                elif v.get("match"):
                    a["verificado_producto"] = True
                    confirmados.append(a)
                # match=False → otro producto: fuera de la lista
        for a in fuera:                            # más allá del tope: sin verificar (badge)
            a["verificado_producto"] = False
        # ganadores primero: confirmados (más días corriendo primero) → sin verificar
        confirmados.sort(key=lambda a: a.get("dias", 0), reverse=True)
        sin_verificar.sort(key=lambda a: a.get("dias", 0), reverse=True)
        fuera.sort(key=lambda a: a.get("dias", 0), reverse=True)
        ad_list = confirmados + sin_verificar + fuera
    else:
        for a in ad_list:
            a["verificado_producto"] = False
        ad_list.sort(key=lambda a: a.get("dias", 0), reverse=True)

    ad_list = ad_list[:count]
    for a in ad_list:
        a.pop("_cover_bytes", None)                # bytes: no serializan a JSON
    n_conf = sum(1 for a in ad_list if a.get("verificado_producto"))
    return {"ok": True, "ads": ad_list, "n_confirmados": n_conf,
            "verificado": verificado, "terminos": terms}


def buscar_creativos(image_path: str | None = None, nombre: str = "",
                     gemini_key: str | None = None, foreplay_key: str | None = None,
                     anthropic_key: str | None = None, count: int = 20,
                     fp_count: int = 20, fp_verify_max: int = _FP_VERIFY_MAX) -> dict:
    """Foto + nombre → creativos del MISMO producto en TikTok Y Foreplay (en paralelo).

    Devuelve {ok, keywords, desc, tiktok:{...igual que /api/tiktok-search...},
              foreplay:{ok, ads, n_confirmados, verificado, terminos, error?}}."""
    nombre = (nombre or "").strip()
    ref_bytes = None
    if image_path and os.path.exists(image_path):
        info = analizar_foto(image_path, nombre, gemini_key)   # 1 sola llamada para AMBAS fuentes
        try:
            with open(image_path, "rb") as f:
                ref_bytes = f.read()
        except Exception:  # noqa: BLE001
            ref_bytes = None
    else:
        info = {"keywords": nombre, "variants": _expandir(nombre, []), "desc": nombre}

    with ThreadPoolExecutor(max_workers=2) as ex:
        tk_fut = ex.submit(buscar, image_path=image_path, nombre=nombre, api_key=gemini_key,
                           count=count, anthropic_key=anthropic_key, analisis=info)
        fp_fut = ex.submit(_buscar_foreplay, info, ref_bytes, foreplay_key, gemini_key,
                           fp_count, fp_verify_max)
        tk = tk_fut.result()
        fpr = fp_fut.result()

    return {"ok": bool(tk.get("links") or fpr.get("ads")),
            "keywords": tk.get("keywords") or info.get("keywords") or nombre,
            "desc": info.get("desc", ""), "tiktok": tk, "foreplay": fpr}
