# Radar Ganadores

Herramienta propia tipo Minea para detectar anuncios y productos ganadores de dropshipping
en Colombia + Europa. Ver `PLAN.md` para el plan maestro completo (fases, scoring, fuentes).

## Uso (Fase 1 — v0)

```bash
python3 radar.py scan      # escaneo completo según config.json (~1 crédito por keyword/país)
python3 radar.py report    # genera docs/reports/YYYY-MM-DD.md con scoring 0-100 (gratis)
python3 dashboard.py       # genera docs/dashboard.html — vista visual tipo Minea (gratis)

# escaneo puntual de prueba:
python3 radar.py scan --pais CO --kw "organizador cocina" --nicho hogar_visual
```

- **Keywords y países**: editar `config.json` (nichos → país → lista de keywords).
- **API key**: en `.env` (`SCRAPECREATORS_API_KEY`). Los créditos restantes se imprimen al final de cada scan.
- **Datos**: `radar.db` (SQLite) — snapshots diarios; el histórico alimenta las señales de tendencia (Fase 2).
- **Reportes**: `docs/reports/` — 🟢 ≥70 candidato fuerte · 🟡 50-69 watchlist · ⚪ <50 descartar.

## Estado

- [x] Fase 0 — cuentas y semillas (API validada 2 jul 2026; endpoint `/ad` confirma `eu_total_reach` real para ads UE)
- [x] Fase 1 v0 — scanner + SQLite + scoring + reporte + filtro de marketplaces
- [x] Fase 1 — primer barrido completo (2 jul: 1.970 ads, 74 candidatos ≥70) + calibración del score
      validada contra un historial real (4/4 aciertos; detalles no documentados)
- [ ] Escaneo diario: activar launchd con `cp com.radar-ganadores.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.radar-ganadores.plist`
- [ ] Fase 2 — Dropi stock tracker, Shopify competidores, engagement de posts
- [ ] Fase 3 — app compartida en Cloud Run (dashboard + cron + alertas)
- [ ] Fase 4 — análisis de creativos con IA

## Regla de seguridad

Nunca scrapear Meta desde las IPs/sesiones donde viven los Business Managers.
Todo request a Meta sale de la infraestructura de ScrapeCreators.
