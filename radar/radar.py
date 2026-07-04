#!/usr/bin/env python3
"""Radar Ganadores — Fase 1 (v0).

Escanea la Meta Ad Library (vía ScrapeCreators) por keywords y países,
guarda snapshots diarios en SQLite y genera un reporte con scoring 0-100.

Uso:
  python3 radar.py scan                        # escaneo completo según config.json
  python3 radar.py scan --pais CO --kw alfombra  # escaneo puntual de prueba
  python3 radar.py report                      # reporte del día con scoring
  python3 radar.py creditos                    # créditos restantes (no gasta)

Scoring v0 (sin engagement E — llega en Fase 2 con el scraping de posts):
  Score = 0.375·L + 0.25·V + 0.25·P + 0.125·R − penalizaciones
  L=longevidad, V=variaciones del creativo, P=ads activos observados de la página,
  R=recencia. Pesos renormalizados de la fórmula del PLAN.md (sección 3).
"""
import argparse
import datetime
import json
import pathlib
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent
API = "https://api.scrapecreators.com/v1/facebook/adLibrary"
DB_PATH = BASE / "radar.db"
REPORTS = BASE / "docs" / "reports"

CTA_COMPRA = {"SHOP_NOW", "BUY_NOW", "ORDER_NOW", "GET_OFFER", "BUY", "PURCHASE"}

# Marketplaces/afiliados gigantes: no son productos replicables por un dropshipper
EXCLUIR = ("temu.com", "temu", "amazon.", "amazon associates", "aliexpress", "shein",
           "mercadolibre", "mercado libre", "ebay.", "walmart", "falabella", "alibaba",
           "linio", "exito.com", "wish.com")


def es_marketplace(page_name, link_url):
    texto = f"{page_name or ''} {link_url or ''}".lower()
    return any(m in texto for m in EXCLUIR)


def cargar_privado():
    """Exclusiones privadas (privado.json, gitignored): páginas que jamás deben
    aparecer en la base ni en los reportes. El archivo es opcional."""
    ruta = BASE / "privado.json"
    if not ruta.exists():
        return {"page_ids_excluir": [], "nombres_excluir": []}
    return json.loads(ruta.read_text())


def es_privado(page_id, page_name, priv):
    if str(page_id) in priv["page_ids_excluir"]:
        return True
    nombre = (page_name or "").lower()
    return any(n in nombre for n in priv["nombres_excluir"])


def load_api_key():
    for line in (BASE / ".env").read_text().splitlines():
        if line.startswith("SCRAPECREATORS_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("No encontré SCRAPECREATORS_API_KEY en .env")


def api_get(path, params, key, retries=3):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"x-api-key": key})
    for intento in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError) as e:
            if intento == retries - 1:
                raise
            time.sleep(5 * (intento + 1))


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS ads (
      ad_archive_id TEXT PRIMARY KEY,
      collation_id  TEXT,
      page_id       TEXT,
      page_name     TEXT,
      country       TEXT,
      nicho         TEXT,
      keyword       TEXT,
      start_date    INTEGER,
      cta_type      TEXT,
      display_format TEXT,
      link_url      TEXT,
      body          TEXT,
      page_like_count INTEGER,
      first_scanned TEXT,
      eu_total_reach INTEGER
    );
    CREATE TABLE IF NOT EXISTS snapshots (
      ad_archive_id  TEXT,
      scan_date      TEXT,
      is_active      INTEGER,
      collation_count INTEGER,
      PRIMARY KEY (ad_archive_id, scan_date)
    );
    CREATE INDEX IF NOT EXISTS idx_snap_date ON snapshots(scan_date);
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ads)")}
    for col in ("media_img", "media_video"):
        if col not in cols:
            conn.execute(f"ALTER TABLE ads ADD COLUMN {col} TEXT")
    return conn


def extraer_media(snap):
    """(url_imagen, url_video) del snapshot; los links del CDN expiran en ~24-48h,
    por eso se refrescan en cada escaneo."""
    for v in (snap.get("videos") or []):
        if v:
            return v.get("video_preview_image_url"), v.get("video_sd_url") or v.get("video_hd_url")
    for i in (snap.get("images") or []):
        if i:
            return i.get("resized_image_url") or i.get("original_image_url"), None
    for c in (snap.get("cards") or []):
        if c:
            img = c.get("resized_image_url") or c.get("original_image_url") or c.get("video_preview_image_url")
            vid = c.get("video_sd_url") or c.get("video_hd_url")
            if img or vid:
                return img, vid
    return None, None


