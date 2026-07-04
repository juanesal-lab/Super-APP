# Radar Ganadores — Plan Maestro

> Herramienta propia tipo Minea, enfocada en Colombia/LATAM, para detectar anuncios y productos
> ganadores de dropshipping. Compartida con socio vía Google Cloud Run.
> Plan creado el 2 de julio de 2026 tras investigación con 3 agentes (~15 min, fuentes primarias verificadas).

---

## 1. La tesis (por qué esto le gana a Minea en nuestro mercado)

- Minea/PiPiAds tienen **sesgo estructural US/EU**: sus playbooks recomiendan Nordics/Canada/Australia; la cobertura de ads en español (CO/EC/PE) es rala y con lag. Sus sales trackers no sirven para tiendas COD <$30k/mes (error 20-40%) e ignoran Dropi/COD por completo.
- **Nadie tiene el spend real fuera de la UE.** Meta no lo publica. Todos los spy tools lo infieren de las mismas señales públicas que nosotros podemos capturar directamente: días activo, variaciones del creativo, ads activos por página, engagement.
- Tenemos una señal que Minea NO tiene: **ventas COD reales en Colombia vía fluctuaciones de stock en Dropi** (técnica confirmada — es lo que venden Dropdata $9.99/mes y TuWinner $29-39/mes).

## 2. Decisiones de stack (verificadas, con precios)

### Fuentes de datos

| Fuente | Para qué | Cómo | Costo | Fase |
|---|---|---|---|---|
| **Meta Ad Library** (fuente principal) | Detectar ads escalando en CO por keyword + espiar páginas competidoras | **ScrapeCreators API** (`/v1/facebook/adLibrary/search/ads`, `/company/ads`, `/ad`, `/ad/transcript`) | Free 1.000 créditos → pack **$47 único, 25.000 créditos, no expiran** (~8-12 meses) | 1 |
| **Engagement del post** | Likes/comments/shares reales del ad (proxy de tracción) | Post ID sale del snapshot del scraper → página pública del post | $0 | 1-2 |
| **Dropi (stock tracking)** | Ventas COD reales en Colombia — la señal más directa que existe | Snapshots periódicos del catálogo con cuenta propia; stock que baja = ventas inferidas. Atajo temporal: Dropdata $9.99/mes | $0 (cuenta propia) | 2 |
| **Shopify competidores** | Best-sellers y productos nuevos de tiendas COD colombianas | `/products.json` + `/collections/all?sort_by=best-selling` (verificado funcionando jul 2026) + diffs de catálogo | $0 | 2 |
| **TikTok Creative Center** | Señal temprana de creativos con tracción en CO (CTR bucket, likes) | Actor de Apify (~$0.30-3 por corrida de 100-500 ads) | ~$5-10/mes | 3 |
| **CJ Dropshipping API** | Adopción global (`listedNum` = cuántas tiendas listaron el producto) | API oficial gratis, 1.000 req/día, endpoint trending | $0 | 3 (opcional) |

### Estrategia multi-región (decisión de Juan, 2 jul 2026)

Escanear **Colombia (mercado propio) + España (validación con datos reales) + México (opcional, segundo LATAM)**:

- **CO** — donde se vende. Señales: días activo, variaciones, ads por página, engagement.
- **ES** — mismo idioma, y por la ley DSA cada ad expone **alcance real** (`eu_total_reach`), demografía por edad/género y targeting. Verificado en vivo el 2 jul 2026: el endpoint `/ad` de ScrapeCreators devuelve `aaa_info.eu_total_reach` con números exactos. Un producto con millones de alcance en España + apareciendo en CO = validación doble.
- **MX** — mercado COD más grande de LATAM; adelanta tendencias que llegan a CO. Activable luego (solo cuesta créditos).

Uso eficiente de créditos: la búsqueda masiva (1 crédito = 30 ads) para descubrir; el endpoint de detalle (1 crédito = 1 ad) solo para candidatos europeos con score alto, para extraer su alcance real.

