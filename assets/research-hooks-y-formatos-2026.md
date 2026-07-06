# 🔬 Research: hooks, subtítulos, arcos y ofertas ganadoras — 2026

> Profundización pedida por Jack sobre `estudio-marcas-grandes-2026.md` y `patron-ganador-validado.md`
> (léelos primero, esto NO los repite). Foco: catálogo de hooks para `creative_variator.py`/`scripts.py`,
> estilos de subtítulo para `caption_styles.py`, arcos por nicho, ofertas/CTA y ganchos visuales.
> Solo LEÍ código (para mapear), no toqué ningún `.py`.

---

## Metodología (honesta — léela antes de confiar en los números)

- **Herramientas usadas:** solo búsqueda web gratuita (WebSearch/WebFetch). NO tengo acceso a TikTok
  Creative Center en vivo (pide sesión/región), NI a Meta Ad Library con scraping real, NI a Foreplay/
  MagicBrief/Segwise con cuenta paga — todo lo de abajo sale de **artículos públicos que YA agregan
  esos datos** (blogs de esas herramientas, agencias y medios especializados), citados con su URL.
- **~20 fuentes consultadas** (búsquedas + fetch de página completa en ~9 de ellas): Segwise, Trendtrack,
  Evolut Agency (500 ads de suplementos), Foreplay, OpusClip (34.635 clips), Brandsearch (523 ads Meta
  en 5 categorías), Blitzcut, Billo, y agregadores de "TikTok Creative Center 2026".
- **⚠️ Alerta de calidad de fuente:** varios de estos sitios (Segwise, Trendtrack, Brandsearch, Evolut,
  OpusClip) son herramientas de marketing/SaaS que publican "estudios 2026" con cifras muy específicas
  (%, "34.635 clips", "523 ads") que **no pude verificar contra el dataset crudo** — son afirmaciones de
  terceros, no medición propia. Los uso como **dirección/consenso** (cuando 3+ fuentes distintas dicen
  lo mismo, hay más confianza), no como verdad matemática exacta. Lo marco explícito abajo donde el
  dato viene de UNA sola fuente sin corroborar.
- **Los 5 nichos de Jack (pest repeller, bee venom, knee brace, incontinencia, cargo leggings):** busqué
  específicamente cada uno. **NO encontré Meta Ad Library ni TikTok Creative Center con ads reales
  navegables de esas marcas exactas** (requieren sesión/región y no son scrapeables por búsqueda). Lo
  que sí encontré: patrones de categoría (belleza/"natural botox" para bee venom, salud/movilidad para
  knee brace, hogar/pattern-interrupt para pest repeller, cambio cultural "performance underwear" para
  incontinencia, moda/reveal para cargo leggings) que aplico por ANALOGÍA de categoría, no ad-por-ad.
  Esto es más débil que el research anterior de Foreplay (30 ganadores +30 días, con API real) — decláralo
  así si Jack pregunta.
- **Ya cubierto por research previo (NO repetido aquí):** los 5 formatos estáticos (Us vs Them,
  Testimonios, etc.), el estudio de 67.852 ads DTC, el hook rate 28-45%, y el patrón visual de 3 ejemplos
  validados. Ver los otros dos `.md`.

---

## (a) Catálogo de HOOKS — tabla lista para copiar a un prompt

15 tipos, con la plantilla EXACTA y de dónde sale. Pensado para dárselo tal cual a `creative_variator.py`
(hoy solo cataloga 7 familias) y a `scripts.py` (que ya tiene 10 tipos en `guion-framework.md` — aquí
sumo los 5 que le faltan y marco cuáles YA tiene con ✅).

