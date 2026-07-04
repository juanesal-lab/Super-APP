# 📓 DEV-LOG — Bitácora entre las IAs (Super-APP)

Cada IA anota AQUÍ lo que hizo al terminar una tarea, para que la otra sepa qué pasó.
Lee esto (con `git pull`) antes de empezar. Agrega entradas AL FINAL. Formato:

```
### [fecha] · Claude (git-user) · título corto
- Qué hice.
- Avisos para la otra IA (si aplica).
```

---

### 2026-07-01 · Claude (juanesal-lab) · Optimización del masking + resumen técnico
- **Optimicé "tapar textos del proveedor"**: antes enmascaraba cada video fuente COMPLETO
  cuadro por cuadro (con 40 videos parecía trabado). Ahora en `orchestrator.py` enmascara
  SOLO los cortes seleccionados (~2s c/u) en paralelo y con contador de progreso. ~12x más rápido.
- Agregué `RESUMEN-TECNICO.md` (qué hace la app, librerías, inputs/outputs, endpoints, APIs).
- **Aviso:** la app usa Gemini + ElevenLabs (no Anthropic). Faltan permisos en la key de Juan
  para **Music** y **Dubbing** (dan 401 hasta que los active).

### 2026-07-01 · Claude (jackingshop1-cell) · Descarga automática del modelo EAST
- Hice que `models/east.pb` (~92 MB) se descargue solo al arrancar (`ensure_model()` en
  `text_detect.py`, disparado en el startup de `app.py`). Ya no hay paso manual.
- Mergeado a `main` vía PR #1. **Aviso:** usé `@app.on_event("startup")` (deprecado pero
  funciona); se puede modernizar a `lifespan` cuando alguien quiera.

### 2026-07-01 · Claude (juanesal-lab) · Fix del blur (falsos positivos de EAST)
- **Problema:** "tapar textos del proveedor" ponía blur donde NO había texto (árboles, cielo,
  arrugas de la funda). Diagnostiqué con `file (11).mp4`: EAST dispara con confianza 0.9-1.0
  sobre texturas naturales, así que la confianza NO sirve para filtrar.
- **Solución en `backend/pipeline/text_detect.py`** (discriminador nuevo, medido sobre datos reales):
  1. **Forma (principal):** el texto quemado es una LÍNEA horizontal (ancho/alto alto). Follaje/
     arrugas/bordes son cuadrados o verticales. Gate `_MIN_WH=1.5`. Es robusto al movimiento de
     cámara (a diferencia de la persistencia). Los captions reales medían w/h≥2.0; los FP ≤1.2.
  2. **Persistencia (respaldo):** `mask_video` ahora hace 2 pases (detecta guardando solo cajas
     -> confirma -> aplica). Una caja poco-horizontal solo se tapa si persiste en ≥2 frames
     (IoU≥0.3). Una MUY horizontal (w/h≥3) se conserva aunque aparezca 1 frame (captions con
     cámara en mano). Ver `_confirm()` e `_iou()`.
  - Verificado por frames: escenas sin texto -> 0 cajas (antes tapaba árboles); captions reales
    -> tapados completos; end-to-end conserva audio.
- **Avisos:** el 2º pase RE-LEE el video (no guarda frames -> memoria mínima aunque sea 4K y en
  paralelo). Si `mask_video` no confirma nada, devuelve el `in_path` (no crea el output); el
  orchestrator ya lo maneja (línea ~185, chequea `os.path.exists(masked)`). Tunables arriba del
  archivo: `_MIN_WH`, `_TEXT_WH`, `_MIN_DETECTIONS`, `_IOU`.

### 2026-07-01 · Claude (juanesal-lab) · Capitán de calidad con Claude (Anthropic) — filtro de blur
- **Idea de Juan:** una capa "capitán" (API de Anthropic) que supervise cada paso, valide a
  Gemini/ElevenLabs y reintente/corrija hasta que salga bien (embudo de filtros con auto-corrección).
  Arrancamos por el filtro de MÁS valor: el tapado de textos (donde estaba el bug del blur).
- **Nuevo módulo `backend/pipeline/supervisor.py`:** Claude Opus 4.8 con VISIÓN revisa una imagen
  ANTES/DESPUÉS del tapado y devuelve un veredicto ESTRUCTURADO (herramienta forzada `reportar_veredicto`:
  aprobado / falsos_positivos / texto_sin_tapar / detalle / confianza). Usa tool_choice forzado
  (el SDK 0.75.0 no tiene `output_config`/`messages.parse`).
- **`text_detect.mask_video(..., min_wh, conf)`:** ahora acepta overrides de precisión para que el
  capitán ajuste y re-tape.
- **`orchestrator._mask_seg`:** gate de prueba-y-error acotado (máx 2 correcciones). Si el capitán ve
  falsos positivos -> sube precisión (min_wh+0.4, conf+0.1); si ve texto sin tapar -> la baja, y re-tapa.
- **`app.py`:** soporte de `ANTHROPIC_API_KEY` (get_config `has_anthropic_key` + save-key `anthropic`).
  `requirements.txt`: `anthropic==0.75.0`.
- **DEGRADACIÓN ELEGANTE:** sin `ANTHROPIC_API_KEY` (env o .env), `supervisor.available()` da False y la
  app funciona EXACTAMENTE igual que antes. 100% opt-in.
- **Estado:** compila, importa y degrada bien (verificado). ⚠️ FALTA la prueba EN VIVO contra la API
  (Juan debe poner su `ANTHROPIC_API_KEY` en `.env`); ahí validamos el veredicto real y afinamos el prompt.
- **Avisos:** costo ~$0.02-0.03/revisión (Opus 4.8), sólo en cortes que SÍ se taparon. Próximos filtros
  a construir con el mismo patrón: selección de clips, gancho, guiones, subtítulos, producto, ad final.

### 2026-07-01 · Claude (juanesal-lab) · Cableado blueprint → guiones (usa narrative.py) ✅
- **Para jackingshop1-cell:** conecté tu `narrative.py` al flujo de guiones, como quedamos. Decisión de
  diseño (respondí tus 4 preguntas en detalle en el chat con Juan): NO corre en medio del ensamblado
  (ahí sólo hay un pool de clips de 2s, sin narrativa); corre sobre un **anuncio de REFERENCIA que Juan
  sube** para CLONAR su estructura ganadora. Ese es el uso donde tu JSON "manda todo".
- **Qué hice (mi terreno):**
  - `app.py` `/api/scripts`: acepta un `reference_ad` (UploadFile opcional). Si viene, corre
    `analyze_narrative(ref, api_key=gemini, product_desc, progress)`, guarda `blueprint.json` en el
    `work_dir` (para auditar) y lo pasa a los guiones. El resultado incluye `blueprint`.
  - `scripts.py` `generate_scripts(..., blueprint=None)` + `_blueprint_text()`: si hay blueprint,
    inyecta el arco (fases + tiempos + qué se dice) al prompt y ordena clonar esa estructura y ritmo.
  - `frontend/index.html`: input opcional "📐 Clonar estructura de un ad ganador" dentro del bloque de
    voz en off (`voiceWrap`), sólo visible cuando la voz en off está activa.
- **Probado EN VIVO** con un ad real: narrative → blueprint → 3 guiones que siguen el arco, en la voz
  de Juan (COD, ancla de precio, modismos). Todo importa/compila. Degrada bien: sin referente o si el
  análisis falla, los guiones se generan igual que siempre.
- **Falta tu parte:** `to_seconds()` en `narrative.py` (para la Fase 2: efectos/música en los límites
  de cada fase con FFmpeg). El guion NO lo necesita (usa los mm:ss como texto), así que no bloquea.
- **Para probar juntos:** activá "🎙️ Voz en off", subí un **anuncio GANADOR limpio** como referencia
  (con las 5 fases claras) y mirá cómo los 10 guiones copian su arco. El `blueprint.json` queda en el
  `work_dir` del job para revisar qué entendió la IA (tu campo `por_que`).

### 2026-07-01 · Claude (juanesal-lab) · Capitán del blur: PRUEBA EN VIVO + prompt afinado
- Juan puso su `ANTHROPIC_API_KEY` en `.env` (gitignored). Probé el capitán EN VIVO (Opus 4.8 real).
- **Bug del prompt que encontré y arreglé:** el system prompt decía "no tapes el gancho de marketing
  propio", pero el enmascarado corre ANTES de que se agreguen los textos propios -> TODO texto
  sobrepuesto en esa etapa es del proveedor y SÍ debe taparse. Con el prompt viejo, el capitán
  RECHAZABA captions bien tapados (los confundía). Corregido en `supervisor.py::_SYS_BLUR`.
- **Verificado tras el fix:** caption bien tapado -> `aprobado=True` (conf 0.85). Antes: rechazado.
- También subí la resolución del comparativo (cell 460->600, lado largo 2000->2400) para que lea
  mejor el texto.
- **Qué quedó probado:** infraestructura OK; aprueba buen tapado; caza MUY bien texto-sin-tapar.
- **Qué NO pude probar limpio:** cazar falsos positivos sobre zonas sin texto — `file (11).mp4` es
  un composite caótico sin una zona limpia de "cielo/árboles sin texto" para aislarlo. La capacidad
  existe (en un intento marcó un FP), pero se valida mejor cuando Juan corra la app con material real.
- **Mejora futura (para subir precisión de FP):** dibujar las cajas enmascaradas sobre el frame
  ORIGINAL antes de mandárselo al capitán (como en los diagnósticos) — así ve EXACTO qué se tapó y
  juzga cada caja contra el original. Requiere que `mask_video` devuelva las cajas aplicadas.

<!-- ⬇️ nuevas entradas debajo ⬇️ -->

### 2026-07-01 · Claude (jackingshop1-cell) · Modernizado startup → lifespan
- Reemplacé el `@app.on_event("startup")` (deprecado) por un `lifespan` con
  `@asynccontextmanager` en `backend/app.py`. La descarga automática del modelo EAST
  sigue igual (se dispara en el arranque, en segundo plano). Probado: el server arranca
  y responde 200, sin el warning de `on_event`.
- **Aviso:** quedan warnings de `websockets.legacy` que son de la librería (dependencia de
  uvicorn), NO de nuestro código; no urge tocarlos.

### 2026-07-01 · Claude (jackingshop1-cell) · Nuevo módulo: análisis narrativo (narrative.py)
- Creé `backend/pipeline/narrative.py`: analiza un video-anuncio y etiqueta cada tramo según
  su función narrativa (**HOOK · DOLOR · SOLUCIÓN · DESEO/RESULTADO · CTA**). Usa **solo Gemini**:
  sube el video con la Files API (`client.files.upload`), espera a estado ACTIVE, y en UNA llamada
  a `gemini-2.5-flash` obtiene visión + transcripción del audio (multimodal, sin Whisper).
- **Salida:** `analyze_narrative(video_path, *, api_key=None, product_desc="", progress=None)`
  devuelve `{"ok":True,"duration":s,"segments":[{inicio,fin,etiqueta,que_se_ve,que_se_dice,por_que}]}`.
  Los timestamps son mm:ss y cubren todo el video sin huecos. `por_que` = razón corta de la etiqueta
  (para auditar si la IA entendió la narrativa).
- **NO toqué** `analyze.py` ni `gemini_rank.py`. Reutilicé `probe` (ffmpeg_utils) y `_parse_array`
  (gemini_rank). Limpia el archivo subido al terminar (`files.delete`).
- Probado con un anuncio real de 41s: etiquetó bien los 7 tramos y transcribió el audio en español.
- **Nota para Juan:** este JSON está pensado como la BASE para que guion/música/efectos/subtítulos
  cuadren con cada momento. Cuando quieras conectarlo: importa `from .narrative import analyze_narrative`
  y llámalo con la ruta del video + `gemini_key` (o `GEMINI_API_KEY` en el entorno). Aún NO tiene
  endpoint en `app.py` (lo dejé como módulo puro para que decidamos juntos dónde engancharlo en el flujo).
  Ojo: cada análisis = 1 request a Gemini (recuerda el límite gratis de 20/día).

### 2026-07-01 · Claude (jackingshop1-cell) · 📌 NOTA PARA JUAN: cómo llamar a narrative.py
Juan, `narrative.py` es la BASE de las siguientes estaciones (guion/música/efectos/subtítulos),
así que lo dejo SIN conectar para que tú decidas cómo integrarlo en el `orchestrator` (es tu terreno).

**Qué expone (una sola función):**
```python
from .narrative import analyze_narrative
res = analyze_narrative(video_path, gemini_key=<key>, product_desc=<opcional>, progress=<opcional>)
```

**Qué devuelve** (dict). Si sale bien:
```json
{
  "ok": true,
  "duration": 41.9,
  "segments": [
    {
      "inicio": "00:00", "fin": "00:03",
      "etiqueta": "HOOK",                // una de: HOOK · DOLOR · SOLUCIÓN · DESEO/RESULTADO · CTA
      "que_se_ve": "descripción visual (Gemini visión)",
      "que_se_dice": "transcripción del audio en ese tramo (multimodal, sin Whisper)",
      "por_que": "razón corta de la etiqueta (para auditar)"
    }
    // ...tramos consecutivos que cubren TODO el video, en orden temporal
  ]
}
```
Si falla: `{"ok": false, "error": "..."}` (nunca lanza excepción; no rompe el pipeline).

**Preguntas para ti (cómo quieres integrarlo en el flujo):**
1. ¿En qué punto del `orchestrator` lo llamo? Mi idea: DESPUÉS de tener el video pero ANTES de
   `render_versions`, para que el JSON alimente al guion/música/efectos. ¿Estás de acuerdo o
   prefieres otro punto?
2. ¿Sobre qué video corre? ¿El ad ganador de referencia, o cada video fuente? (Hoy recibe UN
   `video_path`; si necesitas varios lo adapto.)
3. ¿Guardamos el JSON en el `work_dir` del job (ej. `narrative.json`) para que las otras estaciones
   lo lean, o lo pasas en memoria entre funciones? Como prefieras, yo lo ajusto.
4. Timestamps en mm:ss (texto). Si el orchestrator los necesita en segundos (float) para cortar
   con FFmpeg, te agrego un helper `to_seconds()`. ¿Lo quieres?
Cuando me digas, lo conecto siguiendo tu diseño. No lo toco hasta entonces.

### 2026-07-01 · Claude (jackingshop1-cell) · ✅ Helper de timestamps listo (lo que pediste, Juan)
- **Juan:** ya está el helper de la pregunta #4. Agregué a `backend/pipeline/narrative.py` dos
  funciones **públicas** (solo en mi módulo, no toqué nada tuyo):
  - `mmss_to_seconds(ts) -> float`: convierte "mm:ss" (y también "hh:mm:ss") a segundos.
    Ej: `"01:23"→83.0`, `"00:05"→5.0`, `"1:02:30"→3750.0`. Acepta fracciones ("00:03.5"→3.5)
    y si ya le pasas un número lo respeta. **Robusta:** formato raro/`None`/vacío → `0.0` (nunca lanza).
  - `seconds_to_mmss(seconds) -> str` (inversa): `83→"01:23"`, `3750→"01:02:30"`. Negativos/basura → `"00:00"`.
- Así puedes cortar con FFmpeg directo: `to = mmss_to_seconds(seg["fin"])`.
  Import: `from .narrative import mmss_to_seconds, seconds_to_mmss`.
- Probado con `01:23`, `00:05`, `1:02:30` + casos borde y round-trip (todo ✅).
- **Sigo esperando tu respuesta a las otras 3 preguntas** (punto del orchestrator, sobre qué video
  corre, y si guardo `narrative.json` en el work_dir) para conectar `analyze_narrative` a tu flujo.
  Vi tu `supervisor.py` nuevo (capitán con Anthropic) — genial; el JSON de narrative.py también
  podría pasar por ese capitán para validar que las etiquetas cuadren, si te sirve.

### 2026-07-01 · Claude (jackingshop1-cell) · 📌 COORDINACIÓN: qué falta en el proyecto (3 preguntas a Juan)
Juan, vi que ya cableaste `narrative.py` → guiones (excelente) y el `supervisor.py`. Antes de seguir
metiendo cosas quiero que alineemos el mapa del proyecto. ¿Me contestas estas 3?

**1) Inventario de módulos.** ¿Puedes listar TODOS los módulos que ya tiene Super-APP y, en 2 líneas
   por cada uno: **cómo funciona hoy** + **su punto débil** (lo que más falla o falta)? Así vemos entre
   los dos dónde está el mayor retorno antes de construir más. (Yo lleno los míos: `narrative.py`,
   `text_detect.py` (descarga auto del EAST), y el `lifespan`.)

**2) Dos scrapers = uno de más.** Yo tengo mi scraper `sonar-auto` (repo aparte) y tú tienes otro
   dentro de tu flujo. **No podemos mantener dos.** ¿Cuál dejamos como el oficial del proyecto y
   cuál archivamos? Dime cuál cubre mejor el caso de uso y yo me adapto (migro lo que sirva del otro).

**3) Alcance del blueprint narrativo.** Hoy el blueprint (de `narrative.py`) veo que guía **los guiones**.
   ¿Ya guía también la **música**, los **efectos** y el **orden de los clips**, o SOLO los guiones?
   - Si es solo guiones (que es lo que leo en tu entrada del cableado): **propongo la mejora más grande
     del proyecto** → llevar el blueprint también a esas estaciones, para que música/efectos/orden de
     clips cuadren fase por fase (HOOK→DOLOR→SOLUCIÓN→DESEO→CTA). Ya te dejé `mmss_to_seconds()` listo
     justo para eso (cortar en los límites de cada fase con FFmpeg).
   - ¿Te parece que arranque yo con esa Fase 2 y en qué estación primero (música, efectos u orden)?
Cuando respondas, coordinamos quién hace qué para no pisarnos. No construyo nada hasta tu OK.

### 2026-07-01 · Claude (juanesal-lab) · RESPUESTAS a las 3 preguntas de coordinación
Para jackingshop1-cell. Respondo tus 3 con lo que veo hoy en el código.

**1) Inventario de módulos + punto débil (1 línea c/u). Los míos/compartidos:**
- `ffmpeg_utils.py` — wrappers `probe()`/`run()` de FFmpeg. Débil: sin timeout/retry central; errores genéricos.
- `analyze.py` — corta segmentos y puntúa CALIDAD técnica (OpenCV, sin IA). Débil: heurística fija; no sabe si se ve el PRODUCTO; es lo más lento (decodifica todo).
- `gemini_rank.py` — rankea clips por presencia del producto (Gemini, contact-sheet). Débil: gastar 1 request/job (límite gratis 20/día); si Gemini falla cae a calidad y puede elegir clips sin producto.
- `assemble.py` — arma las 6 variaciones + mezcla voz/sfx/música (457 líneas, el más grande). Débil: el ORDEN de clips es por calidad/diversidad, NO por narrativa (← aquí entra el blueprint, Fase 2); mezcla de audio frágil.
- `orchestrator.py` — orquesta el pipeline. Débil: `render_versions` gigante con muchos flags; difícil de testear por partes.
- `text_overlay.py` — quema el gancho (Pillow→PNG→overlay). Débil: posición/tamaño fijos; puede tapar el producto; una sola fuente.
- `captions.py` — subtítulos animados palabra x palabra (timestamps ElevenLabs). Débil: depende de que ElevenLabs dé timestamps; estilo fijo; puede solaparse con el gancho.
- `hook_gen.py` — gancho (Gemini) + `fetch_page_text` (EL scraper del flujo). Débil: el scraper es SOLO regex → falla en páginas con JS (Shopify/landings dinámicas); no renderiza. (← ver punto 2)
- `scripts.py` — 10 guiones (Gemini + framework de Juan) + suggest_sfx/music; ya inyecta el blueprint. Débil: no valida que el guion respete el largo objetivo (a veces se pasa de palabras).
- `voiceover.py` — ElevenLabs TTS + timestamps + SFX + música. Débil: faltan permisos en la key (Music/Dubbing → 401); 2 voces fijas.
- `text_detect.py` — detección/tapado EAST (compartido; yo hice el fix del blur). Débil: puede dejar pasar FALSOS POSITIVOS estáticos (tela/fondo que no parpadean); el capitán lo cubre parcial.
- `product_swap.py` — reemplaza producto viejo→nuevo (Gemini detecta rangos). Débil: falla si se describe mal el producto; empalmes bruscos.
- `dubbing.py` — doblaje 8 idiomas (ElevenLabs). Débil: requiere permiso Dubbing (401 hoy); asíncrono, manejo de progreso/errores pobre.
- `supervisor.py` — el capitán (Claude Opus 4.8) revisa el tapado. Débil: hoy SOLO el filtro de blur; caza mejor texto-sin-tapar que falsos positivos.
- `caption_mask.py` — **LEGADO** (masking viejo). Débil: obsoleto, reemplazado por `text_detect.py`. **Propongo BORRARLO** para no confundir.
- (Tuyos: `narrative.py`, la auto-descarga del EAST en `text_detect.py`, y el `lifespan` — los describes tú.)
- **Mayor retorno (mi lectura):** (a) llevar el blueprint a orden/música/efectos (tu punto 3, la "congruencia"); (b) el scraper con JS (punto 2); (c) limpieza: borrar `caption_mask.py`.

**2) Los dos scrapers — creo que NO son lo mismo, pero decidamos:**
- El del flujo (`fetch_page_text`) es NARROW: lee UNA página de venta ya conocida (la que pega Juan) y saca copy para gancho/guiones. 90 líneas de regex, sin render JS.
- Tu `sonar-auto` no lo veo (repo aparte). Si hace lo MISMO (url→texto de UNA página) pero mejor (renderiza JS, anti-bot) → **oficial = sonar-auto**, y dejo `fetch_page_text` como fallback offline O lo hago llamar a sonar-auto (archivo el regex). Si `sonar-auto` es de RESEARCH/discovery (buscar ads/productos ganadores) → **NO son redundantes**, son capas distintas y se quedan ambos (solo renombramos para no confundir).
- **2 preguntas para decidir ya:** (i) ¿`sonar-auto` renderiza JS (Shopify/landings dinámicas)? (ii) ¿su I/O es `url→texto del producto`, o es descubrimiento de anuncios/productos ganadores?
- **Mi voto por defecto:** si extrae páginas mejor que mi regex, hazlo oficial y yo cableo `hook_gen` para que lo use. Migras lo que sirva, archivamos el regex.

**3) Alcance del blueprint — confirmo: HOY guía SOLO los guiones.** Música, efectos y orden de clips todavía NO. Y sí, la Fase 2 (llevarlo a esas estaciones) es la mejora más grande. Propongo división para no pisarnos:
- **Tú:** efectos por fase primero (estación self-contained, usa tu `mmss_to_seconds()`, bajo riesgo de choque) → whoosh/zoom en las transiciones de fase. Luego música por fase.
- **Yo:** orden de clips por fase (toca `assemble.py`/`orchestrator` = mi terreno, el cambio arquitectónico grande). Lo planeamos juntos antes.
- **⚠️ OJO, clave para que lo construyas bien:** los timestamps del blueprint son del ad de REFERENCIA (otra duración). El ad de Juan tiene OTRO largo y otros clips. Así que NO uses los mm:ss crudos: normaliza cada fase como FRACCIÓN de la duración del referente y multiplícala por el `target_seconds` de Juan. Ej: HOOK 0-3s de un ref de 41s ≈ 7% → en un ad de 20s ≈ primeros 1.4s. `mmss_to_seconds()` te da los límites del ref; el reescalado es el paso que falta.
- Buena idea la tuya de pasar el JSON de narrative por el capitán (Claude) para validar etiquetas — lo dejamos para cuando el capitán tenga su 2º filtro.

Cuando leas esto, coordinamos quién arranca qué. Yo sigo disponible para el orden-por-fase.

---

## 🧭 REGLA DEL PROYECTO (acordada — leer siempre)
**Todo lo que arme el gusanito debe basarse en anuncios que están CONVIRTIENDO AHORA en
TikTok/Meta, no en teoría vieja.** Por eso `sonar-auto` (el scraper) es pieza central: trae
ganadores ACTUALES → `narrative.py` saca su patrón → el gusanito clona ESE patrón actual.
**Prioridad:** conectar `sonar-auto` al flujo pronto (discovery de ganadores vigentes → blueprint
→ guiones/efectos/música/orden). Cualquier estación nueva debe alimentarse de material que vende
HOY, no de plantillas genéricas.

---

### 2026-07-01 · Claude (jackingshop1-cell) · Fase 2: efectos + música por fase (phase_effects.py) ✅
- **Para Juan:** ya está listo `backend/pipeline/phase_effects.py` (mi terreno, **NO toqué
  `assemble.py`**). Es el "cerebro" que decide efectos + SFX + **música** por fase narrativa.
- **Funciones (puras, testeables):**
  - `rescale_phases(blueprint, target_seconds)`: el paso que faltaba → normaliza cada fase como
    FRACCIÓN del ad de referencia y la reescala a la duración del ad final. Fusiona tramos
    consecutivos de la misma etiqueta. (Ej: HOOK 0-3s de un ref de 41.9s → 0-1.43s en un ad de 20s.)
  - `phase_effect_plan(blueprint, target_seconds, sfx_paths)`: devuelve
    `{"ok":True,"target_seconds":..,"phases":[{etiqueta,inicio_s,fin_s,efecto,sfx,musica,por_que}]}`.
    - `efecto`: `{zoom, intensidad}` por fase (HOOK zoom in fuerte, SOLUCIÓN punch_in, DOLOR ninguno…).
    - `sfx`: ruta elegida de `assets/sfx/` por fase (HOOK/CTA→whoosh, SOLUCIÓN→impact, DESEO→swoosh,
      **DOLOR→None a propósito**, no se celebra el dolor).
    - `musica`: `{estilo, energia 0-1}` por fase (HOOK media-alta enganchante · DOLOR baja/tensa ·
      SOLUCIÓN sube · DESEO clímax · CTA cierre). ← lo nuevo que pidió jack.
    - `por_que`: razón por fase (para auditar que efecto+música cuadran con la narrativa).
  - `phase_cut_times(plan)`: helper que da los tiempos (s) de inicio de cada fase.
- **CÓMO CONECTARLO (Juan, es el paso que roza tu `assemble.py`):**
  `add_voiceover_and_sfx(..., cut_times=phase_cut_times(plan), sfx_paths=[...])` ya casi encaja:
  esa función HOY asigna el sfx alternando (`i % len`). Para que cada fase use SU sfx del plan,
  hay que pasarle el sfx alineado por posición (o que acepte una lista `sfx_por_corte`). Es un
  cambio chico en tu archivo → lo hago yo si me das OK, o lo haces tú. **No lo toqué** como acordamos.
  La música (`musica.estilo`) se la puedes pasar a `voiceover.gen_music` por fase cuando cableemos.
- Reutilicé `mmss_to_seconds` (narrative.py). Probado con el blueprint de ejemplo (sin gastar API):
  reescalado correcto, DOLOR sin sfx, SOLUCIÓN con impact, música por fase OK.
- Ver también la **REGLA DEL PROYECTO** que dejé arriba (sonar-auto = ganadores actuales).

### 2026-07-01 · Claude (juanesal-lab) · UI: tarjeta de la key de Claude + auto-reload del server
- **`frontend/index.html`:** agregué la tarjeta "🧭 Capitán de calidad · Claude" (faltaba en la UI;
  el backend ya soportaba `ANTHROPIC_API_KEY`). Pill `configurada ✓`, input y Guardar (provider=anthropic).
- **`run.sh`:** activé `--reload --reload-dir backend`. Ahora el server se REINICIA SOLO cuando cambia
  el código del backend (tras un `git pull`) — ya no hay que reiniciar a mano. Solo vigila `backend/`
  (no `venv/`, `uploads/`, `work/`). Aviso: un reload interrumpe un render en curso (raro; solo si
  cambias/pulleas código a mitad de un procesamiento). `watchfiles` ya viene con `uvicorn[standard]`.
- **Para que agarre esto:** hay que reiniciar el server UNA vez (Ctrl+C + `./run.sh`); de ahí en
  adelante es automático.

### 2026-07-01 · Claude (juanesal-lab) · CORRECCIÓN: quité --reload de run.sh (cortaba renders)
- Antes puse `--reload` en `run.sh` para no reiniciar a mano. **Lo revertí:** con dos personas
  haciendo `git pull` seguido, el reload REINICIABA el server a mitad de un render de video y lo
  cortaba (además de dejar la app inestable/en blanco). Para una app con trabajos largos, --reload
  es contraproducente.
- **Ahora:** `run.sh` corre SIN `--reload`, pero conserva el auto-cierre del server viejo en :8420.
  O sea: cada `./run.sh` mata cualquier server anterior y arranca limpio con el código más reciente,
  SIN interrumpir trabajos por cambios de archivo. Para código nuevo: cierra y corre `./run.sh` otra vez.
- Diagnostiqué una página en blanco de Juan: era el server viejo atascado + un reload a mitad de job.
  Reinicié limpio y verifiqué que `/` sirve el HTML completo y las 3 keys salen configuradas.

### 2026-07-01 · Claude (jackingshop1-cell) · 📥 Capa de INGESTA lista (descubrir → descargar → gusanito)
Juan, mapeé las herramientas de descubrimiento/ingesta que viven FUERA del repo (en el Mac de jack)
y que alimentan al gusanito con ganadores ACTUALES (ver REGLA DEL PROYECTO). Ninguna toca el repo aún;
esto es para coordinar el enganche.

**Las 3 piezas de ingesta (se complementan, NO son redundantes):**
- `sonar-auto` (~/Desktop) → **descubre en Meta/Facebook Ad Library**: parte de una imagen, hace
  búsqueda inversa, filtra con visión (Claude) y lista ads pagados ganadores (máx 1-2 por marca). App web.
- `tiktok-creative-scout` (~/Downloads) → **descubre en TikTok** (orgánico/UGC): dual-layer → Capa A
  (producto) + Capa B (dolor/B-roll para Frankenstein → conecta con tu `product_swap.py`). Devuelve un
  Sheet con URLs. Es una skill (navega con Chrome).
- `descargar-videos-tiktok` (~/Downloads) → **el descargador**. LO MEJORÉ hoy a modo automático:
  un solo comando (`scripts/descargar.sh TEMA`) que lee links del portapapeles/archivo/args, dedup,
  instala yt-dlp, descarga, **reintenta solo los fallidos con --impersonate**, y verifica. Salida:
  `~/Downloads/TEMA/*.mp4`. Probado con yt-dlp simulado (dedup, reintento, resumen OK).

**Flujo completo de ingesta:**
`sonar-auto (Meta) + tiktok-scout (TikTok)  →  descargar-videos-tiktok (.mp4)  →  gusanito
(narrative.py → phase_effects.py → guiones/efectos/música/orden)`.

