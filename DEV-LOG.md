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
