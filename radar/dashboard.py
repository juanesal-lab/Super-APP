#!/usr/bin/env python3
"""Genera docs/dashboard.html — vista visual tipo Minea del último escaneo.

Uso: python3 dashboard.py            (luego abrir docs/dashboard.html)

Nota: las imágenes/videos vienen del CDN de Meta y expiran en ~24-48h;
cada escaneo diario las refresca.
"""
import json

from radar import BASE, db, calcular_candidatos

PLANTILLA = """<!doctype html>
<html lang="es">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Radar Ganadores</title>
<style>
:root {
  --plane: #0d0d0d; --surface: #1a1a19; --surface-2: #232322;
  --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --border: rgba(255,255,255,0.10); --hair: #2c2c2a;
  --good: #0ca30c; --warn: #fab219; --accent: #3987e5;
}
* { box-sizing: border-box; margin: 0; }
body { background: var(--plane); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; padding: 20px; }
h1 { font-size: 18px; font-weight: 650; letter-spacing: .2px; }
.sub { color: var(--muted); font-size: 12.5px; margin-top: 2px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px; margin: 16px 0; }
.tile { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px; }
.tile .v { font-size: 26px; font-weight: 650; }
.tile .l { color: var(--muted); font-size: 12px; margin-top: 2px; }
.tile .v .dot { font-size: 14px; vertical-align: 3px; }
.filtros { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 12px; position: sticky; top: 8px; z-index: 5; }
.filtros input, .filtros select { background: var(--surface-2); color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 10px; font: inherit; }
.filtros input[type=search] { flex: 1; min-width: 160px; }
.seg { display: flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button { background: var(--surface-2); color: var(--ink-2); border: 0;
  padding: 7px 12px; font: inherit; cursor: pointer; }
.seg button.on { background: var(--accent); color: #fff; font-weight: 600; }
.n-res { color: var(--muted); font-size: 12.5px; margin-left: auto; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 14px; margin-top: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  overflow: hidden; display: flex; flex-direction: column; }
.media { position: relative; aspect-ratio: 1/1; background: var(--surface-2); }
.media img { width: 100%; height: 100%; object-fit: cover; display: block; }
.media .sin { width:100%; height:100%; display:flex; align-items:center;
  justify-content:center; color: var(--muted); font-size: 34px; }
.chip { position: absolute; top: 8px; left: 8px; background: rgba(13,13,13,.82);
  backdrop-filter: blur(4px); border-radius: 999px; padding: 4px 10px;
  font-size: 12.5px; font-weight: 650; display: flex; gap: 6px; align-items: center; }
.chip .band { font-weight: 500; color: var(--ink-2); }
.play { position: absolute; right: 8px; bottom: 8px; background: rgba(13,13,13,.82);
  border-radius: 999px; padding: 4px 10px; font-size: 12px; color: var(--ink);
  text-decoration: none; }
.cuerpo { padding: 11px 13px 13px; display: flex; flex-direction: column; gap: 7px; flex: 1; }
.pagina { font-weight: 600; font-size: 13.5px; display: flex; justify-content: space-between; gap: 8px; }
.pagina .pais { color: var(--muted); font-weight: 500; }
.copy { color: var(--ink-2); font-size: 12.5px; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 2.6em; }
.meta { display: flex; flex-wrap: wrap; gap: 6px; }
.meta span { background: var(--surface-2); border-radius: 6px; padding: 2.5px 7px;
  font-size: 11.5px; color: var(--ink-2); }
.acciones { margin-top: auto; display: flex; gap: 12px; padding-top: 4px;
  border-top: 1px solid var(--hair); }
.acciones a { color: var(--accent); text-decoration: none; font-size: 12.5px; font-weight: 550; }
.nicho-tag { color: var(--muted); font-size: 11.5px; text-transform: capitalize; }
.src { position: absolute; top: 8px; right: 8px; border-radius: 999px; padding: 3px 9px;
  font-size: 11.5px; font-weight: 650; }
.src-dropi { background: rgba(57,135,229,.9); color: #fff; }
.src-importacion { background: rgba(217,89,38,.9); color: #fff; }
.src-maquila { background: rgba(144,133,233,.92); color: #fff; }
.margen { background: rgba(12,163,12,.14); color: var(--good); border-radius: 6px;
  padding: 2.5px 7px; font-size: 11.5px; font-weight: 600; }
.meta .comp-op { background: rgba(12,163,12,.14); color: var(--good); font-weight: 600; }
.meta .comp-sat { background: rgba(224,82,82,.14); color: #e05252; font-weight: 600; }
.play { bottom: 40px; }
</style>
<body>
<h1>📡 Radar Ganadores</h1>
<div class="sub">Escaneo del __FECHA__ · __PAISES__ países · las imágenes expiran en ~48h (se refrescan a diario)</div>

<div class="tiles">
  <div class="tile"><div class="v">__TOTAL__</div><div class="l">Productos únicos</div></div>
  <div class="tile"><div class="v"><span class="dot" style="color:var(--good)">●</span> __FUERTES__</div><div class="l">Candidatos fuertes (≥70)</div></div>
  <div class="tile"><div class="v"><span class="dot" style="color:var(--warn)">●</span> __WATCH__</div><div class="l">Watchlist (50–69)</div></div>
  <div class="tile"><div class="v"><span class="dot" style="color:var(--accent)">●</span> __DROPI__</div><div class="l">Disponibles en Dropi 🟦</div></div>
  <div class="tile"><div class="v">__OPCO__</div><div class="l">🟢 Oportunidades EU→CO</div></div>
</div>

<div class="filtros">
  <input type="search" id="q" placeholder="Buscar producto, página o keyword…">
  <select id="pais"><option value="">País: todos</option></select>
  <select id="nicho"><option value="">Nicho: todos</option></select>
  <div class="seg" id="min">
    <button data-v="0" class="on">Todos</button><button data-v="50">50+</button><button data-v="70">70+</button>
  </div>
  <select id="comp">
    <option value="">Competencia CO: todas</option>
    <option value="oportunidad">🟢 Oportunidad (entrar ya)</option>
    <option value="saturado">🔴 Saturado</option>
    <option value="_sin">⏳ Sin verificar (ES)</option>
  </select>
  <select id="sourcing">
    <option value="">Sourcing: todos</option>
    <option value="dropi">🟦 Dropi (vender ya)</option>
    <option value="importacion">🟧 Importación</option>
    <option value="maquila">🟪 Maquila</option>
    <option value="_sin">⏳ Sin clasificar</option>
  </select>
  <select id="orden">
    <option value="score">Orden: score</option>
    <option value="dias">Orden: días activo</option>
    <option value="variaciones">Orden: variaciones</option>
    <option value="ads_pagina">Orden: ads de la página</option>
  </select>
  <span class="n-res" id="nres"></span>
</div>

<div class="grid" id="grid"></div>

<script>
const DATA = __DATA__;
const st = { q: "", pais: "", nicho: "", min: 0, orden: "score", sourcing: "", comp: "" };
const SRC = { dropi: ["src-dropi", "🟦 Dropi"], importacion: ["src-importacion", "🟧 Importar"],
              maquila: ["src-maquila", "🟪 Maquila"] };
const cop = n => "$" + (n || 0).toLocaleString("es-CO");
const EU = __EU__;
const esc = s => (s || "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const banda = s => s >= 70 ? ["var(--good)", "fuerte"] : s >= 50 ? ["var(--warn)", "watchlist"] : ["var(--muted)", "bajo"];

for (const [id, campo] of [["pais", "pais"], ["nicho", "nicho"]]) {
  const sel = document.getElementById(id);
  [...new Set(DATA.map(d => d[campo]))].sort().forEach(v => {
    const o = document.createElement("option"); o.value = v; o.textContent = v.replaceAll("_", " ");
    sel.appendChild(o);
  });
  sel.onchange = () => { st[campo] = sel.value; render(); };
}
document.getElementById("q").oninput = e => { st.q = e.target.value.toLowerCase(); render(); };
document.getElementById("sourcing").onchange = e => { st.sourcing = e.target.value; render(); };
document.getElementById("comp").onchange = e => { st.comp = e.target.value; render(); };
document.getElementById("orden").onchange = e => { st.orden = e.target.value; render(); };
document.querySelectorAll("#min button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#min button").forEach(x => x.classList.remove("on"));
  b.classList.add("on"); st.min = +b.dataset.v; render();
});

function render() {
  let rows = DATA.filter(d =>
    d.score >= st.min &&
    (!st.pais || d.pais === st.pais) &&
    (!st.nicho || d.nicho === st.nicho) &&
    (!st.sourcing || (st.sourcing === "_sin" ? !d.sourcing : d.sourcing === st.sourcing)) &&
    (!st.comp || (st.comp === "_sin" ? (EU.includes(d.pais) && !d.comp_estado) : d.comp_estado === st.comp)) &&
    (!st.q || (d.producto + " " + d.pagina + " " + d.kw).toLowerCase().includes(st.q)));
  rows.sort((a, b) => b[st.orden] - a[st.orden]);
  document.getElementById("nres").textContent = rows.length + " resultados";
  document.getElementById("grid").innerHTML = rows.slice(0, 200).map(d => {
    const [color, label] = banda(d.score);
    const media = d.img
      ? `<img src="${esc(d.img)}" loading="lazy" onerror="this.outerHTML='<div class=sin>🖼️</div>'">`
      : `<div class="sin">${d.formato === "VIDEO" ? "🎬" : "🖼️"}</div>`;
    const play = d.video ? `<a class="play" href="${esc(d.video)}" target="_blank">▶ video</a>` : "";
    const tienda = d.link ? ` · <a href="${esc(d.link)}" target="_blank">Tienda ↗</a>` : "";
    const src = SRC[d.sourcing]
      ? `<div class="src ${SRC[d.sourcing][0]}">${SRC[d.sourcing][1]}</div>` : "";
    const dropi = d.sourcing === "dropi" && d.dropi_costo
      ? `<span class="margen" title="En Dropi: ${esc(d.dropi_nombre || "")}">💰 ${cop(d.dropi_costo)} → ${cop(d.dropi_sugerido)}</span>` +
        (d.dropi_stock != null ? `<span>📦 ${d.dropi_stock.toLocaleString("es-CO")}</span>` : "") +
        (d.ventas_dia > 0 ? `<span class="margen">🔥 ~${d.ventas_dia} ventas/día</span>`
         : d.stock_delta < 0 ? `<span>📦 restock reciente</span>` : "")
      : "";
    const comp = !EU.includes(d.pais) ? ""
      : d.comp_estado === "oportunidad"
        ? `<span class="comp-op" title="${esc((d.comp_paginas || []).join(", "))}">🟢 ${d.competidores} comp. CO</span>`
      : d.comp_estado === "saturado"
        ? `<span class="comp-sat" title="${esc((d.comp_paginas || []).join(", "))}">🔴 ${d.competidores} comp. CO</span>`
      : d.score >= 70 ? `<span>⏳ CO sin verificar</span>` : "";
    return `<div class="card">
      <div class="media">${media}
        <div class="chip"><span style="color:${color}">●</span>${d.score}<span class="band">${label}</span></div>${src}${play}
      </div>
      <div class="cuerpo">
        <div class="pagina"><span>${esc(d.pagina)}</span><span class="pais">${d.pais}</span></div>
        <div class="nicho-tag">${d.nicho.replaceAll("_", " ")} · kw: ${esc(d.kw)}</div>
        <div class="copy">${esc(d.copy_full || d.producto)}</div>
        <div class="meta">
          <span>📅 ${d.dias} días</span><span>🧬 ${d.variaciones} var.</span>
          <span>📄 ${d.ads_pagina} ads pág.</span>${dropi}${comp}
        </div>
        <div class="acciones"><a href="${d.ad_library}" target="_blank">Ver en Ad Library ↗</a>${tienda}</div>
      </div>
    </div>`;
  }).join("");
}
render();
</script>
</body>
</html>
"""


