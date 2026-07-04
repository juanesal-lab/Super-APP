# MANUAL MAESTRO — App de Creación Automática de Videos Ganadores de Dropshipping (100% IA)

**Documento de especificación y conocimiento para Claude Code.**
Prepara la lógica creativa + técnica + de pipeline para construir una app que genera anuncios de video para dropshipping **enteramente con IA** (sin footage real): imagen→video, avatar IA, voz IA, música IA, subtítulos automáticos.

| Campo | Valor |
|---|---|
| **Autor del negocio** | Juan — tiendas dropshipping CO / EC / USA (Dropi, COD) |
| **Salida** | Videos verticales para **TikTok orgánico + Meta (Facebook/Instagram) ads** |
| **Mercados / idiomas** | Colombia y Ecuador (español colombiano/neutro, COD) · USA (inglés + USA-hispano/TikTok Shop) |
| **Método** | Generación 100% IA end-to-end |
| **Objetivo del doc** | Que Claude Code encode este conocimiento como reglas, prompts, schemas y módulos |
| **Última revisión** | Julio 2026 |

> **La tesis del negocio:** 1 de cada 10–20 ads gana. La app no debe pulir 1 video; debe **producir volumen diverso barato** y dejar que el testing elija. Y sobre todo: **si parece anuncio, perdimos.** El trabajo #1 de la app es generar creativos que se sientan orgánicos y humanos, no IA y no publicidad.

---

## 0. CÓMO DEBE USAR CLAUDE CODE ESTE DOCUMENTO

Este manual está organizado como los **módulos de la app**. Léelo así:

1. **Parte 1** = filosofía y verdades no negociables → son los *tests de aceptación* de cualquier creativo que la app genere.
2. **Parte 2** = arquitectura del pipeline → el esqueleto de ingeniería (etapas, tool/API por etapa, flujo de datos).
3. **Partes 3–9** = un módulo por etapa (guion, shotlist, generación visual IA, voz, música, subtítulos, edición/ensamblaje). Cada módulo termina con una tabla **"Parámetros por defecto (encodables)"** = los valores concretos a hard-codear (y cuáles exponer como config A/B).
4. **Parte 10** = specs técnicas de export + matriz por plataforma.
5. **Parte 11** = QA, benchmarks, kill rules y compliance → los *guardrails*.
6. **Parte 12** = schemas JSON sugeridos (contratos entre módulos).
7. **Parte 13** = ejemplo completo end-to-end (un producto real recorrido por todo el pipeline).
8. **Parte 14** = stack de herramientas con precios/API + fuentes.

**Convenciones:**
- `REGLA:` = comportamiento obligatorio que la app debe garantizar.
- `DEFAULT:` = valor por defecto encodable.
- Términos técnicos y nombres de herramientas van en inglés; la voz/copy de salida va en español (CO/EC) o inglés (USA) según mercado.

---

## 1. QUÉ CONSTRUIMOS + LAS VERDADES NO NEGOCIABLES

La app recibe un **producto** (link o imagen + datos mínimos) y devuelve **N variantes de video** listas para publicar, cada una con su script, assets IA, voz, música, subtítulos y export por plataforma.

### 1.1 Las 12 verdades que gobiernan cada creativo

1. **El creative ES el targeting** (post-Andromeda, oct 2025). Lookalikes e interest stacking están muertos. Broad targeting + creativo fuerte gana. → La app compite en *creativo*, no en segmentación.
2. **~47% del valor del ad se entrega en los primeros 3 s** (Meta). En TikTok el algoritmo decide en **1.5 s**. Sin hook fuerte, lo demás es paja.
3. **Winners son raros (~1/10–20).** Itera masivamente. La app debe generar **10–25 variantes diversas** por producto, no 1 “perfecta”.
4. **85 % mira sin sonido** → subtítulos quemados obligatorios, siempre.
5. **Text hooks ganan +40 % watch time** vs solo audio. El cerebro procesa texto ~60.000× más rápido que audio → overlay de texto en frame 1.
6. **UGC > polished.** UGC genera ~10× conversión en orgánico y 2–4× CTR en paid. Meta y TikTok **penalizan el look de estudio**.
7. **Ritmo:** 9:16 nativo, cortes cada **1.5–3 s** (0.5–1 s en el hook). Nada estático > ~2 s sin un “reset visual”.
8. **Mecanismo único > feature.** Explica POR QUÉ funciona, no qué hace.
9. **Awareness define el hook.** Cold dropshipping = problem-aware o unaware. No generalizar.
10. **CTA en 3 capas** (verbal + visual + texto), **una sola acción**. En VSL, mínimo 3 CTAs.
11. **Ancla de precio SIEMPRE.** Nunca das el precio solo; lo das contra algo más caro (taller, Amazon, “otros lados”, valor protegido).
12. **Si parece anuncio, perdiste.** Y su corolario para esta app: **si parece IA, perdiste doble.** Anti-anuncio + anti-AI-look son el mismo objetivo.

### 1.2 Verdades específicas de una app 100% IA

- **REGLA (autenticidad):** el objetivo técnico central es que el video **no se lea como IA ni como comercial**. Todo el pipeline se optimiza para “¿un humano creería que esto lo grabó una persona real con su celular?”. Si no, se regenera.
- **REGLA (voz de marca):** para CO/EC la locución debe sonar a **pana/vecino colombiano**, no a locutor. Usar clonación de voz (ElevenLabs) sobre una voz colombiana real y natural — nunca TTS genérico “de robot”.
- **REGLA (demo cruda):** los entornos generados deben ser **reales e imperfectos** (bodega, carro, cocina con desorden), no estudio limpio. La imperfección vende.
- **REGLA (consistencia de producto):** el SKU real del cliente debe conservar fidelidad en todos los planos. Nunca “inventar” el producto con text-to-video puro; siempre partir de la **imagen real → image-to-video**.
- **REGLA (diversidad Andromeda):** las N variantes deben ser **genuinamente distintas** (ángulo, hook, formato, avatar, locación), no 30 versiones cosméticas del mismo concepto — Meta las agruparía como un solo Entity ID.

---

## 2. ARQUITECTURA DEL PIPELINE (END-TO-END)

Flujo de datos por etapas. Cada etapa consume el output de la anterior y puede fallar → hay un **QA gate** que regenera.

```
[1] INPUT producto ──► [2] INVESTIGACIÓN/ÁNGULO ──► [3] GUION (script) ──►
[4] SHOTLIST (scene breakdown) ──► [5] ASSETS VISUALES (imagen→video) ──►
[6] VOZ (TTS/clon) ──► [7] MÚSICA + SFX ──► [8] ENSAMBLAJE ──►
[9] SUBTÍTULOS ──► [10] EXPORT por plataforma ──► [QA GATE] ──► entrega N variantes
```

### 2.1 Tabla de etapas (tool/API recomendado + punto de fallo)

| # | Etapa | Qué hace | Tool/API por defecto | Punto de fallo típico |
|---|---|---|---|---|
| 1 | **Input** | Recibe link (Dropi/AliExpress/Amazon/Shopify) o imagen + datos mínimos | Scraper propio o carga manual | Imágenes de baja resolución / con marca de agua → upscale primero |
| 2 | **Investigación / ángulo** | Elige dolor + ángulo + awareness + formato ganador según nicho | LLM (Claude) + este manual | Ángulo genérico → hook débil |
| 3 | **Guion** | Escribe hook (3 capas) + estructura seg-a-seg + copy-paste, en la voz del mercado | LLM (Claude) con Parte 3 | Suena a anuncio → falla test anti-anuncio |
| 4 | **Shotlist** | Convierte el guion en 8–12 planos (ángulo, distancia, duración, foco, avatar/b-roll) | LLM (Claude) con Parte 4 | Demasiados cambios de escena = incoherencia |
| 5 | **Assets visuales** | Imagen-first (limpia producto + keyframes) → image-to-video por plano | Nano Banana Pro (img) + Kling 3.0 / Seedance / Runway Gen-4.5 / Veo 3.1 Fast vía **fal.ai** | SKU deformado, manos raras, “AI look” |
| 6 | **Voz** | Locución en la voz del mercado, con timestamps de palabra | ElevenLabs (clon ES-CO / EN) | Voz demasiado limpia/robótica |
| 7 | **Música + SFX** | Track por BPM/energía + drop en el reveal + SFX sincronizados | Suno Pro / librería licenciada + banco SFX | Audio no licenciado para paid → flag/ban |
| 8 | **Ensamblaje** | Une clips + voz + música con ducking | FFmpeg / Remotion (self-host) o JSON2Video | Desfase audio/video |
| 9 | **Subtítulos** | Word-by-word estilo Hormozi, quemados, en safe zone | WhisperX → .ASS → FFmpeg, o Submagic API | Palabras fuera de sync en cortes rápidos |
| 10 | **Export** | Render por plataforma (TikTok cut / Meta cut) | FFmpeg presets | Aspect/tamaño rechazado por el ad manager |
| — | **QA gate** | Chequea SKU/caras deformadas + “¿parece grabado en celular?” + checklist | LLM visión + reglas Parte 11 | Si falla, vuelve a etapa 5 |