def upsert_ad(conn, ad, country, nicho, keyword, hoy):
    snap = ad.get("snapshot") or {}
    body = ((snap.get("body") or {}).get("text") or "")[:500]
    media_img, media_video = extraer_media(snap)
    if not body and snap.get("cards"):
        body = ((snap["cards"][0] or {}).get("body") or "")[:500]
    conn.execute(
        """INSERT INTO ads (ad_archive_id, collation_id, page_id, page_name, country,
             nicho, keyword, start_date, cta_type, display_format, link_url, body,
             page_like_count, first_scanned, media_img, media_video)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(ad_archive_id) DO UPDATE SET
             page_like_count = excluded.page_like_count,
             media_img = excluded.media_img,
             media_video = excluded.media_video""",
        (ad["ad_archive_id"], ad.get("collation_id"), ad.get("page_id"),
         ad.get("page_name") or snap.get("page_name"), country, nicho, keyword,
         ad.get("start_date"), snap.get("cta_type"), snap.get("display_format"),
         snap.get("link_url"), body, snap.get("page_like_count"), hoy,
         media_img, media_video))
    conn.execute(
        """INSERT OR REPLACE INTO snapshots (ad_archive_id, scan_date, is_active, collation_count)
           VALUES (?,?,?,?)""",
        (ad["ad_archive_id"], hoy, 1 if ad.get("is_active") else 0,
         ad.get("collation_count") or 1))


def scan(args):
    key = load_api_key()
    config = json.loads((BASE / "config.json").read_text())
    conn = db()
    hoy = datetime.date.today().isoformat()
    paginas = config.get("paginas_por_keyword", 1)
    priv = cargar_privado()

    trabajos = []  # (country, nicho, keyword)
    if args.kw:
        trabajos = [(args.pais or "CO", args.nicho or "manual", args.kw)]
    else:
        for nicho, por_pais in config["nichos"].items():
            for country, kws in por_pais.items():
                if country in config["countries_activos"]:
                    trabajos += [(country, nicho, kw) for kw in kws]

    total_ads, creditos = 0, None
    for country, nicho, kw in trabajos:
        cursor = None
        for _ in range(paginas):
            params = {"query": kw, "country": country, "status": "ACTIVE"}
            if cursor:
                params["cursor"] = cursor
            try:
                data = api_get("search/ads", params, key)
            except Exception as e:
                print(f"  ERROR {country}/{kw}: {e}", file=sys.stderr)
                break
            creditos = data.get("credits_remaining", creditos)
            ads = data.get("searchResults") or []
            for ad in ads:
                snap = ad.get("snapshot") or {}
                if es_privado(ad.get("page_id"), ad.get("page_name") or snap.get("page_name"), priv):
                    continue
                upsert_ad(conn, ad, country, nicho, kw, hoy)
            total_ads += len(ads)
            print(f"  {country} · {nicho} · '{kw}': {len(ads)} ads")
            cursor = data.get("cursor")
            if not cursor or not ads:
                break
            time.sleep(1)
    conn.commit()
    conn.close()
    print(f"\nEscaneo {hoy}: {total_ads} ads guardados. Créditos restantes: {creditos}")


# ---------- Scoring (PLAN.md sección 3, v0 sin E) ----------

def interp(x, puntos):
    """Interpolación lineal sobre [(x, score), ...] ordenados."""
    if x <= puntos[0][0]:
        return puntos[0][1]
    for (x1, y1), (x2, y2) in zip(puntos, puntos[1:]):
        if x <= x2:
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    return puntos[-1][1]


def score_ad(dias_activo, collation, ads_pagina, page_likes, cta_type):
    L = interp(dias_activo, [(0, 10), (7, 50), (15, 80), (30, 100), (60, 100), (90, 85), (120, 60)])
    V = interp(collation, [(1, 20), (2, 50), (4, 80), (8, 100)])
    P = interp(ads_pagina, [(1, 25), (3, 55), (6, 85), (16, 100), (50, 100), (100, 60)])
    R = interp(dias_activo, [(30, 100), (60, 70), (90, 40), (120, 10)])
    score = 0.375 * L + 0.25 * V + 0.25 * P + 0.125 * R
    penal = []
    if cta_type not in CTA_COMPRA:
        score -= 20
        penal.append("sin CTA compra")
    if (page_likes or 0) > 500_000:
        score -= 15
        penal.append("marca grande")
    return max(0, round(score)), penal


