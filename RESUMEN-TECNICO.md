# 📋 Resumen técnico — Super-APP

App **local** (corre en tu Mac, nada en la nube salvo las llamadas a las APIs de IA) para
crear creativos de dropshipping automáticamente.

## 0. Visión general (lo común a todo)

| Aspecto | Detalle |
|---|---|
| **Lenguaje** | Python 3.12 (backend) + HTML/CSS/JavaScript vanilla (frontend, un solo archivo) |
| **Framework web** | FastAPI + Uvicorn (servidor local en http://127.0.0.1:8420) |
| **Motor de video** | FFmpeg / ffprobe (todo el corte, escalado, mezcla de audio, concatenación) |
| **Visión/IA local** | OpenCV (análisis de calidad, detección de texto EAST, detección de caras) · NumPy · Pillow (renderizar textos) |
| **Cómo se prende** | `./run.sh` (o `./venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8420`) |
| **Concurrencia** | Trabajos en segundo plano (threading) + render de clips en paralelo (ThreadPoolExecutor) + GPU del Mac (h264_videotoolbox) |
| **APIs externas** | **Google Gemini** (SDK `google-genai`, modelo `gemini-2.5-flash`) y **ElevenLabs** (HTTP REST). **NO usa la API de Anthropic/Claude** — Claude Code se usó para *construir* la app, pero la app en ejecución solo llama a Gemini y ElevenLabs. |
| **Modelo local** | EAST (`models/east.pb`, ~92 MB, se descarga solo la 1ª vez) para detectar texto |

### Organización de carpetas
```
cortador-clips/
├── run.sh                     # arranca la app
├── requirements.txt           # dependencias Python
├── .env                       # API keys (NO se sube a git)
├── models/east.pb             # modelo de detección de texto (auto-descarga)
├── assets/
│   ├── guion-framework.md     # framework de guiones (skill viral-creative-coach)
│   ├── swipe-file-juan.md     # 43 virales reales (voz de Juan)
│   └── sfx/*.wav              # efectos de transición
├── frontend/index.html        # toda la interfaz (595 líneas)
└── backend/
    ├── app.py                 # servidor FastAPI: 12 endpoints, jobs, keys (557 líneas)
    └── pipeline/              # la lógica, un módulo por responsabilidad:
        ├── ffmpeg_utils.py    # wrappers de ffmpeg/ffprobe + probe()
        ├── analyze.py         # puntúa calidad de video, detecta escenas, elige sub-cortes
        ├── gemini_rank.py     # Gemini rankea clips priorizando el producto
        ├── assemble.py        # recorta a formato, arma versiones, mezcla audio/efectos
        ├── orchestrator.py    # une todo el pipeline (analizar→rankear→ensamblar)
        ├── text_overlay.py    # quema el texto de gancho (Pillow→PNG→overlay)
        ├── captions.py        # subtítulos animados palabra-por-palabra
        ├── hook_gen.py        # Gemini genera el gancho + lee la página del producto
        ├── scripts.py         # Gemini genera guiones con el framework de Juan
        ├── voiceover.py       # ElevenLabs: voz, voz+tiempos, efectos, música
        ├── text_detect.py     # EAST: tapa textos del proveedor frame por frame
        ├── caption_mask.py    # (legado) detección de texto con Gemini
        ├── product_swap.py    # detecta y reemplaza el producto viejo por el nuevo
        └── dubbing.py         # ElevenLabs Dubbing (traduce a otro idioma)
```

### APIs por proveedor
- **Google Gemini** (`gemini-2.5-flash`): rankear clips, generar gancho, generar guiones, detectar producto (viejo/nuevo), describir música/efectos según nicho, leer páginas.
- **ElevenLabs** (REST): Text-to-Speech (voz), TTS con timestamps (subtítulos), Sound Effects, Music, Dubbing.

---

## 1. Cortar clips inteligentes (función principal)
- **Qué hace:** toma varios videos de proveedor, detecta escenas, puntúa cada tramo por calidad (nitidez/luz/movimiento), Gemini prioriza dónde se ve el producto, y arma **6 versiones distintas** (clips diferentes cada una) + clips sueltos en 1:1.
- **Librerías/API:** OpenCV + NumPy (análisis), FFmpeg (corte/ensamblado), **Gemini** (ranking).
- **Inputs:** 3–40 videos, formato (1:1/9:16/4:5/16:9), duración total y máx por corte, descripción del producto, toggles (Gemini, mejorar calidad, efectos, tapar textos).
- **Outputs:** 6 videos montados (mp4) + clips sueltos, descargables hasta 4K.
- **Endpoint:** `POST /api/process` → `GET /api/status/{id}`

## 2. Gancho de marketing (texto en pantalla)
- **Qué hace:** quema una frase de gancho arriba/centro/abajo del video. Manual, o la genera la IA.
- **Librerías/API:** Pillow (renderiza el texto a PNG por falta de libfreetype en FFmpeg) + FFmpeg overlay; **Gemini** para generarlo (opcional, lee la página del producto vía link).
- **Inputs:** texto del gancho o link de la página; posición.
- **Outputs:** el mismo video con el texto quemado.

## 3. Guiones de voz en off (copywriting)
- **Qué hace:** genera 10 guiones de voz en off con el **framework real de Juan** (viral-creative-coach: test anti-anuncio, 8 fórmulas, su voz colombiana, anclas de precio, CTA COD).
- **Librerías/API:** **Gemini** + el archivo `assets/guion-framework.md`.
- **Inputs:** descripción/​link del producto, duración, un frame de muestra.
- **Outputs:** JSON con 10 guiones (ángulo + texto hablado).
- **Endpoint:** parte de `POST /api/scripts`

## 4. Voz en off (narración)
- **Qué hace:** convierte el guion elegido en voz. Cada una de las 6 versiones puede llevar un guion/voz distinto. Botón "Escuchar" para previsualizar.
- **Librerías/API:** **ElevenLabs** TTS (`eleven_multilingual_v2`), voces Kate y Juan Carlos.
- **Inputs:** texto del guion, voz elegida.
- **Outputs:** audio mp3 mezclado sobre el video (reemplaza el audio original).
- **Endpoints:** `POST /api/preview-voice`, `POST /api/render`

## 5. Subtítulos animados
- **Qué hace:** subtítulos palabra-por-palabra sincronizados con la voz (estilo TikTok/CapCut).
- **Librerías/API:** **ElevenLabs** TTS-con-timestamps (tiempos exactos por palabra) + Pillow (renderiza) + FFmpeg overlay con `enable=between(t,...)`.
- **Inputs:** el guion (la voz da los tiempos).
- **Outputs:** video con los subtítulos amarillos quemados.

## 6. Efectos (visuales + sonido)
- **Qué hace:** zoom (punch-in) en cada clip, transiciones entre cortes (xfade) y **whoosh reales** en las transiciones (samples en `assets/sfx/`, el usuario puede poner los suyos).
- **Librerías/API:** solo FFmpeg (zoompan, xfade, mezcla de audio). Sin IA.
- **Inputs:** toggle "Efectos".
- **Outputs:** versiones con más dinamismo + sonido.

## 7. Música de fondo
- **Qué hace:** música instrumental de fondo según el **nicho** del producto (herramientas→industrial, salud→suave…).
- **Librerías/API:** **Gemini** (elige el estilo según el nicho) + **ElevenLabs Music** (la genera).
- **Inputs:** toggle "Música" + descripción del producto.
- **Outputs:** música mezclada a bajo volumen bajo la voz. *(Requiere permiso Music en la key.)*

## 8. Tapar textos del proveedor
- **Qué hace:** detecta los captions/textos quemados del proveedor **frame por frame** y los tapa con blur/mosaico, siguiendo el texto mientras se mueve. Excluye caras y texto pequeño (envase).
- **Librerías/API:** **EAST** (OpenCV DNN, modelo local) + detector de caras Haar (OpenCV) + FFmpeg. Sin IA externa.
- **Inputs:** toggle "Tapar textos".
- **Outputs:** video sin los textos del proveedor (audio intacto).

## 9. Reemplazar producto
- **Qué hace:** detecta dónde aparece el **producto viejo** en un ad ganador y mete las **tomas de tu producto nuevo** en su lugar, **conservando el audio**. Analiza ambos productos con IA.
- **Librerías/API:** **Gemini** (detecta el producto viejo y el nuevo por contact-sheet) + FFmpeg (corta y reensambla).
- **Inputs:** video viejo + tus videos nuevos + descripción/​link de ambos productos.
- **Outputs:** el video con tu producto y el audio original.
- **Endpoint:** `POST /api/swap`

## 10. Doblaje (dubbing)
- **Qué hace:** traduce la voz del video a otro idioma manteniendo el tono (8 idiomas).
- **Librerías/API:** **ElevenLabs Dubbing** (asíncrono: crea el trabajo, sondea, descarga) vía `requests`.
- **Inputs:** un video, idioma origen (o auto) y destino.
- **Outputs:** el video doblado. *(Requiere permiso Dubbing en la key.)*
- **Endpoint:** `POST /api/dub`

---

## Endpoints (resumen)
| Endpoint | Función |
|---|---|
| `GET /` | sirve la interfaz |
| `GET /api/config` | estado de keys, voces, idiomas |
| `POST /api/save-key` | guarda API keys (Gemini/ElevenLabs) |
| `POST /api/process` | cortar clips (1 paso, sin voz) |
| `POST /api/scripts` | analizar + generar 10 guiones |
| `POST /api/preview-voice` | escuchar un guion |
| `POST /api/render` | armar las 6 versiones con voz/subtítulos/efectos |
| `POST /api/swap` | reemplazar producto |
| `POST /api/dub` | doblaje |
| `GET /api/status/{id}` | progreso de un trabajo |
| `GET /api/file` · `GET /api/download` | previsualizar / descargar resultados |