### 2.2 Notas de orquestación

- **Paralelización:** las etapas 5 (varios clips), 6 (voz) y 7 (música) se pueden generar en paralelo una vez fijados guion (3) y shotlist (4).
- **Idempotencia por variante:** cada variante lleva un `seed`/`variant_id` para reproducir y para el A/B. Guardar todos los assets intermedios (permite re-editar sin regenerar todo).
- **Costo:** el mayor costo es la etapa 5 (video IA). Preferir modelos baratos por segundo (Kling/Seedance ~$0.025–0.11/s) para el grueso y reservar Veo/Runway para 1 plano “hero”. Ver Parte 14.
- **Regla de reintentos:** clips ≤5 s (menos artefactos). Si el QA gate rechaza un clip, regenerar solo ese plano, no el video entero.

---

## 3. MÓDULO GUION (SCRIPT) — el corazón creativo

Este módulo es el que más determina si el ad gana. Está calibrado con **43 anuncios reales que ya funcionaron en las tiendas de Juan** (no con teoría genérica). El LLM que escribe el guion debe partir SIEMPRE de estos patrones probados.

### 3.1 Regla maestra: NO SONAR A ANUNCIO

`REGLA:` antes de dar por bueno un guion, debe pasar el **test anti-anuncio de 5 preguntas**. Si falla UNA, reescribir:

1. ¿La primera frase es una **opinión, confesión, mala noticia o pregunta incómoda**? (NO una descripción de producto, NO “Hola, hoy te presento…”).
2. ¿El **producto aparece DESPUÉS del gancho**, como solución a algo que ya picó? (Producto en el segundo 0 = catálogo, no anuncio nativo).
3. ¿Suena a un **pana/vecino que descubrió algo**, no a un vendedor? (modismos, “usted/tú” real).
4. ¿Hay un **ancla de precio comparativa** + cierre COD/escasez? (precio solo = débil).
5. ¿La **demo es cruda y real** (bodega, carro, casa) en vez de estudio perfecto?

### 3.2 La voz de Juan (para CO/EC — usar literal, no suavizar)

`DEFAULT (mercado=CO/EC):` inyectar estos modismos y muletillas reales en la locución:

- **Autoridad de barrio:** “Y señores…”, “Oiga…”, “¡Ojo!”, “Miren esto”, “colores tan bacanos”, “le tengo malas noticias”, “dígame con qué se está protegiendo”, “es físico y ya”, “no sé usted, pero yo no me la pienso”.
- **Honestidad performativa (baja defensas):** “No te voy a mentir…”, “Honestamente…”, “Lo que no sabes es que…”.
- **Satisfacción / ASMR:** “Es extrañamente satisfactorio ver cómo desaparece toda esa mugre”, “Podría quedarme viéndolo todo el día”.
- **Cierres:** “Este detalle lo cambia todo”, “Vale la pena”, “No lo pienses demasiado”, “Pura clase”.

`DEFAULT (mercado por país):`
- **CO/EC** → español colombiano + **COD**: “paga cuando llega a tu puerta”, “pide contraentrega, pagas al recibir”, “paga 100% al recibido”, “envíos a todo el país”.
- **USA-hispano / TikTok Shop** → “toca el carrito naranja abajo a la izquierda”, “antes de que se agote”, “el envío es rapidísimo”, ancla vs Amazon.
- **USA-inglés** → CTA directo (“Shop now / Get yours / Claim 50% off”), ancla vs Amazon, trust badges.
- **España** → “coche”, tacos suaves (“de cojones”), “el enlace está abajo”.

### 3.3 Anatomía base (6 bloques, recalibrada con los virales de Juan)

| Segundo | Bloque | Único trabajo | Cómo lo hace Juan |
|---|---|---|---|
| 0:00–0:03 | **HOOK** | Frenar el scroll (texto+visual+audio) | Opinión / mala noticia / sketch — NO el producto |
| 0:03–0:08 | **PROBLEMA** | Nombrar el dolor exacto | “el 90%…”, “se encendió el check engine”, robo |
| 0:08–0:15 | **MECANISMO** | POR QUÉ funciona (el “ajá”) | “una lámpara resuelve 2 alturas”, “es físico y ya” |
| 0:15–0:25 | **DEMO** | Producto resolviendo, acción real, cortes 1.5–3 s | bodega/carro/casa, cruda |
| 0:25–0:30 | **PRUEBA** | Número o ancla específica | precio vs Amazon/taller, “40 millones vs 99 mil” |
| 0:30–fin | **CTA** | UNA acción + COD/escasez | “paga al recibir, antes de que se agote” |

> No todos los bloques son obligatorios (hogar sin voz salta mecanismo). Pero **hook, demo y cierre con ancla SIEMPRE**.

### 3.4 Hook en 3 capas (obligatorio en cada guion)

El hook NO es solo texto. Son 3 capas simultáneas; si falla una, se pierde 30–40 % de hook rate.

- **Texto (overlay):** máx **8 palabras**, sans-serif gruesa, contrastante. Contrarian / curiosidad / mala noticia.
- **Visual (frame 1):** algo que detiene el scroll solo (zoom al desastre, clip de accidente/robo, cara de shock, antes/después, mano sobre la textura). Ver taxonomía Parte 4.
- **Audio (primer sonido):** voz natural **a mitad de frase** o sonido orgánico. NUNCA “Hola a todos”.

### 3.5 Banco de HOOKS REALES (los 10 que más le funcionan a Juan)

El LLM elige el tipo que calce con el producto y **reescribe con el mismo molde** (no inventa de cero):

1. **Mito roto / contrarian de una línea** (el más fuerte) — molde: *“[Creencia común]. [Negación]. [Verdad incómoda].”*
   Ej. “Tu casa no es fea, solo está mal iluminada.” · “Si usted cree que la alarmita lo está protegiendo, le tengo malas noticias.”
2. **Estadística falsa / dato impactante** — *“El [%] de [grupo] [comete este error / no sabe esto].”*
   Ej. “El 90 % de las casas tienen este error y casi nadie lo nota.”
3. **Trigger de ansiedad situacional** — *“[Situación que ya viviste] → no hagas [lo caro/obvio] todavía.”*
   Ej. “Se encendió la luz del check engine. No corras al taller todavía.”
4. **Sketch de reacción (interrumpe)** — dos voces, una exagera para frenar el scroll, luego “mira esto”.
   Ej. “¡Oye! ¿Qué demonios estás haciendo? — Mira esto.”
5. **Descubridor entusiasta** (reseña de amigo, no ad) — “Quien inventó esto se merece un aumento.”
6. **Noticia + gamificación** — “¡Ojo! Salió la lista de las marcas de carros más robadas…” + countdown 5→1.
7. **Pregunta diferencial / de dolor** — “¿Cuál es la diferencia de un protector coreano con cualquier otro?”
8. **Origen secreto / conspirativo** — “China revela un lote de una de las marcas más caras del mundo…”.
9. **Precio shock visual (hogar, sin voz)** — banner fijo “ANTES $280.000 — AHORA $139.900 · SOLO HOY”.
10. **Comparativa numérica / transformación (sin voz)** — “¿CÓMO PASAR DE 1.60 m A MÁS DE 1.98 m?”, “185 → 190”.

