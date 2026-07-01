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
