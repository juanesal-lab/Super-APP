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

<!-- ⬇️ nuevas entradas debajo ⬇️ -->

### 2026-07-01 · Claude (jackingshop1-cell) · Modernizado startup → lifespan
- Reemplacé el `@app.on_event("startup")` (deprecado) por un `lifespan` con
  `@asynccontextmanager` en `backend/app.py`. La descarga automática del modelo EAST
  sigue igual (se dispara en el arranque, en segundo plano). Probado: el server arranca
  y responde 200, sin el warning de `on_event`.
- **Aviso:** quedan warnings de `websockets.legacy` que son de la librería (dependencia de
  uvicorn), NO de nuestro código; no urge tocarlos.
