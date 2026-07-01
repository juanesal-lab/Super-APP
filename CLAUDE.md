# CLAUDE.md — Instrucciones para la IA (Super-APP)

Este repo lo construyen **dos personas con Claude Code**: Juan (`juanesal-lab`) y su amigo
(`jackingshop1-cell`). Para no pisarnos ni perdernos, sigue SIEMPRE este protocolo.

## 🤝 Protocolo de colaboración entre las dos IAs

1. **Al EMPEZAR a trabajar:** haz `git pull origin main` y **lee `DEV-LOG.md`** para saber
   qué hizo la otra IA desde la última vez. No repitas ni rompas su trabajo.

2. **Al TERMINAR cada tarea:** agrega una entrada AL FINAL de `DEV-LOG.md` con:
   - Fecha, **quién** (firma con tu `git config user.name`), qué hiciste, y **avisos** para la otra IA
     (ej. "cambié la firma de tal función", "falta probar X", "no toques Y que estoy en eso").
   Luego: `git add -A && git commit -m "..." && git pull origin main && git push origin main`.

3. **Siempre `git pull` ANTES de `git push`** (evita rechazos y conflictos).

4. **Nunca subas `.env`** (tiene las API keys — ya está en `.gitignore`).

5. Si hay conflicto en `DEV-LOG.md`, conserva **ambas** entradas (es una bitácora, todo suma).

## 🧩 Qué es la app (rápido)
Editor de ads con IA para dropshipping. Backend Python (FastAPI) + FFmpeg + OpenCV,
frontend en `frontend/index.html`. Usa **Gemini** y **ElevenLabs** (NO Anthropic).
Se prende con `./run.sh` en http://127.0.0.1:8420

📄 **Detalle técnico completo:** ver `RESUMEN-TECNICO.md`.

## ⚙️ Reglas técnicas
- Entorno: `./venv/bin/python` (Python 3.12). Instalar: `./venv/bin/pip install -r requirements.txt`.
- El modelo EAST (`models/east.pb`) se descarga solo al arrancar.
- Las API keys se ponen desde la web o en `.env` (cada quien las suyas).
- Reiniciar el server tras cambios de backend para probar.