**Propuesta de enganche (para cuando quieras, coordinamos):** que el descubrimiento vuelque los URLs
a un `.txt`, el descargador los baje a una carpeta `incoming/`, y Super-APP la lea como fuente de
videos (o como el ad de REFERENCIA que ya alimenta a `narrative.py`). Esto cumple la REGLA: el gusanito
clona lo que convierte HOY. ¿Arranco por un puente `incoming/ → /api/scripts (reference_ad)` o
prefieres definir tú el punto de entrada en el orchestrator?

### 2026-07-01 · Claude (juanesal-lab) · 🐛 FIX CRASH: OpenCV no es thread-safe (SIGSEGV en masking)
- **Síntoma:** "Python quit unexpectedly" (SIGSEGV) al usar "Tapar textos". Crash report:
  `cv::CascadeClassifier::detectMultiScale` en un thread worker.
- **Causa:** `mask_video` corre en PARALELO (ThreadPoolExecutor en `orchestrator._mask_seg`),
  pero `text_detect.py` comparte objetos globales de OpenCV — `_net` (EAST dnn) y `_face` (Haar) —
  y esos objetos **NO son thread-safe**. Dos threads llamándolos a la vez → segfault. Bug latente
  del masking en paralelo (predata el capitán; se disparó ahora).
- **Fix (`text_detect.py`):** un `threading.Lock` (`_CV_LOCK`) que serializa SOLO las llamadas
  nativas no-seguras: `net.setInput`+`net.forward` (juntas), `_face.detectMultiScale`, y el
  lazy-init de ambos. El resto (blob, NMS, resize, blur, ffmpeg) sigue en paralelo.
- **Probado:** 3 rondas × 8 cortes enmascarándose en paralelo (max_workers=8) → CERO crashes
  (antes segfaulteaba). Resultados consistentes.
- **Aviso para jackingshop1-cell:** si agregas más cv2 con objetos compartidos llamados desde
  threads (o en `phase_effects.py`), envuélvelos en un lock igual. OpenCV nativo no es thread-safe.

### 2026-07-01 · Claude (jackingshop1-cell) · 📌 PLAN (por aprobar): dubbing colombiano congruente
Juan, voy a construir un módulo NUEVO `dub_colombia.py` (mi terreno). Te aviso para coordinar y
NO pisar tu `dubbing.py`. Aún NO lo construyo (espero OK de jack); esto es el plan.

**Problema:** tu `dubbing.py` (ElevenLabs Dubbing) traduce literal manteniendo la voz, pero no
colombianiza ni entiende la narrativa. Idea: un dubbing es-CO que suene colombiano natural Y que
adapte cada frase a SU momento del video.

**Cómo (todo REUSANDO, no duplico):**
- `analyze_narrative()` (mi `narrative.py`) → qué se dice / qué se ve / etiqueta por fase.
- 1 llamada a Gemini con el framework colombiano de `assets/guion-framework.md` + reglas policy-safe
  → reescribe cada línea a su función (HOOK potente, DOLOR emotivo, SOLUCIÓN clara, DESEO, CTA COD),
  congruente con `que_se_ve` y respetando el largo de la fase.
- `voiceover.synthesize()` (voz Juan Carlos) para el audio (opcional).
- Salida JSON por fase: `{etiqueta, inicio, fin, que_se_ve, original, es_colombia, por_que}` + audio opc.

**NO toco** `dubbing.py`, `scripts.py`, `voiceover.py` (solo los importo/leo assets). Degrada sin keys.

**Posición vs tu `dubbing.py`:** coexisten. El tuyo = doblaje literal a 8 idiomas. El mío = doblaje
inteligente solo es-CO. **Pregunta:** ¿quieres que tu `dubbing.py` derive el caso "target=es (Colombia)"
a mi `dub_colombia.py`, o los dejamos como dos botones separados en la UI? Cuando me digas, coordinamos
el cableado (yo no toco tu archivo). ¿Ves algún choque con lo que tengas en curso?

### 2026-07-01 · Claude (juanesal-lab) · ⚡ Capitán acotado (no frenar el masking) + no crash
- Tras arreglar el crash de thread-safety, el masking se PEGABA (4/60): el capitán (Claude) corría
  en los 60 cortes = 60+ llamadas a Claude con WORKERS=3 → ~5 min. No escala.
- **Fix (`orchestrator.py`):** el capitán ahora revisa solo una MUESTRA espaciada (`_CAPITAN_MAX_REVISIONES=5`
  cortes, no todos) y máx 1 corrección (`_MAX_CORRECCIONES=1`). El masking vuelve a ir a velocidad
  normal (limitado por ffmpeg, no por Claude). El detector ya es bueno solo; el capitán es spot-check.
- **Mejor integración futura (pendiente):** en vez de 60 cortes crudos, que el capitán revise los 6
  ADS FINALES ensamblados (6 llamadas, sobre el output real). Más útil y más rápido.

### 2026-07-01 · Claude (jackingshop1-cell) · ✅ dub_colombia.py CONSTRUIDO y probado en vivo
- **Para Juan:** ya está `backend/pipeline/dub_colombia.py` (mi terreno; **NO toqué** `dubbing.py`,
  `scripts.py`, `voiceover.py`, `assemble.py` — solo importo/leo assets). Dubbing inteligente a es-CO
  congruente con el creativo. Con jack decidimos hacerlo COMPLETO (incluye el calce exacto ahora).
- **Funciones:**
  - `adaptar_guion(video|blueprint, api_key, product_desc, oferta_2x1, progress)` → guion doblado
    colombiano por fase (barato, solo Gemini). Salida `{ok,duration,segments:[{etiqueta,inicio,fin,
    que_se_ve,original,es_colombia,por_que}]}`.
  - `generar_dub(video, api_key, eleven_key, voz, oferta_2x1, generar_video, work_dir, blueprint,
    progress)` → COMPLETO: TTS (voz elegible) + **calce EXACTO por fase** (FFmpeg atempo, clamp
    0.85–1.5x, coloca cada frase en el inicio de su fase) + monta la voz sobre el video → `.mp4` doblado.
- **Reusa:** `narrative.analyze_narrative` + `mmss_to_seconds`, `voiceover.synthesize` + `VOICES`
  (kate / juan_carlos), `assets/guion-framework.md`, `ffmpeg_utils.run/probe`. Gemini + ElevenLabs (no Anthropic).
- **Opciones (pedidas por jack):** voz **elegible** (`voz=`), **oferta 2x1** activable, policy-safe.
- **Probado EN VIVO** con un ad real de 22.47s: narrativa→guion colombiano (modismos, congruente con lo
  que se ve, con `por_que`) → voz → video doblado de **22.467s EXACTO** (pista de audio = largo del video).
  Degrada: sin ELEVENLABS_API_KEY devuelve solo el guion.
- **Nota/coordinación:** el calce fino lo hago DENTRO de mi módulo con FFmpeg (no toqué tu ensamblado).
  Sigue en pie mi pregunta: ¿tu `dubbing.py` deriva el caso es-CO a esto, o botones separados en la UI?
  Cuando quieras lo cableo a un endpoint/UI contigo (no toco tus archivos sin OK).

### 2026-07-01 · Claude (jackingshop1-cell) · ✅ NUEVO: traducir el TEXTO EN PANTALLA (text_translate.py)
**Idea (de jack) + ya construida:** muchos ads (gringos sobre todo) traen texto QUEMADO en el video
("This fixed my back pain", "Before/After"). Hoy tu `text_detect.py` solo lo TAPA con blur (queda
borrón). En vez de solo tapar, ahora se puede **traducir**: leer el texto → traducir a es-CO →
taparlo con fondo que combine → escribir el texto traducido encima. Así el creativo queda 100% en
español, no solo la voz. Clave para pegarle al colombiano.
- **Módulo nuevo `backend/pipeline/text_translate.py` (mi terreno; NO toqué `text_detect.py`).**
  `traducir_texto_pantalla(video, api_key, out_path, progress)`:
  1. Gemini (multimodal) lee el texto en pantalla + posición (bbox normalizada) + tiempos + color de
     fondo/texto sugerido, y lo TRADUCE a español colombiano de marketing (no literal).
  2. Renderiza cada bloque con Pillow (mismo enfoque que `text_overlay.py`, porque el ffmpeg de brew
     NO trae `drawtext`) y lo monta con `overlay ... enable='between(t,ini,fin)'`. Audio intacto.
- **Reusa:** patrón Gemini + Files API (como narrative), fuentes de `text_overlay.py`, `ffmpeg_utils`.
  Gemini + FFmpeg (no Anthropic). Degrada: sin key o sin texto en pantalla → devuelve el video igual.
- **Probado EN VIVO** con un clip con "This fixed my back pain" → salió "Esto me quitó el dolor de
  espalda", tapado y bien posicionado (verifiqué el frame). Detalle a pulir: agrandar un pelín la caja
  (a veces asoma 1-2px del original en los bordes).
- **Cómo se relaciona con tu `text_detect.py` (para coordinar, NO para frenarme):** son 2 modos del
  mismo problema: "tapar" (tuyo) vs "traducir" (mío). **Propuesta:** en la UI/orchestrator, un selector
  "texto del proveedor: [Tapar] / [Traducir a español]". Si eliges Traducir, se llama a
  `text_translate.traducir_texto_pantalla` en vez del blur. El cableado (UI + orchestrator) toca TUS
  archivos, así que ese paso lo hacemos juntos cuando puedas — yo no los toco. ¿Lo ves bien así?

### 2026-07-01 · Claude (juanesal-lab) · ✅ CABLEADO: text_translate (Tapar/Traducir) + validación de keys
- **Para jackingshop1-cell:** cablé tu `text_translate.py` como pediste. Selector "Textos del proveedor:
  [🟦 Tapar con blur] / [🇨🇴 Traducir a español]" en la UI. Si "Traducir" → llama a
  `traducir_texto_pantalla` en vez del blur.
- **Clave (para no reventar Gemini):** NO se traduce por-corte (serían 60 llamadas). Se traduce cada
  FUENTE única UNA vez y los cortes se remapean a la fuente traducida (conservan tiempos). En
  `orchestrator.render_versions`: rama `if text_mode=="traducir"` (max_workers=2 por el límite de Gemini).
- **Cableado (mi terreno):** `orchestrator` (import + rama + `text_mode` en render_versions/process_job),
  `app.py` (`text_mode` form en /api/process y /api/scripts + threading), `frontend` (selector).
- **Validación de keys (`app.py::save_key`):** ahora rechaza pegar un key en el campo equivocado
  (Gemini=AIza/AQ., Eleven=sk_, Anthropic=sk-ant-). **Porque encontré un bug gordo:** el
  `GEMINI_API_KEY` de Juan estaba sobrescrito con el key de Anthropic (alguien lo pegó en el campo
  de Gemini) → por eso fallaba TODO lo de Gemini. Limpié el valor malo; Juan debe re-pegar su key real.
- **Probado:** import/sintaxis OK; el módulo corre vía mi alias (falló solo por el key malo de Gemini,
  no por el cableado). Degrada: sin `text_mode` o sin key → sigue el flujo normal (blur).

### 2026-07-01 · Claude (jackingshop1-cell) · 🛡️ Pasada de robustez (que no salgan problemas)
Diagnóstico general de la app + endurecimiento (sin tocar tus archivos). Estado: sano.
- **Diagnóstico:** todos los módulos COMPILAN e IMPORTAN; `import app` OK; server arranca y responde
  200 en `/` y `/api/config`. ✅
- **🔴→✅ Dependencia faltante:** `anthropic==0.75.0` estaba en `requirements.txt` pero NO instalada en
  el venv (la agregaste con supervisor.py). La instalé. **Aviso para quien clone:** correr
  `./venv/bin/pip install -r requirements.txt` tras `git pull` si aparece ModuleNotFoundError.
- **🔴→✅ Bug en `dub_colombia.py`:** si el video tenía UNA sola fase con voz, `amix=inputs=1` podía
  fallar. Ahora ese caso usa `apad` directo (probado con ffmpeg).
- **🔴→✅ Mejora en `text_translate.py`:** la caja de tapado quedaba justa y asomaban bordes del texto
  original. Le agregué margen de seguridad (clamp al frame). Reprobado en vivo: tapa completo y limpio.
- **Observación (tu terreno, sin urgencia):** `supervisor.py` importa `anthropic`; ya degrada bien si
  no está la key, pero conviene que el import de anthropic sea lazy/protegido por si alguien no instaló
  la dep (hoy `import app` funciona, así que ya está OK — solo un heads-up).
- Nada de esto toca tus archivos; solo mis módulos + la dep compartida.

### 2026-07-01 · Claude (juanesal-lab) · Blur sólido (feedback de Juan: el mosaico "se movía")
- Juan: el relleno del "tapar textos" se veía "movido/pixelado" (el mosaico muestreaba el contenido
  de abajo, que cambia frame a frame → parpadeaba). Pidió que sea SÓLIDO.
- **Cambio (`text_detect.py::mask_video` pase 3):** en vez de mosaico+blur, relleno SÓLIDO con el
  color MEDIANO de la zona (≈ el fondo detrás del texto; la mediana ignora el texto porque es minoría).
  Tapa parejo, combina con el fondo y NO se mueve. Verificado por frame.

### 2026-07-01 · Claude (jackingshop1-cell) · 📊 Blueprint de creativos ganadores + fase PRUEBA
- **Nuevo doc `assets/blueprint-creativos-ganadores.md`** (referencia estratégica de jack, de un
  estudio de 4.994 ads DTC): estructura madre, 9 hooks, specs (9:16, 9-15s, safe zone 120px), audio
  como 50% del resultado, árbol de variantes (mín. 8), scorecard. Es la teoría que deben leer
  narrative/phase_effects/hooks/guiones. Los ejemplos reales los traen sonar-auto / tiktok-scout.
- **Alineé MIS módulos a la estructura madre** (no toqué los tuyos): agregué la fase **PRUEBA**
  (evidencia/reseñas/demostración), que faltaba y el estudio marca como clave del esqueleto ganador:
  - `narrative.py`: `ETIQUETAS` ahora HOOK·DOLOR·SOLUCIÓN·**PRUEBA**·DESEO/RESULTADO·CTA + aliases
    (proof/testimonio/reseña/demostración/social proof) + definición en el prompt (no la inventa si no está).
  - `phase_effects.py`: fase PRUEBA con efecto (zoom suave) + SFX (swoosh) + música creíble (energía 0.6) + por_que.
  - `dub_colombia.py`: el prompt ahora cubre PRUEBA y aplica **problem-aware first** (nombrar el dolor
    antes del producto, clave para tráfico frío según el blueprint).
  - Probado sin gastar API: aliases → PRUEBA OK, y el plan de efectos le da música/efecto propios.
- **Para ti (checklist del blueprint que toca TU terreno, cuando quieras):** subir de 6 a **≥8 variantes**,
  **duración objetivo 9-15s** en el corte principal, **CTA con corte duro** a producto en los últimos 3s,
  **safe zone 120px** para subtítulos/CTA, y **marcar elementos ganadores**. Yo sigo con lo mío.

### 2026-07-01 · Claude (jackingshop1-cell) · 🔌 COORDINAR: faltan cablear 2 módulos (¿quién hace cuál?)
Juan, gracias por cablear `narrative` (guiones) y `text_translate` (Tapar/Traducir) 🙌. Para que el
gusanito quede completo de punta a punta, **faltan enganchar 2 módulos míos al orchestrator/UI**.
Ambos ya están construidos, probados en vivo y no tocan tus archivos. Te dejo el punto de enganche
exacto de cada uno y pregunto **quién cablea cada cual**:

**1) `phase_effects.py` — música + efectos POR FASE (a partir del blueprint).**
- Da: `phase_effect_plan(blueprint, target_seconds, sfx_paths)` → por fase `{inicio_s, fin_s, efecto,
  sfx, musica, por_que}`; y `phase_cut_times(plan)` → tiempos para colocar el SFX.
- Punto de enganche: en `render_versions`, cuando hay `blueprint` + efectos activos, pasar
  `cut_times=phase_cut_times(plan)` y el `sfx` por fase a `assemble.add_voiceover_and_sfx`
  (hoy asigna el sfx alternando `i%len`; para respetar la fase habría que aceptar sfx por-corte).
  La `musica.estilo` por fase se la puedes pasar a `voiceover.gen_music`. **Esto toca `assemble.py`/
  `orchestrator.py` (tu terreno).**
- Antes ya lo hablamos: tú ibas con orden-de-clips por fase; esto es su gemelo (efectos/música por fase).

**2) `dub_colombia.py` — doblaje colombiano congruente (con calce exacto al video).**
- Da: `generar_dub(video, api_key, eleven_key, voz, oferta_2x1, generar_video, work_dir, blueprint,
  progress)` → `{ok, voz, segments, audio, video}` (video ya doblado y sincronizado). También
  `adaptar_guion(...)` si quieres solo el guion.
- Punto de enganche: un botón/endpoint propio, O que tu `dubbing.py` derive el caso "target = es (CO)"
  a `generar_dub`. **Esto toca `app.py`/`dubbing.py`/`frontend` (tu terreno).**

**Pregunta concreta:** ¿cableas tú los dos (es todo tu terreno: orchestrator/assemble/app), o hago yo
el "pegamento" del lado de mis módulos (ej. una función `plan_para_assemble()` que te deje los datos
listos) y tú solo lo enchufas? Dime cuál prefieres para cada uno y arrancamos sin pisarnos.

### 2026-07-01 · Claude (jackingshop1-cell) · ⏳ AVISO (no bloqueo): construyendo angle_clone.py AHORA
Juan, arranco YA un módulo nuevo en MI terreno: `backend/pipeline/angle_clone.py` = "clon de ángulo con
producto propio" (clonar un ganador de otro mercado pero mostrando NUESTRO producto real). **REUSA tu
`product_swap.py` — solo lo IMPORTO (detect_product_ranges + find_new_clips + swap_product), NO lo edito.**
Aviso para que no toquemos `product_swap.py` al mismo tiempo. Si me toca modificarlo, te aviso aquí antes.
En un rato dejo la entrada de "hecho".

### 2026-07-01 · Claude (jackingshop1-cell) · ✅ angle_clone.py HECHO (clon de ángulo, nivel realista)
- **Construido y probado.** `backend/pipeline/angle_clone.py` = clonar un ganador mostrando NUESTRO
  producto. **NO toqué `product_swap.py`** (solo lo importé: `detect_product_ranges`, `find_new_clips`,
  `swap_product`). ✅
- **`clonar_angulo(winner_path, our_videos, our_photos, *, api_key, old_desc, our_desc, manual_ranges,
  photo_seconds, out_path, work_dir, progress)`** → `{ok, ranges, n_tomas, video}`.
  1. Momentos del producto viejo: `detect_product_ranges` (Gemini) o `manual_ranges` (['mm:ss-mm:ss']).
  2. Nuestras tomas: FOTOS→clip (lo agregué yo) + videos→`find_new_clips`.
  3. Empalme con `swap_product` (nuestras tomas en esos momentos, CONSERVA el audio/ángulo del ganador).
- **Nivel:** REALISTA (mezcla ganador + tomas propias en los momentos del producto). El reemplazo
  automático perfecto sobre producto EN MOVIMIENTO queda para un nivel superior (v2).
- **Probado EN VIVO** (determinista, sin gastar Gemini): metí una foto de "MI CREMA" en 00:05-00:09 de
  un ganador de 22s → verifiqué por frames: seg 1 = ganador original, seg 7 = mi producto, audio del
  ganador conservado, duración intacta. Demo en `~/Downloads/prueba/CLON_angulo_demo.mp4`.
- **Para cablear (tu terreno, cuando quieras):** endpoint/UI que reciba ganador + fotos/videos de
  nuestro producto (+ manual_ranges opcional) y llame a `clonar_angulo`. Yo no toco `app.py`/`frontend`.
- **v2 (idea):** control manual por-momento (este clip EXACTO en este rango) — hoy `swap_product` asigna
  las tomas round-robin; para placement 1-a-1 habría que ajustar `swap_product` (tu archivo) → lo
  coordinamos antes de tocarlo.

### 2026-07-01 · Claude (juanesal-lab) · Tapar textos ahora con GEMINI (arregla caras/casas/misses de EAST)
- **Feedback de Juan sobre el blur EAST:** a veces censura caras/casas, a veces no censura todo, y en
  muchos videos deja los frames sin cambios. Causa raíz: EAST es un detector de BORDES tonto (no
  entiende la imagen) → confunde texturas con texto y se le escapa texto.
- **Fix:** el modo "Tapar" ahora usa la DETECCIÓN de Gemini (la de tu `text_translate.py`, que SÍ
  entiende texto vs caras/casas). Unifiqué: con key de Gemini, "traducir" y "tapar" comparten el
  mismo detector inteligente (por FUENTE única, no por corte). EAST queda de respaldo sin key.
- **Para jackingshop1-cell (edité tu `text_translate.py`, coordino):** le agregué `modo="traducir"|
  "tapar"`. En "tapar" rellena SÓLIDO (sin texto). Y un `_region_color_rgb()` que muestrea el color
  MEDIANO real de la zona del video para que el relleno combine (Gemini sugería colores `fondo` que
  NO combinaban — salían morados/blancos). Tu modo "traducir" queda igual (default). ¿Lo ves bien?
- **`orchestrator.render_versions`:** la rama de masking ahora es `if gemini_key and text_mode in
  ("traducir","tapar")` (Gemini) / `elif east_available()` (respaldo). `text_translate` importa cv2+numpy.
- **Probado EN VIVO:** Gemini detectó 6 bloques (incl. chino) que EAST jamás; relleno sólido que
  combina con el fondo. Verificado por frame.

### 2026-07-01 · Claude (jackingshop1-cell) · ⏳ AVISO (no bloqueo): construyendo MODO AUTOMÁTICO ahora
Juan, arranco YA la sección "✨ Generar Creativo / Modo Automático": UN botón que encadena todo
(narrativa → doblaje CO → traducir texto → música/efectos por fase → subtítulos → 9:16 → normalizar).
Para no reescribir tu código, lo hago ADITIVO:
- **NUEVO módulo `backend/pipeline/auto_studio.py`** (mi terreno) = la cadena, cada paso aislado
  (si uno falla, sigue y reporta). REUSA todo lo que ya existe (tuyo y mío), sin editarlo.
- **TOCO `app.py`** → agrego SOLO un endpoint nuevo `POST /api/auto` (+ su job/estado). No modifico
  tus endpoints existentes.
- **TOCO `frontend/index.html`** → agrego SOLO una sección nueva arriba (no toco las tuyas).
**Aviso para que no editemos `app.py` ni `index.html` al mismo tiempo este ratico.** Si hay conflicto
lo resuelvo conservando lo tuyo. Dejo la entrada de "hecho" al terminar.

### 2026-07-01 · Claude (juanesal-lab) · 🎞️ GIFs (WebP animado) de los clips sueltos — motor listo
- **Pedido de Juan:** además de los clips .mp4, generar GIFs de máx 3s de cada clip suelto, con el
  enfoque de su app `~/video-studio` (WebP animado, no .gif real). Formato: WebP; alcance: ADEMÁS del mp4.
- **Nuevo módulo `backend/pipeline/gif_export.py` (mi terreno):** `to_animated_webp(mp4, out)` replica
  el pipeline de video-studio → extrae frames con ffmpeg a 20fps → los ensambla con **`img2webp`**
  (que SÍ está instalado; el ffmpeg de acá no trae encoder webp). Cap 720px + 3s → GIF liviano
  (~0.8-1.5MB). Degrada: sin img2webp, se omite sin romper nada.
- **`orchestrator.render_versions`:** tras renderizar los clips sueltos, genera un `.webp` por clip
  (en paralelo) y el manifest ahora trae **`clip.gif`** (ruta del webp) además de `clip.path` (mp4).
- **⚠️ Para jackingshop1-cell (tú estás en `frontend`/`app.py` con auto_studio):** NO toqué esos
  archivos para no chocar. El manifest ya expone `clip.gif`; falta el botón "Descargar GIF" en el
  render de los clips sueltos del frontend. Cuando termines/pushees tu sección, lo agrego yo en el
  bloque de resultados (o dime si lo metes tú). El `.webp` YA es descargable por `/api/file?path=`.
- Probado: WebP animado válido (720px, 20fps, loop) verificado con Pillow.

### 2026-07-01 · Claude (jackingshop1-cell) · ✅ MODO AUTOMÁTICO ("Generar Creativo") HECHO
Un solo botón: video ganador (cualquier idioma) → creativo terminado en español. Todo aditivo.
- **NUEVO `backend/pipeline/auto_studio.py`** (mi terreno): `generar_creativo_auto(video, *, gemini_key,
  eleven_key, anthropic_key, product_desc, voz, oferta_2x1, verticalizar, work_dir, progress)`.
  Encadena: Narrativa → Doblaje CO → Traducir texto → Música+SFX por fase → Subtítulos por fase →
  9:16 → Normalizar audio → (Supervisor opcional). **Cada paso AISLADO en try/except**: si uno falla,
  conserva el video anterior y sigue. Devuelve `{ok, video, pasos:[{paso,ok,detalle}], resumen}`.
  Reusa TODO (tuyo y mío) sin editarlo; los pasos ffmpeg nuevos (music+sfx mix, subs por fase con
  Pillow, verticalizar cover, loudnorm) viven en mi módulo.
- **TOQUÉ `app.py`** (aditivo, avisado): import + `POST /api/auto` + `_run_auto_job` (usa el patrón de
  jobs/estado existente y `_save_uploads`). NO modifiqué tus endpoints.
- **TOQUÉ `frontend/index.html`** (aditivo, avisado): sección nueva "✨ Generar Creativo" arriba, con
  su propio `<style>`/`<script>` (ids `auto*`), sin tocar tus secciones ni tu `poll()`.
- **Probado:** cadena end-to-end (sin doblaje para no chocar con rate-limit de ElevenLabs de hoy) →
  6/7 pasos OK, video final **1080×1920, audio normalizado, subtítulos por fase, SFX** (demo en
  `~/Downloads/prueba/AUTO_creativo_demo.mp4`). La resiliencia funciona: el doblaje se saltó sin tumbar
  la cadena. Las piezas pesadas (dub, translate, narrative, phase_effects) ya estaban probadas aparte.
- **⚠️ Aviso de rendimiento:** el paso de **doblaje** es el cuello de botella (ElevenLabs TTS ~6 llamadas
  secuenciales, 90s timeout c/u). Hoy con rate-limit tardó >9 min. Está aislado (no rompe), pero para
  producción conviene: paralelizar los TTS o cachear. Lo dejo anotado; si quieres lo optimizo.
- **Cosmético menor:** en `text_translate`, sobre un video que YA está en español, a veces asoma un
  pedacito del texto original arriba + emojis salen como cuadrito (la fuente no los tiene). No afecta el
  caso real (ganador en inglés). Se pule agrandando caja/usando fuente con emojis.
- **Para ti:** el botón ya llama `/api/auto`. Si quieres moverlo de lugar en la UI o cambiar textos,
  es todo `auto*` (aislado). ¿Lo dejamos así o lo reubicamos?

### 2026-07-01 · Claude (jackingshop1-cell) · 🐛 Fix UI del Modo Automático + 🏷️ REBRAND a "CreativeMaxing"
- **Bug arreglado:** el `<label>` de subir video (`.autoDrop`) salía INLINE y se encimaba con el texto
  de arriba. Le puse `display:block` → ahora es un bloque completo, limpio. Verificado con screenshot.
- **REBRAND (lo pidió jack): "Cortador de Clips" → "CreativeMaxing".** Cambié: `frontend` h1
  (`Creative<span>Maxing</span>`) + `<title>`, `app.py` (docstring + `FastAPI(title=...)`), `run.sh`
  (comentario + echo). Aviso porque toca archivos compartidos; es solo texto/marca, sin lógica.
  La API de FastAPI (title) es interna, no afecta endpoints.

### 2026-07-01 · Claude (jackingshop1-cell) · 🎯 Verticalizado INTELIGENTE (fondo desenfocado, no recorta)
- **Bug que reportó jack:** un ganador CUADRADO, al verticalizar, se AGRANDABA y RECORTABA los lados
  → cortaba banners/textos del creativo (se veía "a las Plagas Sin Quím[ico]" cortado, etc.).
- **Fix en `auto_studio._verticalize` (mi terreno):** ahora es format-smart:
  - Si ya es ~9:16 → solo ajusta tamaño, no toca la composición.
  - Si es cuadrado/horizontal → **FONDO DESENFOCADO**: copia ampliada+borrosa (gblur) llena las
    barras y el video ORIGINAL COMPLETO va centrado encima. NO se pierde nada del creativo.
  - Probado: cuadrado con texto pegado a los bordes → izq/der se conservan 100%, fondo borroso OK.
- **Para ti, Juan:** si tu flujo normal (`assemble` aspect) también recorta al verticalizar, te sirve la
  misma técnica (`split` → bg cover+gblur → fg contain → overlay). Puedo pasártela si quieres.
- **Pendientes que jack también señaló (los tomo enseguida):** (a) los **subtítulos por fase salen
  feos/encimados** en videos reales (texto largo/solapado); (b) revisar **cómo se genera el copy/guion**;
  (c) el **tapado de texto** se ve mal en algunos casos. Voy por esos.

### 2026-07-01 · Claude (jackingshop1-cell) · 🐛 Fix subtítulos garabateados del Modo Automático
- **Bug (lo vio jack en file.mp4):** los subtítulos por fase salían ENCIMADOS/garabateados
  ("DilidianTodco... venénôs" = dos textos superpuestos). Causa doble en `auto_studio._burn_subs`:
  (1) si dos fases se pisaban en el tiempo, se renderizaban 2 subtítulos a la vez; (2) un `continue`
  después de agregar el input desalineaba la relación input↔tiempo (subtítulo en el momento equivocado).
- **Fix:** ahora ordena los tramos por inicio, **recorta el fin de cada uno al inicio del siguiente**
  (nunca 2 a la vez) y valida ANTES de agregar el input. Probado con fases que se pisan a propósito:
  en el solape ahora se ve UN solo subtítulo limpio (blanco con borde, en la safe zone).
- Solo toqué `auto_studio.py` (mi terreno). Sigue lo del copy (lo reviso ahora).

### 2026-07-01 · Claude (jackingshop1-cell) · 🔎 Revisión + mejora del COPY del doblaje (dub_colombia)
- **Revisión (lo pidió jack):** el copy del creativo en Modo Automático lo genera
  `dub_colombia.adaptar_guion` (Gemini + framework de Juan). Estaba BIEN (adapta por fase, problem-aware,
  congruente con lo que se ve, policy-safe, COD). Puntos flojos que encontré: ritmo un pelín apretado
  (se pasaba de largo y la voz se aceleraba) y riesgo de repetir ideas entre fases.
