"""📡 Radar Ganadores — módulo de la Super-APP.

Expone el spy tool (radar/) dentro de la app:
  GET /radar                 → dashboard visual tipo Minea (lo regenera el cron diario)
  GET /api/radar/resumen     → conteos del último escaneo
  GET /api/radar/candidatos  → candidatos con score/sourcing/competencia (filtrables)

El motor vive en radar/ (solo stdlib, sin dependencias). Cada quien pone su
ScrapeCreators API key en radar/.env; radar/HANDOFF.md explica todo el sistema.
"""
import json
import os
import sys

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

RADAR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "radar")
sys.path.insert(0, RADAR_DIR)

router = APIRouter()

SIN_DATOS = """<!doctype html><meta charset="utf-8">
<body style="background:#0d0d0d;color:#fff;font-family:system-ui;padding:40px;line-height:1.6">
<h2>📡 Radar Ganadores — todo se hace desde aquí</h2>
<ol>
 <li>Saca tu key GRATIS en <a href="https://scrapecreators.com" target="_blank"
     style="color:#e8b820">scrapecreators.com</a> (regístrate y copia la API key — 1.000 créditos
     gratis; cada escaneo gasta ~69).</li>
 <li>Pégala en la pestaña <b>🔑 Claves</b> de la app (tarjeta "📡 ScrapeCreators — Radar").</li>
 <li>Dale al botón: <button id="scanBtn" onclick="lanzarScan()" style="background:#e8b820;color:#1a1610;
     border:0;border-radius:10px;padding:10px 18px;font-weight:800;cursor:pointer;font-size:14px">
     🛰️ Escanear ahora</button></li>
</ol>
<p id="scanMsg" style="color:#9a927f"></p>
<script>
async function lanzarScan(){
  const b=document.getElementById('scanBtn'), m=document.getElementById('scanMsg');
  b.disabled=true; m.textContent='⏳ Escaneando la Meta Ad Library (2-5 min, gasta ~69 créditos)...';
  try{
    const r=await fetch('/api/radar/scan',{method:'POST'});
    const j=await r.json();
    if(!r.ok||!j.ok){ throw new Error(j.detail||j.error||'no se pudo'); }
    poll();
  }catch(e){ m.textContent='⚠️ '+(e.message||e); b.disabled=false; }
}
async function poll(){
  const m=document.getElementById('scanMsg');
  try{
    const j=await (await fetch('/api/radar/scan-status')).json();
    if(j.status==='running'){ m.textContent='⏳ '+(j.message||'Escaneando...'); setTimeout(poll,4000); return; }
    if(j.status==='done'){ m.textContent='✅ Listo — cargando el dashboard...'; setTimeout(()=>location.reload(),1200); return; }
    m.textContent='⚠️ '+(j.message||'Falló el escaneo'); document.getElementById('scanBtn').disabled=false;
  }catch(e){ setTimeout(poll,4000); }
}
</script>
</body>"""


def _motor():
    import radar as motor
    import dashboard as dash
    return motor, dash


def _hay_datos():
    return os.path.exists(os.path.join(RADAR_DIR, "radar.db"))


def _candidatos_completos():
    """Candidatos del último escaneo con sourcing y competencia fusionados."""
    motor, dash = _motor()
    conn = motor.db()
    fecha = conn.execute("SELECT MAX(scan_date) FROM snapshots").fetchone()[0]
    if not fecha:
        conn.close()
        return None, []
    cands, _ = motor.calcular_candidatos(conn, fecha)
    sourcing = dash.cargar_sourcing(conn)
    competencia = dash.cargar_competencia(conn)
    for c in cands:
        c.update(sourcing.get(c["clave"], {"sourcing": ""}))
        c.update(competencia.get(c["clave"], {}))
    conn.close()
    return fecha, cands


@router.get("/radar")
def radar_dashboard():
    html = os.path.join(RADAR_DIR, "docs", "dashboard.html")
    if os.path.exists(html):
        return FileResponse(html, media_type="text/html")
    return HTMLResponse(SIN_DATOS)


