#!/usr/bin/env python3
"""Clasificador de sourcing: 🟦 Dropi / 🟧 Importación / 🟪 Maquila.

Flujo (semi-automático mientras la sesión Dropi vive en el navegador):
  1. python3 sourcing.py preparar [--min-score 55] [--top 30]
       → escribe docs/sourcing_pendientes.json con los candidatos del día.
         Cada item necesita "nombre_canonico" (lo llena la IA o a mano).
  2. En el navegador autenticado de Dropi se corre la búsqueda por lotes
     (el agente lo hace con javascript_tool) → docs/sourcing_resultados.json
  3. python3 sourcing.py ingerir docs/sourcing_resultados.json
       → guarda etiquetas en la tabla `sourcing` (la lee el dashboard).

Etiquetas:
  dropi       → hay match en el catálogo público de Dropi (se puede vender YA)
  maquila     → sin match y es salud/suplemento/cosmético (fabricación propia)
  importacion → sin match y no es maquila (traerlo por CJ/importación)
"""
import argparse
import datetime
import json
import re

from radar import BASE, db, calcular_candidatos

# señales de producto de maquila (salud/suplementos/cosmética formulada)
MAQUILA_KW = (
    "suplemento", "vitamina", "colageno", "colágeno", "capsula", "cápsula",
    "pastilla", "gomita", "gummies", "crema ", "serum", "sérum", "gotas",
    "shampoo", "champu", "champú", "aceite esencial", "tratamiento capilar",
    "quemador", "detox", "proteina", "proteína", "magnesio", "melatonina",
    "creatina", "antitranspirante", "desodorante", "mascarilla", "tonico", "tónico",
)


def tabla(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS sourcing (
      clave TEXT PRIMARY KEY,
      fecha TEXT,
      nombre_canonico TEXT,
      etiqueta TEXT,             -- dropi | importacion | maquila
      dropi_nombre TEXT,
      dropi_precio_prov INTEGER,
      dropi_sugerido INTEGER,
      dropi_stock INTEGER,
      dropi_id TEXT
    )""")


def es_maquila(nombre):
    t = f" {nombre.lower()} "
    return any(k in t for k in MAQUILA_KW)


def _sin_tildes(s):
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return s


def similitud(a, b):
    """Solapamiento de tokens (0-1) entre nombre canónico y nombre Dropi.
    Normaliza tildes; ignora palabras de relleno."""
    stop = {"para", "con", "sin", "los", "las", "una", "del", "por", "dropi"}
    limpiar = lambda s: {t for t in re.findall(r"[a-zn]{4,}", _sin_tildes(s.lower())) if t not in stop}
    ta, tb = limpiar(a), limpiar(b)
    if not ta:
        return 0
    return len(ta & tb) / len(ta)


def preparar(args):
    conn = db()
    fecha = conn.execute("SELECT MAX(scan_date) FROM snapshots").fetchone()[0]
    candidatos, _ = calcular_candidatos(conn, fecha)
    tabla(conn)
    ya = {r[0] for r in conn.execute("SELECT clave FROM sourcing")}
    pendientes = []
    for c in candidatos:
        if c["score"] < args.min_score or c["clave"] in ya:
            continue
        pendientes.append({
            "clave": c["clave"], "pais": c["pais"], "score": c["score"],
            "nicho": c["nicho"], "pagina": c["pagina"],
            "copy": c["copy_full"][:220],
            "nombre_canonico": "",   # ← lo llena la IA (nombre genérico del producto)
        })
        if len(pendientes) >= args.top:
            break
    out = BASE / "docs" / "sourcing_pendientes.json"
    out.write_text(json.dumps(pendientes, ensure_ascii=False, indent=1))
    print(f"{len(pendientes)} candidatos pendientes → {out}")
    conn.close()


def ingerir(args):
    """Espera JSON: [{clave, nombre_canonico, matches:[{name, sale_price, suggested_price, stock, id}]}]"""
    datos = json.loads((BASE / args.archivo).read_text() if not args.archivo.startswith("/")
                       else open(args.archivo).read())
    conn = db()
    tabla(conn)
    hoy = datetime.date.today().isoformat()
    resumen = {"dropi": 0, "importacion": 0, "maquila": 0}
    for item in datos:
        nombre = item["nombre_canonico"]
        mejor, mejor_sim = None, 0
        for m in item.get("matches") or []:
            s = similitud(nombre, m.get("name") or "")
            if s > mejor_sim:
                mejor, mejor_sim = m, s
        if mejor and mejor_sim >= 0.5:
            etiqueta = "dropi"
        elif es_maquila(nombre) or es_maquila(item.get("copy", "")):
            etiqueta = "maquila"
        else:
            etiqueta = "importacion"
        resumen[etiqueta] += 1
        conn.execute(
            """INSERT OR REPLACE INTO sourcing
               (clave, fecha, nombre_canonico, etiqueta, dropi_nombre,
                dropi_precio_prov, dropi_sugerido, dropi_stock, dropi_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (item["clave"], hoy, nombre, etiqueta,
             mejor and mejor.get("name"), mejor and mejor.get("sale_price"),
             mejor and mejor.get("suggested_price"), mejor and mejor.get("stock"),
             mejor and str(mejor.get("id"))))
    conn.commit()
    conn.close()
    print(f"Ingerido: 🟦 dropi={resumen['dropi']} · 🟧 importacion={resumen['importacion']} · 🟪 maquila={resumen['maquila']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("preparar")
    pp.add_argument("--min-score", type=int, default=55)
    pp.add_argument("--top", type=int, default=30)
    pp.set_defaults(fn=preparar)
    pi = sub.add_parser("ingerir")
    pi.add_argument("archivo")
    pi.set_defaults(fn=ingerir)
    args = p.parse_args()
    args.fn(args)