def calcular_candidatos(conn, fecha):
    """Candidatos únicos (uno por producto) del escaneo de `fecha`, ya puntuados
    y ordenados por score. Devuelve (candidatos, n_excluidos)."""
    ahora = time.time()
    rows = conn.execute("""
        SELECT a.ad_archive_id, a.collation_id, a.page_id, a.page_name, a.country,
               a.nicho, a.keyword, a.start_date, a.cta_type, a.display_format,
               a.link_url, a.body, a.page_like_count, s.collation_count,
               a.media_img, a.media_video
        FROM ads a JOIN snapshots s
          ON s.ad_archive_id = a.ad_archive_id AND s.scan_date = ?
        WHERE s.is_active = 1""", (fecha,)).fetchall()
    if not rows:
        return [], 0

    # ads activos observados por página (proxy de P)
    ads_por_pagina = {}
    for r in rows:
        ads_por_pagina[r[2]] = ads_por_pagina.get(r[2], 0) + 1

    # una fila por producto: collation, o misma página + mismo copy (variantes DPA).
    # Nos quedamos con la más antigua = representativa; contamos variantes observadas.
    por_producto, variantes = {}, {}
    excluidos = 0
    priv = cargar_privado()
    for r in rows:
        if es_marketplace(r[3], r[10]) or es_privado(r[2], r[3], priv):
            excluidos += 1
            continue
        clave = r[1] or f"{r[2]}|{(r[11] or '')[:60]}"
        variantes[clave] = variantes.get(clave, 0) + 1
        if clave not in por_producto or (r[7] or ahora) < (por_producto[clave][7] or ahora):
            por_producto[clave] = r

    candidatos = []
    for clave, r in por_producto.items():
        (ad_id, _coll, page_id, page_name, country, nicho, keyword, start,
         cta, formato, link, body, likes, coll_count, media_img, media_video) = r
        dias = max(0, int((ahora - start) / 86400)) if start else 0
        n_var = max(coll_count or 1, variantes[clave])
        s, penal = score_ad(dias, n_var, ads_por_pagina.get(page_id, 1), likes, cta)
        candidatos.append({
            "clave": clave,
            "score": s, "penal": penal, "pais": country, "nicho": nicho,
            "pagina": page_name, "dias": dias, "variaciones": n_var,
            "ads_pagina": ads_por_pagina.get(page_id, 1), "kw": keyword,
            "producto": (body or "").replace("\n", " ")[:90],
            "copy_full": (body or "")[:300],
            "link": link or "",
            "ad_library": f"https://www.facebook.com/ads/library/?id={ad_id}",
            "img": media_img or "", "video": media_video or "",
            "formato": formato or "", "likes_pagina": likes or 0,
        })
    candidatos.sort(key=lambda c: -c["score"])
    return candidatos, excluidos


def report(args):
    conn = db()
    hoy = datetime.date.today().isoformat()
    candidatos, excluidos = calcular_candidatos(conn, hoy)
    if not candidatos:
        sys.exit(f"No hay snapshot de hoy ({hoy}). Corre primero: python3 radar.py scan")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{hoy}.md"
    lineas = [f"# Radar Ganadores — {hoy}", ""]
    for pais in sorted({c["pais"] for c in candidatos}):
        top = [c for c in candidatos if c["pais"] == pais][:15]
        lineas += [f"## {pais} — top {len(top)}", ""]
        lineas += ["| Score | Nicho | Página | Producto (copy) | Días | Var. | Ads pág. | Links |",
                   "|---|---|---|---|---|---|---|---|"]
        for c in top:
            banda = "🟢" if c["score"] >= 70 else ("🟡" if c["score"] >= 50 else "⚪")
            notas = f" ({', '.join(c['penal'])})" if c["penal"] else ""
            tienda = f" · [tienda]({c['link']})" if c["link"] else ""
            lineas.append(
                f"| {banda} {c['score']}{notas} | {c['nicho']} | {c['pagina']} | {c['producto']} "
                f"| {c['dias']} | {c['variaciones']} | {c['ads_pagina']} "
                f"| [ad]({c['ad_library']}){tienda} |")
        lineas.append("")
    lineas += ["---", "🟢 ≥70 candidato fuerte · 🟡 50-69 watchlist · ⚪ <50 descartar",
               f"Marketplaces/afiliados excluidos: {excluidos} ads (Temu, Amazon, Shein, etc.)",
               "v0: sin señal de engagement (Fase 2). 'Ads pág.' = ads observados en este escaneo (subestima el total real)."]
    out.write_text("\n".join(lineas))
    print(f"Reporte: {out}")
    fuertes = [c for c in candidatos if c["score"] >= 70]
    print(f"{len(candidatos)} productos únicos · {len(fuertes)} candidatos fuertes (≥70)")
    conn.close()


def creditos(args):
    # el endpoint search es el único que reporta créditos; una llamada mínima cuesta 1 crédito,
    # así que solo leemos el último valor conocido del log si existe. Por ahora: aviso.
    print("Los créditos se muestran al final de cada 'scan' (campo credits_remaining).")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Radar Ganadores")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("scan")
    ps.add_argument("--pais")
    ps.add_argument("--kw")
    ps.add_argument("--nicho")
    ps.set_defaults(fn=scan)
    pr = sub.add_parser("report")
    pr.set_defaults(fn=report)
    pc = sub.add_parser("creditos")
    pc.set_defaults(fn=creditos)
    args = p.parse_args()
    args.fn(args)
