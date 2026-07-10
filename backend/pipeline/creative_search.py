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

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import foreplay_search as fp
from .tiktok_search import _expandir, _verificar, _verificar_video, analizar_foto, buscar

log = logging.getLogger("creative_search")

# tope de thumbnails de Foreplay verificados con Gemini (costo acotado; flash es barato pero no gratis)
# Pool más grande (era 24): como ahora SOLO se devuelven matches alta/media (se descarta baja), hace
# falta revisar más candidatos para llegar al N pedido SIN aflojar el juez.
_FP_VERIFY_MAX = 32
_FP_TERMS = 4          # cuántos términos de búsqueda se mandan a Foreplay (cada uno gasta créditos)

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
                     verify_max: int = _FP_VERIFY_MAX,
                     excluir: set[str] | None = None, solo_confirmados: bool = True,
                     rellenar_n: bool = False) -> dict:
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
                if k and k not in ads and k not in (excluir or set()):
                    ads[k] = a
    ad_list = list(ads.values())
    if not ad_list:
        return {"ok": not errores, "error": (errores[0] if errores else ""), "ads": [],
                "n_confirmados": 0, "verificado": False, "terminos": terms}

    # 2) verificar EXACTO: portada (pre-filtro ESTRICTO) → CONTENIDO del video (deep) de los que pasan.
    verificado = bool(ref_bytes and gemini_key)
    if verificado:
        ref_desc = str(info.get("desc") or "")
        pool = ad_list[:verify_max]
        cover_ok = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {}
            for a in pool:
                cand = {"cover": a.get("thumbnail") or "",
                        "title": (a.get("name") or a.get("headline") or "")[:120]}
                futs[ex.submit(_verificar, cand, ref_bytes, ref_desc, gemini_key)] = a
            for fut in as_completed(futs):
                v, a = fut.result(), futs[fut]
                # SOLO match=true de confianza NO baja (alta/media). Nunca baja ni match=false →
                # jamás otro producto (ni siquiera con rellenar_n: el juez NO se afloja).
                if v and v.get("match") and v.get("confianza") != "baja":
                    a["_cover_conf"] = v.get("confianza")
                    cover_ok.append(a)
        # CONTENIDO: baja el video del ad y lo juzga por DENTRO (exacto = match + confianza no baja).
        confirmados = []
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {}
            for a in cover_ok:
                cand = {"video": a.get("video") or "", "play": a.get("video") or "",
                        "title": (a.get("name") or a.get("headline") or "")[:120]}
                futs[ex.submit(_verificar_video, cand, ref_bytes, ref_desc, gemini_key)] = a
            for fut in as_completed(futs):
                v, a = fut.result(), futs[fut]
                if v is None:                    # no se pudo bajar/juzgar el video → cae al veredicto
                    a["_conf"] = a.get("_cover_conf") or "media"   # de portada, que ya pasó el filtro
                    a["verificado_producto"] = True
                    confirmados.append(a)
                elif v.get("match") and v.get("confianza") != "baja":
                    a["_conf"] = v.get("confianza")
                    a["verificado_producto"] = True
                    confirmados.append(a)
                # match=False o confianza baja por contenido → fuera (no es seguro el mismo producto)
        confirmados.sort(key=lambda a: a.get("dias", 0), reverse=True)
        if rellenar_n:
            # TIERED (flujo "buscar creativos"): SOLO confianza ALTA (tier 1) o MEDIA (tier 2). Ya no
            # hay confianza baja aquí (se filtró arriba); tier 3 nunca se devuelve. Ordena tier→días
            # y baja a tier 2 solo para llegar al count. Si faltan, devuelve MENOS (honesto).
            for a in confirmados:
                conf = a.get("_conf") or "media"
                a["tier"] = 1 if conf == "alta" else 2
                a["confianza"] = conf
                a["verificado_producto"] = True
            confirmados.sort(key=lambda a: (a.get("tier", 2), -int(a.get("dias", 0) or 0)))
            ad_list = confirmados
        elif solo_confirmados:
            ad_list = confirmados                # SOLO exactos, sin relleno de "por si acaso"
        else:
            ids = {id(a) for a in confirmados}
            resto = [a for a in ad_list if id(a) not in ids]
            for a in resto:
                a["verificado_producto"] = False
            resto.sort(key=lambda a: a.get("dias", 0), reverse=True)
            ad_list = confirmados + resto
    else:
        for a in ad_list:
            a["verificado_producto"] = False
        ad_list.sort(key=lambda a: a.get("dias", 0), reverse=True)

    ad_list = ad_list[:count]
    for a in ad_list:
        a.pop("_cover_bytes", None)                # bytes: no serializan a JSON
        a.pop("_conf", None)                       # internos (tier ya calculado)
        a.pop("_cover_conf", None)
    n_conf = sum(1 for a in ad_list if a.get("verificado_producto"))
    return {"ok": True, "ads": ad_list, "n_confirmados": n_conf,
            "verificado": verificado, "terminos": terms}