**Descartados (con razón):** API oficial de Meta (ciega para ads comerciales solo-CO — confirmado en docs v25.0 y GitHub issues), actor oficial de Apify (2.55★, 6× más caro), RapidAPI (precios no verificables), TikTok Commercial Content Library (solo Europa), scraper propio con Playwright (mantenimiento perpetuo + proxies + riesgo de exposición de IPs).

**Plan B si ScrapeCreators falla/cierra:** Apify `curious_coder/facebook-ads-library-scraper` ($0.75/1.000 ads, 4.76★, 31.890 usuarios, parches en ~2 días).

### Regla de seguridad NO NEGOCIABLE

**Nunca scrapear Meta desde las IPs, navegadores o sesiones donde viven los Business Managers.** Todo request a Meta sale de la infraestructura del vendor (ScrapeCreators/Apify). El scraping de Dropi y Shopify (que no toca Meta) sí puede correr en Cloud Run. No hay ningún caso documentado de baneo de BM por scrapear la Ad Library, pero Meta vincula cuentas por IP/dispositivo — cero riesgo innecesario.

### Infraestructura

- **Backend + scanner:** Python (FastAPI + cron jobs). Correrá primero local, luego en Cloud Run.
- **Base de datos:** SQLite local en Fase 1 (validación) → **Supabase Postgres free tier** en Fase 3 (Cloud Run es stateless, necesita DB externa; Supabase free = 500MB, suficiente por muchos meses).
- **App compartida:** Cloud Run (mismo esquema que la app que ya comparten) + Cloud Scheduler para el escaneo diario. Capa gratuita cubre este volumen.
- **IA (APIs que ya tiene Juan):** Gemini/OpenAI para agrupar ads por producto, clasificar nicho, analizar ángulos/hooks de los ganadores y resumir transcripciones de video (ScrapeCreators tiene endpoint de transcripción).

### Presupuesto total estimado

| Concepto | Costo |
|---|---|
| Fase 1 (validación) | **$0** (1.000 créditos free) |
| Pack ScrapeCreators | $47 una sola vez (~8-12 meses) |
| Apify TikTok (Fase 3) | ~$5-10/mes |
| Cloud Run + Scheduler + Supabase | ~$0 (capas gratuitas) |
| IA (Gemini) | ~$2-5/mes (ya tiene API) |
| **Total recurrente** | **~$10-20/mes** (techo aprobado: $100) |

## 3. El scoring (fórmula 0-100, calibrable)

Basada en ingeniería inversa de los spy tools + umbrales publicados (30+ días = rentable; 8+ variantes = presupuesto serio; 5-15 anunciantes = zona óptima).

```
Score = 0.30·L + 0.20·V + 0.20·P + 0.20·E + 0.10·R − penalizaciones
```

- **L — Longevidad (30%):** días desde inicio. 0-6d:10 · 7-14d:50 · 15-29d:80 · 30-60d:100 · 61-90d:85 · >90d:60
- **V — Variaciones del creativo (20%):** collation count. 1:20 · 2-3:50 · 4-7:80 · 8+:100
- **P — Ads activos de la página (20%):** 1-2:25 · 3-5:55 · 6-15:85 · 16-50:100 · >100:60 (marca grande)
- **E — Velocidad de engagement (20%):** `(likes + 3·comments + 5·shares) / días_activo`. ≥300/d:100 · 100:75 · 30:50 · 10:25 · <5:0. Bonus +10 si hay comentarios con intención de compra ("precio", "cómo compro", "info")
- **R — Recencia (10%):** first seen ≤30d:100 · 31-60d:70 · 61-90d:40 · >90d:10

**Penalizaciones:** >15 páginas anunciando el mismo producto en CO: −15 (>30: −30) · página sin CTA de compra: −20 · sin variantes nuevas hace >21 días en página grande: −10.

**Bandas:** ≥70 candidato fuerte → checklist de validación · 50-69 watchlist (re-scorear en 5-7 días) · <50 descartar.

