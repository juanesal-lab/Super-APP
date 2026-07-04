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
<body style="background:#0d0d0d;color:#fff;font-family:system-ui;padding:40px">
<h2>📡 Radar Ganadores — sin datos en esta máquina</h2>
<p>El motor está en <code>radar/</code> pero falta configurarlo:</p>
<ol>
 <li>Crea <code>radar/.env</code> con tu <code>SCRAPECREATORS_API_KEY</code>
     (gratis en scrapecreators.com, 1.000 créditos)</li>
 <li>Corre <code>python3 radar/radar.py scan</code> y luego <code>python3 radar/dashboard.py</code></li>
 <li>Guía completa: <code>radar/HANDOFF.md</code></li>
</ol></body>"""


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
