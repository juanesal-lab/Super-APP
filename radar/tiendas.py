#!/usr/bin/env python3
"""Shopify tracker — best-sellers y productos nuevos de tiendas competidoras.

Las tiendas salen solas de los ads del radar (link_url → dominio). A cada
tienda Shopify se le consulta el catálogo público (/products.json) y el
orden best-selling (/collections/all?sort_by=best-selling). No toca Meta,
no gasta créditos — corre completo en el cron diario.

Uso:
  python3 tiendas.py descubrir [--min-ads 2]   # detecta tiendas Shopify nuevas
  python3 tiendas.py snapshot                  # catálogo + best-sellers del día
                                               # e imprime novedades vs día anterior

Señales que produce:
  🆕 producto recién subido por un competidor = lo está por testear
  📈 producto que entra al top best-sellers   = le está funcionando
"""
import argparse
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from radar import BASE, EXCLUIR, db

REPORTS = BASE / "docs" / "reports"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# no-tiendas: apps, redes, links, quizzes, funnels de terceros
NO_TIENDA = EXCLUIR + (
    "play.google", "apple.com", "itunes", "fb.com", "facebook", "instagram",
    "whatsapp", "wa.me", "linktr", "bit.ly", "youtube", "tiktok", "t.me",
    "telegram", "messenger", "fb.me", "typeform", "quiz.", "amzlink", "amzn",
    "google.com", "goo.gl", "forms.gle", "hotmart", "spotify", "onelink",
)
TOP_BESTSELLER = 20


