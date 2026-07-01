# 🧭 HANDOFF — Super-APP (para continuar en otro chat)

Este archivo resume TODO lo construido y lo pendiente, para retomar sin perder nada.
Al abrir un chat nuevo de Claude Code en `~/cortador-clips`, lee también `CLAUDE.md`,
`DEV-LOG.md` y `RESUMEN-TECNICO.md`.

---

## 1. Qué es
**Super-APP** — editor de ads de dropshipping con IA, 100% local en la Mac de Juan.
- Backend: **Python 3.12 + FastAPI + Uvicorn**, motor **FFmpeg**, visión **OpenCV/NumPy/Pillow**.
- Frontend: `frontend/index.html` (HTML/CSS/JS vanilla). Web local en **http://127.0.0.1:8420**.
- Se prende con **`./run.sh`**.
- APIs externas: **Google Gemini** (`gemini-2.5-flash`, SDK `google-genai`) y **ElevenLabs** (REST).
  **NO usa la API de Anthropic** (Claude Code solo la construyó).
- Repo GitHub (privado, 2 colaboradores): **https://github.com/juanesal-lab/Super-APP**
  - Juan = `juanesal-lab` · Amigo = `jackingshop1-cell`.
  - `git push` funciona (credencial en el llavero de macOS). El push/pull necesita RED
    (en Claude Code, correr con el sandbox de Bash desactivado).

## 2. Carpetas (código, sin venv/models/uploads/work)
```
run.sh, requirements.txt, .env (NO se sube), .gitignore
CLAUDE.md          → protocolo de colaboración entre las 2 IAs (auto-cargado)
DEV-LOG.md         → bitácora/"chat" entre las IAs (anotar al terminar cada tarea)
RESUMEN-TECNICO.md → resumen técnico detallado
HANDOFF.md         → este archivo
models/east.pb     → modelo de detección de texto (auto-descarga al arrancar)
assets/            → guion-framework.md + swipe-file-juan.md (voz real de Juan) + sfx/*.wav
frontend/index.html
backend/app.py     → servidor: 12 endpoints, jobs en background, guardar keys
backend/pipeline/  → analyze, gemini_rank, assemble, orchestrator, text_overlay, captions,
                     hook_gen, scripts, voiceover, text_detect, caption_mask(legado),
                     product_swap, dubbing, ffmpeg_utils
```

## 3. Funciones que ya hace la app
1. **Cortar clips inteligentes** → analiza calidad (OpenCV) + Gemini prioriza el producto,
   arma **6 versiones DISTINTAS** (clips disjuntos con muchos videos) + clips sueltos 1:1.
   Formatos 1:1/9:16/4:5/16:9, hasta 4K, duración máx por corte configurable.
2. **Gancho de marketing** (texto quemado): manual, o con IA (Gemini, lee la página vía link).
   Se renderiza con Pillow→PNG→overlay (FFmpeg de Juan NO tiene drawtext/libfreetype).
3. **Guiones de voz en off**: 10 guiones con el framework REAL de Juan (`assets/guion-framework.md`
   de su skill viral-creative-coach: test anti-anuncio, 8 fórmulas, voz colombiana, CTA COD).
4. **Voz en off** (ElevenLabs TTS, voces Kate `qWWAqFomnJ99VwQLREfT` y Juan Carlos
   `G4IAP30yc6c1gK0csDfu`, modelo `eleven_multilingual_v2`). Cada versión puede llevar un
   guion/voz distinto. Botón "Escuchar" para previsualizar.
5. **Subtítulos animados** palabra-por-palabra (ElevenLabs TTS-con-timestamps + Pillow overlay).
6. **Efectos**: zoom (zoompan) + transiciones (xfade) + whoosh REALES (samples en `assets/sfx/`,
   el usuario puede poner los suyos). Solo FFmpeg.
