#!/usr/bin/env python3
"""Snapshot diario de stock Dropi de los candidatos 🟦 — ventas COD reales.

El stock que baja día a día = unidades vendidas de verdad en Colombia
(la señal que Minea no tiene). Solo se consultan los productos matcheados
por el radar, nunca el catálogo completo.

Las consultas a Dropi corren dentro del navegador autenticado (Cloudflare
bloquea curl y el token no sale del navegador) — ver docs/dropi_api.md.

Flujo:
  0. python3 stock.py seed        (una vez: siembra el snapshot de hoy con el
                                   stock que ya trajo el clasificador de sourcing)
  1. python3 stock.py preparar    → docs/stock_pendientes.json (dropi_id + nombre)
  2. En el navegador autenticado se consulta cada producto por id/nombre
       → docs/stock_resultados.json
         [{"dropi_id": "...", "nombre": "...", "stock": N,
           "sale_price": N, "suggested_price": N}]
  3. python3 stock.py ingerir     → snapshot del día en `dropi_stock`
                                    + ventas/día vs snapshot anterior
"""
import argparse
import datetime
import json

from radar import BASE, db

PENDIENTES = BASE / "docs" / "stock_pendientes.json"
RESULTADOS = BASE / "docs" / "stock_resultados.json"


def tabla(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS dropi_stock (
      dropi_id   TEXT,
      fecha      TEXT,
      nombre     TEXT,
      stock      INTEGER,
      precio_prov INTEGER,
      precio_sug INTEGER,
      PRIMARY KEY (dropi_id, fecha)
    )""")
    # Regla de Juan (19 jul 2026): pocos proveedores = exclusividad = el premio.
    # Se captura el proveedor de cada listing para medir exclusividad por producto.
    try:
        conn.execute("ALTER TABLE dropi_stock ADD COLUMN proveedor_id TEXT")
        conn.execute("ALTER TABLE dropi_stock ADD COLUMN proveedor TEXT")
    except Exception:  # noqa: BLE001 — columnas ya existen
        pass


def deltas(conn):
    """Por dropi_id: ventas/día estimadas entre los dos últimos snapshots.
    delta negativo = subió el stock (restock del proveedor)."""
    filas = conn.execute(
        "SELECT dropi_id, fecha, stock FROM dropi_stock ORDER BY dropi_id, fecha").fetchall()
    por_id = {}
    for did, fecha, stock in filas:
        por_id.setdefault(did, []).append((fecha, stock))
    out = {}
    for did, snaps in por_id.items():
        if len(snaps) < 2:
            continue
        (f1, s1), (f2, s2) = snaps[-2], snaps[-1]
        dias = max(1, (datetime.date.fromisoformat(f2) - datetime.date.fromisoformat(f1)).days)
        delta = (s1 or 0) - (s2 or 0)
        out[did] = {"ventas_dia": round(delta / dias, 1), "delta": delta, "dias": dias}
    return out


def seed(args):
    """Siembra el snapshot inicial con el stock capturado por sourcing.py."""
    conn = db()
    tabla(conn)
    filas = conn.execute(
        """SELECT dropi_id, fecha, dropi_nombre, dropi_stock, dropi_precio_prov, dropi_sugerido
           FROM sourcing WHERE etiqueta = 'dropi' AND dropi_id IS NOT NULL""").fetchall()
    for did, fecha, nombre, stock, prov, sug in filas:
        conn.execute("INSERT OR REPLACE INTO dropi_stock VALUES (?,?,?,?,?,?)",
                     (did, fecha, nombre, stock, prov, sug))
    conn.commit()
    n = conn.execute("SELECT COUNT(DISTINCT dropi_id) FROM dropi_stock").fetchone()[0]
    print(f"Sembrado: {n} productos Dropi con snapshot inicial")
    conn.close()


def preparar(args):
    conn = db()
    tabla(conn)
    filas = conn.execute(
        """SELECT DISTINCT dropi_id, dropi_nombre FROM sourcing
           WHERE etiqueta = 'dropi' AND dropi_id IS NOT NULL""").fetchall()
    PENDIENTES.write_text(json.dumps(
        [{"dropi_id": d, "nombre": n} for d, n in filas], ensure_ascii=False, indent=1))
    print(f"{len(filas)} productos Dropi a consultar → {PENDIENTES}")
    conn.close()


def ingerir(args):
    datos = json.loads(RESULTADOS.read_text())
    conn = db()
    tabla(conn)
    hoy = datetime.date.today().isoformat()
    for item in datos:
        conn.execute("INSERT OR REPLACE INTO dropi_stock VALUES (?,?,?,?,?,?,?,?)",
                     (str(item["dropi_id"]), hoy, item.get("nombre"),
                      item.get("stock"), item.get("sale_price"),
                      item.get("suggested_price"),
                      item.get("proveedor_id"), item.get("proveedor")))
    conn.commit()
    print(f"{len(datos)} snapshots guardados ({hoy})\n")
    movs = deltas(conn)
    for item in datos:
        m = movs.get(str(item["dropi_id"]))
        if not m:
            continue
        if m["delta"] > 0:
            print(f"🔥 {item.get('nombre')}: ~{m['ventas_dia']}/día ({m['delta']} uds en {m['dias']}d)")
        elif m["delta"] < 0:
            print(f"📦 {item.get('nombre')}: restock (+{-m['delta']} uds)")
    conn.close()


def preparar_masivo(args):
    """Barrido MASIVO del catálogo Dropi por keywords de los nichos (modo sin créditos,
    19 jul 2026): ~2 keywords por nicho × 85 productos = ~2.000 productos con stock por
    corrida. Dos snapshots (48h) → ranking de ventas COD reales SIN tocar Meta ni gastar
    créditos. Genera docs/stock_masivo.js para pegar en la consola de app.dropi.co
    (sesión iniciada) o para que lo corra Claude-in-Chrome."""
    cfg = json.loads((BASE / "config.json").read_text())
    kws = []
    for nicho, por_pais in cfg.get("nichos", {}).items():
        lista = por_pais.get("CO") or (next(iter(por_pais.values()), []) if por_pais else [])
        kws += lista[:2]
    kws = list(dict.fromkeys(kws))
    js = """(async () => {
  const token = JSON.parse(localStorage['DROPI_LoginResult']).token;
  const kws = %s;
  const porId = {};
  for (const kw of kws) {
    try {
      const r = await fetch('https://api.dropi.co/api/products/v4/index', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
        body: JSON.stringify({pageSize: 85, startData: 0, privated_product: false,
          userVerified: false, favorite: false, with_collection: true, get_stock: true,
          no_count: true, search_type: 'simple', country: 'COLOMBIA', keywords: kw})
      });
      const j = await r.json();
      for (const o of (j.objects || [])) {
        const stock = (o.warehouse_product || []).reduce((s, w) => s + (w.stock || 0), 0);
        const u = o.user || {};
        porId[o.id] = {dropi_id: String(o.id), nombre: o.name, stock: stock,
          sale_price: o.sale_price, suggested_price: o.suggested_price,
          proveedor_id: u.id != null ? String(u.id) : '', proveedor: u.name || ''};
      }
      console.log('[stock_masivo]', kw, '→', (j.objects || []).length);
    } catch (e) { console.log('[stock_masivo] ERROR', kw, String(e)); }
    await new Promise(res => setTimeout(res, 400));
  }
  const out = Object.values(porId);
  window.__stock_masivo = JSON.stringify(out);
  console.log('[stock_masivo] TOTAL:', out.length, 'productos únicos — JSON en window.__stock_masivo');
  try { copy(window.__stock_masivo); console.log('[stock_masivo] copiado al portapapeles'); } catch (e) {}
  return out.length;
})()""" % json.dumps(kws, ensure_ascii=False)
    ruta = BASE / "docs" / "stock_masivo.js"
    ruta.write_text(js)
    print(f"{len(kws)} keywords de {len(cfg.get('nichos', {}))} nichos → {ruta}")
    print("1) Pega el JS en la consola de app.dropi.co (con sesión) — deja el JSON en el "
          "portapapeles y en window.__stock_masivo")
    print("2) Guarda ese JSON en docs/stock_resultados.json")
    print("3) python3 stock.py ingerir   → snapshot + 🔥 ventas/día cuando haya ≥2 snapshots")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for nombre, fn in (("seed", seed), ("preparar", preparar), ("ingerir", ingerir),
                       ("preparar_masivo", preparar_masivo)):
        sp = sub.add_parser(nombre)
        sp.set_defaults(fn=fn)
    args = p.parse_args()
    args.fn(args)