def buscar_creativos(image_path: str | None = None, nombre: str = "",
                     gemini_key: str | None = None, foreplay_key: str | None = None,
                     anthropic_key: str | None = None, count: int = 20,
                     fp_count: int = 20, fp_verify_max: int = _FP_VERIFY_MAX,
                     image_paths: list[str] | None = None,
                     landing_text: str = "", rellenar_n: bool = False) -> dict:
    """Foto + nombre → creativos del MISMO producto en TikTok Y Foreplay (en paralelo).

    `image_paths` (opcional): hasta 6 imágenes del MISMO producto (fotos frente/lado/empaque y/o
    los 5 mejores FRAMES de un video suyo — fotos primero) → ficha más completa; los jueces (TikTok
    y Foreplay) usan las 2 primeras como referencia.
    `landing_text` (opcional): texto de la página de venta → contexto para la ficha y los términos
    (va dentro de la MISMA llamada de analizar_foto: cero llamadas extra).
    Devuelve {ok, keywords, desc, tiktok:{...igual que /api/tiktok-search...},
              foreplay:{ok, ads, n_confirmados, verificado, terminos, error?}}."""
    nombre = (nombre or "").strip()
    ref_bytes = None
    paths = [p for p in (image_paths or [image_path]) if p and os.path.exists(p)][:6]
    if paths:
        info = analizar_foto(paths[0], nombre, gemini_key,     # 1 sola llamada para AMBAS fuentes
                             image_paths=paths, landing_text=landing_text)
        refs = []
        for p in paths[:2]:            # jueces: máximo 2 fotos de referencia (tope de costo)
            try:
                with open(p, "rb") as f:
                    refs.append(f.read())
            except Exception:  # noqa: BLE001
                pass
        ref_bytes = refs or None       # lista: _verificar la acepta tal cual
    else:
        info = {"keywords": nombre, "variants": _expandir(nombre, []), "desc": nombre}

    with ThreadPoolExecutor(max_workers=2) as ex:
        tk_fut = ex.submit(buscar, image_path=image_path, nombre=nombre, api_key=gemini_key,
                           count=count, anthropic_key=anthropic_key, analisis=info,
                           image_paths=image_paths, rellenar_n=rellenar_n)
        fp_fut = ex.submit(_buscar_foreplay, info, ref_bytes, foreplay_key, gemini_key,
                           fp_count, fp_verify_max, rellenar_n=rellenar_n)
        tk = tk_fut.result()
        fpr = fp_fut.result()

    return {"ok": bool(tk.get("links") or fpr.get("ads")),
            "keywords": tk.get("keywords") or info.get("keywords") or nombre,
            "desc": info.get("desc", ""),
            "variants": [v for v in (info.get("variants") or []) if v][:6],
            "tiktok": tk, "foreplay": fpr}


# ══ "🔄 Cambiar" y "🎯 Más con este ángulo" (botones por creativo en la UI) ═══════════════════════