- **Mejoras aplicadas (mi módulo):** bajé el ritmo de 2.6→2.2 palabras/seg; el largo ahora es un MÁXIMO
  ("mejor corto y natural que apretado"); frases HABLADAS cortas; y "no repitas ideas entre fases".
- **Muestra real (video de dolor):** HOOK "¡Ay, no! ¿A usted también le pasa esta vaina?" · DOLOR
  "...la ropa no cierra, uno parece un balón... y lo de la cita, parce, ¡hasta diciembre!". Natural,
  modismos, congruente. (Ese video solo tenía HOOK+DOLOR; la narrativa lo detectó bien.)
- **Nota:** el copy de los 10 GUIONES (`scripts.py`) es tu terreno; ahí no toqué nada. Si quieres que
  unifiquemos el estilo/las reglas entre `scripts.py` y `dub_colombia`, coordinamos.
- **Resumen de la tanda de hoy para jack:** ✅ vertical inteligente (fondo desenfocado, no corta) ·
  ✅ subtítulos sin garabato · ✅ copy más natural. Falta pulir el "tapado" en casos feos (siguiente).

### 2026-07-01 · Claude (juanesal-lab) · 🎨 REDISEÑO del frontend (tema claro + pestañas + guía)
- **Pedido de Juan:** app más linda, profesional, colores CLAROS, dividida en pestañas, con tips y
  "clases" que expliquen cada función. Limpio y minimalista.
- **Qué hice en `frontend/index.html` (solo CSS + estructura HTML; NO toqué la lógica JS):**
  - **Tema claro:** cambié las variables `:root` (fondo claro, tarjetas blancas, sombras suaves) →
    re-tematiza TODA la app (incluida tu sección de Modo Automático, que pasé de degradado oscuro a claro).
  - **Pestañas:** barra de navegación (Crear clips · Automático · Reemplazar · Doblar · Configuración ·
    Guía). Cada sección va envuelta en `<div class="panel" id="p-...">`; un JS chico las muestra/oculta.
  - **Tips + "¿Qué hace?":** cada pestaña tiene su explicación; nueva pestaña **Guía & Tips** con paso
    a paso, qué hace cada función, y tips de creativos.
- **⚠️ IMPORTANTE para jackingshop1-cell:** rehíce toda la ESTRUCTURA del `index.html` (envolví las
  secciones en paneles + tema claro). **Haz `git pull` ANTES de tocar el frontend** para no chocar.
  Conservé TODOS los IDs y tu Modo Automático intacto (solo lo envolví en su panel + lo aclaré).
- **Verificado con screenshot en el navegador:** se ve limpio, claro, las pestañas cambian bien.

### 2026-07-01 · Claude (jackingshop1-cell) · ⏳ AVISO: construyendo "Clon Ganador con mi Producto" ahora
Juan, arranco un módulo nuevo `backend/pipeline/winner_clone.py` (mi terreno) = clonar un ganador
mostrando NUESTRO producto, con REEMPLAZO INTELIGENTE (decide por MOVIMIENTO: producto quieto→reemplaza;
mucho movimiento/manos→corta a toma propia; si no hay buena toma→deja el original para no verse falso).
- **REUSA tu `product_swap.py` (solo importo `detect_product_ranges`/`find_new_clips`, NO lo edito).**
  El empalme por-rango lo hago con mi PROPIA función (necesito control por-momento que `swap_product`
  no da: asigna round-robin). Si al final decido tocar `swap_product`, aviso aquí antes.
- Reusa también auto_studio (verticalizar blur, música/sfx, subs, normalizar), dub_colombia, text_translate.
- **TOCARÉ `app.py` + `frontend`** (aditivo): endpoint `/api/clone` + sección nueva. Aviso para no
  editarlos al tiempo. Dejo entrada "hecho" al terminar.

### 2026-07-01 · Claude (jackingshop1-cell) · ✅ "Clon Ganador con mi Producto" HECHO (reemplazo inteligente)
- **NUEVO `backend/pipeline/winner_clone.py`** (mi terreno): `clonar_ganador(winner, our_photos,
  our_videos, *, product_desc, old_desc, doblar, voz, verticalizar, ...)`. Clona un ganador mostrando
  NUESTRO producto, con **reemplazo inteligente por MOVIMIENTO**:
  - `_motion_score()` mide el movimiento de cada momento del producto (OpenCV, diff media 64×64).
  - Quieto (<4) → **reemplaza** con toma quieta (foto→clip). Movido (>11) → **corta** a toma dinámica;
    si no hay → **deja el original** (no fuerza → no se ve falso). Medio → mejor disponible.
  - Devuelve `decisiones:[{rango,movimiento,accion}]` para auditar qué hizo en cada momento.
- **REUSA tu `product_swap.py` SIN tocarlo:** el empalme lo hace `swap_product` pasándole solo los
  rangos elegidos + la toma alineada a cada uno (aprovecho que asigna en orden). También reusa
  auto_studio (verticalizar blur / música-sfx / subs / normalizar), dub_colombia, text_translate, narrative.
- **TOQUÉ `app.py` + `frontend` (aditivo, avisado):** endpoint `POST /api/clone` + sección
  "🎯 Clon Ganador con mi Producto" (reusa clases `auto*`, ids `cl*`). No modifiqué lo tuyo.
- **Probado:** el clasificador de movimiento distingue 3 niveles (quieto/medio/mucho) con clips
  sintéticos; backend compila/importa; la sección renderiza bien (screenshot). Cada sub-pieza (splice,
  finalización, narrativa, dub) ya estaba validada por separado.
- **Voz:** opción de dejar la ORIGINAL o doblar a es-CO (checkbox).
- **Enganche futuro (tu terreno / externo):** buscar tomas en TikTok (sonar-auto / tiktok-scout) NO se
  llama inline (es skill + navegador); hoy el usuario alimenta `our_photos`/`our_videos` (puede sacarlas
  del scout+descargador). Cuando quieras, cableamos ese puente.
- **v2 (lo más difícil):** reemplazo automático PERFECTO in-place sobre producto en movimiento. Hoy la
  estrategia es "corta a toma propia / deja original" donde el in-place quedaría falso (natural > forzado).

### 2026-07-01 · Claude (jackingshop1-cell) · ⏳ AVISO: motor de subtítulos/estilos (Poppins, auto-fit, 10 estilos)
Juan, arranco `backend/pipeline/caption_styles.py` (mi terreno) para arreglar el texto FEO: auto-ajuste
(nunca se corta, safe zone 120px), **Poppins** (copié a `assets/fonts/`), 10 estilos seleccionables y fix
del tapado. **Tocaré `text_translate.py` y `auto_studio.py`/`winner_clone.py`** (para usar el motor) — si
hay choque conservo lo tuyo. El selector en la UI lo coordino contigo (veo que estás con las pestañas).
Dejo entrada "hecho" con screenshots de cada estilo.

### 2026-07-01 · Claude (juanesal-lab) · ✅ HECHO: pestaña 📥 Descargar (downloader in-app con yt-dlp)
Juan quería una sección para **bajar videos automáticamente** desde links y usarlos como material.
La armé DENTRO de la app (yt-dlp ya está instalado, v2026.03.17) — no depende de tu descargador externo.
- **NUEVO `backend/pipeline/downloader.py`** (mi terreno): `download_urls(urls, out_dir, progress)` →
  baja cada link a `WORK_DIR/job_id/` (servible por `/api/file`), dedup, reintento con `--impersonate chrome`
  si falla (anti-bot). `available()` → False si no hay yt-dlp (no rompe nada).
- **`app.py` (ADITIVO)**: agregué `/api/download-videos` (Form `urls`, uno por línea) + `_run_download_job`
  (patrón idéntico a los otros jobs). Import `from pipeline.downloader import download_urls`. **No toqué**
  tus endpoints ni `text_translate`/`auto_studio`/`winner_clone`.
- **`frontend/index.html` (ADITIVO)**: nuevo botón de tab `data-p="p-descargar"` + panel `#p-descargar`
  (reusa clases `auto*`, trae su propio `<style>`/`<script>` autocontenido) + 1 línea en "Qué hace cada
  pestaña" de la Guía. Probado end-to-end en el navegador: pegar link → 1/1 descargado → preview + "⬇️
  Descargar a mi PC".
- **⚠️ AVISO para ti:** ambos podemos tocar `index.html` (tú con el selector de estilos de subtítulos).
  Mis cambios son autocontenidos (tab nuevo cerca de `p-crear` + su panel al lado de `p-swap`), NO toco
  `text_translate`/captions. Haz `git pull` antes de tu push y no habrá choque. Si hay conflicto en
  index.html, mi bloque es el `<div class="panel" id="p-descargar">…</div>` — consérvalo entero.
- **🔌 Puente futuro (tu ingesta):** este downloader complementa tu scout/descargador externo. Si quieres,
  cableamos: el scout vuelca URLs a un `.txt` → esta pestaña (o un modo "pegar muchas") las baja a
  `incoming/` y quedan como material para Crear clips. Avísame y lo hago.

### 2026-07-01 · Claude (jackingshop1-cell) · ✅ Motor de subtítulos/textos: Poppins + auto-fit + 10 estilos
Arreglé el texto FEO (los 5 problemas de jack). NUEVO `backend/pipeline/caption_styles.py` (Pillow,
porque este ffmpeg NO tiene libass/drawtext):
- **P1 (crítico) NO se corta:** `_fit()` hace word-wrap + baja el tamaño de fuente hasta caber en el
  área segura (ancho = frame − 2*120px). Probado con frase larga → 5 líneas, todo dentro del frame.
- **P2 Poppins:** copié `assets/fonts/Poppins-Bold/ExtraBold.ttf` (de adapta). ExtraBold hooks/hormozi,
  Bold subtítulos. También se lo puse a `text_translate` (todo el texto en Poppins).
- **P3 10 estilos** (`ESTILOS`): bold_outline, hormozi (MAYÚS + keyword amarilla), yellow_highlight,
  red_highlight, highlight_box, pill (cápsula), clean_minimal, karaoke, bounce, typewriter. Con detección
  de keyword. Screenshots: `~/Downloads/prueba/ESTILOS_subtitulos_10.png` (grilla) y `ESTILO_hormozi_demo.png`.
  *(Honesto: sin libass ni word-timestamps, karaoke/bounce/typewriter van con look estático PRO; animación
  real por-palabra = v2.)*
- **P4 oferta:** `render_offer_pill()` (pill Poppins, arriba-centro, auto-fit). Param `oferta` en la cadena.
- **P5 tapado:** `text_translate` ya auto-ajusta + clampa la caja al frame; le añadí Poppins. (Tú ya
  habías mejorado el relleno sólido con muestreo de color — quedó bien.)
- **Cableado:** `auto_studio._burn_subs(style=...)` usa el motor; `generar_creativo_auto` y `POST /api/auto`
  aceptan `caption_style` + `oferta`. **winner_clone** hereda subs con estilo por defecto.
- **Para ti, Juan (tu terreno = las pestañas nuevas):** falta el SELECTOR de estilo + oferta en la UI.
  El backend ya lo soporta (`caption_style` ∈ ESTILOS, `oferta` texto). ¿Lo pones tú en las pestañas
  Automático/Doblar o te dejo el `<select>` listo para pegar? No toqué tus pestañas para no chocar.

### 2026-07-01 · Claude (jackingshop1-cell) · ⚡ OPTIMIZACIÓN de velocidad (doblaje en paralelo + GPU)
Dos cuellos de botella reales, arreglados (solo mis módulos):
- **Doblaje en PARALELO** (`dub_colombia`): las ~6 voces de ElevenLabs se generaban 1 x 1 (era EL
  cuello de botella; llegó a tardar >9 min con rate-limit). Ahora se generan en paralelo con
  ThreadPoolExecutor (hasta 6 a la vez). ~N veces más rápido.
- **Encoder GPU (VideoToolbox)** en toda la cadena `auto_studio` (subtítulos, oferta, verticalizado):
  cambié `libx264` (CPU) por `venc()` de assemble.py → usa `h264_videotoolbox` si hay GPU (este Mac SÍ).
  Probado: un paso de subtítulos con GPU tardó 0.8s. Clon Ganador hereda esto (usa auto_studio).
- El flujo de cortar clips (orchestrator/assemble) ya usaba GPU + paralelo (tuyo). Así toda la app va
  por GPU ahora.
- **Nota:** VideoToolbox usa bitrate alto (12M) → rápido y con buena calidad; menos re-encodes CPU.

### 2026-07-01 · Claude (jackingshop1-cell) · 💬 Subtítulos PALABRA POR PALABRA sincronizados (estilo adapta)
Integré el estilo de subtítulos de adapta adaptado a Super-APP (sin libass, con Pillow, mi terreno).
- **`dub_colombia`**: ahora usa `synthesize_with_timestamps` → captura el tiempo de CADA palabra,
  lo reescala por el atempo del calce y lo ancla al inicio de su fase → tiempos ABSOLUTOS. Devuelve
  `word_timings` en el resultado.
- **`caption_styles.burn_word_captions()`**: muestra pocas palabras a la vez (grupos de 4) y RESALTA la
  palabra que se está diciendo (karaoke). Poppins, auto-ajuste, safe zone. Soporta los estilos (karaoke,
  hormozi, yellow/red, pill, box…).
- **`auto_studio`**: si el doblaje dio `word_timings` → subtítulos palabra x palabra; si no → bloque por fase.
- Probado con tiempos reales sintéticos: el resaltado se mueve palabra por palabra sincronizado
  (frames en `~/Downloads/prueba/SUBS_palabra1/2.png`). Solo mis módulos.
- **Nota:** solo aplica cuando hay doblaje (los tiempos vienen de ElevenLabs). Sin libass no hay sweep
  interno de letra, pero el resaltado por palabra queda igual de pro. winner_clone usa por ahora el
  bloque por fase; si quieres, le paso los word_timings también (rápido).

### 2026-07-01 · Claude (juanesal-lab) · ✅ HECHO: pestaña 🎯 Producto → Clips (semi-auto: links de ganadores → clips)
Juan quería el sueño: dar link+imagen del producto → scout TikTok → descarga → clips, todo de corrido.
**Decisión con Juan (importante):** el scout auto se descartó por ahora. Probé y **yt-dlp NO puede
listar/buscar** un hashtag de TikTok (lo bloquea: *"No working app info"*), pero **SÍ descarga un link
individual de TikTok** (probado, 1.9MB, con el reintento `--impersonate chrome` de mi downloader). Auto-scout
real necesitaría API pagada (Apify/PiPiads) o Playwright (frágil). Así que vamos **SEMI-AUTO**: el humano
encuentra los 2-3 ganadores (juzga mejor) y pega los links; la máquina hace TODO lo demás.
- **NUEVO `backend/pipeline/producto_clips.py`** (mi terreno): `producto_a_clips()` encadena
  `downloader.download_urls` → `describir_producto()` (Gemini vision lee la imagen + `hook_gen.fetch_page_text`
  de la página → product_desc corto) → `process_job(...)`. Devuelve el MISMO shape que process_job
  (versions+clips) + `producto_desc`/`descargados`/`fallidos`. Guard anti-alucinación: si no hay imagen
  NI página, NO deja que Gemini invente el producto (devuelve lo que escribió el user).
- **`app.py` (ADITIVO)**: `/api/producto-clips` (Form winner_urls + product_url + product_desc +
  product_image File opcional + aspect/target_seconds/blur) + `_run_producto_job`. **No toqué** process_job
  ni tus módulos (auto_studio/caption_styles/dub_colombia/winner_clone).
- **`frontend/index.html` (ADITIVO + 1 cambio compartido)**: nuevo tab `p-producto` (autocontenido).
  ⚠️ **Único toque compartido:** `renderResults(res)` → `renderResults(res, rootId)` con default `"results"`
  (tus/las llamadas viejas NO cambian; solo agregué un 2º arg opcional para pintar en `#productoResults`).
- **Probado:** descarga de TikTok real ✓; cadena completa produce **6 versiones + 3 clips (con GIF)** en un
  video multi-escena ✓. (Un TikTok de UNA sola toma da "sin segmentos utilizables" — correcto, material
  no apto, no es bug.)
- **🔌 Para tu ingesta:** esta pestaña ES el consumidor "links → clips". Si tu scout/descargador vuelca
  URLs, entran directo aquí. Cuando quieras cableamos el volcado automático de URLs a este tab.

### 2026-07-01 · Claude (jackingshop1-cell) · ✨ Pulido final: Clon con word-subs, Gemini en paralelo, sin emojis rotos
- **winner_clone (Clon Ganador):** ahora (1) corre narrativa + detección de producto EN PARALELO
  (2 llamadas Gemini a la vez = más rápido) y (2) usa subtítulos PALABRA POR PALABRA (word_timings del
  doblaje) igual que el Modo Automático.
- **Emojis:** Poppins no los tiene → salían como cuadrito □. Ahora se quitan del texto en caption_styles
  (subs/oferta) y en text_translate (tapado). Probado.
- **PRUEBA REAL end-to-end CON doblaje** (Modo Automático, video real): terminó en **106 s** (antes se
  pasaba de 9 min). 7/9 pasos OK — subtítulos palabra x palabra (46 palabras, karaoke) + oferta pill
  ("ENVÍO GRATIS") + 9:16 + normalizado + capitán. La narrativa tuvo un hipo transitorio de Gemini
  (JSON inválido) pero la cadena SIGUIÓ sin romperse (resiliencia OK). Demo:
  `~/Downloads/prueba/FINAL_creativo_completo.mp4`.
- Solo mis módulos. La velocidad ahora la manda la IA externa (Gemini/ElevenLabs), no el código.

### 2026-07-01 · Claude (jackingshop1-cell) · 🔧 Orden correcto del pipeline + subtítulos que tapan menos + pestañas más claras
Jack reportó: subtítulos tapan mucho, el texto viejo se asoma, y las pestañas no se entendían. Arreglos:
- **ORDEN del pipeline (auto_studio y winner_clone):** ahora VERTICALIZA TEMPRANO — después de tapar/
  traducir el texto viejo y ANTES de música/subtítulos/oferta. Beneficios: (1) las bandas del blur salen
  limpias (el texto viejo ya se tapó antes), (2) los subtítulos/oferta se ponen sobre el lienzo 9:16 FINAL
  → bien posicionados, sin re-escalarse ni desubicarse. Este era el origen de los "errores" que veías.
- **Subtítulos tapan menos:** fuente más pequeña (H*0.052) y en el TERCIO INFERIOR (y≈0.80), no al centro.
- **AVISO Juan (toqué tu frontend):** solo renombré las 8 pestañas para que se entiendan (mismo orden y
  paneles, solo el texto): "✨ Crear creativo (automático)", "🔄 Clonar con mi producto", "✂️ Cortar
  videos en clips", "📦 De mi producto a clips", "📥 Descargar de TikTok", "🎙️ Doblar a español",
  "🔑 Mis claves (API)", "📚 Guía y ayuda". Si prefieres otros nombres, cámbialos; no toqué la lógica JS.
- Todo compila, la app arranca, pestañas renderizan.

### 2026-07-01 · Claude (jackingshop1-cell) · 🩹 Fix: pestañas se encimaban (nombres muy largos)
- Mis nombres largos rompían el layout de las pestañas (se solapaban). Los dejé CORTOS y claros:
  Cortar clips · Mi producto · Descargar · Crear creativo · Clonar ganador · Doblar · Claves · Guía.
- Verificado con screenshot: se ven limpias, sin encimarse. Solo texto, no toqué tu lógica/CSS.

### 2026-07-01 · Claude (jackingshop1-cell) · ✨ "Crear creativo" ahora acepta VARIOS videos (lote)
- La sección Automático ya NO es 1 por 1: subes UNO O VARIOS videos ganadores y hace un creativo
  terminado por CADA uno, en lote, con progreso global ("Creativo 1/2...").
- `/api/auto` acepta `files` (lista); `_run_auto_job` itera y devuelve `creativos:[...]`. Frontend:
  input `multiple` + render de cada creativo con su video y botón de descarga.

### 2026-07-01 · Claude (juanesal-lab) · 🐛 FIX: crash al concatenar clips cuando un video fuente NO tiene audio
Juan hizo "Generar guiones de voz" con Efectos y reventó ffmpeg (234): `[6:a]...acrossfade matches no
streams. Error binding filtergraph inputs/outputs`. **Causa:** uno de los videos fuente no tenía audio →
`render_clip(has_audio=False)` lo corta con `-an` (sin pista) → `concat_clips_xfade` arma `[i:a]acrossfade`
para TODOS los clips → el clip mudo no tiene `:a` → crash. (También afectaba a `concat_clips` normal con
clips mezclados.) **Fix (en `assemble.py`, tu terreno — cambio aditivo):** nuevo helper `_ensure_audio(path,
work_dir)` que usa `probe(path).has_audio` y, si el clip no tiene audio, le remuxea una pista de SILENCIO
(anullsrc, `-c:v copy` rápido). Lo llamo al inicio de `concat_clips` y `concat_clips_xfade`. Los clips que
YA tienen audio pasan intactos. Probado: 3 clips (con/SIN/con audio) → antes crasheaba, ahora sale el video
con audio ✓. No toqué `render_clip` ni tu `venc()`/word-subs.
- Probado: POST 2 archivos → "Creativo 1/2". Solo mi sección (autoHero) + mi endpoint.

### 2026-07-01 · Claude (jackingshop1-cell) · 🩹 Fix subtítulos DUPLICADOS + tapado cubre entero
- **Subtítulos duplicados/encimados (varios grupos a la vez):** en burn_word_captions las ventanas de
  tiempo se pisaban (peor si las fases del doblaje se solapaban). Ahora ordeno por inicio y el FIN de
  cada palabra = inicio de la SIGUIENTE en TODA la lista → en cada instante hay UN solo subtítulo.
  Verificado con tiempos que se pisaban a propósito → sale uno solo limpio.
- **Tapado no cubría entero:** subí el margen de la caja en text_translate (mx=bw*0.14+18, my=bh*0.6+20)
  para tapar el original ENTERO sin que se asome. (Toqué esa línea de tu archivo, Juan; solo el margen.)

### 2026-07-01 · Claude (jackingshop1-cell) · 🔎 NUEVA sección "Buscar en TikTok" (foto/nombre → links reales)
Lo que pidió jack: una sección donde pone foto + nombre y recibe LINKS de creativos de TikTok.
- **NUEVO `backend/pipeline/tiktok_search.py`**: `buscar(image_path, nombre, api_key, count)` →
  {ok, keywords, links:[{url,title,cover}], busqueda}. Si hay foto, Gemini visión saca las palabras
  clave; luego busca en TikTok vía la API pública de **tikwm** (sin login) y devuelve links REALES.
  Degradación: si tikwm falla, devuelve el link de BÚSQUEDA de TikTok para abrir a mano.
- **`app.py`**: endpoint síncrono `POST /api/tiktok-search` (foto opcional + nombre + count).
- **`frontend`** (TOQUÉ tu nav, Juan — aviso): pestaña nueva "🔎 Buscar TikTok" + panel `p-buscar`
  (foto/nombre → lista de links + botón "copiar todos"). Usa tu lógica de pestañas genérica (data-p).
- **Probado EN VIVO** (con captura): "faja reductora colombiana" → 19 links reales de TikTok con títulos.
- **Aviso de fragilidad honesto:** tikwm es un servicio de TERCEROS (no oficial); puede limitar o caerse.
  Si algún día falla, la sección igual muestra el link de búsqueda para abrir a mano. Si prefieres algo
  más robusto a futuro, tocaría Playwright/oficial (más pesado).

### 2026-07-01 · Claude (jackingshop1-cell) · 📥✂️ Cortar clips DESDE links de TikTok (pegar links, no solo subir)
Jack pidió: en "Cortar clips", además de subir videos, poder PEGAR links de TikTok.
- **`app.py`**: nuevo `POST /api/process-links` + `_run_links_job`: recibe `links` (texto) + los MISMOS
  ajustes de /api/process, baja los videos con `download_urls` (tu downloader) y luego REUSA `_run_job`
  (tu flujo de cortar clips). No modifiqué /api/process ni process_job.
- **`frontend`** (TOQUÉ tu sección p-crear, Juan — aviso): agregué un cuadro para pegar links + botón
  "Bajar y cortar desde links" → `cortarDesdeLinks()` que reusa tu `buildForm()` y tu `poll()`.
- **Probado end-to-end (con captura):** pegué 1 link real de TikTok → bajó (3.1MB) → analizó → armó
  2 versiones → done. La descarga real de TikTok funciona (yt-dlp).

### 2026-07-01 · Claude (jackingshop1-cell) · 🎙️ Links de TikTok → videos + GUIONES de una
Jack: del flujo de links, que también genere los guiones de voz en off (no solo cortar).
- **`app.py` `_run_links_job`**: tras bajar y cortar (process_job), AHORA también corre analyze_select +
  generate_scripts sobre los mismos videos y mete `scripts` en el MISMO resultado. Si los guiones fallan,
  igual entrega los videos. Guarda el estado (selected, etc.) para la fase 2 de narración.
- **`frontend` (TOQUÉ tu poll, Juan — aviso):** el poll usaba if/else (si había guiones NO mostraba los
  videos). Lo cambié a: si hay `versions` → renderResults; si hay `scripts` → renderScripts. Así se ven
  AMBOS cuando vienen juntos (y no rompe /api/process ni /api/scripts). Botón: "Bajar → cortar + guiones".
- **Verificado EN VIVO (capturas):** 1 link real → 6 versiones + 10 guiones (con ángulos y "▶️ Escuchar").

### 2026-07-01 · Claude (juanesal-lab) · 🎨 FIX: "tapar textos" ahora es DESENFOQUE real (no parche de color)
Juan mostró una captura: el tapado quedaba como un PARCHE DE COLOR sólido feo. Quiere que se vea BORROSO
(vidrio esmerilado), mezclándose con la imagen, como antes. Era el relleno sólido que yo mismo puse cuando
él pidió "que el blur sea sólido" — malinterpreté: quería ESTABLE/sin titilar, no color plano.
- **`text_translate.py` (modo "tapar", TU archivo — cambio quirúrgico):** en vez de overlay de PNG sólido
  (`_render_solid`/`_region_color_rgb`), ahora RECORTA la región + `gblur` fuerte (sigma escala con la caja,
  steps=2) + overlay de vuelta → borroso natural y ESTABLE (caja fija = no titila). Desacoplé el índice de
  PNG (`img_i`) del paso (`n`) porque "tapar" ya no agrega PNGs; el modo "traducir" quedó IGUAL. `_render_solid`
  y `_region_color_rgb` quedaron sin uso (los dejé por si los usas en otro lado). NO toqué tu detección
  Gemini ni tus márgenes (mx/my).
- **`text_detect.py` (EAST, fallback sin key):** el relleno de color mediano → `cv2.GaussianBlur` de la ROI
  (kernel impar que escala con la caja). Mismo look borroso.
- Probado: frame con texto amarillo grande → queda ILEGIBLE y borroso, se mezcla con el fondo (no parche).
- **AVISO:** toqué `text_translate.py` (tu terreno) pero solo el bloque de armado de overlays del modo tapar.
  Pull antes de push.

### 2026-07-01 · Claude (juanesal-lab) · 🚀 UNIFICADO: "Mi producto" hace TODO en un botón (busca TikTok → descarga → clips)
Juan pidió unificar el sueño en UNA pestaña y quitar redundancia. Convertí "📦 Mi producto" (p-producto) en
el flujo completo, ENCADENANDO EN EL FRONTEND (sin tocar backend de nadie):
1. **Fase 1 · scout** → TU `/api/tiktok-search` (nombre + foto) → links reales de TikTok.
2. **Fase 2 · clips** → mi `/api/producto-clips` (baja + Gemini entiende el producto + corta) → 6 versiones
   + clips + GIFs (con `renderResults`).
- **Reusa endpoints existentes tal cual** (tu tiktok-search + mi producto-clips). **CERO cambios de backend
  → cero choque.** Solo toqué mi panel `p-producto` (mío) y su JS.
- UI nueva: nombre del producto + imagen + botón "🚀 Buscar en TikTok y crear mis clips". Los links manuales
  se movieron a un `<details>` "Avanzado" (si los pegas, se salta la búsqueda).
- **Probado EN VIVO (captura):** "faja reductora colombiana" → encontró 8 creativos → "Descargando 1/8" →
  clips. El link del scout descarga OK con yt-dlp (probado aparte, 727KB).
- **⚠️ REDUNDANCIA (tu decisión):** con esto, "📦 Mi producto" ya cubre scout+descarga+clips. Quedan como
  herramientas sueltas: "🔎 Buscar TikTok" (tuya, solo scout) y "📥 Descargar" (mía, solo bajar). NO borré
  ninguna. ¿Las dejamos como "avanzado" o las escondemos del nav para que quede más limpio? Dime y lo hago
  (o hazlo tú). El scout de "Mi producto" usa TU tiktwm igual, así que si mejoras tiktok_search, mejora aquí también.

### 2026-07-01 · Claude (jackingshop1-cell) · 🧽 "Crear creativo" LIMPIO: tapar subs viejos con blur (no traducir/música/oferta)
Jack: el creativo salía "repodrido" (subtítulos viejos asomándose + traducciones + capas de texto).
Quería SOLO: voz en off + tapar los subtítulos originales con blur (detectados frame por frame) +
NUESTROS subtítulos encima. Nada más.
- **auto_studio (generar_creativo_auto):** reescribí la cadena. Ahora: narrativa → doblaje →
  **TAPAR subtítulos viejos con BLUR** (reusa `caption_mask.detect_text_boxes_timed` que detecta SOLO
  texto sobrepuesto, NO el de la escena + `assemble.blur_boxes`; arma la zona de abajo, tope 42% de alto
  anclado abajo) → vertical → NUESTROS subtítulos palabra x palabra → normalizar.
- **QUITÉ** de este flujo: traducir texto en pantalla, música/SFX y oferta pill (eso ensuciaba).
- Probado en el video real de Jack (file (1).mp4): antes 3 capas de texto encimadas → ahora subs viejos
  tapados y UN solo subtítulo limpio ("Absorben hasta 6 veces"). Demos en ~/Downloads/prueba/
  ANTES_repodrido.png y DESPUES_limpio.png.
- Nota: el tope de 42% se activó porque ese archivo ya venía con muchas capas; en un ORIGINAL limpio
  tapa solo la banda real (~25-30%).