| # | Tipo de hook | Plantilla / frase-molde | Ejemplo real citado | ¿Ya en la app? | Fuente |
|---|---|---|---|---|---|
| 1 | **Mito roto / contrarian** | "[Creencia común]. [Negación]. [Verdad incómoda]." | "Everyone says [consejo común]. It's wrong." | ✅ `guion-framework.md` #1 | OpusClip (34.6k clips) |
| 2 | **Negativo / "stop doing X"** | "Deja de [hacer X] ahora mismo. En cambio, [resultado deseado]." | "Stop doing [pain point] right now! Instead [desired result]" | 🟡 parcial (creative_variator tiene "reverse-sell": "NO compres esto…") — falta el molde STOP explícito | Marketingblocks / HeyOrca |
| 3 | **POV / confesión de familiar** | "[Persona] me [verbo] esto y ya no me lo devuelve / y pasó esto…" | "Le compré este tapete a mi mamá…" (récord 15% likes/plays en el banco de Juan) | ✅ ya es el hook #1 del banco de Juan (scripts.py) | swipe-file-juan.md interno |
| 4 | **3-4 razones (numerado)** | "[N] razones por las que [hago/uso/dejé] X" | "4 reasons I drink this" · "Why I quit my supplements for this" (AG1) | ❌ falta explícito — hoy el catálogo no tiene el molde "N razones" | Foreplay (caso AG1, $600M) |
| 5 | **Problema/dolor crudo** | "[Situación cotidiana molesta] → no hagas [lo caro/obvio] todavía" | "Se encendió el check engine. No corras al taller todavía." | ✅ `guion-framework.md` #3 (ansiedad situacional) | swipe-file-juan.md |
| 6 | **Social proof numérico** | "El [%] de [grupo] [comete error/no sabe esto]" | "93% of people have less hair loss" (Nioxin) · "El 90% de las casas…" | ✅ `guion-framework.md` #2 | Segwise DTC hooks / interno |
| 7 | **Handwriting (visual, no verbal)** | Texto ESCRITO A MANO en pantalla, sin voz o con voz de fondo | "TikTok says this booty mask makes your booty pop!" (fuente escrita) | ❌ falta — `caption_styles.py` no tiene estilo "manuscrito"; es un estilo de HOOK, no de subtítulo normal | Segwise DTC hooks |
| 8 | **Pattern interrupt (visual puro)** | Sin texto/voz: corte brusco, textura en primer plano, sonido ASMR | Dominante en Home Goods: 61% de los ganadores (sin voiceover, texturas) | 🟡 la app tiene b-roll de dolor pero no un "modo sin voz, solo textura+ASMR" | Brandsearch (523 ads, 5 categorías) |
| 9 | **Autoridad / bold claim** | "Respaldado por [N estudios clínicos]" / "[N años] haciendo esto — esto es lo que nadie te dice" | "Backed by 12 clinical studies" · "I've worked in [rol] for 12 years…" | 🟡 parcial — el banco tiene "origen secreto" pero no el molde de autoridad-experta | Brandsearch (supl. 52%) / OpusClip |
| 10 | **Resultado primero (outcome-first)** | Muestra el RESULTADO/transformación en 0-2s, ANTES del proceso | "I gained 12 lbs of muscle in 90 days" (fitness, dominante 44%) | ✅ `creative_variator.py` ya tiene "resultado-primero" | Brandsearch / OpusClip (mejor tipo, 2x vistas vs el peor) |
| 11 | **Pregunta relatable** | "¿Te pasa que…?" / "¿Cómo sabes si…?" | "¿Cuál es la diferencia de un protector coreano con cualquier otro?" | ✅ ya en creative_variator — **PERO ojo:** cross-niche solo 8% de los hooks-pregunta sobrevive 30+ días (el peor de todos) | ✅ app / ⚠️ Brandsearch (dato de 1 sola fuente, no corroborado) |
| 12 | **Descubridor entusiasta / testimonio de creador** | "El genio que inventó esto se merece un aumento" / reseña espontánea de "amigo" | "Guys I am very excited about my new electric bike" (Fiido, 2.1M reach) | ✅ `guion-framework.md` #5 | Trendtrack top 10 ads |
| 13 | **Reverse-sell / advertencia** | "NO compres [X]… a menos que [condición]" | (molde propio del banco, sin cita externa 1:1 encontrada) | ✅ ya en creative_variator | interno |
| 14 | **Unboxing + prueba social** | Reacción de sorpresa al abrir/probar + validación de terceros | "I can't believe this is the shirt I got" (2M vistas) | ❌ falta — no hay molde de "unboxing" explícito | Trendtrack top 10 |
| 15 | **Precio-shock visual / comparativa numérica (SIN voz, solo texto fijo)** | Cifra grande en pantalla tipo "185 → 190" | Usado en hogar/suplementos sin voz | ✅ `guion-framework.md` #9-10 — **OJO: la app NUNCA muestra precio (regla de oro)**, así que este molde se usa SOLO para números de transformación, nunca de dinero | interno + Segwise |