def _terminos_angulo(angulo: str, nombre: str, gemini_key: str | None, k: int = 3) -> list[str]:
    """1 llamada a Gemini flash: del título/descr de un creativo ganador saca el ÁNGULO de venta y
    devuelve k búsquedas cortas para encontrar MÁS creativos con ese mismo ángulo. [] si falla."""
    if not (gemini_key and (angulo or "").strip()):
        return []
    try:
        from google import genai
        client = genai.Client(api_key=gemini_key)
        r = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[(f'Título/descripción de un creativo GANADOR de TikTok: "{angulo.strip()[:220]}". '
                       f'Producto: "{(nombre or "").strip()[:120]}". Identifica su ÁNGULO de venta '
                       f"(el dolor/beneficio/gancho que usa) y dame {k} búsquedas CORTAS (2-4 palabras) "
                       "para TikTok que encuentren MÁS creativos con ese MISMO ángulo (mezcla español e "
                       "inglés). Devuelve SOLO las búsquedas, una por línea, sin numerar.")])
        lines = [ln.strip(" -•\"'\t") for ln in (r.text or "").splitlines() if ln.strip()]
        return [ln for ln in lines if 0 < len(ln.split()) <= 6][:k]
    except Exception:  # noqa: BLE001
        return []


def buscar_mas(fuente: str, nombre: str = "", terminos: list[str] | None = None,
               angulo: str = "", excluir: list[str] | None = None, n: int = 1,
               image_path: str | None = None, gemini_key: str | None = None,
               foreplay_key: str | None = None, desc: str = "") -> dict:
    """Busca n creativos NUEVOS (que no estén en `excluir`) en UNA fuente ("tiktok"|"foreplay").

    - Con `angulo` (título del creativo que gustó): 1 llamada a Gemini saca términos de ese ángulo.
    - Sin `angulo` (🔄 cambiar): reutiliza `terminos` (los de la búsqueda original) o expande `nombre`.
    - Con foto (`image_path`): verifica MISMO producto con el juez de siempre (tope chico de costo);
      lo confirmado va primero y lo demás queda `verificado_producto=False` (badge). Sin foto, sin IA.
    Devuelve {ok, items: [...], terminos, error?} — items con el mismo shape del grupo de su fuente."""
    from .tiktok_search import _ES_REGIONS, _tk_key, buscar_tiktok, norm_tk_id

    excl = {str(e).strip() for e in (excluir or []) if str(e).strip()}
    excl_tk = {norm_tk_id(e) for e in excl}   # excl normalizado a video_id (TikTok, sin engaño del @)
    terms = _terminos_angulo(angulo, nombre, gemini_key) if angulo.strip() else []
    terms = terms or [t for t in (terminos or []) if t.strip()][:4] or _expandir(nombre, [])[:3]
    terms = [t for t in terms if t.strip()]
    if not terms:
        return {"ok": False, "error": "Sin términos de búsqueda", "items": [], "terminos": []}
    n = max(1, min(int(n), 12))

    ref_bytes = None
    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, "rb") as f:
                ref_bytes = f.read()
        except Exception:  # noqa: BLE001
            ref_bytes = None

    if fuente == "foreplay":
        info = {"keywords": terms[0], "variants": terms[1:], "desc": desc or nombre or angulo}
        r = _buscar_foreplay(info, ref_bytes, foreplay_key, gemini_key, count=n,
                             verify_max=min(_FP_VERIFY_MAX, max(8, n * 3)), excluir=excl)
        return {"ok": r.get("ok", False), "items": r.get("ads") or [],
                "terminos": terms, "error": r.get("error", "")}

    # ── TikTok ─────────────────────────────────────────────────────────────────────────────────
    cands: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(terms))) as ex:
        for res in ex.map(lambda q: buscar_tiktok(q, count=40, pages=2), terms):
            for c in res:
                k = _tk_key(c)                      # dedup por video_id (no por url: el @ engaña)
                if k not in excl_tk and norm_tk_id(c["url"]) not in excl_tk:
                    cands.setdefault(k, c)
    lst = [c for c in cands.values() if c.get("region") != "CO"]          # regla: sin Colombia
    lst = [c for c in lst if 4 <= c.get("dur", 0) <= 120] or lst
    lst.sort(key=lambda c: (1 if c.get("region") in _ES_REGIONS else 0, c.get("plays", 0)),
             reverse=True)
    if not lst:
        return {"ok": False, "error": "No encontré más creativos con esa búsqueda", "items": [],
                "terminos": terms}

    if ref_bytes and gemini_key:
        ref_desc = desc or nombre or angulo
        # portada = pre-filtro barato (prioriza); confirma por CONTENIDO del video (EXACTO, como buscar())
        pf = lst[:max(20, n * 4)]
        cov: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_verificar, c, ref_bytes, ref_desc, gemini_key): c for c in pf}
            for fut in as_completed(futs):
                v = fut.result()
                if v:
                    cov[id(futs[fut])] = v

        def _pf(c):
            v = cov.get(id(c)) or {}
            return (1 if v.get("match") else 0, {"alta": 2, "media": 1}.get(v.get("confianza"), 0),
                    c.get("plays", 0))
        a_deep = sorted([c for c in pf if c.get("play")], key=_pf, reverse=True)[:max(10, n * 2)]
        conf = []
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(_verificar_video, c, ref_bytes, ref_desc, gemini_key): c for c in a_deep}
            for fut in as_completed(futs):
                v, c = fut.result(), futs[fut]
                if v and v.get("match") and v.get("confianza") != "baja":
                    c["verificado_producto"] = True
                    conf.append(c)
        conf.sort(key=lambda c: c.get("plays", 0), reverse=True)
        items = conf[:n]                                  # SOLO exactos (nada de relleno)
    else:
        for c in lst:
            c["verificado_producto"] = False
        items = lst[:n]
    for c in items:
        c.pop("_cover_bytes", None)
    return {"ok": True, "items": items, "terminos": terms}


