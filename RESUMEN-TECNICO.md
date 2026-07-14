# 📋 Resumen técnico — Super-APP

App **local** (corre en tu Mac, nada en la nube salvo las llamadas a las APIs de IA) para
crear creativos de dropshipping automáticamente. Esto es el MAPA técnico; el uso y las
reglas de Jack están en `PROMPT-ONBOARDING.md`.

## 0. Visión general

| Aspecto | Detalle |
|---|---|
| **Lenguaje** | Python 3.12 (backend) + HTML/CSS/JS vanilla (frontend, un solo archivo) |
| **Framework web** | FastAPI + Uvicorn (servidor local en http://127.0.0.1:8420) |
| **Motor de video** | FFmpeg / ffprobe (corte, escalado, mezcla de audio, concatenación, loudnorm) |
| **Visión/IA local** | OpenCV (calidad, escenas, texto EAST, caras) · NumPy · Pillow (renderizar textos) |
| **Cómo se prende** | `./run.sh` — es un **SUPERVISOR**: arranca uvicorn en :8420 SIN --reload, hace auto-pull de GitHub cada 30s (frontend/docs aplican al instante; backend reinicia SOLO con la app libre, consultando `/api/busy` con doble chequeo) y revive el server si se cae |
| **Concurrencia** | Jobs en segundo plano (threading) + render en paralelo (ThreadPoolExecutor) + GPU del Mac (h264_videotoolbox) |
| **APIs externas** | **Gemini** (`google-genai`, `gemini-2.5-flash` — el cerebro) · **ElevenLabs** (REST: TTS, timestamps, SFX, música, dubbing) · **Claude/Anthropic** (guiones, copy de landings, conceptos de ads imagen, 2º juez de búsquedas — cuando hay key) · **Foreplay** (ads ganadores) · **Pexels/Pixabay** (b-roll de stock) · **ScrapeCreators** (📡 Radar) · **Shopify Admin** (landings) |
| **Modelo local** | EAST (`models/east.pb`, ~92 MB, auto-descarga) para detectar texto quemado |
| **Keys** | `_KEY_ENV` en app.py: gemini, eleven, anthropic, foreplay, pexels, pixabay, scrapecreators, shopify_domain/token/theme. Gemini se valida **EN VIVO** (`gemini_key_status`: genera 1 token, cache 10 min → la pill dice "sin cuota (429)" / "key inválida") |

### Organización de carpetas
```
Super-APP/
├── run.sh                    # supervisor: :8420 + auto-pull + reinicio seguro (/api/busy)
├── requirements.txt
├── .env                      # API keys (NO se sube a git)
├── feedback-jack.md          # feedback de Jack desde la app (/api/feedback) → leerlo al arrancar
├── models/east.pb            # detección de texto (auto-descarga)
├── assets/                   # research + plantillas: estructuras-validadas.json ·
│                             #   patron-ganador-validado.md · playbook-por-nicho.md ·
│                             #   research-hooks-2026-4mercados.md · funnel-tofu-mofu-bofu-2026.md ·
│                             #   landing-templates/ · guion-framework.md · sfx/ · fonts/ · garage/
├── frontend/index.html       # TODA la interfaz (SPA vanilla, ~4.400 líneas, 17 bloques <script>)
├── backend/
│   ├── app.py                # FastAPI: ~65 rutas, jobs (con `tipo`), keys, post-proceso
│   ├── radar_api.py          # monta /radar + /api/radar/* (scan, scan-status, resumen, candidatos)
│   └── pipeline/             # un módulo por responsabilidad (mapa abajo)
├── montador/                 # SUB-APP de Juan "Montador" (:8440, venv y .env PROPIOS)
├── radar/                    # motor del Radar (stdlib puro: radar.py, dashboard.py, sourcing…)
└── work/                     # resultados por job (auto-limpieza de disco) + _eventos.jsonl
```

## 1. Mapa del pipeline (`backend/pipeline/`)

**Núcleo de video**
- `ffmpeg_utils` — wrappers ffmpeg/ffprobe + `probe()` + **`video_ok()`** (valida mp4 de salida) + **`normalize_loudness()`** (-14 LUFS)
- `analyze` — calidad, escenas, sub-cortes
- `assemble` — recorte a formato, versiones, audio/efectos; **`plan_variations(n_versions, start_version)`** = base del "1 de prueba → N más" (índice ABSOLUTO: la versión B siempre recibe los clips/guion/voz de B)
- `orchestrator` — une todo (`render_versions`/`process_job`); `_select_for_target` **penaliza clips con texto quemado** (`text_coverage`) y fuerza los b-roll al pool; manifest con `avisos`
- `regen` — regenerar UNA versión con motivo (guion/otra), honesto si la IA no corre
- `guion_match` — `plan_montaje`: a cada FRASE de la voz el clip que mejor la ilustra + `afinidad` (desempate por contenido, Gemini)
- `phase_classify` / `phase_effects` / `pro_mix` / `gif_export`

**Guiones e IA**
- `scripts` — guiones con el framework de Juan; **`asignaciones`** (avatar × estructura, duración propia); **mix TOFU/MOFU/BOFU** (CTA dura solo en BOFU); si la IA no corre **LEVANTA RuntimeError** (nunca devuelve [] en silencio)
- `estructuras_validadas` — `asignar_estructuras()`: genera 4-8 avatares del producto y asigna (avatar, estructura) por versión; 9 estructuras en `assets/estructuras-validadas.json`; fallback sin IA va rotando la biblioteca (8/8 distintas)
- `narrative` · `winner_blueprint` (+ `blueprint_ganador.json`) — análisis/clonación de estructura de un ad de referencia (🧬)
- `hook_gen` — gancho por mecánica (research 4 mercados) + `generate_hooks_for_versions` (1 hook coherente POR versión, sin precios)
- `gemini_rank` · `gemini_fast` (REST rápido, expone `ultimo_error`)
- **`ia_errors`** — `es_cuota()` + `error_amigable(err, motor)`: TODO error nombra el motor REAL (Claude/Gemini) y qué hacer; es la base del "no mentir con ✅ listo"

**Overlays y masking**
- `text_detect` — EAST frame a frame; **`_obscure` = vidrio esmerilado** (niveles suave/medio/fuerte vía `blur_strength`); **`text_coverage()`** (fracción de frame con texto → penaliza la selección)
- `smart_caption_mask` · `caption_mask` (legado) · `subtitle_band` — masking con Gemini (distinguen cuota vs "no hay subtítulos")
- `text_translate` — traducir el texto quemado del proveedor
- `text_overlay` — gancho (Pillow→PNG→overlay) + **`burn_hook_pill`** (pastilla blanca del hook por versión, 0-3s)
- `captions` / `caption_styles` — subtítulos palabra-por-palabra estilo TikTok
- `offer_banner` — banner "OFERTA 2X1 · ENVÍO GRATIS…" con `line2` personalizada (🎁 tu oferta) y `start`/`dur`
- `end_card` — 🏁 cierre CTA de 1.5s ("PAGAS AL RECIBIR" + pill "PIDE EL TUYO AQUÍ")

**Voz y doblaje**
- `voiceover` — ElevenLabs: TTS, TTS+timestamps, SFX, música
- `dub_colombia` — doblaje colombiano; `generar_dub(segments_override=)` respeta el guion EDITADO por Jack (paso ① de Doblar)
- `dubbing` — ElevenLabs Dubbing (= "🎯 doblaje exacto", conserva la voz original)

**Búsqueda**
- `tiktok_search` — tikwm con **pacer global 1 req/s + retries** (el rate-limit ya no se disfraza de "0 resultados"); `buscar_broll`
- `creative_search` — camino RÁPIDO: `analizar_producto` (1 análisis compartido) + `buscar_foreplay_rapido` + `buscar_tiktok_solo` (TikTok como job en 2º plano); juez de portada + deep de video OPCIONAL (`tk_deep_max`/`fp_deep_max`); resultados por **niveles** (✅ confirmados / 🟡 candidatos); acepta foto O video (5 mejores frames); Claude como 2º juez
- `foreplay_search` — validados +30 días, orden longest_running, Colombia excluida, **`fallback_idiomas`** (badge 🌎), escalera honesta 30→7→sin días
- `stock_broll` — **Pexels/Pixabay = fuente PRINCIPAL de b-roll** (TikTok solo fallback)
- `downloader` — bajar videos por link

**Flujos completos**
- `auto_studio` — ✨ Crear creativo (cadena completa; `ok` REAL por creativo) + Modo Ganador (2x1 opcional)
- `winner_clone` / `angle_clone` / `product_swap` — clon con mi producto / reemplazo (producto ajeno NUNCA visible; `ok` = ¿el reemplazo corrió?)
- `producto_clips` — flujo 📦 Mi producto
- `hook_variator` / `creative_variator` — variar hook / variaciones
- `disruptive_images` — 🎨 ads imagen (conceptos con Claude + Nano Banana 1/2, advertorial con PIL)
- `image_variator` — 📸 variar una imagen ganadora

**Landings y Shopify**
- **`landing_agent`** — `generar_landing()`: Claude (tool_use JSON por bloque) llena la plantilla (📰 Advertorial 16 bloques / 🛍️ Landing 11 bloques, en `assets/landing-templates/`) → **`_limpiar_cifras()`** borra precios/descuentos inventados (solo los EXACTOS de Jack) → imágenes por sección con Nano Banana (falla → foto real + aviso) → preview HTML. `publicar_en_shopify()`: assets `cm-*` (jamás toca lo existente), solo tras el **gate de aprobación**. Reviews = placeholders (nunca inventadas)
- `shopify_admin` — API Admin de Shopify (se usa, no se toca)

**Ops**
- `asistente` — chat 🤖 con EVIDENCIA real: snapshot de jobs, bitácora `work/_eventos.jsonl` (toda búsqueda/job anota conteos, errores, duración), keys en vivo; sin IA responde con `respuesta_deterministica`; puente de dudas a Claude terminal
- `supervisor` — utilidades de supervisión

## 2. Post-proceso de cada versión (EN ORDEN)

```
música → banner de oferta (start/dur) → 🏁 end-card → hooks por versión
      (pastilla; guarda _prehook para re-aplicar) → normalizar audio -14 LUFS
      → video_ok (valida el mp4; manifest avisa corruptos + `avisos` de lo que no corrió)
```

## 3. Robustez (regla "no mentir")
- `ia_errors`: nunca "✅ listo" si la IA no corrió — error con el motor REAL y qué hacer.
- `/api/auto` y clon: `ok` REAL por creativo. `generate_scripts` lanza excepción (no `[]`).
- `gemini_key_status` en `/api/config`: check EN VIVO (429 sin créditos ≠ "configurada ✓").
- `manifest.avisos` / `music_warning` / `reference_warning`: el lote sale pero AVISA lo que faltó.
- `/api/feedback` → `feedback-jack.md`: lo que Jack marca en la prueba llega a Claude terminal.

## 4. Sub-apps (viajan en el repo, corren aparte)
- **`montador/`** — "Montador" de Juan: FastAPI PROPIO en :8440 (venv y `.env` propios —
  ANTHROPIC + ELEVENLABS), embebido en iframe en la pestaña 🎬 Montar ad.
  `/api/montador/status` (up/instalado) y `/api/montador/start` (1ª vez instala el venv solo).
  Incluye **agente B-roll** (`montador/backend/agentes/broll.py`): Claude detecta frases que
  piden ilustración → Pexels/Pixabay → clip en el beat exacto (producto SIEMPRE con tomas del usuario).
- **`radar/`** + `backend/radar_api.py` — Radar de ganadores (Meta Ad Library vía ScrapeCreators).
  Dashboard en `/radar`; `POST /api/radar/scan` corre scan→report→dashboard en background
  (~69 créditos → SOLO manual). La key se guarda desde 🔑 Claves (doble-write a `radar/.env`).

## 5. Endpoints (mapa por grupo)

| Grupo | Endpoints |
|---|---|
| **Núcleo** | `GET /` · `GET /api/config` · `POST /api/save-key` · `GET /api/status/{id}` · `GET /api/file` · `GET /api/download` · `GET /api/busy` |
| **Cortar clips / Mi producto** | `POST /api/process` (1 de prueba, `n_versions`) · `POST /api/scripts` (guiones + `reference_url` 🧬 + banner/oferta/end_card/blur) · `POST /api/preview-voice` · `POST /api/render` (`n_versions`/`start_version`, con voz) · `POST /api/more-versions` (N más sin voz) · `POST /api/reaplicar-hook` · `POST /api/regenerate-version` · `POST /api/producto-clips` · `POST /api/feedback` · `GET /api/caption-preview` · `GET /api/last-project` |
| **Búsqueda** | `POST /api/creative-search` (rápido: Foreplay ya + `tiktok_job` en 2º plano) · `POST /api/creative-search-job` · `POST /api/creative-more` · `POST /api/tiktok-search` · `POST /api/broll-dolor` (landing obligatoria) · `POST /api/fetch-links` |
| **Foreplay** | `POST /api/foreplay-search` · `/api/foreplay-producto` · `/api/foreplay-clips` · `GET /api/foreplay-thumb` · `/api/foreplay-video` · `/api/foreplay-usage` |
| **Auto / Clon / Variar** | `POST /api/auto` · `POST /api/clone` · `POST /api/swap` · `POST /api/variar-hook` (+`-otro`) |
| **Doblar** | `POST /api/dub-preview` (① traducir, editable) · `POST /api/dub-generar` (② voz/exacto + 2x1) · `POST /api/dub` (legado) · `POST /api/download-videos` |
| **Ads imagen** | `POST /api/disruptive-angles/-images/-hd/-add-product/-edit-image/-swap-concept` · `POST /api/regenerate-image` · `POST /api/variar-imagen` |
| **Landings** | `POST /api/landing-generate` (job + preview) · `POST /api/landing-publicar` (GATE) · `GET /api/shopify-check` |
| **Editor** | `GET /api/editor-project` · `POST /api/editor-export` |
| **Montador** | `GET /api/montador/status` · `POST /api/montador/start` |
| **Radar** | `GET /radar` · `POST /api/radar/scan` · `GET /api/radar/scan-status` · `/api/radar/resumen` · `/api/radar/candidatos` |
| **Asistente** | `POST /api/asistente` (🤖 con evidencia real) |