**Nota sobre "I was today years old…":** es un formato meme muy conocido (confesión + descubrimiento
tardío), pero en esta ronda de búsqueda **no encontré una fuente 2026 que lo citara con datos** — lo
incluyo como variante posible del tipo #3 (confesión/POV), no como tipo #16 aparte, porque no lo pude
verificar independientemente.

**Hallazgo cruzado importante (Brandsearch, 523 ads/5 categorías, 30+ días):** solo 3 estructuras cubren
el 71% de los ganadores que sobreviven 30+ días: **dolor/pain-point opener, autoridad/bold-claim, y
pattern-interrupt visual.** Esto valida que el catálogo de `creative_variator.py` debería PRIORIZAR estos
3 por encima de "pregunta" (peor performer, 8% supervivencia) cuando el modelo tenga que elegir cuál usar
si el producto no calza claramente con ningún tipo.

---

## (b) Estilos de subtítulo/caption 2026 — ¿qué le falta a `caption_styles.py`?

Los 10 estilos actuales (`ESTILOS` en `caption_styles.py`) ya cubren MUY bien el consenso 2026:
- El estilo #1 en todas las fuentes es **"word-by-word / short-phrase, alto contraste, tercio
  inferior-medio, keyword resaltada en amarillo/rojo/verde"** → eso es EXACTAMENTE `hormozi` /
  `yellow_highlight` / `red_highlight` / `karaoke` ya implementados, con `group_size=4` y resaltado de
  la palabra activa. ✅ Nada que cambiar en el look base.
- **Acento dinámico que contrasta con el color del producto** (`accent_for_video`) — esto YA es más
  avanzado que lo que describen las fuentes (ellas hablan de "yellow o brand color" fijo; la app lo
  calcula automático por video). ✅ ventaja real de la app.
- **Tendencia 2026 nueva que SÍ falta: "Dynamic Minimalism"** — la evolución del estilo Hormozi que
  quita el ruido (emojis, efectos, colores flasheados) pero mantiene el mecanismo palabra-por-palabra,
  y resalta SOLO con el color de marca (no genérico). La app YA hace la parte de "color dinámico" pero
  el estilo `bounce`/`typewriter` podrían simplificarse a un look "sin sonido/sin exceso" — esfuerzo
  bajo, más cosmético que funcional.
- **Falta un estilo `handwriting`** (fuente tipo manuscrita/marcador) — no para subtítulos largos, sino
  para el TEXTO DEL HOOK (0-3s) o para el `render_offer_pill`. Es el molde #7 de la tabla de hooks
  arriba (autenticidad "post-it" / nota escrita a mano). Ahora mismo todo usa Poppins (sans-serif
  geométrica) — ninguno de los 10 estilos simula escritura a mano.
- **Grupo de 1 palabra ("Word Pop" puro)** — hoy `group_size=4` es fijo con 1 palabra activa resaltada
  dentro del grupo. El estudio de Blitzcut describe el "Word Pop" como una palabra sola apareciendo con
  scale/fade — más agresivo/rápido que mostrar 4 palabras con 1 resaltada. Sería un `group_size=1` como
  variante rápida (¿probar A/B?).

---

## (c) Estructuras/arcos — SÍ cambia por nicho (hallazgo más accionable de esta ronda)

La fuente Brandsearch (análisis de 523 ads Meta, 30+ días, 5 categorías) da un patrón claro que se puede
mapear 1:1 a los 5 nichos de Jack por ANALOGÍA de categoría (ver limitación en metodología — no son sus
marcas exactas, son la categoría más cercana):