**Clave de diseño:** el delta temporal vale más que la foto. Guardamos snapshot diario de P, V y E por ad; en v2 se agrega factor de crecimiento (ΔP semanal >+50% = "Scaling", como etiqueta Winning Hunter).

**Calibración:** el score fue validado una vez contra un historial real de campañas COD en Colombia (4/4 aciertos, y el orden del score coincidió con el desempeño real). Los detalles de esa calibración no se documentan en este proyecto.

### Checklist de validación post-detección (score ≥70)

1. Google Trends: tendencia plana o subiendo
2. Densidad de competencia: `"[producto]" site:myshopify.com` + Ad Library. Ideal 5-15 anunciantes activos en CO
3. Margen COD: precio ÷ (costo + envío) ≥ 2.5×, sweet spot LATAM $20-60 USD
4. Comentarios: intención de compra sí, quejas de calidad/entrega = oportunidad (venden pero fallan en operación)
5. Disponibilidad en Dropi/CJ + tendencia de stock
6. Encaje con los nichos objetivo del operador y BEP viable

### Clasificación por sourcing (decisión de Juan, 2 jul 2026)

Cada producto candidato se etiqueta según **cómo se conseguiría**, y el dashboard tiene un filtro de Sourcing:

| Etiqueta | Significado | Cómo se detecta |
|---|---|---|
| 🟦 **Dropi** | Está en el catálogo público de Dropi → se puede vender YA con COD en Colombia | Matcher contra el catálogo Dropi (cuenta propia): Gemini extrae el nombre canónico del producto desde el copy/imagen del ad → búsqueda difusa en el catálogo |
| 🟧 **Importación** | No está en Dropi → hay que importarlo | Sin match en Dropi; se consulta CJ Dropshipping para verificar sourcing y costo |
| 🟪 **Maquila** | Salud, suplementos, cosméticos, fórmulas → fabricación propia con maquilador | Clasificador de categoría con Gemini (ingeribles, tópicos, fórmulas) |

### Detector de oportunidad Europa → Colombia (regla de Juan)

Pipeline para candidatos descubiertos en Europa (donde hay reach real):

1. **Descubrimiento en ES/EU**: candidatos con score alto y reach verificado.
2. **Nombre canónico**: Gemini extrae el nombre genérico del producto desde el creativo/copy (ej. "cepillo de vapor para mascotas").
3. **Chequeo de competencia en Colombia**:
   - Meta Ad Library CO: buscar el producto y contar **páginas anunciantes distintas** activas (excluyendo marketplaces).
   - TikTok Colombia: verificación best-effort vía Apify (TikTok no tiene Ad Library pública fuera de Europa; se busca contenido comercial del producto).
4. **Regla de corte: más de 2 competidores activos en CO → DESCARTADO.** 0-2 → 🟢 OPORTUNIDAD.
5. El dashboard muestra el estado: 🟢 Oportunidad CO · 🔴 Saturado CO · ⏳ Sin verificar.

Config: `max_competidores_co` (default 2, ajustable). Costo: ~1-2 créditos por candidato verificado — se verifica solo el top del día (ej. top 30 ≈ 30-60 créditos), no todo el barrido.

Nota: la literatura de spy tools considera "validado sin saturar" hasta 5-15 anunciantes; la regla operativa aquí es más estricta (≤2) porque el objetivo es entrar ANTES de la ola, no montarse en ella. Por eso el orden del pipeline es Europa primero (demanda probada con datos reales) → Colombia después (verificar que la ventana siga abierta).

## 4. Fases de construcción

### Fase 0 — Cuentas y semillas (Juan, ~30 min)
- [ ] Crear cuenta en scrapecreators.com (1.000 créditos free) y pasar la API key
- [ ] Confirmar keywords semilla por nicho (propuesta inicial abajo)
- [ ] Lista de 5-20 páginas de Facebook de competidores colombianos a vigilar
- [ ] Confirmar si hay cuenta Dropi activa (para Fase 2)

