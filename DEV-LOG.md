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