def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def tablas(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tiendas (
      dominio TEXT PRIMARY KEY,
      pais TEXT,
      n_ads INTEGER,
      es_shopify INTEGER,   -- 1 sí · 0 no · NULL sin probar
      probado TEXT
    );
    CREATE TABLE IF NOT EXISTS tienda_productos (
      dominio TEXT,
      fecha TEXT,
      handle TEXT,
      titulo TEXT,
      precio REAL,
      publicado TEXT,          -- published_at del producto
      rank_bestseller INTEGER, -- posición en el top best-selling (NULL si no está)
      PRIMARY KEY (dominio, fecha, handle)
    );
    """)


def dominios_de_ads(conn, min_ads):
    """Dominios candidatos desde los link_url de los ads, con conteo y país."""
    doms = {}
    for pais, url in conn.execute(
            "SELECT country, link_url FROM ads WHERE link_url IS NOT NULL AND link_url != ''"):
        try:
            d = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
        except Exception:
            continue
        if not d or any(x in d for x in NO_TIENDA):
            continue
        n, p = doms.get(d, (0, pais))
        doms[d] = (n + 1, p)
    return {d: (n, p) for d, (n, p) in doms.items() if n >= min_ads}


def descubrir(args):
    conn = db()
    tablas(conn)
    doms = dominios_de_ads(conn, args.min_ads)
    ya = {r[0] for r in conn.execute("SELECT dominio FROM tiendas WHERE es_shopify IS NOT NULL")}
    nuevos = {d: v for d, v in doms.items() if d not in ya}
    hoy = datetime.date.today().isoformat()
    print(f"{len(doms)} dominios con ≥{args.min_ads} ads · {len(nuevos)} sin probar")
    shopify = 0
    for d, (n_ads, pais) in sorted(nuevos.items(), key=lambda x: -x[1][0]):
        es = 0
        try:
            body = http_get(f"https://{d}/products.json?limit=1", timeout=8)
            es = 1 if "products" in json.loads(body) else 0
        except Exception:
            es = 0
        conn.execute("INSERT OR REPLACE INTO tiendas VALUES (?,?,?,?,?)",
                     (d, pais, n_ads, es, hoy))
        if es:
            shopify += 1
            print(f"  🛍️ {d} ({pais}, {n_ads} ads)")
        time.sleep(0.6)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM tiendas WHERE es_shopify=1").fetchone()[0]
    print(f"\n{shopify} tiendas Shopify nuevas · {total} en seguimiento")
    conn.close()


def catalogo(dominio):
    """Productos públicos de la tienda (máx 2 páginas = 500)."""
    productos = []
    for page in (1, 2):
        body = http_get(f"https://{dominio}/products.json?limit=250&page={page}")
        lote = json.loads(body).get("products") or []
        for p in lote:
            precio = None
            if p.get("variants"):
                try:
                    precio = float(p["variants"][0].get("price") or 0)
                except (TypeError, ValueError):
                    pass
            productos.append({"handle": p.get("handle"), "titulo": (p.get("title") or "")[:120],
                              "precio": precio, "publicado": (p.get("published_at") or "")[:10]})
        if len(lote) < 250:
            break
        time.sleep(0.5)
    return productos


def bestsellers(dominio):
    """Handles del top best-selling (orden del HTML público)."""
    try:
        html = http_get(f"https://{dominio}/collections/all?sort_by=best-selling")
    except Exception:
        return []
    vistos, orden = set(), []
    for h in re.findall(r"/products/([a-z0-9\-]+)", html):
        if h not in vistos:
            vistos.add(h)
            orden.append(h)
    return orden[:TOP_BESTSELLER]


def snapshot(args):
    conn = db()
    tablas(conn)
    hoy = datetime.date.today().isoformat()
    tiendas = conn.execute(
        "SELECT dominio, pais FROM tiendas WHERE es_shopify = 1 ORDER BY n_ads DESC").fetchall()
    fecha_prev = conn.execute(
        "SELECT MAX(fecha) FROM tienda_productos WHERE fecha < ?", (hoy,)).fetchone()[0]
    novedades = []
    for dominio, pais in tiendas:
        try:
            productos = catalogo(dominio)
        except Exception as e:
            print(f"  ERROR {dominio}: {e}", file=sys.stderr)
            continue
        rank = {h: i + 1 for i, h in enumerate(bestsellers(dominio))}
        for p in productos:
            conn.execute("INSERT OR REPLACE INTO tienda_productos VALUES (?,?,?,?,?,?,?)",
                         (dominio, hoy, p["handle"], p["titulo"], p["precio"],
                          p["publicado"], rank.get(p["handle"])))
        print(f"  {dominio} ({pais}): {len(productos)} productos, top-{len(rank)} best-sellers")

        if fecha_prev:
            prev = {r[0]: r[1] for r in conn.execute(
                """SELECT handle, rank_bestseller FROM tienda_productos
                   WHERE dominio = ? AND fecha = ?""", (dominio, fecha_prev))}
            if not prev:
                # tienda recién descubierta: su primer catálogo completo no es "novedad"
                time.sleep(0.7)
                continue
            for p in productos:
                if p["handle"] not in prev:
                    novedades.append(f"🆕 **{p['titulo']}** — {dominio} ({pais}) · ${p['precio']:,.0f}"
                                     if p["precio"] else f"🆕 **{p['titulo']}** — {dominio} ({pais})")
            for h, r in rank.items():
                if r <= 10 and h in prev and (prev[h] is None or prev[h] > 10):
                    titulo = next((p["titulo"] for p in productos if p["handle"] == h), h)
                    novedades.append(f"📈 **{titulo}** entró al top 10 best-sellers de {dominio} (#{r})")
        time.sleep(0.7)
    conn.commit()
    conn.close()

    if fecha_prev and novedades:
        REPORTS.mkdir(parents=True, exist_ok=True)
        out = REPORTS / f"tiendas_{hoy}.md"
        out.write_text("\n".join([f"# Tiendas competidoras — novedades {hoy}", ""] +
                                 [f"- {n}" for n in novedades]))
        print(f"\n{len(novedades)} novedades → {out}")
    elif fecha_prev:
        print("\nSin novedades vs snapshot anterior")
    else:
        print("\nPrimer snapshot — las novedades salen desde el segundo día")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pd = sub.add_parser("descubrir")
    pd.add_argument("--min-ads", type=int, default=2)
    pd.set_defaults(fn=descubrir)
    ps = sub.add_parser("snapshot")
    ps.set_defaults(fn=snapshot)
    args = p.parse_args()
    args.fn(args)