### 3.6 Las 8 FÓRMULAS ganadoras (plantillas copy-paste, salidas de ads reales)

Cada fórmula sale de un anuncio real de Juan. El módulo mete el producto nuevo en el molde y produce el **bloque copy-paste** (overlay + voiceover + CTA). El copy-paste es una salida obligatoria del módulo.

**F1 — “No corras al taller”** (gadget que evita un gasto/visita técnica):
```
OVERLAY:  0:00 SE PRENDIÓ EL [problema] · 0:06 MENOS DE $[precio] (otros $[precio×2.5]) · 0:30 EN PROMOCIÓN HOY
VOICEOVER: Se [encendió/dañó] [el problema] en tu [contexto]. No corras a [taller] todavía, prueba este
[producto] primero. Te sale en menos de [precio] con envío, cuando en [competidor] cuesta más de [precio alto].
Solo lo [conectas] y en segundos [resuelve]. Es plug and play, sin costos adicionales.
CTA: Está en promoción ahora mismo, [toca el carrito / pídelo contraentrega] antes de que se agote.
```

**F2 — Seguridad + comparativa de valor** (robo/accidente/pérdida):
```
OVERLAY:  0:00 LE TENGO MALAS NOTICIAS · 0:14 [MECANISMO físico] · 0:30 PAGA EN CASA
VOICEOVER: Si usted cree que [la solución común] lo está protegiendo, le tengo malas noticias. [Revela la
vulnerabilidad barata]. Esto es lo único que no le pueden [burlar]: [mecanismo], sin batería, sin señal, es
físico y ya. Dígame: usted le suelta [bien de $40 millones] a [amenaza de $50 mil], o le mete $[precio] a esto.
No sé usted, pero yo no me la pienso.
CTA: Ahí abajo está el botón, en bio. Gratis y paga en casa.
```

**F3 — Mito roto de una línea** (decoración/belleza/lifestyle):
```
OVERLAY (reveal palabra x palabra): 0:00 TU [cosa] NO ES [insulto esperado]
VOICEOVER: Tu [casa/piel] no es [fea/grasosa], solo está [mal iluminada/mal cuidada]. La regla es simple:
[mecanismo en 1 frase]. Y esto resuelve [2 de 3 cosas] de un solo golpe. [Sabor cultural: “ámbar como
atardecer, azul como película de Netflix”].
CTA: La pagas cuando llega a tu puerta. [Producto] antes de [cambiar todo lo demás]. Este detalle lo cambia todo.
```

**F4 — Estadística + educación** (“el experto que revela el secreto”):
```
OVERLAY: 0:00 EL 90% [comete ESTE error]
VOICEOVER: El 90 % de [grupo] tiene este error y casi nadie lo nota. No es [causa obvia 1], no es [causa obvia
2]. Es que [verdadera causa]. Por eso [consecuencia incómoda]. La regla es simple: [solución].
CTA: [oferta + COD].
```

**F5 — Noticia + countdown gamificado** (retención hasta el final):
```
OVERLAY: contador 5 → 4 → 3 → 2 → 1
VOICEOVER: ¡Ojo! Salió la lista de [ranking relevante] en [país] este año. Puesto 5: [X]. Puesto 4: [X]…
el número uno escríbanlo en los comentarios. Si [tu caso] aparece en esta lista, esto que viene le interesa.
[Producto + precio + comparativa].
CTA: El botón está en bio. Gratis y paga en casa.
```

**F6 — Sketch de reacción + demo ASMR** (limpieza/transformación visual):
```
OVERLAY: 0:00 ¿QUÉ DEMONIOS ESTÁS HACIENDO?
VOICEOVER: — ¡[Grito]! — ¡Oye! ¿Qué demonios estás haciendo? — Mira esto. [Producto] convierte [lo común] en
[resultado potente]. Sin [fricción 1], sin [fricción 2]. Y no te voy a mentir, es extrañamente satisfactorio ver
cómo [desaparece la mugre]. Podría quedarme viéndolo todo el día.
CTA: Toca el carrito naranja abajo a la izquierda y aprovecha la oferta flash antes de que se agote.
```

**F7 — Vendedor en bodega + banner de precio** (hogar COD, cierra hasta en silencio):
```
OVERLAY (fijo todo el video): [PRODUCTO] · $[precio] · [medidas] · ENVÍOS A TODO EL PAÍS · PAGA AL RECIBIR
VOICEOVER: Y señores, esta es nuestra [producto], por solamente $[precio], medidas de [medidas]. Miren estos
colores tan bacanos. Por la parte de atrás tiene [beneficio]. Tenemos este y muchos más estilos.
CTA: Recuerde, envíos a todo el país, paga 100 % al recibido.
```
> Aprendizaje: el **banner de precio + medidas fijo** hace que cierre AUNQUE esté en mute. El vendedor dentro de la bodega = prueba de que el stock existe (mata la desconfianza del dropshipping). Para la app: generar el “entorno bodega/almacén real” en los planos.

**F8 — Mito + número + mecanismo** (suplementos/salud — cuidado compliance, Parte 11):
```
OVERLAY: 0:00 ¿CÓMO PASAR DE [estado A] A [estado B]? · 0:28 QUEDAN POCAS UNIDADES
VOICEOVER: Si pensabas que [creencia limitante], estás en un error. Con esto puedes [ganar X resultado], sin
importar [objeción]. No es [categoría barata], es [mecanismo creíble]. Llévate el pegue de 3 para máximos
resultados.
CTA: Te dejo el enlace aquí abajo, trae envío en bio gratis. Quedan pocas unidades.
```

### 3.7 CTAs, ofertas y anclas de precio (reglas)

- `REGLA (ancla):` NUNCA dar el precio solo. Siempre contra algo más caro: “menos de 180 mil… cuando en otros lados está en más de 300 mil”; “menos de 17 dólares… cuando en Amazon cuesta 49 con 99”; “un carro de 40 millones contra un seguro de 99 mil”.
- `REGLA (COD CO/EC):` incluir contraentrega como neutralizador de riesgo (es palanca de conversión, no un detalle).
- `REGLA (escasez con prueba, no vacía):` “la última vez se agotaron por completo”, “si el botón sigue naranja, hay existencias”, “QUEDAN POCAS UNIDADES”. Nada de countdowns inventados (Meta penaliza).
- **AOV/stack dentro del argumento:** “llévate el pegue de 3 para máximos resultados” (upsell integrado, no oferta aparte).

### 3.8 Frameworks de guion de respuesta directa (para elegir estructura)

El módulo elige el framework según **awareness** y **plataforma**:

| Framework | Estructura | Cuándo |
|---|---|---|
| **PAS** (Problema-Agitar-Solución) | dolor → agrandar el costo de no resolverlo → producto | Default para productos que resuelven un dolor sentido |
| **AIDA** | Atención → Interés → Deseo → Acción | Productos wow/novedad, tráfico frío |
| **Hook-Retain-Reward** (Hormozi) | gancho → mantener tensión → pagar con valor/resultado | TikTok orgánico (watch-time = alcance) |
| **BAB** (Before-After-Bridge) | antes doloroso → después deseable → producto = puente | Transformación visual (limpieza, belleza, hogar) |
| **UGC/testimonial** | hook → “tenía bajas expectativas” → reacción → demo → resultado | Nativo TikTok/Reels, vence escepticismo |
| **Problema-Solución-Prueba-CTA** | problema → solución → prueba (demo/reviews) → CTA | Meta paid (la prueba convierte) |
| **VSL / advertorial (SSO)** | historia → solución → oferta | 45–90 s en Reels/Facebook feed |

> **Hook stacking:** encadenar un micro-hook a CADA sección (no un hook + cuerpo plano). Cada transición de escena re-gana la atención → sube VTR y CTR.

### 3.9 Parámetros por defecto (encodables) — módulo Guion