### 2026-07-01 · Claude (jackingshop1-cell) · 🎯 Blur de subtítulos PRECISO (banda tight con EAST, no gigante)
Jack: el blur salía gigante; quería que tape SOLO la franja exacta de los subtítulos.
- **NUEVO `subtitle_band.py`**: usa EAST (text_detect, cajas ajustadas por línea) en ~26 frames y se
  queda con la franja donde el texto aparece de forma CONSISTENTE (≥30% de frames) en la zona baja →
  banda TIGHT {x,y,w,h}. Descarta texto esporádico de la escena (envases, letreros).
- **auto_studio:** el paso "tapar subtítulos" ahora usa `detect_subtitle_band` + `blur_boxes` (antes
  hacía unión de cajas de Gemini → banda enorme de 42%). Ahora tapa solo la franja real.

### 2026-07-01 · Claude (juanesal-lab) · 🎯 Tapado de captions PRECISO en el flujo de CLIPS (EAST afinado + Gemini clasifica)
Juan mostró que el "tapar" ponía blur en lugares RANDOM (encima del volante/producto). Diagnóstico con
capturas: Gemini analizando el video ENTERO localiza PÉSIMO (leyó "Sujetos roban las llantas..." pero puso
la caja encima del CARRO, no abajo donde está); y EAST por defecto (input 320x640) se saltaba captions
grandes-abajo. Ninguno de los dos solo servía.
- **NUEVO `smart_caption_mask.py` (mío):** `mask_captions_smart(in,out,gemini_key)` — (1) EAST AFINADO
  (input 640x1280, min_h 0.013, conf 0.5) localiza el texto frame por frame, PRECISO (agarra captions
  grandes y chicas + algunos falsos positivos tipo reflejos); (2) arma un contact-sheet de las zonas y
  **Gemini clasifica** cada una (caption real vs reflejo/ventana/estantería/producto/tablero); (3) desenfoca
  SOLO las captions. Reusa el EAST de `text_detect`.
- **orchestrator (mi cambio):** el modo "tapar" YA NO va por `text_translate` (Gemini-video-entero,
  impreciso). Ahora: "traducir" → text_translate (necesita leer/traducir); **"tapar" → `_mask_seg` POR
  CORTE**, que usa el smart masker si hay key de Gemini (o EAST puro + capitán Claude si no).
- **Probado (capturas en `~/Desktop/PRUEBAS-CreativeMaxing/_BLUR-TEST/`):** news con caption amarilla gigante
  → caption DESENFOCADA, carro/personas limpios ✅. Honda (reflejos hexagonales, sin caption) → 100% limpio,
  cero falso positivo ✅.
- **⚠️ SOLAPAMIENTO contigo:** tu `subtitle_band.py` (auto_studio, banda tight abajo) y mi `smart_caption_mask.py`
  (process_job, cualquier caption + Gemini rechaza reflejos/producto) resuelven lo MISMO en flujos distintos.
  El tuyo es tight para la banda de subtítulos de abajo; el mío agarra captions en cualquier posición y filtra
  falsos positivos con Gemini. **¿Unificamos en uno solo?** Cuando quieras lo alineamos (no toqué tu `subtitle_band`
  ni `auto_studio`).
- Probado en file(2): antes tapaba y=0.58→1.0 (42%); ahora y=0.69→0.90 (banda del texto, 21%).
  En un ORIGINAL limpio (subs de 1 línea) será aún más fino. Demo: ~/Downloads/prueba/BLUR_tight.png.

### 2026-07-01 · Claude (jackingshop1-cell) · 🔬 20+ pruebas: detección de banda de subtítulos afinada (híbrido Gemini+EAST)
Loop autónomo de test/error (12 videos reales de TikTok × 5 rondas = 60 observaciones) para afinar
`subtitle_band.detect_subtitle_band`. Errores encontrados y arreglados:
- **Ronda 1 (solo EAST):** agarraba texto de ESCENA (etiquetas de producto "BUTTER"/"THERMAL"), UI y
  daba banda en videos SIN subtítulo. → EAST no distingue subtítulo de texto de escena.
- **Ronda 2-3:** GEMINI sí distingue (semántico). Insight clave: los subtítulos REALES salen en muchos
  frames; el texto de escena/falsos, en 0-2. → **regla de consistencia**: solo tapar si el texto aparece
  en ≥3 frames muestreados. Separó PERFECTO subtítulo vs no-subtítulo (7/7 no-subs correctos).
- **Ronda 4-5 (híbrido):** Gemini CONFIRMA + da zona; **EAST afina la caja tight** dentro de esa zona;
  ventana deslizante con tope de alto (0.34) para subtítulos gigantes sobre escena con texto.
- **Resultado:** ~10/12 correctos. Falla el caso raro de subtítulo de 5 líneas sobre escena llena de
  texto de producto. Antes: blur gigante SIEMPRE (42-55%). Ahora: nada si no hay subtítulo, y banda
  tight si lo hay. Montaje de pruebas: ~/Downloads/prueba/PRUEBAS_deteccion_subtitulos.png

### 2026-07-01 · Claude (jackingshop1-cell) · ✏️ Subtítulos más pequeños y con líneas JUNTAS
Jack: los subtítulos salían muy grandes y con mucho espacio entre la línea de arriba y la de abajo.
- **caption_styles `_fit`:** el interlineado usaba `asc+desc+0.18*size` (Poppins tiene métricas ~1.5×
  el tamaño → líneas muy separadas). Ahora `line_h = 1.18*size` → líneas JUNTAS.
- **`_render_wordgroup`:** fuente H*0.052→0.046 y max_h 0.20→0.165 (más pequeño).
- Verificado con render local (sin API): 1 línea y 2 líneas quedan chicas y juntas, acentos OK.
  Demo: ~/Downloads/prueba/SUBS_juntos_chicos.png
- Nota: el file(3) que mostró Jack es output de una versión ANTERIOR (por eso el subtítulo viejo se
  asomaba). La detección/blur ya se afinó (híbrido Gemini+EAST). Falta que pruebe con un ORIGINAL limpio.

### 2026-07-01 · Claude (juanesal-lab) · 🎬 NUEVO: Editor de línea de tiempo (mini CapCut) — FASE 1 (esqueleto)
Juan quiere un editor tipo CapCut DENTRO de la app para corregir A MANO lo que la IA hace mal (mover/quitar
un blur, arreglar una caption) en vez de re-correr todo el pipeline cuando algo sale mal. Pidió empezar por
el TIMELINE completo. Fase 1 lista y probada en vivo:
- **app.py (ADITIVO, no toqué endpoints de nadie):** `/api/editor-project?job_id` (arma el proyecto = clips
  + miniatura + duración de un trabajo ya procesado), `/api/editor-export` (concatena los clips en el ORDEN
  dado con `assemble.concat_clips`), `/api/last-project` (el último job con clips). `/api/file` ahora infiere
  el mime (para servir miniaturas jpg, antes todo era video/mp4). Helper `_thumb()` (1 frame por clip).
- **frontend (ADITIVO):** pestaña nueva `🎬 Editor` + panel `p-editor` AUTOCONTENIDO (mi `<style>`/`<script>`):
  preview + línea de tiempo con bloques de clip (miniatura, número, duración, ✕), **arrastrar para reordenar**,
  clic para ver uno, borrar, ▶️ reproducir en secuencia, 💾 exportar.
- **Probado EN VIVO (navegador, capturas):** cargó 24 clips reales con miniaturas → timeline OK → reordenar/
  borrar OK → export concatenó → video de 0:41 reproducible ✅.
- **PRÓXIMAS FASES:** (2) recortar clips (trim) + música; (3) LO CLAVE para Juan: editar las cajas de BLUR y
  las CAPTIONS (mover/quitar/corregir) — para eso el pipeline debe emitir el "proyecto" con blur+captions como
  DATOS editables (no quemados) y el export renderizarlos. Edición no-destructiva.
- **Aviso:** toqué `frontend/index.html` (nav + panel nuevo) y `app.py` (endpoints nuevos + mime de /api/file).
  Todo aditivo; si chocamos en el nav, mi botón es `data-p="p-editor"`.

### 2026-07-01 · Claude (jackingshop1-cell) · 🎁 Doblaje: checkbox opcional "Oferta 2x1"
- En la pestaña Doblar agregué un checkbox "Es oferta 2x1" (+ campo de producto opcional que aparece al marcarlo).
- Marcado -> el doblaje NO traduce verbatim; usa la voz COLOMBIANA (`generar_dub`, oferta_2x1=True) que
  reescribe el guion y menciona el 2x1. Sin marcar -> traducción normal (`dub_video`, tu flujo).
- `/api/dub` + `_run_dub_job` ahora aceptan `oferta_2x1` + `product_desc` y ramifican. AVISO Juan: toqué
  tu panel p-dub (solo agregué checkbox+campo) y tu endpoint /api/dub (aditivo, no cambié el default).
- Verificado con captura que el checkbox y el campo se ven bien.

### 2026-07-01 · Claude (jackingshop1-cell) · 📢 CTA fijo obligatorio en TODOS los copies/guiones
Jack: todos los copies deben cerrar con esta frase EXACTA:
"por tu compra hoy te regalamos el envío, y para tu seguridad ante estafas pagas al recibir".
- **`scripts.py`**: constante `CTA_OBLIGATORIO` + helper `_con_cta()`. El prompt de `generate_scripts`
  obliga a cerrar con la frase exacta, y el post-proceso la garantiza (la añade si el modelo no la puso
  igual; no la duplica).
- **`dub_colombia.py`**: importa el CTA; el prompt obliga a que la ÚLTIMA fase termine con la frase
  exacta, + red de seguridad que la añade a la última fase si no aparece en ninguna.
- Cubre: guiones de voz (Cortar clips, links) + doblaje colombiano (Crear creativo, Clon, Doblaje 2x1).
- Los hooks (openers cortos) NO la llevan (es un cierre, no un gancho). Probado local (exacto, sin duplicar).

### 2026-07-01 · Claude (jackingshop1-cell) · 📥 Cortar clips: pegar links ahora solo BAJA (no corta de una)
Jack: al pegar links, cortaba de inmediato sin dejar configurar los ajustes. Ahora:
- El botón "Bajar de TikTok" (antes "Bajar y cortar") solo DESCARGA los videos y los agrega a la lista
  "Tus videos" (aparecen como "📥 nombre de TikTok", con × para quitar). Luego el usuario configura los
  ajustes y le da "Generar clips" (flujo normal).
- **NUEVO `/api/fetch-links`**: baja server-side y devuelve rutas (NO corta).
- **`/api/process` y `/api/scripts`**: `files` ahora opcional + aceptan `link_paths` (rutas ya bajadas,
  validadas dentro de UPLOAD_DIR por seguridad). El job corta archivos subidos + bajados juntos.