**Keywords semilla propuestas (ajustar con Juan):**
- Automotriz: "carro accesorios", "volante", "frenos", "obd", "limpieza carro"
- Hogar visual: "alfombra", "tapete", "organizador cocina", "limpieza hogar", "manguera presión"
- Salud/transformación: "crecimiento", "hongos uñas", "sudoración", "postura"
- Genéricas de dropshipping COD: "pago contra entrega", "envío gratis Colombia"

### Fase 1 — Radar Meta MVP (yo, 2-4 días de trabajo)
- Scanner en Python: por cada keyword y página vigilada, consulta ScrapeCreators (CO, activos), guarda snapshot diario en SQLite (ads, páginas, collation, creativos, fechas)
- Scoring 0-100 sobre cada ad/página + agrupación de ads por producto (heurística + Gemini)
- Reporte diario en Markdown/HTML: top 10 candidatos con score, link al ad, días activo, señales
- **Backtest de calibración** contra un historial real de campañas (hecho una vez; detalles no documentados)
- Presupuesto de créditos: ~50-80 requests/día → las 2 primeras semanas salen gratis

### Fase 2 — Señales Colombia + sourcing (yo, +4-6 días)
- **Integración Dropi (cuenta de Juan):** descarga del catálogo público completo + snapshot diario de stock (deltas de stock = velocidad de venta COD real). Cruce: ad escalando en Meta + stock cayendo en Dropi = candidato máximo
- **Clasificador de sourcing (Gemini):** cada candidato se etiqueta 🟦 Dropi / 🟧 Importación / 🟪 Maquila (ver sección 3)
- **Detector de oportunidad EU→CO:** para el top del día descubierto en Europa, contar competidores activos en Colombia (Meta + TikTok best-effort); >2 → descartado, 0-2 → 🟢 Oportunidad (ver sección 3)
- **Shopify tracker:** best-sellers + productos nuevos de las tiendas competidoras (diffs de `products.json`)
- **Engagement real:** likes/comments/shares del post de cada ad candidato + detección de intención de compra en comentarios (Gemini)
- Score v2 con deltas temporales (etiquetas Testing/Scaling/Winning)
- **Dashboard v2:** filtro de Sourcing (Dropi/Importación/Maquila) + badge de competencia CO (🟢 Oportunidad / 🔴 Saturado / ⏳ Sin verificar)

### Fase 3 — App compartida en Cloud Run (yo, +3-5 días)
- Migrar SQLite → Supabase
- Dashboard web (login simple para Juan + socio): explorar candidatos, filtros por nicho/score/fecha, watchlist compartida, marcar "probado/descartado/lanzado"
- Cloud Scheduler: escaneo automático diario (madrugada) + reporte listo cada mañana
- Alertas: nuevo candidato score ≥70 → notificación (definir canal: correo/Telegram/WhatsApp)
- TikTok Creative Center CO vía Apify como señal complementaria

### Fase 4 — Inteligencia (continuo)
- Análisis de creativos ganadores con Gemini: transcripción, hook, ángulo, estructura → insumo directo para crear nuestros propios ads
- Detector de saturación (páginas duplicadas con el mismo creativo)
- Histórico de tendencias por nicho; sugerencia de BEP estimado por producto detectado
- Feedback loop: lo que Juan lanza y su resultado real re-calibra el score

## 5. Criterio de éxito

El radar se paga solo si en los primeros 2 meses detecta **1 producto** que Juan lance y valide (CPA < BEP en 7 días). Métricas de la herramienta: precisión del top-10 diario (¿cuántos candidatos pasan el checklist?), y el backtest de Fase 1 (detectar los ganadores históricos propios).

---

*Fuentes clave: docs oficiales Meta ads_archive v25.0 · scrapecreators.com (precios verificados) · apify.com/curious_coder · Dropdata/TuWinner (técnica Dropi) · Meta v. Bright Data 2024 (scraping público sin login = legal) · guías Minea LATAM. Informes completos de investigación en la sesión del 2 jul 2026.*
