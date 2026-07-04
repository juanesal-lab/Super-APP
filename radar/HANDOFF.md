# Radar Ganadores — Documento de traspaso

> Spy tool propio tipo Minea para dropshipping COD en Colombia/LATAM.
> Detecta anuncios/productos ganadores en Meta Ad Library, los clasifica por
> sourcing (Dropi/importación/maquila), verifica saturación en Colombia y
> rastrea competidores (stock Dropi + catálogos Shopify).
> Estado al 3 jul 2026: Fase 1 ✅ · Fase 2 casi completa · Fase 3 (Cloud Run) pendiente.

## Qué hace la app (pipeline completo)

```
7:30am (launchd, automático)          run_daily.sh
  1. radar.py scan        → Meta Ad Library vía ScrapeCreators (CO+ES, ~69 créditos/día)
  2. radar.py report      → docs/reports/FECHA.md (top candidatos con score 0-100)
  3. tiendas.py descubrir → detecta tiendas Shopify nuevas desde los link_url de los ads
  4. tiendas.py snapshot  → catálogo + best-sellers de las tiendas (🆕 nuevos, 📈 suben al top)
  5. dashboard.py         → docs/dashboard.html (vista tipo Minea con filtros)

Manual/semi-automático (requiere navegador autenticado en Dropi o una IA que llene nombres):
  - sourcing.py preparar/ingerir     → etiqueta 🟦 Dropi / 🟧 Importación / 🟪 Maquila
  - oportunidad.py preparar/verificar→ candidatos ES → cuenta competidores en CO (🟢 ≤2 / 🔴 >2)
  - stock.py preparar/ingerir        → snapshot stock Dropi → 🔥 ventas COD/día reales
```

## Archivos

| Archivo | Qué es |
|---|---|
| `radar.py` | Núcleo: scan (ScrapeCreators→SQLite), scoring 0-100, reporte diario |
| `dashboard.py` | Genera `docs/dashboard.html` (tarjetas con creativo, score, filtros, badges) |
| `sourcing.py` | Clasificador de sourcing contra catálogo Dropi (tabla `sourcing`) |
| `oportunidad.py` | Detector EU→CO: competencia en Colombia por producto (tabla `competencia_co`) |
| `stock.py` | Snapshots de stock Dropi de candidatos 🟦 → ventas/día (tabla `dropi_stock`) |
| `tiendas.py` | Shopify tracker: 117 tiendas competidoras, catálogos y best-sellers |
| `config.json` | Países activos, 12 nichos × keywords, `max_competidores_co: 2` |
| `run_daily.sh` | Ciclo diario completo (lo llama launchd a las 7:30am) |
| `com.radar-ganadores.plist` | LaunchAgent macOS (instalado en `~/Library/LaunchAgents/`) |
| `PLAN.md` | Plan maestro: tesis, stack verificado, fórmula del score, fases |
| `docs/dropi_api.md` | Método de conexión a Dropi (endpoints, token, flujo browser) |
| `radar.db` | SQLite con todo el estado (NO va a git; sí en backups/transfer) |
| `.env` | Credenciales (NO va a git): `SCRAPECREATORS_API_KEY`, `DROPI_EMAIL`, `DROPI_PASSWORD` |
| `privado.json` | Exclusiones privadas del dueño (NO va a git ni a la app compartida — jamás) |

## Base de datos (radar.db, SQLite)

- `ads` — un registro por ad visto (página, copy, CTA, media, fechas, reach EU)
- `snapshots` — estado diario por ad (activo, collation_count) → base del score y deltas
- `sourcing` — etiqueta de sourcing + match Dropi (nombre, costo, sugerido, stock, id)
- `competencia_co` — detector EU→CO (competidores, páginas, estado 🟢/🔴)
- `dropi_stock` — snapshots de stock por producto Dropi (la señal de ventas COD)
- `tiendas` / `tienda_productos` — tiendas Shopify competidoras y sus catálogos diarios

## Scoring (PLAN.md sección 3)

`Score = 0.30·Longevidad + 0.20·Variaciones + 0.20·AdsPágina + 0.20·Engagement + 0.10·Recencia − penalizaciones`
(v0 corre sin E, pesos renormalizados). Bandas: ≥70 fuerte · 50-69 watchlist · <50 descartar.
Calibrado con backtest real: 4/4 aciertos.

## Reglas NO negociables

1. **Nunca scrapear Meta desde IPs/navegadores con sesiones de Business Managers.**
   Todo request a Meta sale de ScrapeCreators. Dropi/Shopify sí pueden ir directo.
2. **`privado.json` jamás se sube, se comparte ni se muestra** en la app compartida.
   El radar solo trabaja con datos públicos de terceros.
3. **Dropi**: el token JWT vive solo en el navegador autenticado (Cloudflare bloquea curl).
   No bajar el catálogo completo — solo consultas puntuales por candidato.
4. Presupuesto: ~$10-20/mes (techo $100). Créditos ScrapeCreators al 3 jul: ~838.

## Estado actual y pendientes

**Hecho:** scan diario automático · scoring calibrado · dashboard con filtros
(sourcing + competencia CO) · 25 candidatos clasificados · 14 productos ES verificados
en CO (4 🟢 oportunidades) · línea base stock Dropi (12 productos) · primer snapshot
Shopify (117 tiendas, 16.954 productos).

**Pendiente Fase 2:**
- Engagement real (E del score): requiere endpoint de posts de ScrapeCreators (verificar docs; el endpoint `/ad` NO trae likes/comments)
- Score v2 con deltas (Testing/Scaling/Winning): se desbloquea con 3-4 días de escaneos

**Fase 3 (siguiente gran bloque):** migrar SQLite→Supabase, dashboard web con login
(dueño + socio), deploy en Cloud Run + Cloud Scheduler, alertas de candidatos ≥70.

## Levantar la app en otra máquina

1. Copiar la carpeta completa (o clonar repo + restaurar `.env`, `privado.json`, `radar.db`)
2. Requisitos: Python 3.10+ (solo librería estándar, cero pip installs)
3. Probar: `python3 radar.py scan --pais CO --kw alfombra` (gasta 1 crédito)
4. Automatizar: copiar el .plist a `~/Library/LaunchAgents/` y `launchctl load` (macOS)
   o cron equivalente en Linux: `30 7 * * * /ruta/run_daily.sh`