# ══ 📚 FOREPLAY PROFUNDO: todos los creativos del PRODUCTO EXACTO (foto → términos → páginas) ═════

def foreplay_producto(image_path: str | None = None, nombre: str = "",
                      foreplay_key: str | None = None, gemini_key: str | None = None,
                      *, max_terms: int = 8, paginas_por_termino: int = 2,
                      verify_max: int = 60, max_ads: int = 400,
                      solo_video: bool = True, solo_activos: bool = False,
                      progress=None) -> dict:
    """El modo "producto exacto" de la pestaña Foreplay: foto (y/o nombre) → Gemini saca TODOS los
    términos de búsqueda del producto (ES+EN) → se busca CADA término en Foreplay con página GRANDE
    (limit=100, orden = más días corriendo) y hasta `paginas_por_termino` páginas → dedup → el juez
    visual confirma cuáles son el MISMO producto (tope `verify_max` thumbnails; el resto queda con
    badge "sin verificar" — nunca se inventa). Devuelve {ok, ads, n_confirmados, terminos,
    total_crudo, verificado, error?}. Costo: 1 Gemini (foto) + ~max_terms×páginas créditos Foreplay
    + hasta verify_max llamadas flash (baratas)."""
    def report(m, p):
        if progress:
            progress(m, p)

    if not foreplay_key:
        return {"ok": False, "error": "Falta la API key de Foreplay (ponla en 🔑 Claves)", "ads": []}

    # 1) Foto → ficha + términos (una sola llamada). Sin foto → expandir el nombre (gratis).
    ref_bytes = None
    if image_path and os.path.exists(image_path):
        report("📸 Analizando la foto del producto (ficha + términos)...", 8)
        info = analizar_foto(image_path, nombre, gemini_key)
        try:
            with open(image_path, "rb") as f:
                ref_bytes = f.read()
        except Exception:  # noqa: BLE001
            ref_bytes = None
    else:
        info = {"keywords": nombre, "variants": _expandir(nombre, []), "desc": nombre}
    terms = _terminos_foreplay(info, max_terms=max_terms)
    if not terms:
        return {"ok": False, "error": "Dame el nombre del producto o una foto", "ads": []}

    # 2) Cada término con página grande + orden ganador + paginación (en paralelo por término)
    report(f"📚 Buscando en Foreplay con {len(terms)} términos ({paginas_por_termino} páginas c/u)...", 22)
    vivos = True if solo_activos else None

    def _termino(t: str) -> list[dict]:
        out, cursor = [], ""
        for _ in range(max(1, paginas_por_termino)):
            r = fp.buscar_ads(t, api_key=foreplay_key, live=vivos, languages="",
                              video_only=solo_video, cursor=cursor,
                              limit=100, order="longest_running")
            if not r.get("ok"):
                break
            out += r.get("ads") or []
            cursor = r.get("cursor") or ""
            if not cursor:
                break
        return out

    ads: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(terms))) as ex:
        for lote in ex.map(_termino, terms):
            for a in lote:
                k = str(a.get("id") or a.get("video") or a.get("foreplay_url") or "")
                if k and k not in ads:
                    ads[k] = a
    # Relevancia TEXTUAL primero (lección de la búsqueda TikTok): ordenar solo por días llena el
    # tope del juez de mega-ads genéricos que matchean flojo (ej. media brands con 1000 días) y el
    # producto REAL nunca se verifica. Palabras significativas de los términos → score por ad.
    stop = {"para", "con", "anti", "las", "los", "del", "que", "the", "and", "for"}
    palabras = {w for t in terms for w in t.lower().split() if len(w) >= 4 and w not in stop}

    def _rel(a: dict) -> int:
        txt = " ".join(str(a.get(k) or "") for k in ("name", "headline", "description")).lower()
        return sum(1 for w in palabras if w in txt)

    for a in ads.values():
        a["_rel"] = _rel(a)
    ad_list = sorted(ads.values(), key=lambda a: (a["_rel"], a.get("dias", 0)), reverse=True)
    relevantes = [a for a in ad_list if a["_rel"] > 0]
    if len(relevantes) >= 30:      # hay suficiente señal → el ruido de 0 relevancia se descarta
        ad_list = relevantes
    total_crudo = len(ad_list)
    if not ad_list:
        return {"ok": True, "ads": [], "n_confirmados": 0, "terminos": terms,
                "total_crudo": 0, "verificado": False}

    # 3) Juez visual sobre los thumbnails de los MÁS RELEVANTES — mismo juez de TikTok
    verificado = bool(ref_bytes and gemini_key)
    if verificado:
        report(f"👁️ Verificando el producto en {min(verify_max, len(ad_list))} ads (los más relevantes)...", 55)
        ref_desc = str(info.get("desc") or "")
        pool, fuera = ad_list[:verify_max], ad_list[verify_max:]
        confirmados, sin_verificar = [], []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_verificar, {"cover": a.get("thumbnail") or "",
                                           "title": (a.get("name") or a.get("headline") or "")[:120]},
                              ref_bytes, ref_desc, gemini_key): a for a in pool}
            hechos = 0
            for fut in as_completed(futs):
                v, a = fut.result(), futs[fut]
                hechos += 1
                if hechos % 10 == 0:
                    report(f"👁️ Verificando... {hechos}/{len(pool)}", 55 + int(35 * hechos / len(pool)))
                if v is None:
                    a["verificado_producto"] = False
                    sin_verificar.append(a)
                elif v.get("match"):
                    a["verificado_producto"] = True
                    confirmados.append(a)
                # match=False → otro producto: descartado
        for a in fuera:
            a["verificado_producto"] = False
        confirmados.sort(key=lambda a: a.get("dias", 0), reverse=True)
        sin_verificar.sort(key=lambda a: (a.get("_rel", 0), a.get("dias", 0)), reverse=True)
        fuera.sort(key=lambda a: (a.get("_rel", 0), a.get("dias", 0)), reverse=True)
        ad_list = confirmados + sin_verificar + fuera
    else:
        for a in ad_list:
            a["verificado_producto"] = False

    ad_list = ad_list[:max_ads]
    for a in ad_list:
        a.pop("_cover_bytes", None)
        a.pop("_rel", None)
    n_conf = sum(1 for a in ad_list if a.get("verificado_producto"))
    report("✅ Listo", 100)
    return {"ok": True, "ads": ad_list, "n_confirmados": n_conf, "terminos": terms,
            "total_crudo": total_crudo, "verificado": verificado}
