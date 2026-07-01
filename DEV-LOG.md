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
