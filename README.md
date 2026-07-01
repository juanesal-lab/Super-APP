# 🎬 Super-APP — Editor de ads con IA (Vidaria)

App **local** para crear creativos de dropshipping automáticamente: corta videos de proveedor,
encuentra los mejores momentos con IA, arma varias versiones y les agrega voz en off, subtítulos,
efectos, música y más. También reemplaza el producto de un ad ganador por el tuyo y dobla a otros idiomas.

Todo corre en tu Mac. Web local en http://127.0.0.1:8420

## ✨ Funciones
- ✂️ Corte inteligente (OpenCV + Gemini priorizando el producto), 6 versiones distintas, formatos 1:1/9:16/4:5/16:9, hasta 4K.
- ✍️ Gancho de marketing (manual o IA) y **guiones de voz en off** con el framework real de Juan (viral-creative-coach).
- 🎙️ **Voz en off** (ElevenLabs), 💬 **subtítulos animados** sincronizados, ✨ efectos (zoom + transiciones + whoosh), 🎵 música por nicho.
- 🟦 **Tapar textos del proveedor** con detección precisa frame-por-frame (EAST) que excluye caras y texto pequeño.
- 🔄 **Reemplazar producto**: detecta el producto viejo y mete tus tomas del nuevo, conservando el audio.
- 🎙️ **Doblaje (dubbing)** a 8 idiomas con ElevenLabs.

## 🔧 Requisitos
- **Mac** con **FFmpeg** y **Python 3.12** (`brew install ffmpeg python@3.12`).
- **API key de Google Gemini** (gratis: https://aistudio.google.com/apikey).
- **API key de ElevenLabs** (para voz/doblaje; permisos: Text to Speech, Voices, Sound Effects, Music, Dubbing).

## 🚀 Instalación
```bash
# 1. Entorno + dependencias
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt

# 2. Modelo de detección de texto (EAST, ~92 MB — no viene en el repo)
mkdir -p models
curl -L -o models/east.pb \
  https://raw.githubusercontent.com/oyyd/frozen_east_text_detection.pb/master/frozen_east_text_detection.pb

# 3. Tus API keys — copia el ejemplo y edítalo (o pégalas desde la web)
cp .env.example .env   # y pon tus keys
```

## ▶️ Correr
```bash
./run.sh
```
Abre solo en http://127.0.0.1:8420

## 📁 Estructura
- `backend/app.py` — servidor web (FastAPI)
- `backend/pipeline/` — análisis, ensamblado, voz, subtítulos, efectos, masking, reemplazo de producto, doblaje
- `frontend/index.html` — interfaz
- `assets/` — framework de guiones + efectos de sonido
- `uploads/`, `work/` — temporales (ignorados por git)

## ⚠️ Notas
- El `.env` (tus API keys) **nunca** se sube — está en `.gitignore`.
- Puedes poner tus propios efectos de transición en `assets/sfx/` (.wav/.mp3).