| Parámetro | Default | Notas |
|---|---|---|
| `hook_max_palabras_overlay` | 8 | frame 1 |
| `producto_aparece_despues_de_hook` | true | test anti-anuncio #2 |
| `capas_hook_obligatorias` | [texto, visual, audio] | fallar 1 = regenerar |
| `ancla_precio_obligatoria` | true | nunca precio solo |
| `cta_unica` | true | 1 sola acción |
| `voz_mercado` | {CO,EC: es-CO pana; USA: en-US casual; USA-hisp: es-neutro TikTokShop; ES: es-ES} | |
| `frameworks_permitidos` | por awareness+plataforma (tabla 3.8) | |
| `variantes_por_producto` | 10–25 | diversidad real (Andromeda) |
| `salida_obligatoria` | bloque copy-paste (overlay + voiceover + CTA) | |

---

## 4. MÓDULO SHOTLIST (SCENE BREAKDOWN)

Convierte el guion en una lista de **8–12 planos** que la etapa 5 va a generar con IA. Cada plano es un clip corto (≤5 s) etiquetado como **avatar** (persona hablando) o **b-roll** (producto/demo/entorno).

### 4.1 Los 14 hooks visuales (elegir uno para el frame 1)

El frame 1 debe detener el scroll SIN texto ni audio. Taxonomía (usar como `shot_type` del primer plano):

| # | Hook visual | Descripción para el prompt de generación |
|---|---|---|
| V1 | **Outcome Drop** | frame 1 = el resultado final ya logrado (cero setup) |
| V2 | **Disaster Zoom** | zoom violento al desastre/problema antes de nada |
| V3 | **Slide-In Reveal** | el producto entra al frame desde fuera con velocidad |
| V4 | **POV Problem** | primera persona viviendo el problema |
| V5 | **POV Solution** | primera persona usando el producto |
| V6 | **Split-Screen Static** | antes \| después desde el frame 1 |
| V7 | **Top-Down Action** | cenital + acción ejecutándose debajo |
| V8 | **Extreme Close-up Texture** | 90 % de pantalla = 1 textura (espuma, polvo, brillo) |
| V9 | **Pull-Out** | empieza muy cerca y se aleja revelando contexto |
| V10 | **Drop & Bounce** | el producto cae y rebota en frame |
| V11 | **Whip Pan Reveal** | giro rapidísimo que aterriza en el producto |
| V12 | **Reaction Reveal** | cara reaccionando a algo que el viewer aún no ve |
| V13 | **Negative-Space Interrupt** | pantalla negra/blanca con 1 elemento + corte directo |
| V14 | **360 Spin** | producto rotando 360° sobre fondo limpio |

**Las 6 dimensiones de un hook visual** (un hook sólido toca ≥3; el top 5 % toca 5–6): *framing* (close-up/POV/top-down/low-angle/dutch), *movimiento* (slide/zoom/hand-pull/whip/drop), *action* (reacción/descubrimiento/gesto/acción del producto), *color/contraste* (cambio brusco, saturación), *scale* (comparación visual), *surprise* (pattern interrupt).

`REGLA (kill switch visual):` frame 1 NUNCA puede ser logo grande, persona estática con sonrisa neutra, producto en packaging shot, ni pantalla negra > 0.5 s sin payoff. Cualquiera = regenerar.

### 4.2 Plantillas segundo-a-segundo (listas para producir)

**T1 — UGC corto universal (15–25 s), la mejor para cold dropshipping:**
```
0:00   HOOK textual full-screen (1.5 s) — overlay bold máx 8 palabras
0:01.5 Producto entra en frame (1 s) — mano/persona, cara feliz/sorprendida
0:02.5 Problema visual (2.5 s) — el “antes”/dolor; VO: “yo también gastaba esto hasta que…”
0:05   Producto en acción (8 s) — demo, 3–4 cortes máx (close-up + mid + result)
0:13   Proof (5 s) — testimonio + número: “✓ 4.8★ · 12.000 vendidos en mayo”
0:18   CTA triple (5 s) — verbal + flecha + “LINK EN BIO 👇”
0:23   Logo + garantía (2 s) — “Garantía 30 días, envío gratis”
```

**T2 — VSL mid-form (60–90 s) para Reels y Facebook feed:**
```
0:00–0:03  Pattern interrupt — visual sorprendente + texto bold
0:03–0:10  Dolor amplificado — persona a cámara, ambiente real, 2–3 manifestaciones
0:10–0:20  Origen del descubrimiento — autoridad: “hasta que mi mecánico/mamá me contó…”
0:20–0:40  Mecanismo único + demo — POR QUÉ funciona, close-ups + ángulos variados
0:40–0:55  Social proof — testimonios (caps WhatsApp, comentarios, antes/después)
0:55–1:15  Oferta + garantía — precio + descuento + bono + “30 días de devolución”
1:15–1:30  CTA + urgencia real — “quedan X unidades” (sin urgencia falsa)
```

**T3 — Split-screen before/after (CleanTok/carros):**
```
0:00–0:02  Solo el “antes” full-screen (sin texto)
0:02–0:04  Texto: “Ver el después” (pattern interrupt)
0:04–0:12  Split-screen: antes (izq estático) | producto en acción (der video)
0:12–0:20  Después full-screen — música climaxea, texto “10 minutos”
0:20–0:25  Beauty shot del producto + CTA
```

**Beat sheets de referencia por plataforma/duración** (para que el módulo elija):
- **15–20 s TikTok:** hook 0–3 s (shots 0.5–1 s) · demo 3–11 s · proof+CTA 11–15/20 s. ~6–10 cortes.
- **30 s Meta:** hook 0–3 s · problema 3–8 s · demo 8–15 s · prueba/social 15–22 s · oferta 22–27 s · CTA 27–30 s. ~12–18 cortes.
- **45–90 s VSL:** ver T2.

### 4.3 Formatos ganadores por nicho (elegir top-3 según producto)