def cargar_sourcing(conn):
    """Etiqueta de sourcing por clave de candidato (si existe la tabla)."""
    try:
        filas = conn.execute("""SELECT clave, etiqueta, dropi_nombre, dropi_precio_prov,
                                       dropi_sugerido, dropi_stock, dropi_id FROM sourcing""").fetchall()
    except Exception:
        return {}
    try:
        from stock import deltas
        movs = deltas(conn)
    except Exception:
        movs = {}
    out = {}
    for clave, etiqueta, dn, costo, sug, stock, did in filas:
        margen = (sug - costo) if (sug and costo) else None
        m = movs.get(str(did), {})
        out[clave] = {
            "sourcing": etiqueta, "dropi_nombre": dn,
            "dropi_costo": costo, "dropi_sugerido": sug, "dropi_stock": stock,
            "margen": margen,
            "ventas_dia": m.get("ventas_dia"), "stock_delta": m.get("delta"),
        }
    return out


def cargar_competencia(conn):
    """Estado de competencia CO por clave (detector EU→CO, si existe la tabla)."""
    try:
        filas = conn.execute(
            "SELECT clave, estado, competidores, paginas FROM competencia_co").fetchall()
    except Exception:
        return {}
    return {clave: {"comp_estado": estado, "competidores": comp,
                    "comp_paginas": json.loads(paginas or "[]")}
            for clave, estado, comp, paginas in filas}


