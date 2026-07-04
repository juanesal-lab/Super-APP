#!/usr/bin/env python3
"""Detector de oportunidad Europa → Colombia.

Para candidatos descubiertos en España (donde la ley DSA expone reach real),
verifica cuántas páginas ya anuncian ese producto en Colombia:
  0-2 competidores  → 🟢 oportunidad (entrar antes de la ola)
  >2                → 🔴 saturado (descartado)
El corte vive en config.json → max_competidores_co.

Flujo (semi-automático, igual que sourcing.py):
  1. python3 oportunidad.py preparar [--min-score 70] [--top 20]
       → docs/oportunidad_pendientes.json con los candidatos ES del último
         escaneo. "nombre_canonico" lo llena la IA (reusa el de sourcing si ya existe).
  2. python3 oportunidad.py verificar [--max 15] [--umbral 0.75]
       → 1 crédito por candidato (búsqueda Ad Library CO, 30 ads).
         Guarda en la tabla `competencia_co` (la lee el dashboard).

Un competidor cuenta solo si su copy coincide con el nombre canónico
(similitud de tokens ≥ umbral) y no es marketplace ni página excluida.
"""
import argparse
import datetime
import json

from radar import (BASE, api_get, calcular_candidatos, cargar_privado, db,
                   es_marketplace, es_privado, load_api_key)
from sourcing import similitud

PENDIENTES = BASE / "docs" / "oportunidad_pendientes.json"


def tabla(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS competencia_co (
      clave TEXT PRIMARY KEY,
      fecha TEXT,
      nombre_canonico TEXT,
      competidores INTEGER,
      paginas TEXT,            -- JSON [nombres de páginas competidoras en CO]
      ads_revisados INTEGER,   -- ads devueltos por la búsqueda (contexto)
      estado TEXT              -- oportunidad | saturado
    )""")


def nombres_de_sourcing(conn):
    """Nombres canónicos ya extraídos por el clasificador de sourcing."""
    try:
        return dict(conn.execute(
            "SELECT clave, nombre_canonico FROM sourcing WHERE nombre_canonico != ''"))
    except Exception:
        return {}


def preparar(args):
    conn = db()
    config = json.loads((BASE / "config.json").read_text())
    paises_eu = set(config.get("paises_eu", ["ES"]))
    fecha = conn.execute("SELECT MAX(scan_date) FROM snapshots").fetchone()[0]
    candidatos, _ = calcular_candidatos(conn, fecha)
    tabla(conn)
    ya = {r[0] for r in conn.execute("SELECT clave FROM competencia_co")}
    canonicos = nombres_de_sourcing(conn)
    pendientes = []
    for c in candidatos:
        if c["pais"] not in paises_eu or c["score"] < args.min_score or c["clave"] in ya:
            continue
        pendientes.append({
            "clave": c["clave"], "score": c["score"], "nicho": c["nicho"],
            "pagina": c["pagina"], "copy": c["copy_full"][:220],
            "nombre_canonico": canonicos.get(c["clave"], ""),
        })
        if len(pendientes) >= args.top:
            break
    PENDIENTES.write_text(json.dumps(pendientes, ensure_ascii=False, indent=1))
    con_nombre = sum(1 for p in pendientes if p["nombre_canonico"])
    print(f"{len(pendientes)} candidatos ES pendientes ({con_nombre} ya con nombre) → {PENDIENTES}")
    conn.close()


def verificar(args):
    key = load_api_key()
    config = json.loads((BASE / "config.json").read_text())
    max_comp = config.get("max_competidores_co", 2)
    datos = json.loads(PENDIENTES.read_text())
    conn = db()
    tabla(conn)
    priv = cargar_privado()
    hoy = datetime.date.today().isoformat()
    # caché por nombre canónico: productos duplicados (varios ads del mismo
    # producto) comparten resultado y no gastan créditos extra
    cache = {r[0]: r[1:] for r in conn.execute(
        """SELECT nombre_canonico, competidores, paginas, ads_revisados, estado
           FROM competencia_co WHERE fecha = ?""", (hoy,))}
    creditos, llamadas = None, 0
    for item in datos:
        nombre = (item.get("nombre_canonico") or "").strip()
        if not nombre:
            continue
        if nombre in cache:
            n_comp, paginas_json, n_ads, estado = cache[nombre]
        else:
            if llamadas >= args.max:
                continue
            llamadas += 1
            data = api_get("search/ads",
                           {"query": nombre, "country": "CO", "status": "ACTIVE"}, key)
            creditos = data.get("credits_remaining", creditos)
            ads = data.get("searchResults") or []
            paginas = {}
            for ad in ads:
                snap = ad.get("snapshot") or {}
                page_name = ad.get("page_name") or snap.get("page_name")
                if es_marketplace(page_name, snap.get("link_url")) \
                   or es_privado(ad.get("page_id"), page_name, priv):
                    continue
                texto = f"{((snap.get('body') or {}).get('text') or '')} {snap.get('title') or ''}"
                for card in (snap.get("cards") or [])[:1]:
                    texto += f" {(card or {}).get('body') or ''}"
                if similitud(nombre, texto) >= args.umbral:
                    paginas[ad.get("page_id")] = page_name
            n_comp, n_ads = len(paginas), len(ads)
            paginas_json = json.dumps(sorted(set(paginas.values())), ensure_ascii=False)
            estado = "oportunidad" if n_comp <= max_comp else "saturado"
            cache[nombre] = (n_comp, paginas_json, n_ads, estado)
            icono = "🟢" if estado == "oportunidad" else "🔴"
            quien = f" ({', '.join(json.loads(paginas_json)[:3])})" if n_comp else ""
            print(f"{icono} {nombre}: {n_comp} competidores CO de {n_ads} ads{quien}")
        conn.execute(
            """INSERT OR REPLACE INTO competencia_co
               (clave, fecha, nombre_canonico, competidores, paginas, ads_revisados, estado)
               VALUES (?,?,?,?,?,?,?)""",
            (item["clave"], hoy, nombre, n_comp, paginas_json, n_ads, estado))
    conn.commit()
    conn.close()
    print(f"\n{llamadas} búsquedas ({llamadas} créditos). Créditos restantes: {creditos}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("preparar")
    pp.add_argument("--min-score", type=int, default=70)
    pp.add_argument("--top", type=int, default=20)
    pp.set_defaults(fn=preparar)
    pv = sub.add_parser("verificar")
    pv.add_argument("--max", type=int, default=15)
    pv.add_argument("--umbral", type=float, default=0.75)
    pv.set_defaults(fn=verificar)
    args = p.parse_args()
    args.fn(args)