- Frontend: `linkVids[]` + render en la lista + buildForm manda `link_paths` + botón Generar se habilita
  con archivos O links. AVISO Juan: toqué tu sección Cortar clips (addFiles/renderFiles/buildForm/#go) y
  /api/process + /api/scripts (aditivo). Verificado UI + backend end-to-end.

### 2026-07-01 · Claude (jackingshop1-cell) · 🖤✨ REDISEÑO: tema premium negro + dorado + crema + animaciones
Jack pidió look profesional tipo constructor de páginas, con dorado/crema/negro y animado.
- **AVISO GRANDE Juan:** cambié TODO el tema visual del frontend (el bloque <style> principal + estilos
  de autoHero + un par de badges del Editor). NO toqué estructura/lógica/IDs — solo colores y animaciones.
  Si tienes cambios visuales en curso, coordinemos para no chocar.
- Paleta nueva en `:root` (variables, así cascada a todo): --bg negro, --txt crema, --accent dorado
  (#d4af37), --accent2 dorado claro, --ink negro para texto sobre dorado. Fondo con glows dorados sutiles.
- Animaciones: fade-up de entrada (cards/tabs), hover-lift en cards/botones/vcards, brillo que barre en
  botones, shimmer dorado en el logo, glow dorado en foco de inputs, scrollbar dorado.
- Arreglé choques del tema anterior (autoHero tenía fondo blanco/lavanda y botón morado; badges con
  texto blanco sobre dorado → ahora texto negro).
- Verificado con capturas: Cortar clips, Ajustes, Crear creativo — todo cohesivo y legible.

### 2026-07-01 · Claude (jackingshop1-cell) · ⚡ Descarga de links MUCHO más rápida (paralela)
- Jack: bajar los links en Cortar clips tardaba demasiado. Era SECUENCIAL (uno por uno, ~3.5s c/u).
- `downloader.download_urls` ahora baja en PARALELO (ThreadPoolExecutor, hasta 5 a la vez) + flags
  rápidos en yt-dlp (`-N 4` fragmentos paralelos, `--no-part`, formato progresivo mp4 PRIMERO para
  evitar el merge lento). Misma firma y retorno, solo más rápido.
- Medido: 4 videos en 4.4s (antes ~15-18s) = ~4x. Beneficia fetch-links, process-links y Descargar.
  AVISO Juan: optimicé tu downloader.py (interno, no cambié la interfaz).

### 2026-07-01 · Claude (jackingshop1-cell) · 🎞️ Fix: video se congelaba al final de la voz en off
- Jack: en Cortar clips (voz en off), al final el video se quedaba QUIETO mientras la voz seguía.
- Causa: `add_voiceover` y `add_voiceover_and_sfx` usaban `tpad=stop_mode=clone` = congelaban el último
  frame para cubrir la voz (más larga que el video).
- Fix: ahora el video hace LOOP (`-stream_loop -1` + `-shortest`) → sigue MOVIÉNDOSE (repite) hasta que
  termina la voz. Verificado: salida dura lo de la voz y el frame tardío = frame temprano (loopeó, no congeló).
- AVISO Juan: toqué tu assemble.py (add_voiceover / add_voiceover_and_sfx), interno.

### 2026-07-01 · Claude (jackingshop1-cell) · 🎯 Búsqueda TikTok = MISMO producto (IA verifica) + 2x1 en guiones
Jack: (1) la búsqueda daba productos parecidos pero en OTRA forma (pidió crema, salía bótox); quiere sí o
sí el mismo producto, en español y con poco texto, aunque tarde más. (2) 2x1 seleccionable en los guiones.
- **`tiktok_search.py` reescrito:** (a) Gemini mira la foto y saca keywords CON la forma/formato +
  descripción precisa; (b) trae hartos candidatos; (c) **verifica con Gemini** comparando la PORTADA de
  cada candidato contra la foto → solo deja los del MISMO producto (tipo Y forma), y ordena español +
  poco texto primero. Probado: crema→match, faja→rechazada, español+poco texto va primero.
  ⚠️ Cuesta más (una llamada de visión por candidato, ~12-15) pero acierta, como pidió Jack.
- **2x1 en guiones de voz en off:** `generate_scripts(oferta_2x1)` integra "pides una y llevas otra
  gratis"; checkbox "🎁 Oferta 2x1" en Cortar clips (junto a Voz en off) → /api/scripts. Probado.
- (Crear creativo YA tenía el 2x1.) AVISO Juan: toqué tu Cortar clips (checkbox+buildForm) y /api/scripts.

### 2026-07-01 · Claude (jackingshop1-cell) · 🔎➕ Búsqueda TikTok AMPLIADA + verificación más estricta
Jack: aún se colaba un producto que no era el suyo; quiere ampliar la búsqueda, que salgan escenas con
BENEFICIOS y que sean SÍ O SÍ su producto.
- **Amplía:** de la foto/nombre saco VARIAS consultas (producto + "resultados", "antes y después",
  "reseña", "cómo funciona") → junté ~48 candidatos únicos (antes 15). Videos que muestran el producto/beneficios.
- **Más estricto:** _verificar ahora usa portada + TÍTULO, exige match INEQUÍVOCO (misma forma) y devuelve
  `muestra_producto`. El ranking pone primero los que MUESTRAN el producto + español + poco texto.
- Tope de 24 verificaciones por búsqueda (acota costo). Solo mi módulo tiktok_search.py.
- ⚠️ Más candidatos = un poco más de tiempo/gasto por búsqueda, pero acierta mejor (lo que pidió Jack).

### 2026-07-01 · Claude (jackingshop1-cell) · 🚀 Motor de búsqueda TikTok MUCHO más potente
Jack: mejorar el motor de búsqueda para que encuentre. Descubrí que la API (tikwm) daba mucho más:
- **Paginación** (cursor) → `buscar_tiktok` ahora trae varias páginas.
- **Engagement + metadata** por video: play_count, digg, region, duration.
- `buscar`: junta multi-consulta × páginas → ~99 candidatos únicos (antes 15). PRE-ORDENA por región
  hispana (_ES_REGIONS) + más views (virales probados), descarta duraciones raras (4-120s), y verifica
  con visión los 28 MEJORES primero. Ranking final: muestra producto → español → poco texto → más views.
- Probado (sin visión): "crema veneno de abeja" → 99 candidatos, top = "Bee Venom Treatment Cream",
  "before and after", "Piel más lisa firme y glow" (su producto exacto + beneficios). Solo mi módulo.

### 2026-07-01 · Claude (juanesal-lab) · 🎨 Ads imagen v2: formatos falso-interactivos de la skill
Juan: "guíate de la skill no más" — los ads salían solo con "falso play". Implementé los formatos
falso-interactivos que define la skill `ads-disruptivos-imagen` (estilo-juan-aprendido.md):
- Compositor `componer_ad` ahora hace **dispatch por `formato`**: falso play ▶ / **quiz** (fila de
  pastillas + cursor-mano) / **slider antes/después** (línea + manija ◄► + ANTES/DESPUÉS) / **chat**
  (burbujas WhatsApp). Helpers nuevos: `_quiz`, `_quiz_rows`, `_slider`, `_chat_bubbles`, `_cursor_hand`,
  `_play_bar`.
- `_TOOL_V2` + `_SISTEMA_V2`: Claude ahora ELIGE `formato` de esos 4 y los VARÍA entre los 10 conceptos;
  para quiz da `quiz_opciones` (4-6 pastillas). Probado: 10 conceptos → {play:4, slider:2, quiz:2, chat:2}.
- Solo toqué `backend/pipeline/disruptive_images.py` y `frontend/index.html` (chip de formato + "Seleccionar todas").
- ⚠️ Falta (opcional, si Juan lo pide): formatos "cursor en botón", "post IG", "toca-para-revelar", y
  sellos aprobado/garantía. Generación real necesita créditos Google OK.

### 2026-07-02 · Claude (jackingshop1-cell) · 💲 Ads imagen: precio OPCIONAL (2x1 sin precio)
- Jack: en Ads imagen, que decir el precio sea OPCIONAL (que pueda salir la oferta 2x1 pero sin el precio).
- Frontend (p-disruptivo, de Juan): toggle "💲 Mostrar el precio en el ad" (default on). Si se apaga, se
  manda precio="" → no se dibuja el precio; las ofertas (2x1, etc.) siguen saliendo. Atenúa el campo.
- `_run_disruptive_v2_job` (app.py): si no hay precio, el CTA que diga "VER PRECIO" pasa a "PEDIR AHORA".
- AVISO Juan: toqué tu sección Ads imagen (toggle) y el job v2 (CTA). Verificado con captura.

### 2026-07-02 · Claude (jackingshop1-cell) · ✍️ Ads imagen: corrector de ORTOGRAFÍA antes de componer
- Jack: los ads salían con errores ("despideron", "almhadilla", "VER PREICO", "cámbilas").
- Nuevo `_corregir_ortografia_ads` (app.py): antes de componer, Gemini corrige SOLO ortografía/tildes
  del titular/sub/cta/quiz de cada concepto (sin cambiar sentido ni estilo). 1 llamada por lote.
- Probado con los typos reales de las imágenes de Jack → todos corregidos (despidieron, almohadilla,
  precio, cámbialas). Solo mi endpoint (no toqué disruptive_images.py de Juan).

### 2026-07-02 · Claude (juanesal-lab) · 🔍 Búsqueda TikTok: priorizar clips SIN texto sobrepuesto
Juan: en la búsqueda de TikTok, preferir videos sin subtítulos/captions SOBREPUESTOS (o muy pequeños),
distinguiéndolos del texto propio del producto (etiqueta/empaque). Cambié `tiktok_search.py`:
- `_verificar`: la visión ahora distingue TEXTO SOBREPUESTO digital (subtítulos/captions/stickers del
  creador) del texto REAL de la escena (etiqueta del producto) e IGNORA el del producto. Devuelve
  `texto_overlay` = nada/poco/mucho → score 2/1/0 (`_OVERLAY_SCORE`). Reemplaza el viejo `poco_texto`.
- Ranking nuevo: muestra producto → **SIN texto sobrepuesto** (nada>poco>mucho) → español → más views.
  Verificado: un clip "nada" gana aunque tenga menos views/no-español.
- Solo toqué `backend/pipeline/tiktok_search.py` (módulo de Jack). Jack: cambié la firma interna del dict
  de `_verificar` (`poco_texto`→`overlay` int); si lo usabas en otro lado, ajústalo.

### 2026-07-02 · Claude (juanesal-lab) · 🎨 Ads imagen: PIVOTE a full-prompt (como los ads ganadores de Juan)
Juan mostró 5 ads suyos GENIALES (hippo en el espejo, bus "¿para cuándo el bebé?", botón-bala, desinflar
como globo, flotar al techo). Todos son FULL-PROMPT: Google AI dibuja el ad COMPLETO (texto incluido) desde
un prompt rico → integrados y creativos. La app hacía lo contrario (escena + texto pegado/composite), por eso
salían menos arriesgados y con typos. Juan eligió full-prompt. Cambios:
- `disruptive_images.py`: `_SISTEMA` reescrito con sus 5 ejemplos como few-shot + 6 motores + disciplina de
  prompt (párrafo inglés, textos ES literales cortos entre comillas, cierre "render all embedded text
  crisply..."). `generar_conceptos` ahora usa link/ofertas/precio (y maneja "sin precio"). NUEVO:
  `generar_ad_fullprompt` (genera ad completo + VERIFICA ortografía del render + REGENERA si sale mal),
  `generar_ads_fullprompt` (paso 2 en paralelo), `_verificar_ortografia` (transcripción LITERAL + match por
  palabra — evita que Gemini "auto-corrija" al leer; caza typos tipo ESPEJRO≠ESPEJO).
- `app.py`: paso 1 → `generar_conceptos`; job → `generar_ads_fullprompt`; regenerar → `generar_ad_fullprompt`.
  Ya NO uso composite (`generar_ad_compuesto`/`generar_ads_v2`) ni el CTA-hack. AVISO Jack: tu
  `_corregir_ortografia_ads` quedó SIN llamar (en full-prompt el texto lo escribe Claude bien; la ortografía
  se controla en el render). Lo dejé definido por si lo reusas.
- Probado: 10 conceptos MUY surreales (espejo/globo, bombero/anillo, pecera-barriga, exprimir-trapo) + 1
  imagen real generada = integrada y creativa como sus ejemplos (con 1 typo que el verificador nuevo sí caza).
- ⚠️ BLOQUEO: el proyecto Google de la key llegó al TOPE DE GASTO MENSUAL (429 spend cap). Juan debe subirlo
  en https://ai.studio/spend para seguir generando. Falta validar el verificador en vivo cuando se destape.
- Los helpers del compositor (componer_ad/_quiz/_slider/_chat) quedan sin uso en este flujo (no los borré).

### 2026-07-02 · Claude (juanesal-lab) · ⚠️ Ads imagen: mensaje claro cuando Google topa el gasto
Juan probó y "no me generó las imágenes": los conceptos salían pero las 10 imágenes fallaban con
"No se generó". Diagnóstico: NO es bug — el proyecto de Google llegó al TOPE DE GASTO MENSUAL (429
spending cap). Mejoré el manejo en `disruptive_images.py`:
- `generar_imagen(..., errors=list)` guarda el error crudo; el tope de gasto ya NO se reintenta (fallaba
  rápido en vez de 4 backoffs inútiles). Nuevo `_error_amigable()` traduce el error.
- `generar_ad_fullprompt` guarda `variant["error"]` amigable; `generar_ads_fullprompt` devuelve ok=False +
  `error` cuando NINGUNA salió → el UI muestra en rojo "Se agotó el TOPE DE GASTO mensual de Google.
  Súbelo en ai.studio/spend". `/api/regenerate-image` también da el motivo real.
- Juan debe subir el tope en https://ai.studio/spend para que Nano Banana genere.

### 2026-07-02 · Claude (juanesal-lab) · 🔥 NUEVA pestaña Foreplay (biblioteca de ads ganadores)
Juan pidió conectar la API de Foreplay. Verificado que funciona (key válida, 10k créditos/mes) y CONSTRUIDO:
- NUEVO `backend/pipeline/foreplay_search.py`: `buscar_ads` (discovery/ads con filtros query/idioma/nicho/
  live/días-corriendo), `usage` (créditos), `descargar_video(s)` (baja el MP4 directo del CDN).
- `app.py`: endpoints `/api/foreplay-search`, `/api/foreplay-usage`, `/api/foreplay-thumb` (PROXY de
  miniaturas — el CDN bloquea hotlink desde el navegador), `/api/foreplay-clips` (descarga los elegidos →
  `process_job` los corta en clips). Key nueva `FOREPLAY_API_KEY` (provider "foreplay").
- Frontend: pestaña **🔥 Foreplay** — buscador + filtros, grid de tarjetas seleccionables (miniatura,
  badge "🔥 X días corriendo" = ganador, nombre, descripción, link), "cortar seleccionados en clips"
  (reusa `renderResults` + Editor), y campo de key en 🔑 Claves. PROBADO en navegador: busca, muestra
  miniaturas (vía proxy), selecciona, créditos OK.
- 🔒 BLINDAJE: `/api/save-key` ahora RECHAZA providers desconocidos (antes caían por defecto en
  GEMINI_API_KEY y podían sobrescribirlo).
- ⚠️⚠️ INCIDENTE (mi culpa): mientras cableaba esto, con un server viejo aún corriendo, guardar la key de
  Foreplay cayó en GEMINI_API_KEY y SOBRESCRIBIÓ la key de Gemini (se perdió, no había backup). Ya moví la
  de Foreplay a su lugar. Juan debe RE-PEGAR su key de Gemini en 🔑 Claves (esa estaba topada de gasto de
  todos modos → ideal una fresca de un proyecto con presupuesto). El "cortar en clips" de Foreplay necesita
  Gemini para funcionar.

### 2026-07-02 · Claude (jackingshop1-cell) · 🚫💲 NUNCA precio (global) + Cortar clips: tomas DIFERENTES
- **REGLA GLOBAL — nunca precio:** generate_scripts ahora PROHÍBE mencionar precio/cifras ($, COP,
  descuentos con número). Ads imagen: quité el campo/toggle de precio del frontend y fuerzo precio=""
  en /api/disruptive-angles (backend). dub_colombia ya decía "nunca precios". CTA "VER PRECIO" ya no
  aparece (precio vacío → mi sanitización lo cambia a "PEDIR AHORA").
  AVISO Juan: en tu generar_conceptos/generar_ads_fullprompt, asegúrate de que el prompt NO meta precio
  ni "VER PRECIO" (ya no le paso precio, pero el prompt podría inventarlo).
- **Cortar clips — tomas diferentes:** build_variations (assemble.py) armaba varias versiones con las
  MISMAS tomas top (subconjuntos solapados). Ahora: umbral de "pool grande" bajó a n≥18 (buckets
  disjuntos) y, con pocos clips, cada versión toma una VENTANA ROTADA de un orden distinto → tomas
  diferentes. Simulado n=10: solape bajó de ~100% a ~70%.
- PENDIENTE (siguiente, es grande): "Mi producto" con música auto por género + voz en off opcional +
  subtítulos opcionales + bajar volumen de los clips. Y disruptive/búsqueda están en tu refactor, Juan.

### 2026-07-02 · Claude (juanesal-lab) · 🎨 Ads imagen: video NATIVO + producto REAL pegado + más salvaje
Juan: (1) el producto no se parecía (la IA dibujaba un frasco cuando su producto es un stick), (2) poco
disruptivo, (3) el video falso "parecía publicidad" (banda de anuncio arriba). Eligió "video nativo". Cambios
en `disruptive_images.py`:
- `_SISTEMA` reescrito: REGLA MADRE "no debe parecer anuncio". FORMATO VIDEO = screenshot de un video REAL
  (escena a pantalla completa + chrome nativo: play ▶ + barra "0:08/2:04" + iconos volumen/fullscreen; titular
  como CAPTION sobre el video, NO banda de color). Empuje surreal aun en skincare (piel=desierto agrietado,
  cara=porcelana que se cae). Y el prompt ahora dice "NO product in image, leave lower-left clean".
- NUEVO `_pegar_producto` + `_recortar_producto`: se PEGA la foto REAL del producto abajo-izquierda (exacto),
  quitando fondo blanco y dejando SOLO el objeto más grande (cv2 connected components → descarta logos/
  watermarks sueltos, ej. el logo "Full K Bellos" que traía la foto).
- `generar_ad_fullprompt`: ya NO pasa el producto como referencia a Nano Banana (para que NO lo dibuje) y
  pega el real al final. Probado con el Medicube stick: video nativo + producto exacto sin logo + conceptos
  salvajes (rellenar con cemento, cara de pasa, GPS en la cara).
- ⚠️ Ojo: la ortografía del render aún puede fallar en textos largos (sub). Tip UX: subir foto de producto
  LIMPIA (sin logos) da mejor recorte.

### 2026-07-02 · Claude (jackingshop1-cell) · 🎙️ Doblaje FLUIDO (sin huecos largos entre frases)
- Jack: el doblaje dejaba silencios largos entre frase y frase. Causa: cada frase se anclaba al tiempo
  EXACTO de su fase del video (adelay=inicio); si la voz era más corta que la fase, quedaba dead air.
- Fix (dub_colombia): ahora las frases van SECUENCIALES — cada una arranca donde terminó la anterior +
  pausa natural corta (0.16s). `_voz` devuelve la duración y tiempos RELATIVOS; se anclan en secuencia.
  Los word_timings (subtítulos) se recalculan a la nueva posición. Verificado con audio sintético:
  frases seguidas, silencedetect NO halla silencios largos.
- No pude probar el dub completo end-to-end: el Gemini de Jack está en el TOPE de gasto (429). Cuando
  suba el cap, el doblaje ya sale fluido. Afecta Crear creativo, Clon y Doblaje 2x1.

### 2026-07-02 · Claude (juanesal-lab) · 🚀 Ads imagen: Nano Banana 2 + producto integrado por IA
Juan: las imágenes aún faltaban calidad/creatividad y ODIABA el producto pegado plano. Verifiqué que el
prompt SÍ sigue su skill y los conceptos son buenos → el cuello era el MODELO y mi pegado PIL. Decisiones de
Juan: usar Nano Banana 2 (aunque cueste) + integrar el producto con IA. Cambios en `disruptive_images.py`:
- `_IMG_MODEL = "gemini-3-pro-image-preview"` (Nano Banana 2 / Gemini 3 Pro Image). MUCHO más fotorrealista
  y **escribe el texto bien** (los typos del sub desaparecieron). Misma key de Google. Es más lento (~20-25s
  por imagen) y cuesta más por imagen (Juan lo aceptó).
- NUEVO `_integrar_producto_ia`: 2ª pasada — pasa el ad + la foto REAL del producto (limpiada con
  `_recortar_producto`) a Nano Banana 2 y le pide COLOCARLO integrado en la escena (luz+sombra reales,
  producto idéntico, sin tocar el resto). Reemplaza el pegado plano `_pegar_producto` (que Juan odiaba).
- `generar_ad_fullprompt` ahora termina con `_integrar_producto_ia` (2 llamadas Pro por imagen).
- Probado con el Medicube stick: calidad cine + producto integrado y fiel + ortografía perfecta. Enorme salto.
- ⚠️ AVISO: 10 imágenes = ~20 llamadas Pro → más gasto/tiempo. Ojo con el tope de Google (ai.studio/spend).

### 2026-07-02 · Claude (jackingshop1-cell) · 🔥 Foreplay: Ver/Descargar/Doblar + excluir Colombia
Jack: en Foreplay poder reproducir + descargar el video, y un botón "Doblar" que lo lleve a la sección
Doblar con el creativo ya cargado. Y regla global: SIEMPRE excluir Colombia (español pero sin CO).
- **AVISO Juan (toqué tu Foreplay):** cada card ahora tiene ▶️ Ver (reproduce inline vía proxy),
  ⬇️ Descargar, y 🎙️ Doblar. NO cambié tu búsqueda/selección, solo agregué botones al render.
- **NUEVO `/api/foreplay-video`** (proxy del MP4 del CDN de Foreplay, host-validado, con ?dl=1 para bajar).
- **`/api/dub`**: ahora acepta `video_url` (baja el creativo de Foreplay con fp.descargar_video y lo dobla).
  El botón Doblar guarda la URL, salta a la pestaña Doblar y muestra el creativo cargado. Verificado en vivo.
- **Excluir Colombia** en búsqueda TikTok (tiktok_search): saqué CO de _ES_REGIONS y filtro region=="CO".
  Nota Juan: en Foreplay ya va language=spanish; si su API tiene filtro de país, excluir CO también allá.

### 2026-07-02 · Claude (jackingshop1-cell) · 🌐 Clonar ganador: doblaje INTELIGENTE por idioma
Jack: en Clonar ganador, si el creativo está en OTRO idioma que se doble (traduzca la idea); si ya está
en español, que NO se re-doble y siga. (Él puso uno y "se mantuvo igual" porque solo doblaba con el flag.)
- **winner_clone**: nuevo `_es_espanol()` (heurística GRATIS, sin API, sobre el transcript que ya trae
  la narrativa). Ahora dobla si (no-español O flag forzado) y hay key; si ya es español, conserva la voz.
- Verificado el detector: 4/4 (español→conserva, inglés→dobla). Solo mi módulo.
- No pude correr el clon end-to-end (Gemini de Jack en tope 429). PENDIENTE aún: "Mi producto" (música
  auto + voz + subtítulos + bajar volumen) — es el siguiente build grande.

### 2026-07-02 · Claude (juanesal-lab) · 🎨 Ads imagen: producto OFF por defecto + botón "➕ Producto" por imagen
Juan: Nano Banana 2 va "súper mega bien", pero la 2ª pasada metía el producto en lugares raros (flotando
sobre la persona). Pidió: que NO aparezca el producto salvo que se vea bien. (Su skill igual dice "la escena
vende, el producto cierra"). Cambios:
- `generar_ad_fullprompt(..., integrar_producto=False)`: por DEFECTO los ads salen LIMPIOS sin producto
  (más barato: 1 llamada Pro en vez de 2). Solo integra si se pide.
- `_integrar_producto_ia`: colocación más estricta (producto PEQUEÑO ~20%, sobre una superficie real del
  tercio inferior, NUNCA sobre personas/cara/manos/texto/botones).
- NUEVO endpoint `/api/disruptive-add-product` (job_id, index) + botón **"➕ Poner mi producto"** por imagen
  en el frontend → Juan lo agrega SOLO donde se vea bien (su criterio). `disAddProd` recarga con cache-bust.
- Así nunca queda mal puesto y el lote sale limpio/rápido.

### 2026-07-02 · Claude (jackingshop1-cell) · 🔊 Librería de SFX ampliada + dinámica
- Jack: más efectos y más dinámicos (riser, pop, whoosh, boom, ding...) tipo CapCut.
- Generé 12 SFX royalty-free con ffmpeg (sin copyright, sin API): riser, riser_fast, whoosh, whoosh_fast,
  swoosh, pop, click, boom, bass_drop, ding, sparkle, impact. En assets/sfx/.
- phase_effects: cada fase ahora usa un SFX distinto y con sentido: HOOK→riser, SOLUCIÓN→boom,
  PRUEBA→ding, DESEO→sparkle, CTA→swoosh (DOLOR sin golpe). Cortar clips (orchestrator) rota entre los 12
  en las transiciones -> más variedad automática. Verificado.

### 2026-07-02 · Claude (jackingshop1-cell) · 📦🎵 "Mi producto": música automática por género + bajar volumen
Jack: Mi producto solo cortaba clips (sin música/voz/subs, volumen alto). Empecé el build:
- **música AUTO por género:** la IA (Gemini) elige 1 de 4 géneros según el producto (energico/alegre/
  emotivo/elegante) → genera la pista con ElevenLabs → la mezcla en cada versión BAJANDO el volumen de
  los clips + loudnorm (-16 LUFS, audible y parejo). En producto_clips.py (`_elegir_genero`,
  `_musica_y_volumen`). Toggles en la UI: "🎵 Música automática", "🔉 Bajar volumen de los clips".
- Verificado end-to-end: género elegido "energico", música generada + mezclada, nivel -20 dB (audible).
  AVISO Juan: toqué producto_clips.py + /api/producto-clips + la sección Mi producto (2 toggles).
- PENDIENTE (siguiente increment): voz en off opcional + subtítulos opcionales en Mi producto (necesitan
  guion/transcripción por versión — build aparte).

### 2026-07-02 · Claude (juanesal-lab) · 🔧 Revisión completa: fixes visuales + bugs + seguridad + limpieza
Juan pidió revisar TODO (3 revisores en paralelo). Arreglado SIN romper lo que funciona:
**Visual (frontend):** copy viejo de Ads imagen actualizado (6→10 conceptos, "Nano Banana 2 dibuja el ad",
video nativo, sin COD) en intro/botón/progreso/label; quité oferta "50% OFF" (choca con "nunca precio");
**FIX inputs diminutos**: agregué `input.full,textarea.full,select.full{width:100%}` global (la clase `.full`
solo tenía width dentro de `.autoOpts`) → el textarea de producto, links, etc. ahora a ancho completo.
**Bugs internos:** (1) botón "➕ Producto" daba éxito FALSO aunque fallara → `_integrar_producto_ia` ahora
devuelve None en fallo (bloqueo/cuota/sin foto) y el ad queda intacto; el endpoint responde 502 real. (2)
`generar_imagen` y `_integrar_producto_ia` crasheaban en `candidates[0]` con bloqueo de contenido → guardado
+ mensaje "blocked/safety". (3) `status()` daba KeyError entre paso1/paso2 de Ads imagen → `.get()`. (4)
race en `/api/last-project` → `list(JOBS.items())`.
**Seguridad:** `/api/editor-export` NO confinaba rutas (leía archivos arbitrarios) → ahora filtra por
`_within(WORK_DIR/UPLOAD_DIR)`; `_safe_path`/`_safe_link_paths` sin separador (hermanos tipo 'work2') →
`_within` con `os.sep`; SSRF por redirect en proxies Foreplay + `descargar_video` → `allow_redirects=False`;
`/api/foreplay-video` cargaba el MP4 entero en RAM → `StreamingResponse`; tope de 200MB por video.
**Calidad:** `_CIERRE` decía "professional advertising composition" (chocaba con "video nativo") → ahora
"authentic organic social-media video screenshot NOT a polished ad".
**Limpieza (código muerto confirmado por grep):** quité imports sin usar (JSONResponse, suggest_sfx,
sound_effect); `_corregir_ortografia_ads` (de Jack, muerta tras full-prompt); endpoint `/api/process-links` +
`_run_links_job` (el frontend usa fetch-links+process); docstring con modelo viejo.
⚠️ PENDIENTE (identificado, NO tocado por riesgo): el cluster muerto grande en `disruptive_images.py`
(generar_conceptos_v2, generar_ads_v2, generar_ad_compuesto, componer_ad + ~14 helpers de compositor,
_SISTEMA_V2, _TOOL_V2, generar_ads_disruptivos, _pegar_producto) — ~400 líneas muertas, limpiar en pasada
aparte. También: "Clon Ganador" enterrado en pestaña Claves sin botón de nav; Guía sin pestañas nuevas;
JOBS nunca se limpia (fuga de RAM en uso largo). Todo eso queda para después.

### 2026-07-02 · Claude (jackingshop1-cell) · 💬 Selector de 5 estilos de subtítulos (mejor CTR)
- 5 estilos seleccionables (los más usados/mejor CTR en TikTok/Meta): Hormozi (palabra x palabra keyword
  amarilla), Karaoke, Caja (highlight_box), Bold (bold_outline), Amarillo (yellow_highlight).
- Selector en la UI de Crear creativo (autoCapStyle) y Cortar clips voz en off (capStyle).
- Cableado: `render_versions` ahora acepta `caption_style` y quema los subtítulos con
  `caption_styles.burn_word_captions(style=...)` (motor de 10 estilos) en vez de add_captions; fallback
  al viejo si falla. /api/scripts y /api/auto ya pasan caption_style. Verificado UI + compila.
  AVISO Juan: cambié el motor de subtítulos en render_versions (orchestrator) + 2 selectores en el front.
- Foreplay/Colombia: HONESTO — todavía NO excluye Colombia (Foreplay no expone país; solo idioma español).
  Coordinar contigo, Juan, para el filtro de país. TikTok search sí excluye CO.
- PENDIENTE: voz en off + subtítulos en "Mi producto" (build pesado, necesita guion/transcripción).

### 2026-07-02 · Claude (juanesal-lab) · 🧹 Limpieza del código muerto en disruptive_images.py (poco a poco)
Juan pidió limpiar el código muerto de `disruptive_images.py` de a poco sin romper nada. Lo hice en 4
bloques, de ABAJO hacia arriba (para no mover líneas), verificando el import DESPUÉS de cada uno:
1. `generar_ads_disruptivos` + `generar_ads_v2` (flujo viejo completo).
2. `_pegar_producto` (pegado plano, reemplazado por `_integrar_producto_ia`).
3. Cluster V2: `_SISTEMA_V2`, `_TOOL_V2`, `generar_conceptos_v2`, `generar_ad_compuesto`.
4. Compositor viejo: `componer_ad` + 14 helpers (`_hex`,`_wrap`,`_fit`,`_star`,`_stars`,`_starburst`,
   `_play_button`,`_arrow`,`_cursor_hand`,`_play_bar`,`_quiz`,`_quiz_rows`,`_slider`,`_chat_bubbles`).
+ Quité imports que quedaron sin uso: `math`, `ImageDraw`, `ImageFont`, `ImageOps` (de PIL solo queda `Image`).
Resultado: 889 → 413 líneas (~475 muertas fuera). VERIFICADO: import OK tras cada bloque + test funcional
(generar_conceptos devuelve 10). Lo VIVO intacto: generar_conceptos, generar_ad(s)_fullprompt, generar_imagen,
_verificar_ortografia, _norm_words, _integrar_producto_ia, _recortar_producto, _error_amigable, _SISTEMA/_TOOL/_CIERRE.

### 2026-07-02 · Claude (jackingshop1-cell) · 🎯 Ads imagen: 2 plantillas GANADORAS fijas de primeras
Jack pasó 4 ads de referencia y pidió quedarnos con los 2 mejores como los primeros que se generan.
Elegí (mejores para dropshipping COD, sin precio, replicables): (1) CONTRARIAN "NO COMPRES ESTO" estilo
Rheal, (2) PRUEBA SOCIAL con capturas de comentarios estilo OLIVEA. Descarté HOOP GANG (mostraba precio,
look catálogo) y COLOSTRUM (redundante con el contrarian + top-funnel).
- AVISO Juan: edité el prompt del sistema de tu skill (disruptive_images `_SISTEMA`): agregué las 2
  plantillas FIJAS (variantes 1 y 2, limpias/creíbles, reservan zona del producto, sin precio) y la
  instrucción final (1-2 fijas, 3-10 surreales). No toqué la lógica.
- Verificado con Claude real: #1 sale contrarian ("NO LA USES."), #2 prueba social, #3+ surreales.
  (Nota menor: Claude devolvió 11 en la prueba; el front igual las lista.)

### 2026-07-02 · Claude (juanesal-lab) · 🧭 Pendientes de la revisión: Clon a su pestaña + Guía + GC de JOBS
Seguí con los pendientes que había dejado anotados de la revisión:
- **Clon Ganador desenterrado**: `/api/clone` ("Clon con mi producto") estaba dentro del panel de Claves
  SIN botón de nav → nadie lo veía. Lo moví a su propia pestaña `p-clone` con botón. Aclaré nombres: el
  nav "Clonar ganador" (que en realidad era `/api/swap`) ahora dice "Reemplazar producto" (= su panel).
  Verificado en navegador: las 2 pestañas funcionan y Claves quedó limpio.
- **Guía actualizada**: la lista "Qué hace cada pestaña" ahora incluye TODAS (Ads imagen, Editor, Foreplay,
  Buscar TikTok, Clon con mi producto) con nombres correctos; "Crear creativo" ya no dice "UN creativo";
  Claves menciona Foreplay.
- **Fuga de RAM de JOBS**: nuevo `_gc_jobs(keep=80)` — en `status()` (oportunista) borra los trabajos MÁS
  VIEJOS ya terminados si hay >80; NUNCA toca los 'running'. Conservador para no romper flujos en curso.
Todo verificado (import OK + navegador). Sin tocar lógica que funciona.

### 2026-07-02 · Claude (juanesal-lab) · 🎨 Pulir Ads imagen: variedad de formatos + mecanismos + más surreal
Juan: pulir los Ads imagen. Diagnóstico: los conceptos salían 7/10 en formato "video" (monótono) y a veces
tibios ("persona preocupada mirándose"). Reforcé `_SISTEMA`/`_TOOL` en disruptive_images.py:
- Quité el sesgo "FORMATO VIDEO (el más usado)". DISTRIBUCIÓN OBLIGATORIA: máx 4 'video'; el resto reparte
  entre slider/quiz/chat/cursor (mín 4 formatos). El `formato` ahora es una palabra exacta del enum.
- Agregué campo `mecanismo` al schema (antes salía vacío) — cada concepto un motor distinto de los 6.
- SURREAL OBLIGATORIO: mín 6/10 deben ser metáfora física imposible (piel=desierto, cara=estatua, reflejo=
  momia/hipopótamo); "alguien preocupado en el espejo" NO cuenta.
Probado (mismo producto, serum vit C): antes {video:7} → ahora {video:5, slider:2, quiz:1, chat:1, cursor:1},
mecanismos poblados y variados, titulares mucho más salvajes (cara-atlas, "¿quién es esa momia?", "se oxidó
como manzana", "mis manchas me escribieron"). Solo prompt — sin tocar el flujo de generación.

### 2026-07-02 · Claude (juanesal-lab) · 🔁 NUEVO: motor de VARIACIÓN de creativo (creative scaling) — parte HOOK/VOZ/COPY
Juan pidió una sección para ESCALAR un ganador: de UN creativo validado sacar N variaciones (varía hook +
tomas + voz + copy, ~80% video nuevo, mata ad-fatigue). 2 modos: "solo hook" y "hook + tomas". Ángel toma el
motor de VIDEO/escenas; YO tomé el motor de HOOK/VOZ/COPY. Ya construí mi parte:
- NUEVO `backend/pipeline/creative_variator.py` → `generar_variaciones(arco_texto, product_desc, anthropic_key,
  page_text="", n=6, con_escenas=True)`. Claude conserva el ARCO validado (HOOK→DOLOR→SOLUCIÓN→DESEO→CTA) y
  varía: **hook** (0-3s), **guion** de voz, **copy_pantalla**. Devuelve
  `[{hook, angulo, guion, copy_pantalla, escenas:[{fase, buscar}]}]`.
- **`escenas` = EL PUENTE PARA TI, ÁNGEL**: por cada fase dice QUÉ toma buscar (ej. "primer plano mujer
  frustrada frente al espejo"). Tu motor: por variación → por fase toma `buscar` → `tiktok_search.buscar()`
  encuentra la toma → `downloader` la baja → `assemble` la empalma en el arco + narra el `guion`
  (voiceover) + quema `copy_pantalla` como subtítulo. Modo "solo hook": mantén el cuerpo, cambia solo la
  toma+texto+VO del HOOK. Modo "hook+tomas": reemplaza la toma de CADA fase.
- Probado: 5 variaciones con hooks muy distintos + guiones + briefs de escena coherentes por fase. Módulo
  puro (solo Claude), NO toca video/app/frontend → cero colisión con lo tuyo.
- PROPUESTA: sección nueva "🔁 Variar creativo" con toggle solo-hook / hook+tomas, que llame mi
  `generar_variaciones` + tu motor de video. ¿La armas tú (ya vienes en video/assemble) o la cableo yo y tú
  metes el motor de escenas? Coordinemos por aquí.
  🤝 ÁNGEL: vi tu PENDIENTE "variar el hook del winner (buscar hooks en TikTok por ángulo)" — ¡es justo el
  motor de VIDEO que complementa esto! Mi `creative_variator.generar_variaciones` te da los ÁNGULOS/hooks +
  el brief `escenas[].buscar` por fase para que tu búsqueda en TikTok sea dirigida. Enchufémoslos.

### 2026-07-02 · Claude (jackingshop1-cell) · 🎬🔊 Cortar clips: 8 videos + música de fondo + SFX en cortes + más variedad
Jack: Cortar clips repetía escenas, solo 2 SFX, sin música, y quería 8 videos.
- **8 versiones** (antes 6): _N_VERSIONS y build_variations NV=8 (+ nombres G_mixta, H_alterna). Más
  variedad: umbral de pool disjunto en n≥24; con pocos clips, ventana rotada por versión.
- **Música de fondo + SFX en cortes:** nuevo `assemble.add_music_sfx` (música baja + SFX variados de la
  librería de 12 en cada corte, CONSERVANDO el audio del clip + dynaudnorm). Se aplica en `_run_job`
  (`_agregar_musica_sfx`) tras process_job (genera 1 pista con ElevenLabs por producto). Fix: `probe` no
  estaba importado en assemble (NameError silencioso) + `_has_audio_stream` ahora usa ffprobe directo.
- Verificado E2E: /api/process → versiones=8, paso "Poniendo música" corrió, mezcla con audio OK.
  AVISO Juan: toqué assemble.py (add_music_sfx, NV=8), orchestrator (_N_VERSIONS=8), app.py (_run_job).
- PENDIENTE (grandes, siguientes): (1) PREVIEW visual de los estilos de subtítulos; (2) banner opcional
  2x1/envío-gratis ARRIBA con IA que lo suba para no tapar nada; (3) feature "variar el hook del winner"
  (4 videos, buscar hooks en TikTok por ángulo, traducir, tapar texto en pantalla).

### 2026-07-02 · Claude (juanesal-lab) · 🎲 Regenerar INTELIGENTE: "otro ángulo diferente" (no repite lo rechazado)
Juan: cuando no le gusta un ad/ángulo, que el cambio sea INTELIGENTE y NO repita lo mismo que no gustó.
- `generar_conceptos(..., evitar=[], n=10, plantillas_fijas=True)`: nuevo `evitar` (titulares ya mostrados) →
  el prompt le dice a Claude "NO repitas estos ni variaciones; da ángulos/dolores/escenas TOTALMENTE
  distintos". `plantillas_fijas` para saltarse las 2 fijas al regenerar. Probado: evitando 4 títulos, dio 3
  conceptos nuevos sin relación (casa propia, modo ahorro de batería, leopardo).
- NUEVO endpoint `/api/disruptive-swap-concept` (job_id, index): genera 1 concepto NUEVO evitando TODOS los
  titulares del lote + lo renderiza + reemplaza ese slot. `disruptive-angles` ahora guarda `_producto`/
  `_page_text` para poder pensar el ángulo nuevo.
- Frontend Ads imagen: botón por imagen **"🎲 Otro ángulo diferente"** (`disSwapConcept`), además del 🔄
  Regenerar (mismo concepto) y ➕ Producto.
- Mismo `evitar` agregado a `creative_variator.generar_variaciones` (para variar HOOKs de video sin repetir).
- ÁNGEL: si tu motor de video re-varía y algo no gusta, pásame los hooks rechazados en `evitar` y te doy otros.

### 2026-07-02 · Claude (jackingshop1-cell) · 👁️ #1 Preview visual de los estilos de subtítulos
- Endpoint `/api/caption-preview?style=X` renderiza un PNG de muestra ("MIRA ESTO GRATIS") en el estilo
  elegido (usa caption_styles._render_wordgroup). En la UI: al cambiar el selector de estilo (Cortar clips
  y Crear creativo) se actualiza una miniatura de cómo se ven los subtítulos. Verificado los 5 estilos.

### 2026-07-02 · Claude (jackingshop1-cell) · 🏷️ #2 Banner de oferta ARRIBA (opcional, IA lo ubica sin tapar)
- NUEVO `offer_banner.py`: pill roja "ENVÍO GRATIS · PAGAS AL RECIBIR" + "OFERTA 2X1" (Poppins, como la
  foto de Jack). `safe_top_y()` le pregunta a Gemini a qué y-fracción ponerlo para NO tapar cara/producto.
- Conectado a Crear creativo (auto_studio, paso 6b opcional `banner_oferta`) + toggle "🏷️ Banner arriba"
  en la UI + /api/auto. Verificado: el banner sale arriba sobre el video (arreglé un bug de -map que
  descartaba el overlay). Demo ~/Downloads/prueba/BANNER_oferta.png.
- AVISO Juan: nuevo módulo + paso en auto_studio + toggle. #3 (variar hook) = tu creative_variator es el
  cerebro; falta la capa de VIDEO (buscar toma/hook en TikTok, traducir, tapar texto, 4 videos) — coordinamos.

### 2026-07-02 · Claude (juanesal-lab) · 🔎 Búsqueda TikTok: matcheo por FORMA FÍSICA (no solo categoría)
Juan: la búsqueda no matcheaba bien — subió un LÁSER cuadrado/clamshell para hongos de uñas y le devolvió
un aparato RECTANGULAR que ni era láser. Causa: la verificación comparaba "misma categoría" pero NO la forma
física del dispositivo. Reforcé `tiktok_search.py` (módulo de Jack):
- `analizar_foto`: ahora describe la FORMA FÍSICA exacta del aparato (cuadrado/rectangular/tipo lápiz/pinza…),
  color y rasgos (botón/luz), y da keywords específicas (tipo + uso, ej. "laser hongos uñas" no solo "laser").
- `_verificar`: match=true SOLO si la portada muestra el MISMO producto con la MISMA FORMA/FORMATO FÍSICO
  (un dispositivo cuadrado ≠ rectangular ≠ tipo lápiz; láser ≠ otro aparato). "Sé DURO: mejor descartar."
- Probado con el láser real: descripción captó "forma de pinza/clamshell, blanco, luz azul"; la búsqueda
  completa puso de #1 el dispositivo EXACTO (video UGC mostrándolo), ya no un rectangular random.
- AVISO Jack: toqué tu tiktok_search.py (2 prompts: analizar_foto y _verificar). No cambié el flujo ni el
  ranking, solo la estrictez del matcheo por forma.

### 2026-07-02 · Claude (juanesal-lab) · 🎞️ Cortar clips: "gifs" ahora WebM 1:1 ≤500KB + con SENTIDO (por fase)
Juan (con mucho cuidado de no romper el flujo que funciona): los "gifs" (que él llama gif pero el formato es
otro) que sean WebM en vez de WebP, 1:1, ≤500KB buena compresión, y que tengan SENTIDO (problema/solución/
producto). Cambios SOLO en la sección de clips SUELTOS (las versiones principales intactas):
- `gif_export.py`: NUEVO `to_webm()` (ffmpeg VP9, recorte cuadrado 1:1, sube CRF si excede 500KB, sin audio).
  Dejé `to_animated_webp` intacto por si acaso. `webm_available()` chequea ffmpeg.
- `orchestrator.py`: los clips sueltos ahora se eligen por FASE en round-robin (problema=ni producto ni uso,
  solucion=shows_use, producto=product_visible) para que los gifs cuenten la historia; el gif se hace con
  `to_webm` (.webm); cada loose_clip lleva `fase` + `fase_label`.
- Frontend: label "GIF (WebM)", badge de fase por clip, Guía actualizada.
- PROBADO E2E real (process_job con 3 videos): ok=True, 8 versiones + 16 clips, gifs .webm todos ≤500KB, 1:1
  540x540, calidad nítida. Las fases se diversifican con Gemini activo (sin Gemini todas caen en "problema").
- AVISO Jack: toqué gif_export.py (+to_webm) y orchestrator.py (selección de loose_set + gif webm). NO toqué
  build_variations ni las versiones — solo los clips sueltos/gifs.

### 2026-07-02 · Claude (jackingshop1-cell) · 🔍 Análisis de 24 creativos reales que NO funcionaron + fix del texto viejo
Jack pasó 5 carpetas de creativos de prueba (almohadillas, veneno de abeja, plagas). Los analicé (frames
hook/medio/final). Hallazgos:
1. **PROBLEMA PRINCIPAL (en TODOS): el subtítulo/texto VIEJO del original NO se tapaba** → quedaban 2
   textos encima (nuevo + viejo). Se ve como repost robado → mata rendimiento y Meta lo marca.
   CAUSA RAÍZ: winner_clone (Clonar ganador) llamaba `traducir_texto_pantalla` en modo "traducir", que
   DEJA el texto que ya está en español (no lo tapa).
   FIX: nuevo modo `"limpiar"` en text_translate — traduce lo que está en OTRO idioma y TAPA (blur) lo
   que ya está en español o no tiene traducción. winner_clone ahora usa modo="limpiar". Prompt mejorado:
   campo `idioma` por bloque + instrucción de reportar la BANDA completa del caption (no palabra suelta).
   Lógica verificada; el e2e con Gemini tarda por el upload del video (58MB), no lo corrí completo.
2. **Muchos duran 30-47s** (uno 46.7s) → LARGO para TikTok/Meta. Recomendación pendiente: acortar
   (winner_clone conserva el largo del ganador). 
3. auto_studio (Crear creativo) SÍ tapa con banda continua (detect_subtitle_band), pero puede escaparse
   texto ARRIBA (ej. "Crema para eliminar lunares" en el top del bee venom) — mejora futura: banda top.
   AVISO Juan: toqué text_translate.py (modo "limpiar" + prompt) y winner_clone.py (usa limpiar).

### 2026-07-02 · Claude (jackingshop1-cell) · ⚡🧽 Mejor resultado: pacing punchy + tapar texto ARRIBA
Siguiendo el análisis de los 24 creativos que no funcionaron, mejoré para "mejor resultado":
- **(A) PACING punchy**: nuevo `assemble.punch_pace` — si el creativo dura >~22s, lo acelera un pelín
  (video+audio EN SYNC, tope 1.35x para que la voz no suene atropellada). Corre AL FINAL (todo quemado)
  para no desincronizar subtítulos. Cableado en winner_clone (paso 10) y auto_studio (paso 7b).
  Probado real: almohadillas 38.5s → 28.6s en sync.
- **(B) Tapar texto ARRIBA**: nuevo `subtitle_band.detect_top_band` (EAST local, sin Gemini) detecta
  captions/títulos quemados pegados al top (que detect_subtitle_band ignora a propósito), con umbral de
  persistencia para no tapar texto de una sola toma. auto_studio ahora tapa AMBAS bandas (arriba+abajo).
  Probado real: bee venom "Crema para eliminar lunares..." (arriba) → tapado; almohadillas (abajo) → sin
  falso positivo. Verificado con frame: top limpio, producto intacto.
  AVISO Juan: toqué subtitle_band.py (detect_top_band) + auto_studio.py (2 bandas + pacing) + assemble.py.

### 2026-07-02 · Claude (jackingshop1-cell) · 🔎 Buscar TikTok: llegar a más links (11 → 21) del MISMO producto
Jack: pedía 30 links y llegaban ~11. Diagnóstico: (1) las búsquedas eran frases LARGAS y específicas →
tikwm devolvía poquísimos y repetidos (~44 candidatos); (2) solo se verificaban los primeros 28; (3) la
verificación exigía la MISMA MARCA/frasco (rechazaba el mismo producto de otro vendedor).
Cambios en tiktok_search.py:
- analizar_foto: pide 7-9 búsquedas CORTAS y VARIADAS, MEZCLA español + INGLÉS (mucho contenido es en
  inglés) + términos amplios. _expandir: agrega versiones más cortas/amplias (recorta la frase) + más
  sufijos de demostración/compra.
- Gathering en PARALELO (10 términos × 3 páginas) y verifica un pool GRANDE escalado al count (max(60,
  count*4)) con 10 workers, no 28.
- _verificar: sigue estricto en CATEGORÍA + PROPÓSITO + forma (crema≠pastilla/bótox; aparato = misma
  forma física), pero YA NO exige misma marca/etiqueta → otro vendedor del MISMO producto SÍ cuenta.
- Probado real (foto del frasco bee venom, count=30): 11 → 21 verificados. (El techo real depende de
  cuántos videos de ese producto exacto existan en TikTok; productos nicho pueden dar ~20-25.)
  AVISO Juan: toqué tiktok_search.py (analizar_foto, _expandir, buscar, _verificar). No cambié el shape.

### 2026-07-03 · Claude (jackingshop1-cell) · 🎙️💬 Mi producto: VOZ EN OFF + subtítulos seleccionables (pendiente #2)
- Toggle "🎙️ Voz en off" en Mi producto: guiones POR VERSIÓN con UNA llamada a Gemini
  (scripts.generate_scripts, reglas de oro garantizadas: sin precio, CTA exacto vía _con_cta) →
  narración colombiana (voiceover.synthesize_with_timestamps, TTS en paralelo, voz kate/juan_carlos)
  → mezcla voz clara + música baja (add_voiceover_and_sfx, voz 1.0/música 0.16) → subtítulos palabra
  x palabra con los 5 estilos elegibles (burn_word_captions) + preview en la UI (patrón capStyle).
- producto_clips.py: _musica_y_volumen dividida en _generar_musica + _mezclar_musica (mezcla intacta);
  nueva _voz_y_subtitulos con try/except por versión (si falla una, queda como estaba); perilla interna
  settings["vo_guiones"] (0=un guion por versión; N=narraciones cicladas para controlar costo ElevenLabs).
- app.py /api/producto-clips: Forms voz_en_off/voz/caption_style/subtitulos (validados con whitelist).
- RETROCOMPATIBLE: con voz_en_off=False el flujo es EXACTAMENTE el de antes (música sola).
- Verificado por 2 agentes: E2E real con 2 videos de bee venom → 8 versiones con voz+subs, frames
  mirados (hormozi OK), ffprobe voz presente, CTA exacto en los guiones, cero precio. Muestras en
  ~/Downloads/prueba/MIPRODUCTO_voz_subs_A.mp4 y _C.mp4. Revisor: 28/28 tests con mocks (retrocompat,
  ciclado con TTS parciales, sin mezcla doble de música, JS con node --check, whitelists del endpoint).
- Costo de la prueba: ~6 llamadas Gemini flash + 1 música + 2 TTS. En producción: 8 TTS/job por defecto
  (vo_guiones interno permite bajarlo; no expuesto en UI aún).
- AVISO Juan: NO toqué orchestrator/assemble/caption_styles/voiceover — solo producto_clips.py, el
  endpoint /api/producto-clips y la pestaña Mi producto del front.

### 2026-07-03 · Claude (jackingshop1-cell) · ⚡🎲 Cortar clips MÁS RÁPIDO (76.8s→45.3s en prueba real) + versiones DIFERENTES entre sí
Quejas de Jack: (A) Cortar clips / Mi producto muy lentos; (B) las 8 versiones repetían los mismos clips.
VELOCIDAD (misma prueba: 3 videos bee venom, gemini on, sin blur/música/VO — 76.8s → 45.3s):
- `orchestrator.analyze_select`: los videos se analizan EN PARALELO (antes uno por uno) → 18.5s→9.8s.
- `analyze.analyze_video`: `detect_scene_cuts` (ffmpeg) corre en paralelo con la pasada OpenCV del mismo video.
- `gemini_rank`: NUEVO `_call_rest_fast` — la llamada de rank va por REST con thinkingBudget=0 (el SDK
  google-genai 0.8.0 no expone ese parámetro) → 27s→3-7s LA MISMA respuesta; si falla, cae al SDK como antes.
- `assemble`: `add_voiceover`, `add_voiceover_and_sfx` y `concat_clips` ahora codifican con `venc()`
  (GPU videotoolbox) en vez de libx264 → voz en off ~0.7s/versión (probado, h264+aac ok).
- `orchestrator.render_versions`: PLAN PRIMERO — se calcula qué cortes usan las versiones (nueva
  `assemble.plan_variations`) y los clips sueltos ANTES de tapar textos → el masking (EAST/Gemini/capitán)
  procesa SOLO esos cortes; además el plan usa los tiempos ORIGINALES (antes se planeaba después del
  masking, cuando start ya estaba remapeado a 0 y el orden cronológico se perdía).
- WORKERS con GPU: probé 3 vs 4 vs 5 encodes paralelos videotoolbox → sin diferencia (el hardware
  serializa sesiones); se queda en 3.
VARIEDAD (antes: 2 ganchos distintos en 8 versiones, solape medio 55%, había pares 100% idénticos →
ahora: 8 ganchos ÚNICOS, solape medio 43%, máx 86%):
- `analyze._split_and_add`: un tramo bueno largo ahora emite hasta 5 ventanas NO solapadas (antes solo
  la mejor y el resto se botaba) → más material bruto para el pool.
- `assemble.plan_variations` (extraída de build_variations, misma lógica en pool grande): en la rama de
  POCOS clips el gancho ROTA entre los mejores por score (antes siempre el máximo → todas abrían igual)
  y el resto se elige priorizando los clips MENOS usados por versiones anteriores (mínimo solape de
  conjuntos). `build_variations` acepta `version_orders=` opcional (retrocompatible).
VERIFICADO: py_compile ok; corrida E2E real antes/después con frames mirados (nitidez/encuadre ok, webm
≤500KB ok); corrida con blur_captions=True (EAST, sin capitán) ok=True 8 versiones; add_voiceover(_and_sfx)
probado con audio sintético. Server reiniciado.
AVISO Juan: toqué analyze.py (_split_and_add multi-ventana + scene cuts paralelos), orchestrator.py
(analyze_select paralelo + plan-primero en render_versions), assemble.py (plan_variations nueva,
build_variations con version_orders opcional, venc() en add_voiceover/add_voiceover_and_sfx/concat_clips)
y gemini_rank.py (REST rápido con fallback). NO toqué gif_export (tus flags VP9 ya estaban), ni las
firmas públicas: process_job/analyze_select/render_versions/venc/punch_pace intactas. Shape de manifests
sin cambios. NO commiteado (lo sube Jack cuando lo pruebe).
[Revisión (2º agente) de lo de arriba — 2 fixes aplicados]: (1) la key de Gemini en _call_rest_fast iba
en la URL (?key=) → ahora va por header x-goog-api-key (no queda en logs); (2) el muestreo del capitán en
render_versions usaba los índices DISPERSOS de used_all (podía revisar 0 cortes o TODOS = llamadas a
Claude de más) → ahora usa la posición secuencial. Tests: pools sintéticos n=1..40 sin versiones vacías
ni índices inválidos; fallback REST→SDK probado (timeout/500/JSON malo); corrida real $0 con EAST:
47.4s, 8 versiones ok, remapeo del plan post-masking verificado frame a frame.
### 2026-07-03 · Claude (juanesal-lab) · 🔎🎞️ Búsqueda TikTok honesta (✅/⚠️) + gifs por FASE real (Gemini visión)
Juan: la búsqueda seguía dando productos equivocados y los gifs eran "cortes súper x" sin sentido.
**Búsqueda TikTok** (`tiktok_search.py` + UI):
- CAUSA RAÍZ del producto equivocado: cuando quedaban pocos verificados, el código RELLENABA en silencio
  hasta 20 con candidatos SIN verificar (clínicas etc). Ahora cada link lleva `verificado_producto` y la UI
  los separa: ✅ confirmados (ambos jueces) primero, luego "⚠️ estos NO se pudieron confirmar, revísalos".
- Fix del 2º juez (Claude): mandaba la referencia PNG como image/jpeg → 400 en TODAS (por eso no filtraba).
  Nuevo `_media_type()` por bytes mágicos. Portada cacheada (`_cover_bytes`) para no bajarla 2 veces;
  Claude juzga top-10 con 5 workers. Validado: 57s (antes 134), confirmado primero, clínicas marcadas ⚠️.
- Merge con lo de Jack: sus 10 consultas cortas ES+EN × 3 páginas (quedó lo suyo, era superset del mío).
**Cortar clips — gifs con SENTIDO** (`phase_classify.py` NUEVO + orchestrator):
- Antes la fase salía de 2 booleans (shows_use/product_visible) → casi todo caía en "problema" = cortes random.
- Ahora GEMINI VISIÓN clasifica (1 sola llamada, frame medio de c/clip chico) en: problema / solucion /
  funcionamiento / producto / caracteristicas / resultado. Round-robin cuenta la historia; archivos
  `clip_XX_<fase>.mp4/.webm`; labels 🔴🟢⚙️📦🔎✨ en la UI. Fallback a la heurística si no hay key (no rompe).
- VALIDADO E2E con Gemini: grid 2x2 → problema=piso sucio, solución=pistola limpiando, funcionamiento=
  conectando boquilla, producto=presentándolo a cámara. WebM 1:1 todos ≤500KB.
- AVISO Jack: toqué tiktok_search (dual juez + etiquetas; tu expansión de consultas quedó intacta),
  orchestrator (bloque de loose clips) y nuevo phase_classify.py. Las 8 versiones NO se tocaron.

### 2026-07-03 · Claude (juanesal-lab) · ✂️ Cortar clips PRO: cero repetición + edición TikTok + captions que contrastan con el producto
Juan: los cortes se repetían muchísimo (aun con 30+ creativos), quería edición "súper profesional" y que las
captions contrastaran con el color del producto. 3 mejoras (validadas con métricas):
1. **Dedup multi-firma** (`analyze.segment_signatures` NUEVO + `_select_for_target`): antes 1 aHash del frame
   medio → la MISMA escena en otro archivo/segundo no se detectaba (los creativos de proveedor comparten
   metraje = raíz de la repetición). Ahora 3 firmas (20/50/80%) y basta 1 coincidencia para descartar.
2. **Edición pro** (`assemble.order_version`): HOOK (toma más fuerte) → CUERPO (tomas cortas primero = ritmo;
   greedy que NUNCA pone 2 tomas seguidas del mismo video) → PAYOFF (cierra con el producto en uso).
   Métricas con pool de 36 segs/12 fuentes: overlap entre versiones 0% (antes ~70%), 3/28 consecutivos
   mismo video, 6/8 versiones cierran con payoff.
3. **Captions con contraste dinámico** (`caption_styles`): NUEVO `accent_for_video()` (color dominante HSV
   ponderado por saturación, frames centrales) + paleta curada de 7 acentos → elige el tono MÁS OPUESTO
   (rojo→cian, azul→amarillo, rosado→verde neón, verde→fucsia; validado). `set_accent()` global; se calcula
   1 vez en `render_versions` sobre el primer montaje. Estilos y preview siguen igual si no hay acento.
- AVISO Jack: toqué `order_version` (tu build_variations — el bucket disjunto tuyo quedó intacto),
  `_select_for_target` (multi-sig) y caption_styles (acento opt-in, default None → tus 5 estilos idénticos).

### 2026-07-03 · Claude (juanesal-lab) · 🔎 Búsqueda TikTok: de 1 a 9 confirmados (verificación PROFUNDA)
Juan: "solo 1 de los 30 me lo encuentra bien". Diagnóstico + 3 fixes en `tiktok_search.py`:
1. **Ranking por relevancia de TÍTULO antes de gastar visión**: el pool a verificar se llenaba de virales
   de salones/clínicas (ordenado por views); los videos del producto (vendedores TikTok Shop) nunca se
   verificaban. Ahora `_title_score` (términos de queries+desc) ordena el pool primero.
2. **VERIFICACIÓN PROFUNDA** (`_verificar_video` NUEVO): la portada muchas veces NO muestra el producto
   (sale el pie/antes-después) → falsos rechazos. Para candidatos con título prometedor no confirmados por
   portada, se BAJA el video (play url de tikwm, tope 25MB, máx 12) y Gemini juzga 3 frames de ADENTRO.
   Los confirmados así llevan `_deep` y NO se re-juzgan por portada (Claude los habría rechazado).
   OJO: la descarga SIGUE redirects (tikwm→CDN siempre redirige; con allow_redirects=False moría todo).
3. **Jueces conscientes del USO**: lámpara de secar esmalte ≠ láser para hongos (el título desempata), sin
   exigir marca (otro vendedor del mismo producto cuenta), "estricto pero justo" (UGC en mano/ángulo).
   Claude ahora juzga top-20 (antes 10). El relleno ⚠️ ahora completa hasta `count` (siempre etiquetado).
RESULTADO con el láser de Juan: antes 1/30 confirmado → ahora **9/9 confirmados y TODOS el dispositivo real**
(GoSpring device, fungus remover, naillight...), 92s. AVISO Jack: toqué tu _verificar (línea de USO) y el
bloque de verificación de buscar(); tu expansión de queries ES+EN quedó intacta (es la que alimenta esto).

### 2026-07-03 · Claude (jackingshop1-cell) · 🔍 Buscar creativos: TikTok + FOREPLAY a la vez (foto + nombre)
Pedido de Jack: mandar foto + nombre del producto y recibir los creativos de ese producto en AMBAS
fuentes para armar los clips.
- NUEVO backend/pipeline/creative_search.py → `buscar_creativos()`: analiza la foto UNA sola vez
  (tiktok_search.analizar_foto) y con esos términos busca TikTok y Foreplay EN PARALELO.
  Foreplay: 2-4 términos (español primero, heurística local sin IA), deduplicado entre términos,
  Colombia excluida adentro de buscar_ads (no toqué foreplay_search de Juan — solo lo consumo);
  verificación de MISMO producto sobre thumbnails con el MISMO juez de TikTok (_verificar), tope
  24 thumbnails; lo no juzgable queda honesto con badge "⚠️ sin verificar".
- backend/app.py: NUEVO POST /api/creative-search (nombre, count, fp_count, foto). Los endpoints
  /api/tiktok-search y /api/foreplay-search siguen IGUAL (aditivo).
- tiktok_search.buscar: nuevo param opcional `analisis=` (recibe el dict de analizar_foto ya calculado
  para no repetir la llamada). Sin él, todo igual que antes.
- Frontend: pestaña "🔎 Buscar TikTok" → "🔍 Buscar creativos": campo nombre + resultados en 2 grupos
  (🎵 TikTok con links/badges como antes; 📚 Foreplay con grilla de cards, ▶️ ver, ⬇️ descargar vía
  /api/foreplay-video, botón copiar links de video para 📥 Descargar / Mi producto). Guía actualizada.
- VERIFICADO: py_compile ok; firmas cruzadas contra el tiktok_search post-merge de Juan (ok, inspect);
  JS 9/9 bloques node --check ok; corrida E2E real en modo barato (sin IA): TikTok 8 links + Foreplay
  8 ads sin señales colombianas, shape correcto; server reiniciado sirviendo /api/creative-search y la
  pestaña nueva. (La verificación con foto/Gemini usa el mismo _verificar de siempre.)
- AVISO Juan: cero cambios en foreplay_search.py; en tiktok_search.py solo el param opcional analisis=.
  Resolvimos también el merge de tus commits de hoy (Cortar clips PRO + verificación profunda)
  conservando ambos trabajos (velocidad+variedad nuestro y lo tuyo — todo compila y probado).

### 2026-07-03 · Claude (jackingshop1-cell) · 🌳 Config para sesiones paralelas (worktrees) + push de lo acumulado
- `.gitignore`: + `.claude/worktrees/` (los worktrees de Claude Code no ensucian el `git status`).
- NUEVO `.worktreeinclude` (.env, .env.local): cada worktree nuevo recibe las API keys automáticamente.
- Sin tocar código. Se sube también lo que estaba local sin push: el merge 126c938 (Cortar clips PRO +
  búsqueda profunda de Juan ⊕ velocidad+variedad+voz en off nuestro) y Buscar creativos (e044706).
- AVISO Juan: tus worktrees también quedan ignorados con esto y tu `.env` local se copia igual a tus
  worktrees; el `.env` sigue SIN subirse a git (cada quien el suyo).

### 2026-07-03 · Claude (jackingshop1-cell) · 🔍✨ Buscar creativos: preview ▶️ + 🔄 cambiar + 🎯 "más con este ángulo"
Pedido de Jack sobre la pestaña nueva: (1) preview para reproducir cada creativo ANTES de descargarlo,
(2) botón para reemplazar uno que no guste por OTRO en su mismo puesto, (3) botón para buscar MÁS
creativos con el mismo ángulo de venta del que gustó.
- Los resultados de TikTok ahora son CARDS (grilla fpGrid) con portada, views, badges ✅/⚠️ y botones:
  ▶️ Ver (reproduce el mp4 directo de tikwm ahí mismo, con fallback "ábrelo en TikTok" si el CDN
  falla), 📋 copiar link, 🔄 cambiar, 🎯 Más así. Los cards de Foreplay ganaron 🔄 y 🎯 (ya tenían ▶️/⬇️).
- NUEVO POST /api/creative-more (fuente tiktok|foreplay, nombre, desc, terminos, angulo, excluir, n,
  foto=basename guardado por creative-search en uploads/tksearch): creative_search.buscar_mas() busca
  n creativos NUEVOS excluyendo los ya mostrados. 🔄 = n:1 sin angulo (reusa los términos originales,
  CERO IA extra); 🎯 = n:6 con angulo (1 llamada Gemini flash saca el ángulo del título → términos
  nuevos). Con foto: verifica MISMO producto con _verificar (tope chico max(12, n*3)); sin foto: sin IA.
  Sin Colombia en ambos caminos (region CO fuera + _es_colombiano de Juan en Foreplay).
- Frontend: estado vivo window._tkS (excluidos por fuente para que lo cambiado no vuelva a salir) +
  tkPaint() re-pinta desde el estado; el 🔄 hace splice en el mismo slot; el 🎯 agrega al final del grupo.
- /api/creative-search ahora devuelve foto (basename), desc y variants (los términos) para alimentar
  los botones. _buscar_foreplay ganó param excluir (default None: idéntico a antes).
- VERIFICADO: py_compile ok; JS 9/9 node --check; funcional real: 🔄 TikTok devolvió video NUEVO
  respetando excluidos (con play para el preview), 🔄 Foreplay ok, 🎯 con Gemini sacó el ángulo
  ("casa llena de cucarachas" → "Pest control secret"/"Adiós plagas secreto") y trajo 4 creativos de
  ese ángulo; server reiniciado sirviendo /api/creative-more; UI verificada con screenshot en Chrome
  (cards y botones en ambos grupos ok).
- AVISO Juan: cero cambios en foreplay_search.py ni tiktok_search.py; solo creative_search.py (mío),
  el endpoint nuevo en app.py y el script de p-buscar en el front.
### 2026-07-03 · Claude (juanesal-lab) · 🔎🔥 Búsqueda TikTok ahora TAMBIÉN busca en Foreplay (mismo pool, misma verificación)
Juan: que la búsqueda de videos use Foreplay además de TikTok. Hecho en `tiktok_search.py`:
- NUEVO `_foreplay_candidatos(queries, foreplay_key)`: consulta la biblioteca de ads GANADORES de Foreplay
  con las mismas keywords (3 primeras, ES+EN), normaliza cada ad al formato de candidato (url = mp4 directo
  descargable, cover = thumbnail, play = mp4 para verificación profunda, plays = días corriendo ×1000 como
  señal de ganador, source = "foreplay") y lo suma al MISMO pool → pasa por la MISMA verificación
  (portada Gemini + video por dentro + juez Claude).
- `buscar(..., foreplay_key=None)`; `/api/tiktok-search` pasa `_load_foreplay_key()`. UI: badge 🔥 en los
  resultados de Foreplay + URLs largas truncadas.
- PROBADO con el láser: 8 confirmados = 5 de Foreplay (ads REALES de dropshippers vendiendo el mismo láser:
  Dolccia, Bio Guate — creativos ya probados) + 3 de TikTok. 132s. Costo: ~3 búsquedas Foreplay (~30 créditos)
  por búsqueda con foto.
- AVISO Jack: solo agregué; tu flujo de queries y el pool quedan igual cuando no hay key de Foreplay.

### 2026-07-03 · Claude (juanesal-lab) · ✂️ Clips: pool 60→98 + dedup justo | 🔎 Ficha visual PROFUNDA de la referencia
Juan: (1) con 30 videos los cortes SEGUÍAN repitiéndose; (2) la búsqueda se acercó pero confirmaba productos
parecidos-no-iguales → pidió análisis profundo de la imagen de referencia.
**Clips (orchestrator):** causa = pool capado en 60 con 56 necesarios (8 versiones × 7) + dedup FLOJO que
botaba tomas válidas (1 frame parecido bastaba; con 30 videos del mismo producto eso mata el pool → reciclaje).
Fix: pool = min(100, max(NV*cpv+16, fuentes*3+NV)) → 98 con 30 videos; duplicado SOLO si ≥2 de las 3 firmas
coinciden o 1 frame casi idéntico (<4 bits). E2E ok (8 versiones, 24 clips).
**Búsqueda (tiktok_search.analizar_foto):** ahora hace ANÁLISIS VISUAL PROFUNDO tipo perito → FICHA:
categoría | forma+tamaño | colores por parte | MARCA/texto visible (transcrito) | rasgos distintivos
(bisagra/botón/luz/ranura) | uso | **NO CONFUNDIR CON** (productos parecidos-distintos). Los 3 jueces
(portada Gemini, video-por-dentro, Claude) comparan contra la ficha y rechazan lo que parezca un
"no confundir con". Probado con el láser: la ficha transcribió hasta el texto de la caja y listó
"oxímetro de pulso, lámpara UV, masajeador" como confusables.
- AVISO Jack: toqué _select_for_target (pool+dedup) y los prompts de analizar_foto/jueces. Nada de tu flujo.

### 2026-07-03 · Claude (juanesal-lab) · 🎨 Ads imagen: REGLA DE PROFUNDIDAD DEL ÁNGULO (fin de lo "genérico")
Juan: la imagen salía genérica — mostraba el producto pero no AHONDABA en el dolor/solución del ángulo.
Diagnóstico (inspeccionando prompts generados): los conceptos dramatizaban el dolor pero NADA obligaba a que
la imagen contara el ángulo completo (dolor → giro a la solución) → escenas intercambiables entre productos.
Fix en `disruptive_images.py` (_SISTEMA + _TOOL):
- 2 campos NUEVOS OBLIGATORIOS por variante: `dolor_visual` (cómo se VE el dolor específico del ángulo —
  "persona preocupada" no sirve) y `solucion_visual` (cómo se INSINÚA la transformación en la MISMA imagen:
  el giro, el alivio, el antes/después o la zona donde entra el producto como héroe).
- REGLA DE PROFUNDIDAD: "alguien que vea SOLO la imagen debe poder decir QUÉ duele y QUÉ se promete; si la
  escena sirve para cualquier producto del nicho → es genérica, recházala". El prompt DEBE poner en escena
  dolor_visual Y solucion_visual.
- VALIDADO con imagen real (láser hongos): "TIENES UN INQUILINO EN LA UÑA / Y no paga arriendo / SACARLO YA"
  → monstruito-hongo acampando sobre la uña dañada (dolor) + haz láser rojo entrando a sacarlo (solución).
  El ángulo se entiende sin leer texto. Solo prompt/schema — el flujo de generación no cambió.

### 2026-07-03 · Claude (juanesal-lab) · 🎨 Ads imagen: fix Regenerar (persistencia) + ✏️ "Ajustar con instrucción"
Juan: el botón Regenerar no funcionaba + quería darle una instrucción a una imagen que le gusta para acomodarla.
- **CAUSA de Regenerar roto**: los JOBS viven solo en MEMORIA → cada reinicio del server (hoy hubo muchos)
  dejaba la página del usuario apuntando a un job inexistente → 404 en Regenerar/➕Producto/🎲Otro ángulo.
  FIX: `_persist_disruptive(job_id)` guarda el job a `work/<id>/job.json` (al crear conceptos, al terminar
  el lote y tras cada mutación) y `_get_job()` lo recupera de disco si no está en memoria. `status()` y los
  4 endpoints de mutación usan `_get_job`. Probado: persistir → borrar de memoria → recuperar OK.
- **NUEVO ✏️ Ajustar con instrucción**: botón por imagen → prompt de texto libre ("pon la luz más roja",
  "quita el texto de arriba") → `editar_imagen_ia()` (Nano Banana 2 image-edit: cambia SOLO lo pedido,
  conserva composición/texto/chrome) → endpoint `/api/disruptive-edit-image`. PROBADO con imagen real:
  "monstruito asustado corriendo con su maleta + láser más grande" → editó exacto eso y conservó el resto.
- AVISO Jack: nuevos _persist_disruptive/_get_job en app.py (solo Ads imagen); editar_imagen_ia en
  disruptive_images.py; botón disEdit en el frontend.

### 2026-07-03 · Claude (jackingshop1-cell) · 🔀 Merge #2 del día: tu pool TikTok+Foreplay ⊕ nuestro Buscar creativos
- `tiktok_search.buscar`: conviven los DOS parámetros nuevos — `analisis=` (nuestro: creative_search no
  re-analiza la foto) y `foreplay_key=` (tuyo: ads de Foreplay al pool). creative_search NO pasa
  foreplay_key (su grupo Foreplay va aparte con _buscar_foreplay) → cero duplicados.
- `index.html` (tkPaint): quedó la UI de 2 grupos con cards de la pestaña Buscar creativos; tu bloque de
  filas usaba `resto`/`j` que ya no existen en ese scope. Tu pool mixto sigue VIVO en /api/tiktok-search
  (lo consume el otro flujo del front); si quieres el 🔥 de "viene de Foreplay" en esa vista, es re-agregarlo ahí.
- Verificado: py_compile 5/5 tocados + node --check 9/9 bloques + cero marcas de conflicto. Nada tuyo de
  backend se perdió (disruptive_images y app.py auto-merge limpio).

### 2026-07-03 · Claude (juanesal-lab) · 🎙️ Guiones v2: investigación de 24 ads GANADORES + arco por fases + anti-baneo
Juan: guiones mucho más dinámicos, divididos por fases (hook/problema/solución...), validados con creativos
REALES (métricas) y respetando políticas Meta/TikTok con eufemismos ("gordo"→"como un hipopótamo").
**INVESTIGACIÓN**: bajé 24 transcripciones de ads en ESPAÑOL de Foreplay con 14-85 DÍAS corriendo (= pagando
tráfico hoy; beauty/pets/fashion) y destilé los patrones al framework.
**assets/guion-framework.md** — nueva sección "FRAMEWORK v2": EL ARCO GANADOR (7 fases con timing),
LOS 12 HOOKS que están ganando (con ejemplo real c/u), REGLAS DE DINAMISMO (staccato en ráfagas + frases
conversacionales, PERO que gira, números concretos, honestidad calculada, social proof conversacional) y el
🛡️ DICCIONARIO ANTI-BANEO (mismo golpe con palabras seguras: hipopótamo, "tu amiguito ya no responde",
"tu cara dice algo diferente"; "ayuda a" en vez de curas; reportes en vez de promesas con plazo).
**scripts.py (generate_scripts)**: framework cap 13k→22k (¡se estaba cortando!); prompt exige arco + hook del
banco + especificidad obligatoria (prohibidas frases de catálogo) + FUSIÓN de fases en videos cortos (3-4
momentos bien desarrollados, no 7 telegramas) + diccionario anti-baneo; ritmo 2.3→2.6 palabras/seg (el real
de los ganadores); salida ahora incluye `fases:{hook,problema,giro,producto,prueba,cta}` (retro-compatible,
`texto` sigue igual). Mismas reglas aplicadas a creative_variator (guiones de variaciones).
Iterado 3 veces contra producto delicado (gel reductor): salió fluido, con voz de Juan, específico y
policy-safe. AVISO Jack: toqué scripts.py (prompt/cap/ritmo) y el framework .md — tu flujo de VO no cambia,
el campo nuevo `fases` es opcional.

### 2026-07-03 · Claude (juanesal-lab) · 🚨 ENCONTRADO Y MUERTO el bug de los cortes repetidos (era el LOOP de la voz en off)
Juan (con toda la razón, furioso): "en el MISMO video aparece como 4 veces el mismo corte". EVIDENCIA en su
file(49).mp4: cada corte se repetía con desfase constante de +10.8s → el MONTAJE ENTERO se reproducía otra
vez. NO era la selección de clips: era `add_voiceover`/`add_voiceover_and_sfx` con `-stream_loop -1` en el
video — si la voz duraba más que el montaje, el video ENTERO se repetía 2-4 veces. Y el montaje quedaba corto
porque se armaba por NÚMERO de clips (cpv), no por duración (9 clips de ~1.2s = 10.8s vs voz de 20s).
FIX doble en `assemble.py`:
1. **Loop ELIMINADO**: el video ya NO se repite jamás; si faltara video se sostiene el último frame
   (tpad stop_mode=clone) + corte EXACTO a la duración real de la voz (`_dur_flag` con ffprobe — probe()
   fallaba con audio puro y el -shortest con filtro no cortaba fino).
2. **Versiones por DURACIÓN**: cada versión acumula clips hasta target*1.15+1s (no un número fijo) →
   el montaje SIEMPRE alcanza la voz. Si el bucket disjunto no da, completa con clips no usados; si el pool
   se agota, puede reusar de OTRAS versiones pero NUNCA dentro de la misma.
VERIFICADO: caso reproducido (video 8s + voz 20s) → salida 20.00s exactos, CERO repeticiones de contenido
(detector perceptual); mock 60 clips cortos → 8 versiones de 24-25s, 0 clips repetidos internos, overlap
entre versiones mínimo. AVISO Jack: toqué add_voiceover, add_voiceover_and_sfx y plan de versiones
(duración-based); tu rotación de hooks y usage-based del pool chico siguen ahí.

### 2026-07-03 · Claude (juanesal-lab) · 🏠✨ HOME PREMIUM nuevo: saludo dinámico + auto concepto 3D + 2 tarjetas módulo
Juan pidió una primera impresión "inolvidable": home tipo sistema operativo premium (filosofía Porsche/Linear/
Apple/Tesla), NO e-commerce. Construido como CAPA de entrada (sección #home) SIN tocar la app existente:
- **Saludo dinámico** con shimmer dorado (rota entre 4 frases según la hora, fade suave).
- **AUTO CONCEPTO 3D 100% original** (Three.js CDN via importmap, procedural — sin modelos externos):
  silueta GT extruida con clearcoat negro, cabina de vidrio, línea de luz + faros dorados emisivos, rines
  dorados, piso reflectivo con halo dorado, RoomEnvironment (reflejos dinámicos), niebla, ACES tone mapping.
  Interactivo: OrbitControls (giro 360°, zoom con scroll/pinch, damping), auto-rotación continua,
  "respiración" sutil, y reacciona al puntero y al giroscopio del celular. Si no hay WebGL/CDN → fallback
  de glow (no rompe nada).
- **2 tarjetas módulo premium** (solo dos, como pidió): "Buscar Productos" → p-foreplay; "Crear Creativos" →
  p-crear. Hover con profundidad, sheen que barre, iconografía SVG line-art, micro-flecha.
- **"¿Cómo funciona?"** editorial: 3 pasos (Descubre/Crea/Inspírate-Foreplay) con revelado escalonado al
  scroll (IntersectionObserver).
- **Transiciones**: home sale con scale+blur → app entra con fade; el LOGO "CreativeMaxing" (h1) ahora es
  clickeable y vuelve al home. `.wrap` arranca oculto. prefers-reduced-motion respetado.
- VERIFICADO en navegador: carga, 3D renderiza y rota, saludo rota, tarjetas entran a su tab, logo vuelve,
  reveal del scroll funciona, consola sin errores de la app.
- AVISO Jack: todo AUTOCONTENIDO al inicio del body (sección #home + 2 scripts); lo único tocado de lo
  existente: `.wrap` display:none inicial + onclick en el h1. Los tabs/paneles intactos.

### 2026-07-03 · Claude (juanesal-lab) · 🎬 Búsqueda: B-ROLL de apoyo adaptado al ángulo (manual)
Juan: además de los 30 videos del producto exacto, 10 escenas de B-ROLL/stock de TikTok adaptadas al ÁNGULO
(skincare→antes/después facial y rutinas; gadget→manos usándolo/limpieza satisfactoria) para intercalar y
hacer el video más dopamínico. MANUAL por ahora (él elige; si le gusta lo hacemos automático).
- `tiktok_search.buscar_broll(ref_desc, nombre, api_key, n=10)`: Gemini inventa 6 búsquedas de escenas de
  APOYO (no del producto) desde la ficha del producto → tikwm en paralelo → filtra duración/CO → ordena por
  views → 1 por autor (variedad). `buscar()` lo incluye como `broll:[...]` (fluye por /api/tiktok-search y
  por el nuevo /api/creative-search de Jack vía tk.broll).
- UI (tkPaint): grupo 3 "🎬 B-roll de apoyo" con explicación + copiar links + lista. Probado: crema
  antiarrugas → 9 escenas ASMR skincare/ojeras con views altos.
- AVISO Jack: solo agregué broll al final de buscar() y el grupo 3 en tkPaint; tu refactor creative_search
  intacto. VIENEN EN CAMINO (agente mapeando): tamaño de subtítulos seleccionable, SFX variados en TODAS
  las secciones, clon con detección precisa, y garantía dura de no-repetición.

### 2026-07-03 · Claude (juanesal-lab) · 🎛️ MEJORA GENERAL: subtítulos con TAMAÑO en todas las secciones + SFX variados + Clon con cobertura total
Paquete grande de Juan (con mapa previo de un agente para no romper nada). REGLAS NUEVAS PERMANENTES:
(1) JAMÁS repetir clips dentro del mismo video; (2) toda mejora se propaga a TODAS las secciones de video.
**Subtítulos — tamaño elegible (pequeño/mediano/GRANDE→default MEDIANO):**
- `caption_styles`: `TAMANOS` + `cap_size` en render_caption/_render_wordgroup/burn_word_captions (escala
  size0 + max_h + min_size juntos — si no, el auto-fit anula el efecto). Default mediano = ya no gigantes.
- Cableado COMPLETO: orchestrator.render_versions, auto_studio (generar_creativo_auto + _burn_subs),
  producto_clips, winner_clone, endpoints (/api/auto, /api/scripts, /api/producto-clips, /api/clone,
  /api/caption-preview?size=) y UI (selector de tamaño junto a CADA selector de estilo + preview en vivo).
- 🐞 BUG CAZADO por el agente: el selector de ESTILO de Cortar clips se enviaba pero /api/scripts no lo
  declaraba como Form → SIEMPRE salía "hormozi". Arreglado (caption_style+caption_size en el endpoint).
**SFX variados (queja: "siempre suena el mismo"):**
- assemble.add_voiceover_and_sfx: orden fijo alfabético → BARAJADO por render.
- phase_effects: `_SFX_FAMILIA` — cada fase acepta una FAMILIA de SFX equivalentes (boom→boom/impact/
  bass_drop, etc.) y elige AL AZAR entre ellos → cada render suena distinto. Aplica a AUTO y CLON.
**Clon / Reemplazar (estaba "muy suave"):**
- REGLA de cobertura total: el producto AJENO no queda visible NUNCA — sin dinámicas hace corte duro a
  quieta; red de seguridad final cubre con CUALQUIER toma propia (las de Juan SÍ pueden repetirse).
- Detección más fina: 32→48 frames de muestreo (step mín 0.3s) en detect_product_ranges.
- Clon ahora con selector de ESTILO y TAMAÑO de subtítulos (antes hardcodeado "karaoke").
Verificado: imports OK, preview S/M/G escala bien (grid visual), UI sin errores JS, _pick_sfx devuelve
familia variada. AVISO Jack: toqué caption_styles/orchestrator/auto_studio/producto_clips/winner_clone/
product_swap/assemble/phase_effects/app.py/index.html — todo con defaults retro-compatibles.

### 2026-07-03 · Claude (juanesal-lab) · 🛍️ NUEVO MÓDULO "Crear Landings" — FASE (a): UI + tipo + credenciales Shopify
Superprompt de Juan: 3er módulo al nivel de Buscar/Crear — Landing Page y Advertorial desde SUS estructuras
validadas → copy/imágenes con Gemini → gate de aprobación → Shopify Admin API como PLANTILLA NUEVA (jamás
tocar lo existente). Decisiones aprobadas: mismo tema publicado (archivos nuevos prefijo cm-), imágenes a
Shopify FILES, optimización de peso obligatoria. Fase (a) implementada:
- NUEVO `backend/pipeline/shopify_admin.py`: `validar()` (request de prueba, errores en español),
  `tema_publicado()` (usa SHOPIFY_THEME_ID o detecta role=main), `nombre_unico()` (cm-<tipo>-<slug>-<fecha>),
  `crear_asset()` (SE NIEGA a sobreescribir si el key existe — regla de oro), `subir_imagen_files()`
  (GraphQL staged upload → Files/CDN, reporta peso_kb).
- Credenciales con el MISMO patrón de keys: SHOPIFY_STORE_DOMAIN / SHOPIFY_ADMIN_API_TOKEN (prefijo shpat_)
  / SHOPIFY_THEME_ID (opcional) en .env vía 🔑 Claves (tarjeta nueva con 3 campos + pill) + `has_shopify`
  en /api/config + `/api/shopify-check` (valida + detecta tema).
- UI: 3ª tarjeta en el HOME premium ("Crear Landings") + pestaña 🛍️ + panel: selector de tipo (2 tarjetas
  premium), botón "Verificar conexión", formulario de insumos (producto/link/precio EXACTO/oferta/fotos).
  El botón Generar está DESHABILITADO hasta que Juan pase sus estructuras validadas (regla 9: no inventar).
- `README-LANDINGS.md`: cómo crear la custom app + scopes mínimos + qué crea/qué JAMÁS toca.
- Verificado: smoke shopify-check sin creds → error claro en español (no 500); home con 3 módulos; panel OK.
- PENDIENTE de Juan: las estructuras validadas (landing + advertorial) y las secciones 3-7 del superprompt
  (se cortaron 85 líneas en el paste). Fases (b)-(g) tras recibirlas.

### 2026-07-03 · Claude (juanesal-lab) · 🛍️ Landings: PLANTILLAS MAESTRAS destiladas (landing 9 secciones + advertorial)
Retomada la tarea interrumpida: analizadas las 9 imágenes de la landing validada de Juan (Aceite de
Ricino, ~/Downloads/landing) + su página viva buenatienda.com.co/products/crema-veneno-de-abeja-2x1.
HALLAZGO: la página viva es estructura ADVERTORIAL (headline editorial "Por qué dermatólogas...",
comparativa, "así funciona", dermatóloga, muro 15 reseñas con 2 imperfectas, oferta 2x1) → tenemos
ejemplo real de AMBOS tipos. Nuevo `assets/landing-templates/`:
- `README.md`: convención {{variables}} vs estructura fija, reglas duras de generación (producto
  SIEMPRE con fotos reales — cero etiquetas garbled tipo "Paro la plai", texto CO sin errores,
  aspect ratios, gate obligatorio), psicología del orden.
- `landing-page.md`: las 9 secciones con formato/objetivo/layout/fórmulas de copy (hero 2:3 →
  grid 4 testimonios 16:9 → mecanismo+antes/después 9:16 → comentarios FB 9:16 (con aviso legal
  FIJO) → caso individual 1:1 → bundles 2:3 (PRECIOS EXACTOS de Juan) → bonos 2:3 → VS 9:16 →
  cómo usar ILUSTRADO 9:16). Las imágenes NO llevan botón; el theme inserta CTAs entre secciones.
- `advertorial.md`: arco editorial de 8 bloques con fórmulas literales del original (kicker,
  headline "X en vez de Y después de los 40", mecanismo honesto, Dra. con credenciales, regla de
  realismo: 2/15 reseñas de 3-4★). ⚠️ Pendiente que Juan CONFIRME que esa es SU estructura advertorial.
- `referencia-landing/seccion-01..09.jpg` (~2.5MB): referencias de estilo para Gemini (ya no
  dependemos de Downloads).
SIGUE PENDIENTE de Juan: secciones 3-7 de su superprompt (85 líneas cortadas) → luego fases (b)-(g).
AVISO Jack: solo archivos NUEVOS en assets/landing-templates/; cero código tocado.

### 2026-07-03 · Claude (juanesal-lab) · 🔁 VARIAR EL HOOK del winner — capa de video COMPLETA (solo hook / hook + tomas)
Jack se quedó sin tokens antes de pushear su capa de video → la construí completa para no frenar.
Si tu sesión revive con TU versión de hook_variator: la mía es autocontenida (archivo nuevo + 2
endpoints aditivos + 1 pestaña), comparamos y fusionamos conservando ambos.
- NUEVO backend/pipeline/hook_variator.py — `variar_hook(winner, producto, modo="hook"|"tomas", n,
  voz, evitar=, variaciones=, hook_fin=)`. Cerebro: creative_variator.generar_variaciones (NO lo
  toqué, solo lo consumo) sobre el arco REAL del winner (analyze_narrative → transcripción etiquetada).
  · modo "hook" (default): gancho nuevo usando VENTANA LIMPIA del propio winner — nueva
    `ventana_limpia(video, dur, desde=)`: EAST muestrea 1 frame/0.5s y devuelve el tramo SIN texto
    quemado ($0). Plan B: hook original con el texto TAPADO (mask_video). Voz CO de ElevenLabs con
    timestamps + subtítulos palabra x palabra (burn_word_captions) SOLO en el hook; CUERPO INTACTO.
  · modo "tomas": narra el guion COMPLETO (1 sola llamada TTS) y por cada escena del brief
    [{fase, buscar}] busca la toma en TikTok ($0 buscar_tiktok sin IA, SIEMPRE region != "CO", sin
    repetir toma entre variaciones), ventana limpia, normaliza 9:16, concat_clips + add_voiceover +
    subs + punch_pace. Plan B por fase: metraje del winner con offset DISTINTO por fase; último
    recurso: texto tapado.
- backend/app.py (aditivo): POST /api/variar-hook (Form: producto, link O video subido, modo
  default "hook" = retrocompatible, n, voz) → job en thread + _persist_varhook (work/<id>/job.json,
  patrón _persist_disruptive → sobrevive reinicios; _get_job lo rehidrata). POST /api/variar-hook-otro
  (job_id, index) = 🎲 Otro hook con evitar=[hooks ya mostrados], calcado de disruptive-swap-concept;
  el result guarda `arco` y `hook_fin` para NO repagar narrativa al regenerar.
- frontend/index.html: pestaña 🔁 Variar hook (upload/link + producto + selector "solo hook /
  hook + tomas" + 2/4/6 variaciones + voz) → poll → grid 9:16 con ⬇️ descargar, 🎲 Otro hook y
  detalle guion + pasos.
- PROBADO barato: py_compile ok; JS 11/11 node --check; E2E offline con IAs MOCKEADAS (TTS silencio
  + timings sintéticos, narrativa fake, buscar_tiktok=[]) sobre winner sintético con texto quemado
  en 0-3s y 6-12s → modo hook 12.5s (hook nuevo SIN el texto viejo, karaoke visible, cuerpo intacto
  — verificado FRAME A FRAME con capturas); modo tomas 8.0s exactos (= duración de la voz, 3 fases
  con metraje distinto). Ruta de red real $0 ok (buscar + bajar toma de TikTok: 82s). Server smoke
  en :8422 (pestaña servida, 400/404 correctos).
- HONESTIDAD: en el último plan B (cero ventanas limpias) el blur de mask_video deja texto GIGANTE
  aún medio legible (con texto de tamaño normal se ve bien — es el mask estándar de la app; no lo
  toqué por no afectar blur_captions global).
- AVISO Jack/Landings: NO toqué assemble.py (el fix del stream_loop quedó intacto), ni
  creative_variator, ni tiktok_search, ni nada del módulo Landings nuevo (shopify_admin.py). Mi
  merge conserva su fase (a) completa.

### 2026-07-03 · Claude (juanesal-lab) · 🔁 FIX RAÍZ de los cortes repetidos: el plan ahora cubre la VOZ REAL
Juan: "cada 7 clips se repite la misma secuencia" — TENÍA RAZÓN, incluso después del fix del
stream_loop. Diagnóstico con datos (job 835a77d01678, 07:00): montajes de 6-8s vs voces de ~22s.
- CAUSA 1 (la repetición literal que vio Juan): ese render salió de un server que arrancó ANTES
  del fix de las 05:48 → todavía loopeaba el montaje (~3 vueltas de 8s = su queja exacta). El fix
  de Jack está bien; había que REINICIAR el server.
- CAUSA 2 (el hueco que quedaba): el plan del montaje usaba el TARGET pedido, pero la voz real
  sale más larga (el guion a veces excede el tope de palabras y ElevenLabs habla a ~1.8 pal/seg,
  no 2.6 → una voz "de 6s" salió de 22s). Montaje 8s + voz 22s = loop antes / final congelado
  14s después. Ni el tpad ni el plan por duración cubrían esto.
- FIX (orchestrator.render_versions): antes de plan_variations se mide la voz MÁS LARGA ya
  sintetizada (version_vos + voiceover_path, ffprobe) y el plan usa
  plan_seconds = max(target, voz_real + 0.5). El "pool agotado → prestar clips de otras
  versiones" de assemble (de Jack) hace el resto — nunca repite DENTRO de una versión.
- VALIDADO con el pool real del job caído (43 clips, 0.8-1.8s): las 8 versiones pasan de 6-8s a
  27-28.5s (≥ need 26.8s ≥ voz 22s), 0 duplicados internos. add_voiceover corta exacto al final
  de la voz → ni loop ni congelado. py_compile ok.
- AVISO Jack: solo toqué render_versions (el bloque PLAN PRIMERO — tu plan_variations y tu
  préstamo de clips quedaron intactos y ahora sí se lucen). ⚠️ REINICIAR el server después de
  este pull (el proceso viejo sigue sirviendo código de antes de las 05:48).

### 2026-07-03 · Claude (jackingshop1-cell) · 🤝 FUSIÓN Variar hook: quedó TU versión + injertos nuestros (y por qué)
Juan: mi sesión revivió (Jack sin tokens unas horas) — yo TAMBIÉN había construido la capa de video
completa y verificada (E2E real con el ganador de toallas: 4/4 videos, frames mirados, revisor 2º agente).
Chocamos de frente con tu c5a9184; hice la fusión que propusiste ("comparamos y fusionamos"):
- SE QUEDÓ TU CABLEADO completo (tu hook_variator.py con modo hook/tomas + /api/variar-hook +
  /api/variar-hook-otro 🎲 + _persist_varhook + tu pestaña con selector de modo). Razón: tus 2 modos y
  persistencia son superset del mío, y tu E2E offline + ruta de red $0 estaban verificados. Mi versión
  entera queda en la historia (commit 11c02f4) por si quieres pescar algo: tenía toma NUEVA de TikTok
  también en modo "hook" (brief de la fase HOOK → buscar_tiktok → hasta 3 descargas buscando ventana
  limpia EAST → si ninguna, tapar con Gemini), armado de variaciones en PARALELO (2 workers), y
  traducción del cuerpo con "solo_otro". Si te sirve, enchufamos eso como opción "toma nueva" luego.
- INJERTO en tu hook_variator.py: filtro DURO anti-precio `_PRECIO`/`_sin_precio` (regla de oro; tu
  versión confiaba solo en el prompt del variator) — bloquea $/€/precio/"COP 49900"/"cuarenta mil
  pesos"/"50% off" pero deja "2x1"/"envío gratis"/"100% algodón" (16/16 casos); ahora se piden n+2
  variaciones al cerebro para reponer descartes.
- DE NUESTRA RAMA quedaron además: `-ar 48000 -ac 2` en assemble.add_voiceover (convive con tu fix
  del no-loop/tpad — el mp3 de ElevenLabs es 44.1k mono y el demuxer de concat_clips ralentizaba y
  desafinaba el audio de lo concatenado después: medido por FFT, 220 Hz sonaba a 202 Hz; tu
  hook_variator ya re-encodeaba a 48k por su cuenta, así que doble cinturón); modo "solo_otro" en
  text_translate.py (traduce SOLO texto extranjero, deja el español — tu código lo usa);
  `vo_guiones` expuesto en /api/producto-clips + selector "Guiones: 8/4/2" en Mi producto (control
  de costo ElevenLabs, pendiente del handoff); línea de la pestaña en la Guía.
- LIMPIEZA del merge: el auto-merge había CONCATENADO nuestros dos hook_variator.py (dos def
  variar_hook, SyntaxError), duplicado el endpoint /api/variar-hook y entreverado los dos paneles en
  una sola pestaña (vhRun/vhPoll definidos 2 veces). Quedó 1 módulo (el tuyo + injerto), 1 endpoint +
  el 🎲, 1 pestaña (la tuya). py_compile ok, node --check ok, rutas únicas verificadas.
- AVISO: tu entrada de arriba lo dice y lo confirmo — nada de Landings ni de tus fixes del día se
  tocó. Mi E2E real de anoche queda como evidencia de que el flujo con toma nueva funciona (por si
  lo retomamos): work/e3ec35398393/ tiene los 4 videos de muestra.

### 2026-07-03 · Claude (juanesal-lab) · 🖼️ Ads imagen: el PRODUCTO REAL ahora entra AUTOMÁTICO e integrado al diseño
Pedido de Juan: que el producto se vea en las imágenes (la gente debe saber que ÉL es la solución),
sin cambiar el estilo que ya le gusta. Cambio mínimo, cero cambios al prompt creativo de Claude:
- `_integrar_producto_ia`: prompt ADAPTATIVO — analiza el layout: si hay zona limpia RESERVADA
  (plantillas no_compres/capturas) pone el producto AHÍ como héroe (hasta ~30% ancho); si no, chico
  (~20%) sobre superficie real del tercio inferior. Siempre luz/perspectiva/sombra de contacto reales,
  jamás sobre caras/texto/chrome. NUEVO: si el producto YA está en la escena lo REUBICA (exactamente
  1 instancia) → el botón manual ahora sirve para reubicar sin duplicar.
- `generar_ad_fullprompt`: con `integrar_producto` marca `variant["producto_integrado"]` True/False
  (si falla la 2ª pasada el ad queda limpio, no se pierde). `generar_ads_fullprompt` (batch),
  /api/regenerate-image y /api/disruptive-swap-concept ahora integran AUTO cuando hay foto de producto.
  /api/disruptive-add-product marca el flag.
- UI: mensaje de resultado actualizado; botón según estado: "🔁 Reubicar mi producto" (integrado) /
  "⚠️ El producto no entró — reintentar" (falló) / "➕ Poner mi producto" (jobs viejos sin flag).
- Probado REAL con job e8216f0e4350 (aceite de ricino, sobre COPIAS en scratchpad): plantilla
  contrarian → producto grande en la zona reservada derecha, label legible; surreal slider → producto
  con sombra al lado del "después", sin tapar CTA ni manija. py_compile OK.
- AVISO Jack: toqué disruptive_images.py (_integrar_producto_ia, generar_ad_fullprompt,
  generar_ads_fullprompt), app.py (3 endpoints) y el disRender del index. Retro-compatible con jobs
  viejos (flag ausente = botón de siempre). Reiniciar server para probar.

### 2026-07-03 · Claude (jackingshop1-cell) · 🏎️ HOME: "El garaje de Jack" — showroom rotativo con los carros de verdad
Jack pidió su garaje en la portada: sus 4 naves (Porsche 911 GT3 RS, Ducati Panigale V4, Lamborghini
Huracán STO, Rolls-Royce Phantom Drophead) rotando cada 10s, el home teñido con los colores del carro
de turno y la tipografía con la vibra de cada marca. Las secciones de adentro quedan IGUAL.
- IMÁGENES: las fotos que mandó Jack (chiquitas, la del Porsche era un juguete con control y escudo
  encima) se re-renderizaron a calidad de ESTUDIO con Nano Banana (editar_imagen_ia de Juan, 4 llamadas:
  fondo negro showroom, piso reflectivo, sin logos ni juguetes) → assets/garage/*.webp (54-82KB c/u,
  quality 86). OJO: editar_imagen_ia SOBREESCRIBE el archivo de entrada (trabajé sobre copias).
- backend/app.py: mount NUEVO `/assets` (StaticFiles sobre BASE/assets) — sirve el garaje y de paso
  cualquier asset futuro del frontend.
- frontend/index.html (SOLO la sección #home): fuera el carro 3D genérico de three.js (y su CDN unpkg
  — el home ya no depende de internet); entra el showroom: 2 <img> apiladas con crossfade 1.15s +
  máscara radial que funde la foto con el fondo, halo del color del carro, flotación sutil, parallax
  3D al puntero/gyro (rotateY/rotateX con perspective). Variables --hacc/--hacc2 POR CARRO tiñen:
  saludo (gradiente), bordes/hover de las hCards, iconos, flechas, "MAXING" del brand, números de
  pasos y fondo radial. Tipografías por marca (system fonts, $0, sin red): Porsche Helvetica 800,
  Ducati Avenir Next 900 itálica, Lambo Futura uppercase, Rolls DIDOT serif (queda divino). Badge
  "TU GARAJE · marca · modelo". setInterval 10s + guard `girando` (atómico: si se dispara doble,
  imagen y tema jamás quedan de carros distintos — lo vi pasar adelantando a mano y lo blindé).
  prefers-reduced-motion respetado (sin parallax).
- VERIFICADO visual (screenshots en :8421): Porsche tema rojo/blanco ✓, Ducati tricolor con badge
  sincronizado a ritmo natural ✓, Lambo Futura grafito ✓ (computed style), Rolls Didot plata ✓;
  /assets/garage 200; py_compile ok; node --check 13/13; sin three.js en el html.
- AVISO Juan: NO toqué tus hCards/hSteps/homeEnter ni el resto del home — solo el escenario (#hStage),
  el <script> del 3D (reemplazado) y tintes a var() en tu CSS del home. Si quieres cambiar los carros
  o los colores: array GARAJE en el script "EL GARAJE DE JACK" + assets/garage/.

### 2026-07-03 · Claude (jackingshop1-cell) · 🎥 Garaje del home ahora en VIDEO 3D (Veo): la cámara ORBITA cada carro
Jack: "necesito que sea 3d y como animado". Hecho con la key de Gemini que ya tenemos (Veo 3.1 fast,
image-to-video desde las fotos de estudio del garaje):
- 4 videos de 8s (cámara orbitando el carro quieto en el estudio negro, estilo comercial de lujo) →
  post en ffmpeg: sin audio, LOOP PING-PONG (ida+vuelta = jamás se nota el corte), 1280w crf26 →
  assets/garage/*_orbit.mp4 (1-2MB c/u). Las .webp quedan de POSTER/fallback.
- frontend: los <img> del showroom ahora son <video autoplay muted loop playsinline> con crossfade;
  `cargar()` espera loadeddata con red de seguridad de 1.6s (nunca se cuelga esperando);
  prefers-reduced-motion → se queda con la FOTO (no carga video). Preload por fetch.
- Verificado visual en :8421: dos capturas separadas 3s muestran ángulos DISTINTOS del Porsche
  (el orbital corre de verdad). JS 13/13 node --check.
- Costo: 4 llamadas a Veo 3.1 fast (8s c/u) a la cuenta de Gemini de Jack — autorizado por él
  (primero intentamos Higgsfield, prefirió Veo por usar el API que ya tenemos; en Higgsfield solo
  se subieron fotos, 0 créditos gastados).
- AVISO Juan: solo cambió el bloque del garaje en index.html + 4 mp4 nuevos en assets/garage.
  El array GARAJE ahora lleva `vid:` + `src:` (poster) por carro.

### 2026-07-03 · Claude (juanesal-lab) · 🎬 EDICIÓN PRO: motor de mezcla y montaje reescrito con reglas de 4 ads ganadores reales
Queja de Juan: "la edición (SFX, cortes) queda amateur; el contenido está bien". Puse 2 agentes a
analizar 4 referencias pro suyas (~/Downloads file 71-74; el 75 era duplicado): uno frame a frame
(cortes/optical flow/Gemini video) y otro la banda sonora (ebur128/RMS/onsets/Gemini). Reglas
completas en **`assets/edicion-pro-reglas.md`** (leerla antes de tocar edición). Implementación:
- NUEVO `pipeline/pro_mix.py`: plan_sfx (presupuesto 1/1.8s, ~50% de cortes, whoosh 150ms ANTES
  del corte, jerarquía sutil −14dB / medio −9dB / protagonista −2dB, brillo protagonista en el
  momento del producto, hot-start pop, nada en DOLOR, jitter ±1.5dB, nunca 2x el mismo sample) +
  filtros_mezcla (música aloop + fade-out 1.5s + DUCKING sidechaincompress 4:1 con la voz de
  llave) + cadena_final (amix + loudnorm I=-18:TP=-1.5:LRA=8). FIX: sin música no se hace asplit
  de la llave (quedaba colgado el pad → error de filtergraph).
- `assemble.py`: add_voiceover_and_sfx y add_music_sfx REESCRITAS sobre pro_mix (antes: SFX 0.8
  en CADA corte + música plana 0.16 sin ducking ni fades). `-ar 48000` obligatorio post-loudnorm.
  Nuevo param `phases` (rangos DOLOR sin SFX + momento del producto).
- MONTAJE: concat_clips_xfade ya NO rota slideleft/wipeup/circleopen (PowerPoint) → DISSOLVE de
  5 frames (0.17s) en todo + corte casi-duro (0.034s) 1 de cada ~5 y en la entrada del payoff;
  devuelve los CUT_TIMES REALES post-overlap vía cut_times_out. build_variations: curva de ritmo
  por slot (ancla ≤1.6s → ráfaga ≤0.9s → crucero ≤1.7s → CTA ≤2.2s con planos que se calman),
  movimiento por plano (hook in_fuerte, payoff punch 18%/s con fx, cuerpo Ken Burns 2%/s
  alternando 2in:1out — NADA estático), dedup de renders por (clip, tope, motion), y SIEMPRE
  dissolve (antes solo con fx). plan_variations acumula con tope 1.7s para seguir cubriendo la voz.
  _motion_chain: zoompan estateless por 'on' (OJO: crop NO anima w/h — se evalúan una vez; me pasó).
- Propagación (regla 2): orchestrator y app._agregar_musica_sfx usan los cut_times reales del
  montaje; producto_clips ahora pasa sfx+cut_times (antes solo música); auto_studio._add_music_sfx
  reescrito con pro_mix (SOLUCIÓN=protagonista, HOOK/CTA=medio, resto sutil; prompt de música
  a ElevenLabs pide cama plana SIN drops); phase_effects: HOOK riser→swoosh sutil (cero risers en
  los 4 ads), SOLUCIÓN boom→sparkle/chime protagonista.
- Verificado E2E con clips sintéticos: master −18.0 LUFS exacto en ambas rutas, duración = voz,
  curva de ritmo en cut_times (1.51/0.74/0.79/1.6/1.53/2.03/2.1), dissolve real (frame intermedio
  = mezcla de colores), jerarquía de movimiento medida (punch 4.69 > fuerte 2.53 > suave 1.29 >
  out 1.09 > estático 0.12), ruta sin música y ruta auto_studio OK. py_compile todo OK.
- NO implementado a propósito: repetir el "clip ancla" 2-3 veces (los pros lo hacen, pero choca
  con la regla dura de Juan de no repetir clips) — pendiente decisión de Juan.
- AVISO Jack: toqué assemble.py (montaje+mezcla), pro_mix.py (nuevo), auto_studio._add_music_sfx,
  phase_effects (_PHASE_CFG), producto_clips (_voz_y_subtitulos), orchestrator (_cut_times),
  app.py (_agregar_musica_sfx). Firmas retro-compatibles (params nuevos opcionales). Las versiones
  ahora traen "cut_times" en el dict. Reiniciar server para probar.

### 2026-07-03 · Claude (juanesal-lab) · 💰 Ads imagen: BORRADOR barato + botón ✨ HD (gasto de Gemini ~-70%)
Juan: $50 de Gemini en 3 días. Diagnóstico con datos: el gasto NO es de las llamadas de visión
(flash, centavos) — son las IMÁGENES con gemini-3-pro-image: 117 finales en work/ en 3 días
(+ regeneraciones/verify ocultas que sobreescriben) ≈ $27-47. Aparte se evaluó Magnific: su
"ilimitado" solo aplica generando A MANO en su web; por API cobra créditos (60/imagen ≈ mismo
precio que Gemini pro) — NO es más barato para la app.
- disruptive_images.py: NUEVO `_IMG_MODEL_DRAFT = "gemini-2.5-flash-image"` (Nano Banana 1,
  ~$0.04). `generar_ad_fullprompt(..., hd=False)`: el LOTE completo, 🔄 Regenerar y 🎲 salen en
  borrador; `hd=True` re-renderiza con el pro (~$0.13). `max_regen` default 2→1 (peor caso 2
  gens, no 3). `generar_imagen`/`_integrar_producto_ia` ganaron param `model=` (default = pro,
  igual que antes). El verify de ortografía ya usaba flash (no se tocó).
- app.py: NUEVO POST /api/disruptive-hd (job_id, index) — mismo patrón que regenerate-image,
  con hd=True; marca `v["hd"]=True` y persiste.
- frontend: botón "✨ Calidad HD (la que vayas a usar)" por card (muestra "✅ Ya está en HD"
  después). Flujo: el lote de 10 sale por ~$0.40 (antes $1.30-4.00) y Juan paga HD solo en las
  2-3 que de verdad va a pautar.
- PROBADO: py_compile ok; JS 13/13 node --check; 1 generación REAL con el modelo borrador
  ($0.04): texto en español nítido y sin errores (verificado visualmente).
- AVISO Jack/Landings: la firma vieja sigue funcionando igual (hd default False = borrador;
  si algún flujo necesita pro directo, pasa hd=True). Para el módulo Landings: usen
  _IMG_MODEL_DRAFT para las previews del gate de aprobación y el pro solo al aprobar — es
  exactamente el mismo patrón.

### 2026-07-03 · Claude (juanesal-lab) · 🎬 MONTAJE GUIADO POR GUION: "primero se crea el guion y después se edita"
Pedido explícito de Juan: el sistema debe mirar TODOS los clips y, según el guion, elegir el mejor
clip para CADA momento de la voz (antes el montaje era ciego y la voz se pegaba encima).
- NUEVO `pipeline/guion_match.py`: frases_de_vo (parte la voz en FRASES con los tiempos por
  palabra de ElevenLabs: puntuación, pausas >0.35s, tope 4.8s, micro-frases fundidas, el silencio
  post-frase pertenece a la frase) + etiquetar_frases (fase narrativa por frase: 1 llamada Gemini
  flash para TODAS las versiones + heurística keywords/posición de fallback, incluye fase "cta") +
  plan_montaje (cada frase se llena con el clip de SU fase visual — fallback por vecindad de
  significado _PREFERENCIA —, balanceo de uso entre versiones, JAMÁS repite clip en la versión,
  hook en ráfaga ≤1.2s / cierre ≤2.2s, colitas absorbidas o estiradas con el clip).
- `assemble.build_variations`: nuevo param `version_caps` — el guion fija la DURACIÓN de cada
  slot (+compensación del overlap del xfade, espejo de la regla de cortes duros: sin esto la voz
  se desincroniza ~0.17s por transición). Filenames de combos ahora con cap en milésimas.
- `orchestrator.render_versions`: la clasificación visual por fase (phase_classify) se movió
  ANTES del plan (top-60, antes top-30 y solo para gifs) → si hay voz con timings (version_vos o
  voiceover+word_timings), el plan ciego se REEMPLAZA por el plan por guion (por versión; si a
  una versión le falta voz/timings conserva el plan clásico — nunca rompe). _apply_vo: los SFX
  ya no dependen del toggle "efectos" (el plan pro es sutil por diseño; "efectos" sigue mandando
  en lo visual).
- `process_job`: passthrough nuevo (version_vos/sfx_paths/music_path/captions/estilo/tamaño).
- **Mi producto (producto_clips) reestructurado al flujo guion-primero**: _voz_y_subtitulos se
  partió — _guiones_y_narraciones (guiones+TTS) corre ANTES de process_job; la música también se
  genera antes; el render monta por guion y quema voz+subtítulos+mezcla pro ADENTRO (antes se
  pegaban sobre un montaje ya cerrado). Sin voz → comportamiento viejo intacto (música sola).
- Verificado E2E sintético: 6 frases etiquetadas bien por heurística (problema→solucion→
  funcionamiento→caracteristicas→resultado→cta), 12/12 slots con la fase pedida o su vecina,
  0 clips repetidos, suma de slots = duración exacta de la voz, y tras el render real cada borde
  de frase tiene su corte a ≤0.18s (dentro de la ventana del dissolve). py_compile + imports OK.
- AVISO Jack: toqué orchestrator (process_job + render_versions + _apply_vo), assemble
  (build_variations firma), producto_clips (reestructurado el flujo; _voz_y_subtitulos YA NO
  existe — ahora _guiones_y_narraciones), guion_match.py nuevo. Todo retro-compatible si no pasas
  los params nuevos. Tu disruptive_images (draft/HD) no lo toqué.

### 2026-07-03 · Claude (juanesal-lab) · 🐞 FIX doble del "video quieto 30s al final" (bug real de Juan, file 76)
Diagnóstico con el video real: NO era el tpad del final — del s24 al s53 el montaje encadenó
segmentos CONSECUTIVOS del MISMO video fuente (un testimonio hablando a cámara fija): clips
técnicamente distintos (la regla de no repetir se respetó) pero la MISMA toma en pantalla 30s =
"se ve congelado". Además los guiones de Mi producto salieron de 43-55s para un target de 15s.
1. `guion_match.plan_montaje`: REGLA DE VARIEDAD DE FUENTE (la tenía el plan clásico y el plan
   por guion la perdió): nunca 2 tomas seguidas del mismo video-fuente; si toda la fase preferida
   es de la misma fuente, busca fase vecina u otro clip del pool de OTRA fuente; racha dura ≤2.
   Probado: fuente con 20 segmentos de la misma fase ahora alterna (racha máx 1).
2. `scripts.py`: presupuesto de palabras REAL — 2.4 palabras/s (medido con ElevenLabs es-CO, el
   2.6 teórico quedaba corto) INCLUYENDO el CTA obligatorio (16 palabras ≈ 7s), prompt con
   consecuencia explícita, y `_ajustar_largo()`: recorte DURO post-Gemini por frases (Gemini
   ignoraba el "MÁXIMO N palabras": 154→33 palabras conservando el CTA exacto al final).
3. `orchestrator`: si los clips cubren MENOS que la voz (>1.5s de hueco), progress con ⚠️ claro
   ("los clips cubren Xs de Ys — el cierre queda quieto").
py_compile + tests unitarios OK. AVISO Jack: guion_match._mejor reescrito, scripts.generate_scripts
(max_words + _ajustar_largo), orchestrator (aviso cobertura). Nada de firmas públicas cambió.

### 2026-07-03 · Claude (jackingshop1-cell) · 🔥 Foreplay al fin COMPLETO: de 2 resultados a cientos + búsqueda por FOTO del producto exacto
Queja de Jack (con razón): "en Foreplay hay 1000 anuncios y en la app 2, y está súper fea".
DIAGNÓSTICO (medido contra el API real): (1) nunca se mandaba `limit` → el API devuelve ~10 por
página por defecto (acepta 100); (2) las búsquedas LARGAS matan ("toallas de tela reutilizables"=3,
"toallas tela"=10+cursor); (3) una sola búsqueda de un solo término se queda corta siempre.
- `foreplay_search.buscar_ads` (Juan): + params ADITIVOS `limit` (1-100) y `order`
  ("newest"|"oldest"|"longest_running" — ganadores primero). Nada tuyo cambia sin pedirlo.
- /api/foreplay-search: passthrough de limit+order (default UI: limit=50, order=longest_running).
- NUEVO `creative_search.foreplay_producto()` + POST /api/foreplay-producto (job): foto y/o nombre →
  analizar_foto saca ~8 términos ES+EN → CADA término con limit=100 × 2 páginas en paralelo → dedup →
  RELEVANCIA TEXTUAL primero (tu lección del _title_score de TikTok: ordenar el pool del juez solo
  por días lo llenaba de mega-ads genéricos — "Brasil Paralelo" 1032 días — y confirmaba 0; con
  relevancia: 27 confirmados) → juez visual (_verificar) top-60 thumbnails → ✅ confirmados primero
  (por días), ⚠️ resto por relevancia. Ruido con 0 relevancia se bota si hay ≥30 relevantes.
- Pestaña Foreplay RE-DISEÑADA estilo Discovery de Foreplay: masonry real por columnas (thumbnails
  a su proporción), card con avatar+marca+plataformas, badge VERDE "● N días", drop 📸 "PRODUCTO
  EXACTO", filtros (idioma/orden/activos/video/mín días), contador, SCROLL INFINITO por cursor
  (IntersectionObserver, carga sola), y en modo producto DOS secciones (✅ confirmados / ⚠️ sin
  verificar — la masonry por columnas regaba el orden). Se conservan INTACTOS: selección + ✂️ Cortar
  en clips (fpCut→/api/foreplay-clips), 🎙️ Doblar, ▶️ Ver inline, proxies thumb/video.
- PROBADO REAL: "faja" → 47 en la 1ª página (antes ~2-8) ordenados 1032/999/920 días; FOTO del
  repelente ultrasónico (landing webp de Jack) → 512 ads crudos, 354 relevantes, ✅ 27 CONFIRMADOS
  del dispositivo exacto (Bakanoforth-a ~500 días + "OFERTA 2X1" en español). Costo del modo foto:
  1 Gemini foto + ~16 créditos Foreplay + ≤60 flash. Screenshots verificados. JS 13/13.
- AVISO Juan: en tu foreplay_search.py solo los 2 params aditivos; _es_colombiano sigue filtrando
  adentro (regla de oro). La pestaña vieja quedó reemplazada (fpSearch/fpRender nuevos, resto igual).

### 2026-07-04 · Claude (jackingshop1-cell) · 🧠 La app ya NO pierde el trabajo con el gesto atrás / recargas
Queja de Jack: dos dedos a la izquierda sin querer → el navegador se devuelve, y al volver la app
arranca desde cero (portada) y se pierde lo que había. Fix en frontend/index.html (3 capas, aditivo):
1. `html,body{overscroll-behavior-x:none}` → el gesto de swipe-atrás de Chrome queda BLOQUEADO
   dentro de la app (raíz del accidente).
2. Historial interno: homeEnter hace pushState → el botón atrás vuelve AL GARAJE (dentro de la app)
   en vez de salirse; adelante regresa a la pestaña. popstate manejado.
3. Memoria de sesión (sessionStorage, por pestaña del navegador): pestaña activa (cm_tab),
   resultados de Foreplay completos (cm_fp: ads+modo+cursor+query, se guarda en cada fpRender) y
   TRABAJOS EN CURSO (cm_job_*: los poll fpProductoPoll/fpPoll/vhPoll/clonePoll/autoPoll/prodPoll/
   swapPoll/dubPoll quedan envueltos para recordar su job_id) → al recargar se re-enganchan contra
   /api/status (si el server ya no conoce el job, se limpia la clave). Todo con try/catch — si algo
   falta, la app carga normal.
- PROBADO en vivo: buscar "faja" (47 ads) → reload completo → cae directo en Foreplay con la query
  y los 47 ads restaurados; history.back() → garaje sin salir del sitio; overscrollBehaviorX="none"
  por computed style. JS 14/14 node --check.
- AVISO Juan: solo index.html — un <style> de 1 línea y un <script> nuevo al final que ENVUELVE
  (no reemplaza) homeEnter/fpRender/los polls. Si agregas una pestaña con job propio, suma su poll
  a la lista de nombres y queda con memoria gratis.

### 2026-07-04 · Claude (jackingshop1-cell) · ⏱️ Fix: "Analizar conceptos" colgado 20+ minutos (Claude sin timeout)
Jack quedó 20 min mirando "Claude analiza y crea 10 conceptos..." — la llamada al SDK de Anthropic
NO tenía timeout: el default es 600s POR INTENTO × 2 reintentos ≈ hasta 30 min colgado si la red/API
se pega. Fix: `Anthropic(api_key=..., timeout=120.0, max_retries=1)` en los 4 clientes
(disruptive_images, creative_variator, tiktok_search juez, supervisor) → cualquier cuelgue muere en
~2-4 min con el error visible en la UI (los 4 sitios ya capturaban excepción y reportaban).
AVISO Juan: solo el constructor del cliente; prompts/flujo intactos.

### 2026-07-04 · Claude (juanesal-lab) · 🎨 Diversidad ENTRE versiones en el montaje por guion
Queja de Juan (con screenshot): las 8 versiones salían con LOS MISMOS clips (A y B abrían con el
mismo testimonio). El plan por guion balanceaba clips sueltos (usage) pero perdió la diversidad
entre versiones que tenía el plan clásico (buckets disjuntos + gancho rotado). En plan_montaje:
- GANCHO ROTA DE FUENTE: `hook_srcs` compartido entre versiones (lo muta el plan) — una versión
  no puede abrir con la fuente con la que ya abrió otra (primer criterio del sort en el 1er slot).
- BUCKETS por ranking: el pool se reparte v, v+N, v+2N... y cada versión prefiere SU tajada
  (criterio nuevo tras usage).
- `usage` sigue castigando clips usados por otras versiones (ya existía).
Firma: plan_montaje(..., version_i, n_versiones, hook_srcs) — opcionales, retro-compatible.
Probado (10 fuentes × 6 segmentos, 4 versiones con guiones iguales): ganchos de 4 fuentes
DISTINTAS, solapamiento entre versiones 0-2 clips de ~10 (antes casi 100%), cada versión usa
7-9 fuentes. py_compile OK. AVISO Jack: orchestrator pasa los params nuevos; nada más cambió.

### 2026-07-04 · Claude (jackingshop1-cell) · 🚀 Fix RAÍZ de la lentitud: 15 endpoints congelaban TODA la app
Jack: "se me demora mucho la app en darme cosas, mucho". Causa: 15 handlers declarados `async def`
SIN ningún await adentro — corren EN el event loop de uvicorn, así que mientras uno trabaja
(disruptive-angles ~2 min de Claude inline, creative-search ~1-2 min, uploads grandes de clone/swap)
TODO el server queda congelado: miniaturas, /api/status de otros jobs, todas las pestañas.
FIX: `async def` → `def` en los 15 (process, fetch_links, auto, tiktok_search, creative_search,
creative_more, clone, scripts, swap, dub, download_videos, producto_clips, foreplay_producto_api,
disruptive_angles, disruptive_images) → FastAPI los corre en su threadpool (~40 hilos) y el loop
queda libre. PROBADO: con una búsqueda TikTok corriendo, el home respondió en 0.04s (antes esperaba).
AVISO Juan: regla de la casa a partir de hoy — handler SIN await = `def` a secas; `async def` solo
si de verdad hace await. Cero cambios de lógica/firmas, solo la palabra async.

### 2026-07-04 · Claude (jackingshop1-cell) · 🖼️ Ads imagen: HD ya NO pierde el producto + TODO 1:1 SIEMPRE
Quejas de Jack: (1) "✨ HD quita el producto" → tocaba re-pagar la integración; (2) "todas las
imágenes deben ser 1:1 cuadradas SIEMPRE".
- CAUSA de (1): /api/disruptive-hd RE-DIBUJABA desde el prompt (otra escena) y re-intentaba la 2ª
  pasada del producto; además el modelo PRO (gemini-3-pro-image-preview) está SIN CUOTA (429
  RESOURCE_EXHAUSTED medido hoy) → la integración moría en silencio y el ad quedaba limpio.
  FIX: si la imagen YA existe, HD la REFINA TAL CUAL con editar_imagen_ia (misma escena, mismo
  producto, mismos ajustes de ✏️); si falla, la imagen queda INTACTA y el error sale amigable
  (_error_amigable — ahora editar_imagen_ia reporta errors= en vez de tragarse el 429). El botón
  "➕ Poner mi producto" ahora usa el modelo BARATO (draft) — funciona aunque el PRO esté sin cuota
  y cuesta ~3x menos; el PRO queda solo para HD.
- FIX de (2): prompts pasados de "4:5 vertical" a "1:1 SQUARE" (base sale 1024×1024 ✓) + como los
  EDITS de Nano Banana a veces ignoran el aspecto (medido: devolvía 832×1248), nueva _a_cuadrado():
  re-encuadre LOCAL determinista a 1:1 con fondo difuminado estilo IG ($0, nunca recorta producto/
  texto) aplicado tras generar/integrar/editar. Los ads viejos 4:5 quedan cuadrados al próximo edit/HD.
- PROBADO real (~$0.12 en draft): base 1024×1024 ✓ → producto integrado con draft ✓ (2 unidades,
  ondas, sombra) → edit no-cuadrado re-encuadrado a 1248×1248 ✓ mirado con ojos. El refine HD queda
  pendiente de que la cuota PRO reinicie (mañana) — con cuota agotada el botón ahora DICE el motivo.
- AVISO Juan: en tu disruptive_images.py — _CIERRE/prompt a 1:1, editar_imagen_ia con errors=
  opcional, _a_cuadrado nueva aplicada en 3 puntos; en app.py tu /api/disruptive-hd refina la actual
  y disruptive_add_product usa _IMG_MODEL_DRAFT. Tu flujo de lote borrador+HD sigue igual.

### 2026-07-04 · Claude (jackingshop1-cell) · 🧊 Fix clips CONGELADOS + 📁 Mi producto acepta videos locales
(1) Jack: "los creativos se quedan congelados" (file (45).mp4: 6 tramos pegados de ~1s, medidos con
diff de frames). CAUSA: en guion_match.plan_montaje, con el pool agotado (cada clip se usa 1 vez) las
frases restantes quedaban SIN video → el tpad sostenía el último frame en cada hueco. FIX: pool
agotado → se REPITE el clip menos usado (prefiriendo otra fuente) en vez de congelar. OJO Juan: tu
regla "jamás repetir clip en la versión" se relaja SOLO como último recurso vs congelarse — con pool
suficiente nada cambia. Probado $0: pool de 3 clips vs guion de 24s → antes huecos, ahora 24.0/24.0s
cubiertos.
(2) "déjame seleccionar de Descargas": Mi producto ahora tiene 📁 selector de videos locales junto a
los links (combinables). producto_a_clips(+archivos_locales=), endpoint winner_files: File([]),
validación acepta solo-archivos (salta el scout). 
(3) PENDIENTE: Jack reporta ~20 min por corrida de Cortar clips — falta PERFILAR una corrida con
este build (los congelados de hoy también alargaban: huecos → más regeneraciones?). Próxima sesión:
cronometrar por etapa con los mtimes del work dir.

### 2026-07-04 · Claude (jackingshop1-cell) · 🎞️ Cortar clips: slot de B-ROLL por links
Pedido de Jack: un espacio aparte en Cortar clips para pegar links de escenas de APOYO (contexto/
dolor/ambiente). Nuevo textarea "🎞️ Escenas B-ROLL" + botón que reusa bajarLinks()/api/fetch-links
(generalizada con srcId/btnId) — los b-roll se bajan y entran como material extra al pool (el
analizador los puntúa y el guion los usa donde calcen). Solo frontend.
PENDIENTE anotado (plantilla de búsqueda de Jack): cuando la búsqueda TikTok no confirme NADA,
decir QUÉ búsquedas probó y pedir marca/hashtag/país (punto 5 de su plantilla; el resto — ficha
profunda, multi-búsquedas ES+EN, verificación obligatoria, sin relleno mezclado — ya está).

### 2026-07-04 · Claude (jackingshop1-cell) · 📋 PLAN "búsqueda 30/30" (pedido de Jack, para la próxima sesión)
Meta real: precisión 100% (cero falsos confirmados) + encontrar TODOS los que existan + honestidad
cuando haya menos de los pedidos. Palancas, en orden:
1. RASTREAR CUENTAS VENDEDORAS: al confirmar videos, explorar la cuenta (tikwm api/user/posts) —
   los vendedores suben el MISMO producto 10-30 veces → es LA palanca de volumen exacto.
2. Modo EXIGENTE: verificación profunda (frames por dentro) a TODO lo que se muestre, no solo top-12.
3. Toggle "solo confirmados" + mensaje honesto con las búsquedas probadas y pedir marca/hashtag/país
   cuando no llegue al count (punto 5 de la plantilla de Jack).
4. Multi-foto de referencia (frente/lado/empaque) para el juez.
(Contexto: hoy 9/9 láser, 21 bee venom, 27 repelente — el techo actual es supply + cuentas sin explorar.)

### 2026-07-04 · Claude (jackingshop1-cell) · 🏷️ Cortar clips: toggle "Oferta 2x1 · envío gratis" (banner arriba)
Jack pidió elegir la oferta en Cortar clips y que salga el banner de su foto (pill roja "ENVÍO
GRATIS - PAGAS AL RECIBIR" + "OFERTA 2X1"). Se REUSA offer_banner.add_offer_banner (el de Crear
creativo, diseño calcado de su referencia; safe_top_y con Gemini para no tapar caras/producto):
- app.py: Form banner_oferta en /api/process + _agregar_banner_oferta() aplicada a las 8 versiones
  tras la música en _run_job. UI: checkbox junto a "🟦 Textos del proveedor".
- Regla de oro intacta: oferta SIN cifras de precio.
AVISO Juan: cero cambios en offer_banner/auto_studio; solo el hook en _run_job + Form + checkbox.

### 2026-07-04 · Claude (jackingshop1-cell) · ⏸️ Plan "búsqueda 30/30": sesión cortada ANTES de implementar (sigue pendiente)
Jack pidió cerrar YA. La sesión alcanzó solo la lectura de contexto (DEV-LOG, tiktok_search.py,
creative_search.py, endpoints y pestaña 🔍 Buscar creativos) — CERO cambios de código, nada a medias,
nada que revertir. El plan 30/30 completo (multi-foto ≤3 en /api/tiktok-search y /api/creative-search,
cuentas vendedoras vía tikwm api/user/posts de los confirmados, toggle "solo confirmados" + mensaje
honesto, modo exigente) queda TAL CUAL en la entrada 📋 del 2026-07-04 para la próxima sesión.
Verificado antes de cerrar: py_compile ok (app.py, tiktok_search.py, creative_search.py) y
node --check 14/14 bloques de index.html — el repo queda sano e idéntico a origin/main.
AVISO Juan: no toqué nada tuyo ni nada en general; esta entrada es solo la traza del corte.

### 2026-07-04 · Claude (jackingshop1-cell) · 🔍 Búsqueda 30/30: multi-foto + cuentas vendedoras + mensaje honesto (implementado)
Las 3 piezas del plan 📋, todas con params NUEVOS OPCIONALES (firmas viejas intactas):
1. MULTI-FOTO (≤3): /api/tiktok-search y /api/creative-search aceptan `fotos` (campo viejo `foto`
   sigue igual). analizar_foto(image_paths=...) → UNA llamada Gemini con todas las fotos = ficha más
   completa; jueces (_verificar y Claude) usan máx las 2 primeras como referencia (_refs normaliza:
   bytes o lista — creative_search/_buscar_foreplay pasan la lista tal cual). UI: input multiple,
   etiqueta "📸 N fotos". El profundo (_verificar_video) sigue con 1 sola ref (tope de costo).
2. CUENTAS VENDEDORAS (buscar(..., explorar_cuentas=True)): si tras verificar faltan videos para el
   count, toma los @usuario de los confirmados (máx 3), baja tikwm api/user/posts (30 c/u, shape
   igual a search), dedup contra lo visto, region != CO, dur 4-120s, y los juzga SOLO por portada
   (sin profundo ni Claude). Los confirmados se suman DESPUÉS de los del doble juez.
3. HONESTIDAD: si confirmados < count → `mensaje_busqueda` ("Encontré N confirmados con estas
   búsquedas: [términos]. Dame la marca, un hashtag o el país para ampliar.") y la UI lo pinta 💬
   bajo el grid de TikTok.
PRUEBA REAL (repelente ultrasónico, count=30, misma ficha en ambos runs): explorar_cuentas=False →
25/30 confirmados (129s); True → 22/30 (153s). La diferencia es RUIDO de tikwm (candidatos distintos
por corrida); el bloque de cuentas corrió y sumó 0 AQUÍ porque las 3 cuentas confirmadas son
multi-gadget: test dirigido → user/posts sí trae 30 posts/cuenta (covers absolutos, GET 200) pero
0 de 24 portadas recientes muestran el repelente → el juez honesto no infla. Con cuentas
mono-producto (lo común en dropshipping) la palanca sí suma. Smoke HTTP en :8421 con 2 fotos
(campo `fotos`): ok, 5/5 confirmados, sin CO, mensaje vacío por llegar al count. py_compile ok
(app.py, tiktok_search.py, creative_search.py) + node --check 14/14. Reglas intactas: Colombia
excluida siempre, sin precio, topes (Claude top-20, profundo ≤12, cuentas solo portada).
AVISO Juan: _verificar/_verificar_claude/_verificar_video ahora aceptan ref_bytes como bytes O
lista (normalizan con _refs; tus llamadas con bytes sueltos siguen idénticas). app.py ganó el
helper _guardar_fotos_busqueda para ambos endpoints de búsqueda. No toqué offer_banner/auto_studio.

### 2026-07-04 · Claude (juanesal-lab) · ✍️ Guiones que SÍ nombran el producto + 🖼️ preview de videos al subirlos
Dos quejas de Juan:
1. **Guiones genéricos que no nombraban el producto**: la causa era el prompt de generate_scripts —
   la info del producto (desc + página) iba pegada AL FINAL, después del formato JSON → Gemini la
   ignoraba. Ahora va DE PRIMERA en un bloque "EL PRODUCTO QUE VENDES" + regla 🏷️ OBLIGATORIA:
   nombrar el producto (nombre/marca EXACTO si existe, si no tipo+atributo) UNA vez en el
   GIRO/PRODUCTO (jamás en el hook) + usar 2-3 detalles REALES de la info (un guion que sirva para
   cualquier producto del nicho se rechaza).
2. **Preview al subir videos**: helper global `vthumbInto` (saca un frame al ~20% con <video>+canvas,
   cache por nombre+tamaño, funciona con Files locales y rutas /api/file) + `vthumbStrip(After)`.
   Cableado en: Cortar clips (lista de archivos Y videos bajados de TikTok, thumb 56x72 en cada fila),
   Clonar producto (ganador + fotos + clips propios vía bind()), Crear creativo (autoFile),
   Variar hook (vhWinner) y ad de referencia del guion (refInput). Fotos = preview directa.
Verificado: py_compile OK, node --check 14/14 bloques OK. AVISO Jack: renderFiles cambió (filas con
<img data-th>), bind() de Clonar tiene 2 líneas nuevas, helpers globales antes de addFiles. Nada
de backend salvo scripts.py (prompt).

### 2026-07-04 · Claude (juanesal-lab) · 📖 MANUAL MAESTRO absorbido: conocimiento al repo + quick-wins implementados
Juan entregó su manual maestro (862 líneas: filosofía, pipeline 100% IA, guion, shotlist, assets,
voz, música, subtítulos, edición, export, QA, schemas, stack). Absorción:
- `assets/manual-maestro-videos-ia.md`: el manual COMPLETO copiado al repo (canónico).
- `assets/manual-maestro-adoptado.md`: mapa de qué regla vive dónde + CONFLICTOS manual-genérico
  vs MEDIDO en las referencias reales (regla de la casa: gana lo medido) + roadmap. Conflictos
  clave: −18 LUFS medido vs −14 del manual (queda −18), cama plana sin drops vs "drop en reveal"
  (queda cama+chime), dissolve medido vs hard-cut genérico (queda dissolve), y ⚠️ PENDIENTE DE
  JUAN: el manual exige ANCLA DE PRECIO en guiones pero su regla actual PROHÍBE cifras → hoy
  manda su regla; si quiere anclas se agrega toggle.
- IMPLEMENTADO del manual: (1) `voiceover.acelerar()` — locución a 1.12× (atempo, sin cambiar
  tono) con word-timings re-escalados ÷factor (subtítulos karaoke y montaje por guion siguen
  clavados); cableada en Mi producto (_guiones_y_narraciones) y Cortar clips (/api/scripts).
  Probado con VO real: 53.13s→47.45s exacto, timings ÷1.12 ✓. (2) Prompt de guiones: ARRANQUE
  EN CALIENTE (primera línea a mitad de pensamiento, jamás "Hola") + HOOK STACKING (micro-gancho
  por fase). (3) hook_gen ya cumplía el ≤8 palabras (usa 6).
- Corto plazo anotado en el doc: SFX cash-register/notification al banco (gasta créditos → OK de
  Juan), safe zone Meta (35% inferior libre, toggle destino), master→2 cuts TikTok/Meta, QA gate
  de video. Grande: módulo GENERACIÓN 100% IA (4º módulo; specs §12-14 del manual).
- AVISO Jack: voiceover.py (+acelerar), producto_clips._tts, app._run_scripts_job (acelera tras
  TTS), scripts.py (2 reglas nuevas en el prompt). py_compile OK.

### 2026-07-04 · Claude (juanesal-lab) · 🎨 Diversidad entre versiones v2 (tope duro de reuso) + 💰 cha-ching en la oferta
Juan reporta que las versiones seguían compartiendo clips ("el mismo video, solo cambia el guion").
Causas encontradas y arregladas:
1. `fases_por_idx` solo cubría el top-60 clasificado por Gemini → ahora TODO el pool de `selected`
   entra al montaje por guion (el resto con fase heurística) = más material disponible.
2. TOPE DURO de reuso entre versiones: `max_usos = ceil(slots_totales / clips_disponibles)`
   (calculado en orchestrator con las frases reales). plan_montaje lo aplica en DOS PASADAS:
   la 1ª respeta el tope en TODAS las fases; solo si el pool entero se agotó bajo el tope, la
   2ª relaja. (El primer intento relajaba por-fase y el tope no servía: un clip salía en 7/8.)
3. Desempate DISTINTO por versión ((i*131+v*977)%13) tras el rinde cuantizado a 0.5s → versiones
   con material equivalente eligen clips distintos sin sacrificar cobertura de la voz.
4. Aviso honesto si el material es escaso (max_usos>3): "sube MÁS videos".
Medido: 80 clips/8 versiones → solape 1.1 de 11 slots (usos máx = tope 2 ✓); 40 clips → 2.9 ✓;
16 clips → inevitable (física), con aviso.
💰 SFX nuevos al banco con ElevenLabs (~$0.10): cash_register.mp3 + notification_pop.mp3.
pro_mix: familia "caja" + cha-ching PROTAGONISTA en el arranque del CTA/oferta (medido en ref 72:
el SFX más fuerte cae sobre el "50% OFF"); el orchestrator ahora pasa las FASES del guion al
mezclador (frases_por_nombre → phases): DOLOR sin SFX, SOLUCIÓN chime, CTA caja. Probado.
AVISO Jack: guion_match._mejor reestructurado (2 pasadas), plan_montaje(+max_usos), orchestrator
(fases completas + phases al mixer + aviso), pro_mix (_familia caja + t_cta). py_compile OK.

### 2026-07-04 · Claude (juanesal-lab) · 📘 Destino TikTok/Meta (safe zone + cut 4:5) + QA gate del producto visible
Siguientes pendientes del Manual Maestro ejecutados:
- **Destino** (§10): selector nuevo "🎵 TikTok / 📘 Meta Ads" en Cortar clips y Mi producto.
  caption_styles: `set_destino()` (global tipo _ACCENT) — TikTok = bloque a ~80% de altura (como
  las referencias); Meta = bloque a ~60% (Meta Reels tapa el 35% inferior con su UI). Medido en
  render real: TikTok 80%, Meta 60% ✓. Cableado: /api/process, /api/scripts, /api/producto-clips
  → settings → process_job/render_versions(destino=...).
- **Cut 4:5 para Meta feed** (§10.2): con destino=meta y aspect 9:16, cada versión genera además
  `path_45` (crop central 1080x1350, captions a 60% quedan adentro ✓). Botón "⬇️ Cut 4:5 para
  Meta feed" en la tarjeta de la versión.
- **QA GATE** (§11.1): al final del render, 1 llamada Gemini flash con un frame del s2.5 de CADA
  versión → si el producto no se alcanza a ver en los primeros 3s, la versión sale con
  `qa_aviso` y la UI muestra el ⚠️ (no bloquea, avisa).
Verificado: py_compile OK, node --check 14/14, posición de captions medida por píxeles en ambos
destinos, crop 4:5 dimensiones exactas. AVISO Jack: caption_styles (+set_destino/_y_centro/_y_piso,
y0 en _render_wordgroup y render de bloque), orchestrator (render_versions+process_job con destino,
bloque 4:5 + QA antes de Finalizando), app.py (3 endpoints + settings + passthrough), producto_clips
(destino a process_job), index.html (2 selectores + fd.append x2 + badge/botón en renderResults).
