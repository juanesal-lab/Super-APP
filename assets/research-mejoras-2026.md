# 🔬 Research "todo lo bueno" 2026 — mejoras accionables para Super-APP

Investigación (agente, 2026-07-15) para Jack: **dropshipper COD en Colombia** que crea ads con IA
y necesita que **VENDAN**. Foco en lo accionable para UNA persona con ESTA app (nada enterprise,
nada que necesite equipo). Cuatro frentes: (a) creative testing Meta/TikTok, (b) herramientas
tipo Foreplay/Motion/Icon.me/AtriaAI, (c) COD LATAM, (d) señales de Meta para matar/escalar.

> Cada mejora del roadmap dice **sobre qué módulo real** se monta (según `RESUMEN-TECNICO.md`) y,
> si ya lo tenemos, **lo dice claro**.

---

## A) Creative testing Meta/TikTok en 2026 — números concretos

**Estructura de campaña (post-Andromeda, Q1-2026):** el estándar en ecommerce es **1 campaña
CBO de prospecting, 1 ad set, colocaciones amplias, sin exclusiones, con 15-50 creativos
apilados adentro**. ABO queda SOLO para tests aislados de un ángulo nuevo o para forzar gasto a
un creativo puntual. Andromeda lee el CONTENIDO del anuncio y agrupa los parecidos → hay que
darle ángulos/temperaturas DISTINTAS, no variar color/copy.
[skaleit](https://skaleit.agency/blog/meta-ads-testing-structure-post-andromeda/) ·
[segwise](https://segwise.ai/blog/abo-cbo-meta-ads-budget-strategies)

**Cadencia (cuántos creativos por semana):**
- Presupuesto chico (el caso de Jack, <$100/día): **1 campaña amplia con 6+ creativos**, toda la
  energía en la CALIDAD del creativo.
- Volumen manda: marcas que testean **20+ ads nuevos/mes rinden 65% más ROAS** que las que
  testean <10. En TikTok, testear 100+ videos/mes supera a testear 10 aunque el otro piense mejor.
- Iteración de un ganador: **4-6 variaciones** en cuentas de bajo gasto (8-12 medio, 15-20 alto).
  Un ganador debe volverse **5-10 iteraciones rentables**, no un solo ad que exprimes hasta que muere.
[adriselab](https://adriselab.com/blog/meta-ads-budget-optimization-2026) ·
[hawky](https://hawky.ai/blog/creative-iterations-scale-winning-ads) ·
[tikadtools](https://tikadtools.com/blog/tiktok-ads-dropshipping/)

**Señales tempranas de ganador (el orden en que aparecen):**
1. **Thumbstop / hook rate** (vistas de 3s ÷ impresiones): si el gancho es débil, se ve ACÁ primero.
   Bueno = **25-35% en Meta, 35-45% en TikTok**.
2. **Hold rate** (reproducciones de 15s ÷ vistas de 3s): promedio sano **40-50%**.
3. En TikTok las señales tempranas (CTR, CPC, add-to-cart, CPM) salen a las **48-72h**; compra real
   a los **3-5 días** si el creativo está sano.
[motionapp](https://motionapp.com/blog/key-creative-performance-metrics) ·
[admanage](https://admanage.ai/blog/what-is-a-good-hook-rate-for-facebook-ads) ·
[tikadtools](https://tikadtools.com/blog/tiktok-ads-dropshipping/)

**Reglas matar/iterar/escalar (umbrales 2026):**
- **Escalar:** hook rate **>30%** Y CPA ≤ objetivo.
- **Iterar:** hook rate **>25%** pero CPA **10-30% arriba** del objetivo (el gancho engancha, el cuerpo/oferta falla).
- **Matar:** hook rate **<25%** O CPA **>50% arriba** del objetivo.
- **Muestra mínima para creerle a un CPA:** ~**50 resultados por variante**, o **3-4 días** (menos de
  4 días casi siempre es ruido). Gasta **1.5-2× tu CPA objetivo** (o 2-3× el precio del producto)
  antes de juzgar. Matar a las pocas horas = tirar plata y data.
[topgrowthmarketing](https://topgrowthmarketing.com/meta-ads-creative-testing-framework/) ·
[youngurbanproject](https://www.youngurbanproject.com/how-to-build-a-meta-ads-creative-decision-framework/) ·
[stackmatix](https://www.stackmatix.com/blog/meta-ads-minimum-daily-budget-2026)

**Refresh / fatiga (basado en señal, no en calendario):** refrescar TOFU cada 1-2 semanas, MOFU
2-4, retargeting 4-6 — pero SOLO cuando dispara el gatillo (frequency alta, caída de CTR o de CVR).
[goodmorningco](https://goodmorningco.com/blog/how-often-refresh-meta-ads-creative)

---

## B) Herramientas (Foreplay / Motion / Icon.me / AtriaAI) — qué hacen y qué NOS falta

| Herramienta | Qué hace | ¿Lo tenemos? |
|---|---|---|
| **Foreplay** | Swipe file + librería 100M ads + **Briefs**: transcribe el ad, resume hook/cuerpo/CTA, y de 5 refs saca patrón → script → **storyboard** en 1 clic, en 150+ idiomas. | Parcial: usamos su API de ganadores + 🧬 "usar estructura". NO exportamos brief/storyboard reusable. |
| **Motion** | Analítica **post-lanzamiento**: etiqueta tus creativos por hook/ángulo/formato y compara performance (CPA/ROAS) por etiqueta, Meta+TikTok. Útil solo con gasto real (>$5k/mes). | NO — y requiere conectar la cuenta de ads (API Meta). Fuera de alcance solo-operador chico. |
| **Icon.me** | Conecta tu ad account → reporte de performance con **hook rate/conversiones**; + editor de video (AdCut) e imagen (Canvas) hechos para ads. | NO el reporte (necesita Meta API). El editor SÍ lo tenemos (Editor + Ads imagen). |
| **AtriaAI** | **Raya** (agente estratega, feb-2026): monitorea competidores, etiqueta tus creativos, sugiere y GENERA conceptos sin que se lo pidas. **Radar** analiza tu cuenta y sugiere variaciones. Librería 25M ads. | Parcial: nuestro 📡 Radar (ScrapeCreators) monitorea ganadores; NO analiza la cuenta propia. |
| **Arcads / Creatify** | **UGC con actor IA**: 300-1500+ avatares que hablan (gestos, emoción, 29+ idiomas incl. español). Arcads ($100/mo) = hero realista; Creatify ($39/mo) = volumen. | NO — gap real. Requiere key/pago nuevos que Jack no tiene hoy. |

**Lectura crítica:** las herramientas de analítica de cuenta (Motion/Icon/Atria-Radar) necesitan la
**Meta Marketing API** conectada y gasto suficiente — no encajan con un solo operador de presupuesto
chico. Lo que SÍ nos falta y es viable: **(1)** decirle a Jack CÓMO testear/matar/escalar (nadie en
la app lo guía hoy), **(2)** una convención de nombres para que lea sus campañas por avatar/etapa, y
**(3)** UGC con actor IA cuando tenga key.
[tryatria](https://www.tryatria.com/blog/best-ai-ad-tools-for-creative-analysis) ·
[foreplay/briefs](https://www.foreplay.co/briefs) ·
[adlibrary/motion-vs-foreplay](https://adlibrary.com/posts/motion-vs-foreplay) ·
[creatify/icon-me](https://creatify.ai/review/icon-me) ·
[arcads](https://www.arcads.ai/) ·
[designrevision](https://designrevision.com/blog/arcads-vs-creatify-vs-clipmake)

---

## C) COD LATAM (contraentrega, upsells, WhatsApp) — 2026

- **Colombia:** 74% de adopción de WhatsApp; la cultura de compra es negociación directa → WhatsApp
  encaja con cómo ya compran. COD = **15-17%** de las transacciones en CO/PE/MX.
- **WhatsApp Pay** llega a ≥6 países LatAm (incl. Colombia y México) a fin de 2026: dentro del chat
  se ofrecen 3 opciones — prepago total, depósito parcial, o **contraentrega** — y el agente empuja
  al prepago con un **pequeño descuento**. Se proyecta que 65% de las transacciones por WhatsApp en
  LatAm serán asistidas por IA hacia 2027.
- **Confirmación de pedido** por teléfono/WhatsApp ANTES de despachar es estándar (baja pedidos
  falsos y hace upsell/cross-sell). Apps tipo **EasySell** reemplazan el checkout por un **formulario
  COD** con: **upsells y ofertas por cantidad**, **downsells**, **recuperación de carrito** y
  **verificación OTP por SMS/WhatsApp** contra pedidos fantasma.
[easysellapp](https://easysellapp.com/blogs/wiki/whatsapp-ai-agents-ecommerce-latin-america-cod-2026) ·
[trafficmanager](https://www.trafficmanager.com/blog/2025/09/how-and-why-cash-on-delivery-cod-replaced-dropshipping-in-europe-and-is-about-to-do-it-in-latam-as-well/) ·
[Shopify App Store — EasySell](https://apps.shopify.com/easy-order-form)

**Lectura crítica:** la app arma la LANDING pero NO da munición para el momento COD que decide la
venta: el **guion de confirmación por WhatsApp** y los **upsell/downsell** (donde se gana el margen).
El formulario COD/OTP es una app de Shopify (EasySell) que Jack instala aparte — nosotros podemos
generar el **copy/flujo** en es-CO, con su oferta EXACTA (sin inventar precios, regla de oro).

---

## D) Señales de Meta para matar/escalar — resumen accionable (ver §A para fuentes)

| Métrica | Fórmula | Umbral 2026 | Acción |
|---|---|---|---|
| Hook rate (thumbstop) | vistas 3s ÷ impresiones | ≥30% escala · 25-30% itera · <25% mata | primero que mira |
| Hold rate | plays 15s ÷ vistas 3s | 40-50% sano | si baja: el cuerpo aburre |
| CPA | gasto ÷ compras | ≤ objetivo escala · +10-30% itera · +50% mata | decisión final |
| Muestra | — | 50 resultados o 3-4 días o 1.5-2× CPA | antes de juzgar |
| Frequency / CTR delta | — | gatillo de refresh (no calendario) | refrescar el creativo |

---

# 🗺️ ROADMAP priorizado (máx 10) — valor/esfuerzo, sobre módulo real

Orden = valor/esfuerzo para Jack HOY (COD Colombia, presupuesto chico, sin keys nuevas).

### 1. ✅ QUICK WIN — "Plan de testeo Meta/TikTok 2026" por lote (esfuerzo **S**) — IMPLEMENTADO
- **Qué es:** al generar los videos, un botón **📋 Plan de testeo** que arma un plan concreto por
  avatar/etapa con los umbrales 2026 (hook rate, hold rate, CPA, muestra mínima, matar/iterar/escalar,
  refresh) + un **nombre de anuncio copiable** por versión para leer las campañas. $0 de APIs (texto
  determinístico), copiable/descargable.
- **Por qué vende más:** la app ya crea creativos por avatar, pero NADIE le dice a Jack cómo testear
  ni cuándo matar/escalar (su flujo paso 6 estaba "a ojo"). Con umbrales duros deja de quemar plata en
  perdedores y escala al ganador a tiempo. Es la pieza que faltaba entre "genero" y "vendo".
- **Módulo:** nuevo `backend/pipeline/testing_plan.py` + endpoint `POST /api/testing-plan` + botón en
  `renderResults` (frontend). Usa los campos que ya viajan en el manifest (`stage`, `avatar`, `hook_used`).

### 2. Convención de NOMBRE de anuncio por avatar/etapa/hook (esfuerzo **S**)
- **Qué es:** cada versión trae un nombre listo para Ads Manager tipo `PROD_AVATAR_TOFU_v1` (ya va
  incluido dentro del Quick Win #1; separarlo permite estamparlo también en el nombre del archivo).
- **Por qué vende más:** es el "Motion/Atria de pobre": sin conectar la cuenta, Jack lee sus reportes
  y sabe qué AVATAR y qué ETAPA está ganando → itera sobre el ángulo correcto.
- **Módulo:** `orchestrator` (manifest) + `testing_plan`. Ya lo tenemos a medias (badges en UI);
  falta el string copiable y opcionalmente en el filename.

### 3. Motor de ITERACIÓN del ganador — 5-8 variaciones por ejes (esfuerzo **M**)
- **Qué es:** dado el video que ganó, generar una FAMILIA de iteraciones cambiando UN eje por vez:
  primeros 1s (pattern-interrupt), hook de texto, hold (reordenar demo/prueba), y dureza de CTA.
- **Por qué vende más:** el research es tajante: un ganador = 5-10 iteraciones rentables, no un ad
  que exprimes. Hoy solo tenemos **🔁 Variar hook** (un solo eje).
- **Módulo:** ampliar `creative_variator` / `hook_variator` con "ejes de iteración".

### 4. Generador de flujo COD WhatsApp (confirmación + upsell/downsell) (esfuerzo **S-M**)
- **Qué es:** junto a la landing, generar en es-CO el **guion de confirmación por WhatsApp** + un
  **upsell** (2x1/cantidad) + **downsell** + mensaje de **recuperación**, usando la oferta EXACTA de
  Jack (misma regla anti-precios-inventados de landings: `_limpiar_cifras`).
- **Por qué vende más:** en COD el margen se gana en la confirmación y el upsell; la app hoy no toca
  ese momento (solo la landing). Colombia = 74% WhatsApp, es donde se cierra.
- **Módulo:** nuevo `cod_flow.py` atado a 🛍️ Crear Landings, reutilizando Claude + `_limpiar_cifras`.

### 5. Alertas de fatiga/refresh en el Plan de testeo (esfuerzo **S**)
- **Qué es:** el plan incluye los gatillos de refresh (frequency alta, caída de CTR/CVR) y recuerda
  la cadencia por etapa (TOFU 1-2 sem, MOFU 2-4, retargeting 4-6).
- **Por qué vende más:** evita que Jack mate un ad sano por impaciencia o riegue uno fatigado.
- **Módulo:** parte de `testing_plan.py` (extensión del Quick Win #1) — ya incluido en la #1.

### 6. UGC con actor IA (hero) — Arcads/Creatify/HeyGen (esfuerzo **L**, requiere KEY nueva)
- **Qué es:** generar un creativo "hero" con un actor IA que habla en español (testimonio/demo UGC).
- **Por qué vende más:** el UGC con cara humana sigue siendo el formato que más convierte en 2026 y
  hoy la app no genera actores hablando (solo voz en off sobre clips).
- **Módulo:** nuevo `ugc_avatar.py`. ⚠️ **Bloqueado:** Jack no tiene key de Arcads/Creatify/HeyGen —
  por eso NO es el quick win. Dejar listo el módulo para cuando consiga la key.

### 7. Pattern-interrupt forzado en el primer 1s (esfuerzo **M**)
- **Qué es:** en la selección de clips, forzar movimiento/producto/cara en 0-1s para subir el thumbstop.
- **Por qué vende más:** el hook rate se decide en el primer frame; es la métrica que Meta mira primero.
- **Módulo:** `orchestrator._select_for_target` (ya penaliza texto quemado; añadir preferencia de
  "arranque con movimiento"). Parcial: ya priorizamos clips limpios.

### 8. Diversidad de concepto forzada anti-Andromeda (esfuerzo **S**, casi hecho)
- **Qué es:** garantizar que el lote no repita familia de hook/formato (Andromeda agrupa parecidos).
- **Por qué vende más:** más clusters de targeting = escalar sin subir el CPA.
- **Módulo:** `scripts` + `estructuras_validadas`. **Ya lo tenemos casi:** el fallback rota 8/8
  estructuras distintas y el funnel mete TOFU/MOFU/BOFU. Falta verificar que NO se repita familia de hook.

### 9. Static angle-matrix en 🎨 Ads imagen (esfuerzo **M**, parcial)
- **Qué es:** generar una matriz de estáticos concepto × ángulo (dolor / prueba / oferta) de una vez.
- **Por qué vende más:** los estáticos siguen siendo el testeo más barato de ÁNGULO.
- **Módulo:** `disruptive_images`. Parcial: ya generamos varios conceptos; falta la matriz por ángulo.

### 10. Export de BRIEF/storyboard del ganador clonado (esfuerzo **S**, valor bajo solo-operador)
- **Qué es:** exportar el 🧬 blueprint clonado como brief legible (hook/cuerpo/CTA + escenas).
- **Por qué vende más:** poco, para UNA persona (los briefs de Foreplay son para pasar a un editor
  externo). Útil solo si Jack terceriza edición. **Baja prioridad.**
- **Módulo:** `winner_blueprint` → export markdown.

---

## Resumen crítico (qué ya tenemos vs qué falta de verdad)
- **Ya cubierto:** avatar×estructura por versión, embudo TOFU/MOFU/BOFU, hook por versión, variar-hook,
  clon de ganador, blur vidrio-esmerilado, subtítulos TikTok, banner de oferta, end-card, doblaje
  exacto, Radar de ganadores, stock b-roll, landings con gate. La app está MUY completa del lado creativo.
- **El hueco real (barato y de alto valor):** la app te da el creativo pero **no te enseña a testearlo
  ni a leer resultados**, y no toca el **momento COD/WhatsApp** donde se cierra la venta. El Quick Win
  #1 (Plan de testeo) ataca lo primero con $0; el #4 (flujo COD) ataca lo segundo.
- **El hueco caro (bloqueado por keys):** UGC con actor IA (#6) — dejar el módulo listo para cuando
  Jack consiga la key de Arcads/Creatify.

_Fuentes: todas enlazadas arriba con fecha de consulta 2026-07-15. Meta Ad Library / TikTok Creative
Center requieren login; los umbrales se triangularon de breakdowns públicos de agencias 2026._