7. **Música de fondo por nicho** (Gemini elige estilo + ElevenLabs Music). ⚠️ requiere permiso.
8. **Tapar textos del proveedor**: EAST (OpenCV DNN) frame-por-frame + excluye caras (Haar) +
   ignora texto chico. Optimizado: enmascara solo los cortes usados en paralelo. ⚠️ ver bug abajo.
9. **Reemplazar producto**: Gemini detecta el producto viejo (contact-sheet) y las tomas del
   nuevo, y las intercambia conservando el audio. `POST /api/swap`.
10. **Doblaje (dubbing)** a 8 idiomas (ElevenLabs Dubbing, asíncrono). ⚠️ requiere permiso.

## 4. APIs / keys / permisos
- `.env` tiene `GEMINI_API_KEY` (AQ.Ab8... funciona con billing) y `ELEVENLABS_API_KEY` (sk_7cae...).
- **Gemini:** ojo, `gemini-2.0-flash` da `limit:0` en la cuenta de Juan → usar `gemini-2.5-flash`.
- **ElevenLabs — permisos que FALTAN activar en la key de Juan** (dan 401 hasta activarlos):
  - **Music Generation** (para la música de fondo).
  - **Dubbing → Write** (para el doblaje).
  - Ya activados: Text to Speech, Voices, Sound Effects.

## 5. Colaboración entre las 2 IAs (idea de Juan)
- `CLAUDE.md` (auto-cargado por Claude Code) tiene el protocolo: al empezar `git pull` + leer
  `DEV-LOG.md`; al terminar cada tarea, anotar en `DEV-LOG.md` + commit + pull + push.
- Regla fija de Juan: **al terminar CADA tarea, subir a GitHub** (commit+push) sin pedirlo.

## 6. ✅ RESUELTO — Bug del blur (falsos positivos de EAST)
**Antes:** el masking de "tapar textos" ponía blur donde NO había texto (árboles, cielo, arrugas).
**Diagnóstico** (con `file (11).mp4`): EAST dispara con confianza 0.9-1.0 sobre texturas naturales,
así que la confianza no discrimina. La **consistencia temporal sola tampoco** basta: un árbol
estático se confirma, y un caption con cámara en mano (posición cambiante) se pierde.

**Fix aplicado en `backend/pipeline/text_detect.py`** (medido sobre datos reales del video):
1. **Forma (discriminador principal):** el texto es una LÍNEA horizontal; follaje/arrugas/bordes
   son cuadrados/verticales. Gate `_MIN_WH=1.5` (ancho/alto). Robusto al movimiento de cámara.
2. **Persistencia (respaldo):** `mask_video` hace 2 pases (detecta→confirma→aplica). Caja poco
   horizontal solo se tapa si persiste ≥2 frames (IoU≥0.3); caja muy horizontal (w/h≥3) se
   conserva aunque aparezca 1 frame. Ver `_confirm()` / `_iou()`.
- Verificado: escenas sin texto → 0 blur; captions reales → tapados completos; audio conservado.
- Tunables arriba del archivo: `_MIN_WH`, `_TEXT_WH`, `_MIN_DETECTIONS`, `_IOU`.
- (Descartado por ahora: OCR/Tesseract — mejoraría precisión pero es dependencia de sistema extra.)

## 7. Ideas que Juan quiere implementar (pidió pasar la lista, quedó pendiente)
- Juan mencionó "varias cosas que queremos implementar" pero la lista NO llegó (mensaje se cortó).
  **Preguntarle la lista** al retomar.

## 8. Cómo continuar (chat nuevo)
1. `cd ~/cortador-clips`, leer `CLAUDE.md`, `DEV-LOG.md`, este `HANDOFF.md`.
2. Arreglar el bug del blur (sección 6) — es lo más urgente.
3. Preguntar a Juan la lista de mejoras pendientes.
4. Al terminar cada tarea: anotar en `DEV-LOG.md` + `git add/commit`, `git pull`, `git push`
   (con red / sandbox de Bash desactivado).