def main():
    config = json.loads((BASE / "config.json").read_text())
    conn = db()
    fecha = conn.execute("SELECT MAX(scan_date) FROM snapshots").fetchone()[0]
    if not fecha:
        raise SystemExit("Base vacía. Corre primero: python3 radar.py scan")
    candidatos, _ = calcular_candidatos(conn, fecha)
    sourcing = cargar_sourcing(conn)
    competencia = cargar_competencia(conn)
    for c in candidatos:
        c.update(sourcing.get(c["clave"], {"sourcing": ""}))
        c.update(competencia.get(c["clave"], {}))
    conn.close()

    fuertes = sum(1 for c in candidatos if c["score"] >= 70)
    watch = sum(1 for c in candidatos if 50 <= c["score"] < 70)
    en_dropi = sum(1 for c in candidatos if c.get("sourcing") == "dropi")
    op_co = sum(1 for c in candidatos if c.get("comp_estado") == "oportunidad")

    html = (PLANTILLA
            .replace("__FECHA__", fecha)
            .replace("__TOTAL__", str(len(candidatos)))
            .replace("__FUERTES__", str(fuertes))
            .replace("__WATCH__", str(watch))
            .replace("__DROPI__", str(en_dropi))
            .replace("__OPCO__", str(op_co))
            .replace("__PAISES__", str(len(config["countries_activos"])))
            .replace("__EU__", json.dumps(config.get("paises_eu", ["ES"])))
            .replace("__DATA__", json.dumps(candidatos, ensure_ascii=False)))

    out = BASE / "docs" / "dashboard.html"
    out.write_text(html)
    print(f"Dashboard: {out}  ({len(candidatos)} productos, {fuertes} fuertes)")


if __name__ == "__main__":
    main()