- **Hogar:** Satisfying Demo Loop (CleanTok) · Restock Aesthetic · Problem-Solution Pattern Interrupt · Founder/Origin · Before/After Split · Voiceover Hack no-face.
- **Carros:** ASMR Detailing · Headlight Restoration before/after · Hidden Spots Cleaning · Tech Gadget Drop · POV Conductor · Quality Control Reaction.
- **Multi-nicho (universales):** Product/Outcome Showcase (**el #1**, mostrar el resultado en frame 1) · Authority + Curiosity Gap · Contrarian/Mythbuster · Storytime/POV · “TikTok made me buy it” · Native Discovery (“I found this and…”).

### 4.4 Parámetros por defecto (encodables) — módulo Shotlist

| Parámetro | Default |
|---|---|
| `planos_por_video` | 8–12 |
| `duracion_clip_max` | 5 s (menos artefactos IA) |
| `duracion_shot_hook` | 0.5–1 s |
| `duracion_shot_body` | 1.5–3 s |
| `frame1_hook_visual` | uno de V1–V14, ≥3 dimensiones |
| `mix_avatar_broll` | alternar; nunca 1 solo plano largo de avatar |
| `kill_switch_visual` | activo (ver 4.1) |

---

## 5. MÓDULO ASSETS VISUALES (GENERACIÓN 100% IA)

La parte más cara y más delicada. **Regla de oro:** no generar el producto con text-to-video puro. Siempre **imagen real del SKU → imagen limpia/keyframe (image model) → image-to-video (video model)**. Así el producto conserva fidelidad.

### 5.1 Sub-pipeline visual

```
imagen real del producto
   └─► [5a] IMAGE MODEL: limpiar producto, quitar fondo/marca de agua, generar keyframe
        por plano (producto en la escena/entorno real, consistencia de SKU)
        → Nano Banana Pro (Gemini 3 Pro Image) · alt: Flux, Ideogram (texto-en-imagen)
   └─► [5b] VIDEO MODEL (image-to-video): animar cada keyframe en un clip ≤5 s
        → Kling 3.0 / Seedance (volumen, barato) · Runway Gen-4.5 (consistencia/cámara) ·
          Veo 3.1 Fast (1 plano hero cinematográfico)
        acceso unificado vía fal.ai o Replicate (facturación por segundo)
   └─► [5c] AVATAR (si el plano es “persona hablando”):
        → HeyGen Avatar IV (API madura) · Arcads (UGC más realista; automatizable con el
          repo externo arcads-claude-code) · Topview (“avatar sostiene tu producto real”)
```

### 5.2 Selección de modelo por tipo de plano (encodable)

| Tipo de plano | Modelo por defecto | Por qué |
|---|---|---|
| B-roll producto (volumen) | **Kling 3.0** o **Seedance 1.5** | consistencia + costo (~$0.025–0.11/s) |
| Plano con cámara/consistencia fina | **Runway Gen-4/4.5** | reference-image + control de cámara |
| 1 plano “hero” cinematográfico | **Veo 3.1 Fast** | máxima calidad/adherencia ($0.15/s) |
| Keyframe / producto en escena | **Nano Banana Pro** | líder en consistencia de producto/personaje ($0.04–0.13/img) |
| Avatar hablando (UGC) | **HeyGen Avatar IV** / **Arcads** | realismo + API |
| Avatar sosteniendo el SKU real | **Topview** | demo “creador con tu producto” |

> `REGLA:` NO construir sobre **OpenAI Sora** — su API se descontinúa (web/app abr-2026, API sep-2026).

### 5.3 Cómo evitar el “AI look” (reglas de prompt encodables)

El QA gate rechaza cualquier clip que “huela a IA”. Para prevenirlo, inyectar en TODOS los prompts:

- `REGLA:` pedir **imperfección**: “messy real room, mixed/natural lighting, slightly imperfect skin texture, no plastic skin, clothing wrinkles, handheld slight shake, phone-camera look, amateur framing”.
- `REGLA:` **evitar** lo que delata IA: “no studio lighting, no glossy influencer polish, no perfect symmetry, no floating objects, no warped hands, no morphing product”.
- `REGLA (manejo del producto):` el avatar **referencia el producto a mitad de pensamiento**, no lo “presenta” de frente como catálogo.
- `REGLA (un solo actor):` mantener **el mismo avatar y la misma voz** en todas las variantes de una campaña (cambiar de actor rompe la confianza del viewer).
- `REGLA (mezcla de modalidades):` combinar **avatar hablando + b-roll real del producto** (image-to-video) en vez de un solo plano largo de IA — esconde debilidades del modelo y se lee como UGC editado.
- **Entorno CO/EC:** pedir explícitamente contexto local real: “home/garage/warehouse in Latin America, everyday realistic setting, not a showroom”. Conecta con la Fórmula 7 (vendedor en bodega).

### 5.4 Fidelidad del producto (SKU)

- `REGLA:` pasar 1–3 imágenes reales del SKU como **reference images** al image model; regenerar si el QA detecta que el producto cambió de forma/color/logo.
- Clips cortos (≤5 s) reducen el “morphing”. Si un plano necesita más, dividir en dos clips.
- Para planos de demo (producto en acción), generar primero el keyframe “producto en la mano/en uso” con el image model y animar solo el movimiento necesario.

### 5.5 Parámetros por defecto (encodables) — módulo Assets

| Parámetro | Default |
|---|---|
| `image_model` | Nano Banana Pro |
| `video_model_default` | Kling 3.0 |
| `video_model_hero` | Veo 3.1 Fast (1 plano) |
| `video_model_consistencia` | Runway Gen-4.5 |
| `avatar_engine` | HeyGen Avatar IV / Arcads |
| `acceso_modelos` | fal.ai (o Replicate) |
| `clip_len_max` | 5 s |
| `ref_images_sku` | 1–3 obligatorias |
| `anti_ai_prompt_block` | inyectado en todos los prompts |
| `mismo_avatar_voz_por_campaña` | true |
| `prohibido` | OpenAI Sora (deprecado) |

---

## 6. MÓDULO VOZ (VOICEOVER / TTS)

`DEFAULT engine:` **ElevenLabs** (mejor naturalidad ES-LATAM e inglés, clonación de voz, control de emoción/ritmo, API madura; devuelve **timestamps a nivel de palabra** → alimentan directo los subtítulos).

- `REGLA (CO/EC):` usar una **voz colombiana clonada** natural (pana/vecino), no TTS genérico. Es lo que hace que “no suene a anuncio”.
- `DEFAULT ritmo:` locución a **1.1–1.2× de velocidad** → suena más enérgica y retiene mejor en short-form.
- `REGLA:` la primera línea del VO entra **a mitad de frase** (nunca “Hola a todos”), y arranca ≤0.5 s.
- **Costo:** ElevenLabs ~$0.10/1.000 chars (Multilingual v2/v3), ~$0.05/1.000 (Flash/Turbo). Derechos comerciales desde el plan Starter.
- **Alternativas:** Fish Audio S2 Pro, Amazon Polly Generative (AWS-native), PlayHT, o **Chatterbox** (open-source, MIT, 23 idiomas incl. español, clon desde 5–10 s → control de costo a escala).

| Parámetro | Default |
|---|---|
| `tts_engine` | ElevenLabs (v2/v3) |
| `voz_CO_EC` | clon voz colombiana natural |
| `voz_USA` | en-US casual |
| `velocidad` | 1.1–1.2× |
| `entrega_timestamps_palabra` | true (para subtítulos) |
| `primera_linea` | a mitad de frase, ≤0.5 s |

---

## 7. MÓDULO MÚSICA + SFX

### 7.1 Selección de música (BPM = ritmo del corte)

- `DEFAULT BPM:` **100–140**. Alta energía (fitness, moda, gadgets, cocina) **120–140**; storytelling/wellness/skincare/suplementos **80–100** (tonos menores, melodía suave).
- `REGLA (sync):` colocar el **drop / acento musical en el reveal del producto** y en el hook (≈1–2 s). La sincronía audio-visual sube completion hasta ~40 %. El “momento wow” cae sobre el clímax del audio.
- `REGLA (música + VO):` bottom-funnel usa **música + voz juntas** (≈2× conversión vs una sola).
- **TikTok vs Meta:** TikTok = audio nativo/tendencia (borrowed attention). Meta = tracks más “educativos/emocionales”, siempre asumiendo mute (los subtítulos cargan la historia).

### 7.2 Licencia (crítico para paid — enforce en la app)

`REGLA (paid ads):` un audio cleared para orgánico **NO** está cleared para ads pagados. Usar trending audio sin licencia en un ad pagado → rechazo o ban de cuenta. Fuentes seguras únicas:
- **TikTok Commercial Music Library (CML)** — 1M+ tracks pre-cleared para paid.
- **Meta Sound Collection** — 14.000+ tracks/SFX cleared para uso comercial (default para Meta).
- Librerías royalty-free con licencia comercial: Epidemic Sound, Artlist, Uppbeat, Soundstripe.
- **Música IA:** **Suno Pro/Premier** otorga derechos comerciales (el plan free es no-comercial y no se convierte retroactivamente). Evitar Udio para ads (pasó a “walled garden”). Guardar el recibo de licencia.

`DEFAULT arquitectura:` para pipeline automatizado → **música IA (Suno Pro) o librería royalty-free**, etiquetada con BPM + energía + mood. Nunca scrapear audio orgánico de TikTok para el lado Meta.

### 7.3 SFX que convierten + dónde ponerlos

| SFX | Cuándo |
|---|---|
| **Whoosh** | cada cambio de escena, swipe, movimiento de cámara, aparición de texto (duración = largo de la transición, ~400–500 ms) |
| **Ding / pop** | al aparecer un texto/bullet en pantalla (hace que el gráfico “viva”) |
| **Cash register (cha-ching)** | reveal de precio, sello de descuento, momento CTA |
| **Impact / boom** | slam de título, corte duro de acento |
| **Notification pop / sparkle** | hooks de “te llegó un mensaje”, brillo en el hero shot |

`REGLA sync SFX:` alinear dentro de **100–200 ms** del evento visual (ajuste fino a 1 frame).

### 7.4 Mezcla de audio (dB — encodable)

| Elemento | Nivel |
|---|---|
| **Voz / VO** | −6 a −12 dB |
| **Música de fondo** | −18 a −25 dB (≈15–20 dB por debajo del VO) |
| **Techo (clipping)** | nunca > 0 dB |
| **Loudness integrado** | ~ **−14 LUFS**, true-peak −1 dBTP |

- `REGLA (ducking obligatorio):` la música baja automáticamente bajo el VO y sube en las pausas (sidechain con el VO como trigger).
- EQ: hueco en medios de la música (VO vive ~1–3 kHz); high-pass del VO < 80 Hz.
- `REGLA (QA):` **probar siempre en parlante de celular**. Si falla ahí, no se publica.

| Parámetro | Default |
|---|---|
| `bpm` | 100–140 (por categoría) |
| `drop_en_reveal` | true |
| `fuente_musica_paid` | CML / Meta Sound Collection / Suno Pro / royalty-free |
| `vo_db` / `music_db` | −6…−12 / −18…−25 |
| `ducking` | on (sidechain VO) |
| `loudness` | −14 LUFS / −1 dBTP |
| `sfx_sync_ms` | 100–200 |

---

## 8. MÓDULO SUBTÍTULOS (CAPTIONS)

Los subtítulos son obligatorios (85 % ve en mute; captions suben views hasta +40 % y completion). Estilo **word-by-word / karaoke (Hormozi)**: cada palabra escala o cambia de color al pronunciarse.

### 8.1 Reglas de estilo (encodables)

- `DEFAULT estilo:` word-by-word con highlight de la palabra activa.
- `DEFAULT densidad:` **3–5 palabras por línea**, máx 4–6 palabras / 2 líneas en pantalla. Nunca párrafos.
- `DEFAULT velocidad de lectura:` **160–200 WPM** (12–20 CPS cómodo; tope 25 CPS). Sincronizar highlights al audio (timestamps de la etapa 6).
- `DEFAULT fuente:` sans-serif **bold** (Montserrat Bold / Proxima Nova / Impact-class), **MAYÚSCULAS** para legibilidad a distancia.
- `DEFAULT color:` relleno blanco o amarillo + **borde negro 8–12 px** (sobre 1080×1920). Amarillo en la palabra clave.
- `DEFAULT posición:` centro a tercio medio-bajo, **dentro de la safe zone** (ver Parte 10). En Meta Reels/Stories mantener el **tercio inferior (~35 %) libre**.
- Animación: pop/scale-in por palabra; evitar fades lentos.

### 8.2 Implementación

- `DEFAULT (barato, control total):` **WhisperX** (timestamps a nivel de palabra) → generar **.ASS** → **FFmpeg** quema los subtítulos en un solo pass. Costo marginal ~0. Si el VO viene de ElevenLabs, ya trae timestamps y se salta la re-transcripción.
- `ALT (turnkey):` **Submagic API** o **ZapCap** (~$0.10–0.15/min; plantillas Hormozi, emojis, B-roll) si se quiere estilo animado sin construir el renderer.

| Parámetro | Default |
|---|---|
| `estilo` | word-by-word (Hormozi) |
| `palabras_por_linea` | 3–5 |
| `wpm` | 160–200 |
| `fuente` | sans bold, MAYÚSCULAS |
| `color` | blanco/amarillo + stroke negro 8–12 px |
| `posicion` | tercio medio-bajo, dentro de safe zone |
| `motor` | WhisperX→ASS→FFmpeg (o Submagic API) |

---

## 9. MÓDULO EDICIÓN / ENSAMBLAJE

Une los clips + voz + música + SFX + subtítulos con el ritmo correcto. Motor: **FFmpeg** o **Remotion** (self-host, mejor unit-economics y control) o **JSON2Video** (cloud, más rápido de montar, duración de elementos auto-ajustada + TTS incluido).

### 9.1 Ritmo y cortes (encodable)

- `DEFAULT cadencia:` **1 corte cada 2–4 s** de promedio; en el hook shots de **0.5–1 s**; nada > ~3 s sin corte, zoom o cambio de texto (“reset visual”).
- `DEFAULT presupuesto de cortes:` 15 s → 6–10 cortes · 30 s → 12–18 · 60 s → 20–30 (con un reset cada 8–10 s).
- `REGLA:` el producto debe estar en pantalla y **en movimiento** para el segundo 2–3.

### 9.2 Transiciones (cuándo dispara cada una)

| Transición | Uso |
|---|---|
| **Hard cut / jump cut** | default en todo (backbone; comprime dead air) |
| **Zoom punch-in** | énfasis: sobre el claim clave, el precio o el reveal (sync al beat) |
| **Whip pan** | cambio de escena/locación (1–2 por ad máx) |
| **Match cut** | continuidad producto/acción (“objeto-problema → producto”) |
| **J-cut / L-cut** | audio-led: entra el audio del siguiente clip antes que su video (suaviza VO) |

`REGLA:` máx ~2–3 transiciones decorativas por 15–30 s; el resto hard cuts.

### 9.3 Movimiento sobre clips estáticos/IA (anti “frame muerto”)

- `REGLA:` aplicar movimiento continuo a **todo** asset estático (Ken Burns): push-in lento **5–15 %** sobre la duración del plano; alternar dirección plano a plano.
- Punch-in rápido (100→120 %) en stills clave sincronizado al beat.
- `REGLA (motion floor):` ningún plano > ~1.5–2 s sin *algún* movimiento (zoom, parallax, o un subtítulo animándose).

### 9.4 Color / look

- `DEFAULT:` look **punchy** para mobile — subir contraste + saturación ligera, separación tonal clara (no cinematográfico apagado).
- Orden: (1) exposición + white balance, (2) LUT mobile, (3) ajuste final de contraste/saturación en capa aparte.
- El producto debe ser el elemento más brillante/saturado del frame.

### 9.5 Gráficos y texto en pantalla

- **Headline card 0–3 s:** una línea bold de beneficio/curiosidad reforzando el hook (para el que ve en mute).
- **Flechas/círculos dibujados a mano** ganan a gráficos pulidos en TikTok; apuntan al producto/resultado.
- **Anclas de precio / comparativas:** strike-through precio viejo → nuevo; “ellos vs nosotros”; badges “40 % OFF / SOLO HOY”.
- Animar el texto (pop/slide); mantenerlo el tiempo suficiente para leerse al WPM objetivo.

| Parámetro | Default |
|---|---|
| `cadencia_corte` | 2–4 s (hook 0.5–1 s) |
| `producto_en_movimiento_seg` | ≤3 s |
| `transicion_default` | hard cut |
| `decorativas_max` | 2–3 por 15–30 s |
| `ken_burns_push` | 5–15 % |
| `motion_floor` | sin plano estático > 1.5–2 s |
| `look` | alto contraste + saturación (LUT mobile) |
| `motor_render` | FFmpeg / Remotion / JSON2Video |

---

## 10. SPECS TÉCNICAS DE EXPORT + MATRIZ POR PLATAFORMA

### 10.1 Canvas maestro y export

`DEFAULT:` autor en **1080×1920 (9:16), 30 fps**; derivar los demás ratios de ahí.

| Spec | Valor |
|---|---|
| **Aspect ratios** | 9:16 (1080×1920) TikTok/Reels/Stories · 4:5 (1080×1350) Meta Feed · 1:1 (1080×1080) carrusel |
| **Resolución** | 1080×1920 |
| **Frame rate** | 30 fps constante (60 solo para acción rápida) |
| **Códec / bitrate** | H.264 High Profile · 8–15 Mbps VBR |
| **Audio** | AAC-LC, 44.1 kHz, ~256 kbps stereo |
| **Loudness** | −14 LUFS integrado, −1 dBTP |
| **Peso** | < 100 MB (ad managers) |

**Safe zones (mantener subtítulos/CTA/logo dentro):**
- **TikTok 9:16:** ~top 14 %, **bottom 20–35 %**, sides 6 %.
- **Meta Reels/Stories:** más estricto — **bottom ~35 % libre** (top ~14 %, sides ~6 %).
- Encodar un “title-safe box” por placement; nunca renderizar caption/precio/CTA fuera.

**Duración:** sweet spot **15–30 s** para tráfico frío; 15–60 s aguanta en Meta; Reels ≤90 s. Default cold = **20–25 s**.

### 10.2 Un master timeline → dos cuts

`REGLA:` generar UN timeline maestro 9:16 y emitir **dos renders**:

| Dimensión | **TikTok cut** | **Meta cut** |
|---|---|---|
| Look | crudo, UGC, scrappier | UGC o algo más pulido/branded |
| Gráficos | flechas dibujadas, emojis, meme text | overlays de precio/comparativa aceptables |
| Audio | trending/native (vía CML) + hook hablado | música + VO, subtítulos obligatorios (mute) |
| Formato | 9:16 | 4:5 **+** 9:16 (Feed + Stories/Reels) |
| Safe zone | top 14 / bottom 20–35 | bottom 35 estricto |

> `REGLA:` NO subir un ad estilo-Meta pulido a TikTok — rinde 2–3× peor (CPA más alto). El estilo debe ser nativo por plataforma.

### 10.3 Matriz de plataforma (resumen operativo)

| Variable | TikTok | Instagram Reels | Facebook (Meta) | YouTube Shorts |
|---|---|---|---|---|
| Duración óptima | 15–30 s | 60–90 s | 15–30 s | 15–30 s |
| Hook decide en | 1.5 s | 3 s | 2–3 s | 3 s |
| Audio | trending crítico (CML en paid) | trending +engagement | mute (85 %) | mute |
| Subtítulos | quemados word-by-word | quemados | **obligatorio** | **obligatorio** |
| Estética | lo-fi nativo | curado pero auténtico | lo-fi UGC > polished | lo-fi nativo |
| CTA | link in bio / carrito naranja | link in bio / sticker | botón Shop Now / Learn More | link descripción |
| Ad fatigue | 1–2 semanas | 2–3 semanas | 2–3 semanas (Andromeda) | 1–2 semanas |

---

## 11. QA, BENCHMARKS, KILL RULES Y COMPLIANCE (guardrails)

### 11.1 QA gate automático (antes de export)

Chequear con LLM-visión + reglas:
- [ ] ¿SKU fiel (forma/color/logo sin deformar)? ¿Manos/caras sin artefactos?
- [ ] ¿“Parece grabado en celular por una persona real”? (no AI look, no estudio)
- [ ] ¿Frame 1 pasa el kill-switch visual (no logo/estático/packaging)?
- [ ] ¿Subtítulos legibles, en sync y dentro de safe zone?
- [ ] ¿Producto visible y en movimiento ≤ seg 3? ¿Demo entre seg 5–20?
- [ ] ¿CTA único (verbal + visual + texto)? ¿Ancla de precio presente?
- [ ] ¿Audio licenciado para paid? ¿Mezcla ok en parlante de celular?

Si falla un ítem visual → regenerar solo ese plano (etapa 5). Si falla el guion → volver a etapa 3.

### 11.2 Benchmarks (para kill/scale)

- **Hook rate / thumbstop** = 3-s views ÷ impresiones (TikTok mide a **2 s**, Meta a **3 s** → no comparar cruzado).
  - Meta: objetivo **30–40 %**; **< 25 % = arreglar creativo**. TikTok: **30 %+** (top 40–45 %).
  - Umbral interno de Juan: **hook rate < 25 % en 3.000 imps = kill.** Retención objetivo 65–70 % a los 3 s = viral.
- **Hold rate** = 15-s views ÷ 3-s views. Cold saludable: Meta 15–25 %, TikTok 10–18 %.
- **CTR** ecom: **1.5–2.5 %** bueno en Meta; TikTok > 1 % “jala”.
- **Diagnóstico en orden:** (1) hook rate bajo → problema de creativo, cambia hooks primero; (2) hook ok pero hold bajo → el cuerpo no cumple la promesa; (3) hold ok pero CVR bajo → oferta/CTA/landing.
- **Kill rule:** correr 48–72 h con ≥2.000 imps antes de juzgar; matar si CTR < 50 % del control o CPA > 25 % sobre target.

### 11.3 Diversidad para Andromeda (Meta 2026)

`REGLA:` un ad set con **20–25 creativos genuinamente diversos** > 5 ad sets de 5. Variar creador/ángulo/hook/formato/locación. 30 variaciones cosméticas = mismo Entity ID = cuentan como 1. → La app debe medir y garantizar diversidad real entre variantes (distinto hook visual, distinto framework, distinto avatar/voz-tono).

### 11.4 Compliance (bloqueos duros)

`REGLA (la app NUNCA genera):`
- ❌ Claims médicos directos.
- ❌ Antes/después de **cuerpo** en el creativo (ban garantizado). Para suplementos (F8), usar mecanismo/comparativa numérica sin foto corporal.
- ❌ Urgencia falsa (countdowns inventados).
- ❌ Copiar marca/nombre de una referencia (adaptar el patrón, no el contenido).

`REGLA (aritmética CO/EC COD):` el precio/margen debe aguantar **25–30 % de no-entrega** en contraentrega. La app debe exponer este supuesto al calcular ofertas.

---

## 12. SCHEMAS JSON (contratos entre módulos)

Contratos sugeridos para que Claude Code implemente los módulos con interfaces claras.

**Input de producto:**
```json
{
  "product_id": "candado-volante-01",
  "source_url": "https://...",
  "images": ["s3://.../front.jpg", "s3://.../angle.jpg"],
  "name": "Candado antirrobo de volante",
  "price": {"amount": 99000, "currency": "COP"},
  "price_anchor": {"vs": "valor del carro", "amount": 40000000},
  "market": "CO",
  "language": "es-CO",
  "niche": "autos_seguridad",
  "pain": "robo de carro / clonación de señal",
  "awareness": "problem-aware",
  "platforms": ["tiktok", "meta"],
  "cod": true
}
```

**Guion (output etapa 3):**
```json
{
  "variant_id": "candado-volante-01__v3",
  "framework": "seguridad_comparativa_valor",
  "hook": {
    "text_overlay": "LE TENGO MALAS NOTICIAS",
    "visual_hook": "V2_disaster_zoom",
    "audio_first_line": "Si usted cree que la alarmita lo está protegiendo..."
  },
  "beats": [
    {"t": "0:00-0:03", "block": "hook", "vo": "...", "overlay": "..."},
    {"t": "0:03-0:08", "block": "problema", "vo": "...", "overlay": "..."}
  ],
  "cta": {"text": "Ahí abajo está el botón, en bio. Gratis y paga en casa.", "type": "cod"},
  "copy_paste": "OVERLAY: ...\nVOICEOVER: ...\nCTA: ..."
}
```

**Shotlist (output etapa 4):**
```json
{
  "variant_id": "candado-volante-01__v3",
  "duration_s": 22,
  "shots": [
    {"i": 1, "t": "0:00-0:01", "type": "b-roll", "visual_hook": "V2_disaster_zoom",
     "prompt": "extreme close-up, thief breaking into a car at night, handheld, mixed street lighting, phone-camera look",
     "video_model": "kling-3.0", "duration_s": 1.0},
    {"i": 2, "t": "0:01-0:03", "type": "avatar",
     "prompt": "colombian man ~35 talking to camera in a real garage, casual, imperfect lighting",
     "avatar_engine": "heygen-avatar-iv", "duration_s": 2.0}
  ]
}
```

**Render job (output etapa 4 → 8/10):**
```json
{
  "variant_id": "candado-volante-01__v3",
  "canvas": {"w": 1080, "h": 1920, "fps": 30},
  "audio": {"vo": "s3://.../vo.wav", "music": {"track": "cml://...", "bpm": 128, "drop_at_s": 12}},
  "captions": {"style": "hormozi", "font": "Montserrat-Bold", "wpm": 180},
  "exports": [
    {"platform": "tiktok", "ratio": "9:16", "safe_zone": "tiktok"},
    {"platform": "meta", "ratios": ["4:5", "9:16"], "safe_zone": "meta_strict"}
  ]
}
```

---

## 13. EJEMPLO END-TO-END (recorrido completo)

Producto: **candado antirrobo de volante**, CO, COD, $99.000, problem-aware, TikTok + Meta.

1. **Ángulo:** nicho autos/seguridad → dolor = robo → framework **F2 (seguridad + comparativa de valor)** → hook tipo *mito roto* (“le tengo malas noticias”).
2. **Guion (voz de Juan):**
   ```
   OVERLAY:  0:00 LE TENGO MALAS NOTICIAS · 0:14 ACERO POR FUERA, TITANIO POR DENTRO · 0:30 PAGA EN CASA
   VOICEOVER: Si usted cree que la alarmita lo está protegiendo, le tengo malas noticias. Con 50 mil pesos le
   clonan la señal y se llevan el carro. Esto es lo único que no le pueden burlar: acero por fuera, titanio por
   dentro, sin batería, sin señal. Es físico y ya. Dígame: usted le suelta un carro de 40 millones a un aparatito
   de 50 mil, o le mete 99 mil a esto. No sé usted, pero yo no me la pienso.
   CTA: Ahí abajo está el botón, en bio. Gratis y paga en casa.
   ```
   → pasa el test anti-anuncio (abre con mala noticia, producto después del gancho, ancla 40M vs 99k, COD).
3. **Shotlist (≈22 s, 9 planos):** V2 disaster-zoom (robo, 1 s) → avatar colombiano en garage real (2 s) → close-up del aparato clonador (1.5 s) → demo instalación en el volante, hand-pull (3 s) → producto puesto, giro (2 s) → texto “40.000.000 vs 99.000” (2 s) → avatar cierre (3 s) → banner precio+COD (2 s) → CTA flecha (1.5 s).
4. **Assets IA:** Nano Banana Pro limpia el SKU y arma keyframes (candado en el volante, entorno garage LATAM real, imperfecto) → Kling 3.0 anima los b-roll ≤5 s → HeyGen Avatar IV para los planos de avatar (mismo actor en todas las variantes) → prompts con bloque anti-AI-look.
5. **Voz:** ElevenLabs, clon de voz colombiana, 1.15×, primera línea a mitad de frase.
6. **Música/SFX:** track 128 BPM de CML, drop en el reveal del candado (seg ~12); cha-ching en “99 mil”; whoosh en cada corte.
7. **Ensamblaje:** FFmpeg, cortes 1.5–3 s, Ken Burns en stills, ducking música bajo VO.
8. **Subtítulos:** WhisperX→ASS→FFmpeg, word-by-word, blanco+amarillo, MAYÚSCULAS, tercio medio-bajo.
9. **Export:** TikTok cut (9:16, scrappy, audio nativo) + Meta cut (4:5 + 9:16, overlays de comparativa, bottom-35 libre).
10. **QA + variantes:** generar 10–15 variantes cambiando **hook** (F2 mito-roto, F5 noticia+countdown de “carros más robados”, sketch de reacción), avatar y locación → diversidad Andromeda. Kill las de hook rate < 25 % a 3.000 imps.

---

## 14. STACK DE HERRAMIENTAS (precio / API) + FUENTES

### 14.1 Tabla de herramientas

| Etapa | Herramienta | API | Costo aprox. | Nota |
|---|---|---|---|---|
| Imagen / keyframe | **Nano Banana Pro** (Gemini 3 Pro Image) | sí | $0.04–0.13/img | líder consistencia producto |
| Video (volumen) | **Kling 3.0** | sí | ~$0.029–0.11/s | mejor costo/consistencia |
| Video (barato) | **Seedance 1.5/2.0** | sí | ~$0.025/s | el más económico |
| Video (consistencia/cámara) | **Runway Gen-4/4.5** | sí | medio | reference-image, motion brush |
| Video (hero) | **Veo 3.1 Fast** | sí (Gemini/Vertex) | $0.15/s | cinematográfico |
| Acceso unificado | **fal.ai** / Replicate | sí | por segundo | una integración, muchos modelos |
| Avatar UGC | **HeyGen Avatar IV** | sí | ~$1/min std, $4/min IV | API madura |
| Avatar UGC (realismo) | **Arcads** | plan Pro | desde ~$110/mes | repo `arcads-claude-code` para automatizar |
| Avatar + producto real | **Topview** | sí | por crédito | “creador sostiene tu SKU” |
| URL→video (alt rápida) | **Creatify** | sí | desde ~$39/mes | “product URL in, ad out” |
| Voz | **ElevenLabs** | sí | $0.05–0.10/1k chars | clon ES-CO / EN, word timestamps |
| Voz (open-source) | **Chatterbox** | self-host | ~0 | MIT, 23 idiomas |
| Música IA | **Suno Pro** | wrappers 3os | sub mensual | derechos comerciales en plan pago |
| Música licenciada | CML / Meta Sound Collection / Epidemic | — | incluida/sub | única vía segura para paid |
| Subtítulos | **WhisperX + FFmpeg** | self-host | ~0 | word-level, .ASS, burn 1-pass |
| Subtítulos (turnkey) | **Submagic / ZapCap** | sí | $0.10–0.15/min | plantillas Hormozi |
| Ensamblaje | **FFmpeg / Remotion** | self-host | ~0 | mejor unit-economics |
| Ensamblaje (cloud) | **JSON2Video** | sí | desde ~$50/mes | duración auto + TTS incluido |

### 14.2 Creadores de referencia (para calibrar el estilo)

Savannah Sanchez (hooks DTC, la más citada), Alex Hormozi (Hook-Retain-Reward), Davie Fogarty (test en volumen), Nathan Nazareth (wow-product first), AC Hampton (native content, Ice-Breaking testing), Ecom King / Hayden Bowles (AI UGC), Nick Theriot, Ben Heath (Meta ads), Motion/Dara Denney (creative analytics). CapCut es el editor de facto (auto-captions, TTS, keyframes, beat-sync, efectos trending).

### 14.3 Fuentes (investigación jul-2026)

**Edición / ritmo / captions / specs:**
- OpusClip — Shorts length & retention · TikTok caption best practices · auto zoom tools (opus.pro/blog)
- Submagic / Ascynd — Hormozi captions
- StudioBinder — types of editing transitions · Cloudinary — Ken Burns effect
- Postiz / Stackinfluence — TikTok sizes & safe zones · Superscale / Get-Ryze — Meta ad sizes & safe zones
- Glued.me / Billo / Sovran — hook rate vs hold rate · AAApresets — LUTs mobile 2026

**Hooks / guiones / anatomía / benchmarks:**
- UGC Humans — UGC hook formulas · Motion — creative metrics & UGC scripts · Zeely — TikTok hooks
- WinAds — UGC script structure · Curtis Howland — $100M Meta ads framework · Copy Posse / Thrivethemes — VSL
- Billo / Sovran / AdLibrary — hook/hold benchmarks · easysellapp / Kiki LATAM — COD Colombia/Ecuador

**Generación IA (pipeline):**
- HeyGen API pricing & realistic UGC guide · Arcads vs Creatify (EzUGC) · `github.com/krusemediallc/arcads-claude-code` · Topview OpenAPI
- InVideo / Imagine.art / Lushbinary — Kling vs Sora vs Veo vs Runway vs Seedance · fal.ai & Replicate model docs · DevTk — AI video pricing 2026
- Google Devs — Veo 3.1 pricing · Google blog — Nano Banana Pro · ElevenLabs API pricing · Deepgram — TTS alternatives
- Dynamoi / Billboard — Suno/Udio licensing · Submagic API docs · WhisperX guide · Samautomation / Plainly — video render APIs
- Digital Synopsis / Notch / Atlabs — evitar el “AI look”

**Música / sonido / creadores:**
- TikAdSuite — best music for TikTok ads (BPM, drops, CML) · ProTunesOne / TierMusic — Meta music licensing 2025 · Uppbeat — SFX
- Descript / OpenClip / MightyVO — audio levels & ducking · Motion — best DTC Meta ad hooks 2025 (Savannah Sanchez)
- CapCut — auto-caption & AI features · Predictive Marketing / Optimal / Zeely / Spocket — dropshipping video ad frameworks

**Conocimiento interno de Juan (máxima prioridad, calibrado con sus ventas reales):**
- `viral-creative-coach` → playbook-2026, swipe-file (43 virales reales), visual-hooks, guiones-que-convierten
- `marketing-viral-pro` → 12 verdades, frameworks UGC/VSL, Meta Ads 2026, benchmarks, operación CO/EC/Dropi

---

*Fin del manual. Revisar trimestralmente: los modelos de video IA, precios y APIs cambian rápido (próxima rev sugerida: oct-2026). El conocimiento creativo (Partes 1, 3, 4) es estable; el stack (Partes 5, 14) es volátil.*