| Categoría análoga | Nicho de Jack | Duración ganadora | Hook dominante | Ritmo/estilo |
|---|---|---|---|---|
| Home goods (61% pattern-interrupt visual) | 🐀 **Pest repeller** | 20-35s | Sin voz, texturas/ASMR, corte brusco | Ya calza con `patron-ganador-validado.md` (20-23s) ✅ |
| Beauty (38% pain-point, ingrediente) | 🐝 **Bee venom** ("natural botox" en TikTok) | 45-60s | Problema/solución + close-up de producto, landing con desglose de ingredientes | Más LARGO de lo que usa hoy la app (target genérico ~15-25s) — 🔴 gap |
| Supplements (52% autoridad, founder UGC 67%) | 🦵 **Knee brace** (mecanismo/salud) | 30-60s | Autoridad/mecanismo ("por qué funciona") | También más largo; el arco de `guion-framework.md` YA tiene bloque MECANISMO — usarlo explícito aquí |
| — (sin categoría directa; uso el consenso de "reducir estigma con humor" de las fuentes de incontinencia) | 🩹 **Incontinencia** | corto, 20-25s, tono empático NO clínico | Humor/normalización, nunca vergüenza | Reforzar en el prompt: "nunca tono clínico o de burla" (coincide con la regla ya escrita en `patron-ganador-validado.md` sobre antes/después "aspiracional, no de vergüenza") |
| Fashion (60% estático, reveal <15s) | 🩳 **Cargo leggings** | 12-18s, MUY corto | Reveal visual puro, casi sin voz, cortes rápidos | Mucho más CORTO que el default de 15-25s — 🔴 gap, hoy se trataría igual que salud |

**Conclusión:** hoy `scripts.py` usa un `target_seconds` que el usuario fija manualmente y UN solo arco
universal (HOOK→PROBLEMA→GIRO→PRODUCTO→PRUEBA→CTA) para todos los productos. El research dice que la
duración y el énfasis de fase SÍ deberían variar por categoría de producto (bee venom/knee brace piden
más tiempo de mecanismo; cargo leggings pide casi puro visual y corto). Esto es una mejora de tamaño
MEDIANO (no es solo copy, es lógica de duración por defecto).

---

## (d) Ofertas y CTA que cierran (compatible con "sin precio, CTA fijo COD")

- **Un solo CTA por creativo.** Varias fuentes (persuasión DTC 2026) coinciden: mezclar 2-3 llamados a
  la acción en el mismo ad baja conversión por "choice overload". La app ya hace esto bien (un solo
  `CTA_OBLIGATORIO`). ✅
- **Urgencia y escasez deben ser REALES, nunca inventadas** — coincide con la regla ya escrita en
  `scripts.py` (nada de plazos garantizados, nada de cifras falsas). ✅ ya cumplido.