# ── 🛰️ Escaneo DESDE LA APP (pedido de Jack: cero terminal) ──────────────────────────────
# Corre scan → report → dashboard como subprocesos (el motor es stdlib puro). Estado en
# memoria; el botón de la página /radar (SIN_DATOS) lo dispara y sondea /api/radar/scan-status.
_SCAN = {"status": "idle", "message": ""}


def _radar_key_ok() -> bool:
    """¿Hay SCRAPECREATORS_API_KEY en radar/.env? (el motor lee SU propio .env)."""
    try:
        renv = os.path.join(RADAR_DIR, ".env")
        return os.path.exists(renv) and any(
            l.startswith("SCRAPECREATORS_API_KEY=") and l.split("=", 1)[1].strip()
            for l in open(renv))
    except Exception:  # noqa: BLE001
        return False


def _run_scan():
    import subprocess
    pasos = [("Escaneando la Meta Ad Library (~69 créditos)...", [sys.executable, "radar.py", "scan"]),
             ("Armando el reporte del día...", [sys.executable, "radar.py", "report"]),
             ("Generando el dashboard...", [sys.executable, "dashboard.py"])]
    try:
        for msg, cmd in pasos:
            _SCAN["message"] = msg
            r = subprocess.run(cmd, cwd=RADAR_DIR, capture_output=True, text=True, timeout=1800)
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "").strip()[-400:]
                _SCAN["status"] = "error"
                _SCAN["message"] = f"Falló '{' '.join(cmd[1:])}': {err or 'sin detalle'}"
                return
        _SCAN["status"] = "done"
        _SCAN["message"] = "Radar listo"
    except Exception as e:  # noqa: BLE001
        _SCAN["status"] = "error"
        _SCAN["message"] = f"Error del escaneo: {e}"


@router.post("/api/radar/scan")
def radar_scan():
    """Dispara el ciclo scan+report+dashboard en background. Gasta ~69 créditos de ScrapeCreators
    → SOLO se corre cuando el usuario le da al botón (nunca automático)."""
    if _SCAN["status"] == "running":
        return {"ok": True, "ya_corriendo": True}
    if not _radar_key_ok():
        return {"ok": False,
                "error": "Falta la key de ScrapeCreators — pégala en 🔑 Claves (tarjeta 📡 Radar) "
                         "y vuelve a intentar."}
    _SCAN["status"] = "running"
    _SCAN["message"] = "Arrancando el escaneo..."
    import threading
    threading.Thread(target=_run_scan, daemon=True).start()
    return {"ok": True}


@router.get("/api/radar/scan-status")
def radar_scan_status():
    return dict(_SCAN)


@router.get("/api/radar/resumen")
def radar_resumen():
    if not _hay_datos():
        return {"instalado": False}
    fecha, cands = _candidatos_completos()
    return {
        "instalado": True,
        "fecha": fecha,
        "productos": len(cands),
        "fuertes": sum(1 for c in cands if c["score"] >= 70),
        "watchlist": sum(1 for c in cands if 50 <= c["score"] < 70),
        "en_dropi": sum(1 for c in cands if c.get("sourcing") == "dropi"),
        "oportunidades_eu_co": sum(1 for c in cands if c.get("comp_estado") == "oportunidad"),
        "paises": sorted({c["pais"] for c in cands}),
    }


@router.get("/api/radar/candidatos")
def radar_candidatos(min_score: int = 50, pais: str = "", sourcing: str = "",
                     limite: int = 100):
    if not _hay_datos():
        return {"instalado": False, "candidatos": []}
    fecha, cands = _candidatos_completos()
    filtrados = [c for c in cands
                 if c["score"] >= min_score
                 and (not pais or c["pais"] == pais)
                 and (not sourcing or c.get("sourcing") == sourcing)]
    return {"instalado": True, "fecha": fecha, "total": len(filtrados),
            "candidatos": filtrados[:limite]}