- **Garantía/política de devolución agresiva sube conversión ~23%** y reduce abandono de carrito ~56%
  cuando la marca cubre el costo de la devolución — esto es DIFÍCIL de aplicar 1:1 porque la app no
  controla la logística del cliente, pero SÍ se puede agregar una LÍNEA de guion opcional tipo "si no te
  gusta, no pagas" (ya lo cubre el propio contraentrega: el cliente literalmente no paga si no lo recibe
  a gusto) — vale la pena que el guion lo diga explícito como diferencial ("y si no te convence, ni
  siquiera pagas, así de fácil") en vez de asumir que el usuario lo infiere. Esfuerzo CHICO.
- **Ancla de valor sin cifra** (ya implementado: "menos de lo que ya gastaste en cremas que no
  funcionan") — coincide exacto con lo que las fuentes llaman "value anchor" en el cierre. ✅
- **Prueba social específica > superlativos** (ya cubierto en `estudio-marcas-grandes-2026.md`, no
  repito).

---

## (e) Ganchos visuales del primer frame (lo que hace que el scroll pare)

- **El primer frame ES el thumbnail del ad** (en Meta específicamente, la plataforma usa ese frame
  congelado como miniatura en el feed). Si ese frame fijo no es interesante SOLO, el video ni arranca a
  reproducirse. Fuente: consenso de 3+ blogs de creative-testing 2026 (Zeely, ROASPIG, Smartly's 2026
  report vía terceros).
- **Qué hace que un frame fijo funcione solo:** cara humana con expresión fuerte, texto grande, producto
  + "antagonista" juntos (la plaga junto al repelente, ya validado en `patron-ganador-validado.md`),
  contraste de color/textura inusual, o movimiento capturado a mitad de gesto (no un frame "de reposo").
- **Gap real en la app:** revisé `hook_gen.py`, `text_overlay.py`, `winner_blueprint.py` — la app
  genera TEXTO de gancho (Gemini) y usa EAST para encontrar ventanas limpias de texto, pero **no hay un
  paso que evalúe si el FRAME FIJO inicial (frame 0, antes de que cualquier animación arranque) es
  "interesante por sí solo"** (cara/producto+antagonista/contraste). Hoy se asume que el clip elegido
  para HOOK ya lo es, pero no se verifica con IA. Esto es la misma idea de `safe_top_y` en
  `offer_banner.py` (usar Gemini para juzgar un frame) pero aplicada a "¿este frame para SOLO detiene el
  scroll?" en vez de "¿dónde va el banner?".
- **Framework de testing recomendado (3 rondas) de una fuente 2026 (vía Smartly, no verificado
  directo):** (1) mismo ad, cambiar SOLO el frame 1; (2) mismo frame 1, cambiar SOLO la primera línea;
  (3) mismo hook, cambiar SOLO el overlay de texto. Sirve de inspiración para cómo Jack podría probar el
  "🔁 Variar hook" — variar UNA capa a la vez en vez de las tres juntas, para saber cuál mueve la aguja.

---

## 🎯 Recomendaciones por módulo (con esfuerzo)

| Módulo | Recomendación | Esfuerzo |
|---|---|---|
| `creative_variator.py` | Agregar 4 tipos de hook que faltan al catálogo: **"stop doing X"** (molde explícito), **"N razones"** (numerado, tipo AG1), **autoridad/bold-claim** ("respaldado por…", "llevo N años haciendo esto"), **unboxing+prueba social** | 🟡 mediano (son 4 familias nuevas + ejemplos en el system prompt) |
| `creative_variator.py` | Bajar la prioridad de "pregunta relatable" cuando el modelo elija entre familias (dato: peor performer cross-niche, 8% supervivencia) — dejarla disponible pero no la default | 🟢 chico |
| `scripts.py` / duración | Duración por defecto SEGÚN categoría de producto en vez de fija: pattern-interrupt/hogar 20-35s, belleza/mecanismo 45-60s, salud/autoridad 30-60s, moda/reveal 12-18s | 🔴 grande (requiere clasificar el producto + lógica de duración condicional) |
| `caption_styles.py` | Nuevo estilo `handwriting` (fuente tipo manuscrita) para el TEXTO DEL HOOK (0-3s) — no para subtítulos largos | 🟡 mediano (requiere conseguir/embeber una fuente script libre de licencia + ajustar `_fontpath`) |
| `caption_styles.py` | Variante `group_size=1` ("Word Pop" puro, una palabra a la vez) como opción A/B junto al `group_size=4` actual | 🟢 chico (el parámetro ya existe, solo exponerlo en la UI) |
| Nuevo (frame inicial) | Verificación con Gemini del FRAME FIJO 0 del clip HOOK: "¿este frame por sí solo detiene el scroll? (cara/producto+antagonista/contraste)" — mismo patrón que `offer_banner.safe_top_y` | 🟡 mediano |
| `scripts.py` (guion) | Línea de guion opcional de "garantía implícita COD" ("si no te convence, ni siquiera pagas") antes del CTA fijo | 🟢 chico |
| Ads imagen / pattern-interrupt | Modo "sin voz, solo textura + sonido ASMR" para nichos tipo hogar (pest repeller) — dominante 61% en esa categoría | 🟡 mediano (necesita SFX de textura + timing sin voiceover) |
| `scripts.py` (bee venom / knee brace) | Reforzar explícito el bloque MECANISMO ("por qué funciona") para estos 2 nichos — ya existe en `guion-framework.md` pero no se fuerza por categoría | 🟢 chico |
| `scripts.py` (incontinencia) | Reforzar en el prompt "tono empático/humor, JAMÁS clínico ni de burla" — ya está la regla para antes/después, extenderla explícita a este nicho | 🟢 chico |

---

## 🏆 Top 10 quick-wins (impacto/esfuerzo, para cuando el repo esté libre)

1. **[chico]** Agregar el molde exacto "Stop doing [dolor] ahora mismo. En cambio, [resultado]" al
   catálogo de `creative_variator.py` — hook negativo con plantilla clara, hoy solo existe como
   "reverse-sell" genérico.
2. **[chico]** Agregar molde "N razones por las que…" (3-4 razones) — patrón de AG1 ($600M en ads),
   fácil de generar con Claude, cero riesgo de compliance.
3. **[chico]** Despriorizar "pregunta relatable" como default cuando el modelo elija tipo de hook (peor
   supervivencia cross-niche según Brandsearch) — dejarla como opción, no como primera opción.
4. **[chico]** Línea de "garantía implícita COD" antes del CTA fijo ("si no te convence, ni siquiera
   pagas") — refuerza lo que ya es cierto por el modelo de negocio, sin inventar nada.
5. **[chico]** Reforzar en el prompt de `scripts.py` el tono "empático/humor, nunca clínico" para el
   nicho de incontinencia (extensión de una regla que ya existe para antes/después).
6. **[mediano]** Nuevo estilo `handwriting` en `caption_styles.py` para el texto del hook (autenticidad
   tipo "nota escrita a mano") — molde de hook #7 de la tabla, ningún estilo actual lo cubre.
7. **[mediano]** Verificación IA del frame fijo inicial ("¿detiene el scroll por sí solo?") — mismo
   patrón ya usado en `offer_banner.safe_top_y`, aplicado al primer frame del HOOK.
8. **[mediano]** Duración por defecto según categoría de producto (bee venom/knee brace más largos con
   bloque MECANISMO explícito; cargo leggings mucho más corto y visual) — el gap más grande encontrado.
9. **[mediano]** Modo "sin voz + textura/ASMR" para pattern-interrupt puro (nicho hogar/pest repeller) —
   dominante 61% en esa categoría según Brandsearch.
10. **[chico]** Exponer `group_size=1` ("Word Pop" de una palabra) como variante de subtítulo junto al
    `group_size=4` actual, para A/B rápido sin tocar el motor de renderizado.

_Generado por sesión de investigación (Sonnet 5), 2026-07-06. Fuentes principales: Segwise, Trendtrack,
Evolut Agency, Foreplay, OpusClip, Brandsearch, Blitzcut, Billo, y agregadores de TikTok Creative Center
2026 (todas citadas por URL abajo). Limitación honesta: ningún ad de Meta Ad Library ni TikTok Creative
Center de los 5 nichos exactos de Jack fue navegado en vivo — el mapeo a esos 5 nichos es por analogía de
categoría, no ad-por-ad verificado._

### Fuentes citadas (URLs)
- https://segwise.ai/blog/dtc-ad-creative-hooks
- https://www.trendtrack.io/blog-post/best-performing-ad-hooks
- https://evolutagency.com/supplement-marketing-2026/
- https://evolutagency.com/we-analyzed-500-top-supplement-ads/
- https://www.foreplay.co/post/how-to-analyze-top-performing-hooks
- https://www.foreplay.co/post/athletic-greens-600m-ad-creative-strategy-how-foreplay-helps-you-dominate-the-market
- https://www.opus.pro/blog/tiktok-hooks-that-go-viral-2026
- https://brandsearch.co/blog/winning-meta-ad-patterns-2026
- https://blitzcutai.com/blog/best-caption-style-tiktok
- https://billo.app/blog/hook-rate-to-hold-rate/
- https://www.marketingblocks.ai/50-viral-hook-templates-for-ads-reels-tiktok-or-captions-2026-frameworks-examples-ai-prompts-included/
- https://www.heyorca.com/blog/the-best-social-media-hooks-for-2026
- https://zeely.ai/blog/7-scroll-stopping-hooks/
- https://ads.tiktok.com/help/article/how-to-use-the-top-ads-dashboard
