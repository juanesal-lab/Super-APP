# HANDOFF (Fable 5) — CreativeMaxing / Super-APP · traspaso para la nueva sesión

> **Léeme primero.** Este archivo te pone al día para seguir construyendo esta app sin perderte.
> Después, haz `git pull origin main` y lee **`CLAUDE.md`** + **`DEV-LOG.md`** (bitácora cronológica de
> TODO lo hecho). El `HANDOFF.md` viejo del repo está **desactualizado**; ignóralo, usa ESTE.

---

## 1) Qué es la app
**CreativeMaxing** = editor local de creativos (ads) con IA para **dropshipping** (LATAM/España, pago
contraentrega). El usuario sube videos/imágenes ganadores y la app genera creativos listos para subir:
clips, versiones, doblaje colombiano, subtítulos, música/efectos, ads de imagen, búsqueda de creativos.

- **Backend:** Python 3.12 + FastAPI (Uvicorn), puerto **8420**. Carpeta `backend/`.
- **Frontend:** una sola página `frontend/index.html` (tema negro/dorado/crema, con pestañas).
- **IA:** Google **Gemini** (`gemini-2.5-flash`; imágenes `gemini-3-pro-image-preview` = Nano Banana 2),
  **ElevenLabs** (voz/música/SFX), **Anthropic/Claude** (`claude-opus-4-8`, cerebro de "Ads imagen"),
  **Foreplay** (biblioteca de ads).
- **Media:** FFmpeg (GPU `h264_videotoolbox` vía `assemble.venc()`), OpenCV, EAST (`models/east.pb`,
  se baja solo), Pillow.

### Cómo correrla
```bash
cd /Users/jaca/Transcriptor/Super-APP
./run.sh                       # o:
./venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8420
# abre http://127.0.0.1:8420
```
Usa SIEMPRE `./venv/bin/python`. Deps: `./venv/bin/pip install -r requirements.txt`.
Las API keys se ponen desde la web (pestaña **🔑 Claves**) o en `.env` (**NUNCA commitear `.env`**).

---

## 2) Con quién trabajas (perfil del usuario)
- Es **jackingshop1** (git: `jackingshop1-cell`). **NO es técnico** → háblale en **español colombiano**,
  simple, sin jerga. No expliques código salvo que lo pida.
- **Consciente del costo:** "no me hagas gastar mucha plata". Pruebas **baratas y dirigidas**, no corridas
  pagas a ciegas.
- **Exige calidad:** se molesta si entregas algo visual sin verificarlo. **Verifica SIEMPRE con captura
  (screenshot) o extrayendo un frame ANTES de decir "listo".**

## 3) Colaboración con la otra IA (Juan)
Dos personas construyen el repo con Claude: **Juan** (`juanesal-lab`) y el usuario (`jackingshop1-cell`).
Repo: https://github.com/juanesal-lab/Super-APP
1. **Al empezar:** `git pull origin main` + lee `DEV-LOG.md`.
2. **Al terminar cada tarea:** entrada al FINAL de `DEV-LOG.md` firmada, con **avisos** para Juan ("toqué
   tal archivo/función"). Luego `git add -A && git commit && git pull --no-rebase && git push`.
3. **Siempre `git pull --no-rebase` ANTES de `git push`.** Juan trabaja en paralelo → habrá conflictos;
   resuélvelos conservando el trabajo de AMBOS (en `DEV-LOG.md` conserva las dos entradas).
4. Firma como `jackingshop1-cell`.

---

## 4) ⭐ REGLAS DE ORO (no romper NUNCA)
1. **NUNCA mostrar PRECIO** en ninguna sección (ni $, COP, ni descuentos con número). Ofertas "2x1" o
   "envío gratis" SÍ (son texto, no cifra).
2. **SIEMPRE excluir COLOMBIA** de las búsquedas (español pero NO Colombia). Ya aplicado en Buscar TikTok
   (`region != "CO"`). En **Foreplay TODAVÍA NO** (ver pendientes).
3. **CTA obligatorio EXACTO** (no cambiar):
   `"por tu compra hoy te regalamos el envío, y para tu seguridad ante estafas pagas al recibir"`.
4. **Verifica visualmente** antes de decir que quedó (screenshot Chrome MCP o frame con ffmpeg).
5. **No commitear `.env`.** Cost-conscious. Reinicia el server tras cambios de backend.

---

## 5) Mapa de la app (pestañas → archivos)
Pestañas: **Cortar clips · Mi producto · Editor · Ads imagen · Descargar · Foreplay · Buscar TikTok ·
Crear creativo · Clonar ganador · Doblar · Claves · Guía**.

Backend (`backend/`):
- `app.py` — servidor + endpoints (`/api/process`, `/api/scripts`, `/api/auto`, `/api/dub`,
  `/api/producto-clips`, `/api/tiktok-search`, `/api/foreplay-search`, `/api/foreplay-video`,
  `/api/caption-preview`, `/api/save-key`…). Jobs en background.
- `pipeline/orchestrator.py` — `process_job` / `render_versions` (Cortar clips, Mi producto). Versiones
  = **8**. Subtítulos con `caption_styles.burn_word_captions(style=caption_style)`.
- `pipeline/assemble.py` — FFmpeg: `build_variations` (8 versiones diversas), `add_music_sfx` (música baja
  + SFX variados en cortes, conserva audio), `punch_pace` (acelera >~22s en sync, tope 1.35x), `blur_boxes`,
  `venc()`.
- `pipeline/caption_styles.py` — 5 estilos elegibles: **hormozi, karaoke, highlight_box, bold_outline,
  yellow_highlight**. `burn_word_captions`, `_render_wordgroup`.
- `pipeline/auto_studio.py` — "Crear creativo" (auto): doblaje CO → tapar subtítulos viejos (2 bandas:
  `detect_subtitle_band` abajo + `detect_top_band` arriba) → vertical 9:16 → música/SFX por fase → banner
  oferta opcional → subtítulos (caption_style) → normalizar → **pacing**.
- `pipeline/winner_clone.py` — "Clonar ganador". Doblaje inteligente por idioma; texto en pantalla modo
  **"limpiar"** (traduce lo extranjero, TAPA lo español); subtítulos; + **pacing** al final.
- `pipeline/text_translate.py` — `traducir_texto_pantalla(modo="traducir"|"tapar"|"limpiar")`.
- `pipeline/subtitle_band.py` — `detect_subtitle_band` (abajo) + `detect_top_band` (arriba, EAST local).
- `pipeline/tiktok_search.py` — "Buscar TikTok" (tikwm). Excluye CO. Verificación IA de MISMO producto
  (categoría+propósito+forma; acepta otra marca). Términos cortos + inglés, pool grande en paralelo.
- `pipeline/producto_clips.py` — "Mi producto" (links ganadores + tu producto → clips + música auto).
- `pipeline/disruptive_images.py` — "Ads imagen" (**de Juan**; Claude=cerebro, Nano Banana=imagen). 2
  plantillas fijas primero (contrarian + prueba social), resto surreales.
- `pipeline/offer_banner.py` — banner "ENVÍO GRATIS · PAGAS AL RECIBIR / OFERTA 2X1" arriba (IA lo ubica).
- `pipeline/creative_variator.py` — **(de Juan)** cerebro para variar hook/guion de un ganador (aún SIN
  capa de video ni endpoint/UI).
- `pipeline/{scripts,dub_colombia,voiceover,phase_effects,narrative,foreplay_search,downloader}.py`.

---

## 6) Estado ACTUAL — hecho recientemente (jul 2026)
- ✅ **Selector de 5 estilos de subtítulos** + **preview** (`/api/caption-preview`) en Cortar clips y
  Crear creativo.
- ✅ **Ads imagen**: 2 plantillas GANADORAS fijas de primeras (contrarian "NO COMPRES ESTO" + prueba
  social con capturas), resto surreales.
- ✅ **Cortar clips**: 8 videos + música de fondo + SFX variados en cortes + más variedad de escenas.
- ✅ **Banner de oferta ARRIBA** opcional (toggle en Crear creativo); IA lo ubica sin tapar.
- ✅ **Análisis de 24 creativos reales que fallaban** → arreglado: subtítulos VIEJOS ya no quedan
  (Clonar ganador "limpiar"; Crear creativo tapa 2 bandas), + **pacing punchy** (acorta >22s en sync).
- ✅ **Buscar TikTok**: más links del MISMO producto (11 → 21 en prueba real): términos cortos+inglés,
  pool grande en paralelo, acepta el mismo producto de otra marca. Excluye Colombia.

## 7) PENDIENTES (lo que sigue)
1. **#3 "Variar el hook del winner"** (grande): subir un ganador → buscar hooks en TikTok por su ángulo →
   si ya tiene hook, quitarlo y poner el nuevo; si no, ponerlo antes → **4 videos** variando el hook. Hook
   en otro idioma → traducir; texto en pantalla → taparlo (fondo blanco + Poppins) y traducir (si es
   español, dejar). → **Juan ya hizo el CEREBRO** (`creative_variator.py`). **Falta la capa de VIDEO**
   (poner el hook, buscar toma, tapar/traducir, ensamblar los 4). **COORDINAR CON JUAN antes de tocar.**
2. **Voz en off + subtítulos SELECCIONABLES en "Mi producto"** (pesado): hoy Mi producto pone música +
   volumen, pero NO tiene voz en off ni subtítulos (necesita guion/transcripción por versión).
3. **Foreplay: excluir Colombia** — hoy NO se excluye (la API no expone el país; solo filtra idioma
   español). Coordinar con Juan (`foreplay_search.py`).

## 8) Cómo verificar (lo que espera el usuario)
- Backend: `./venv/bin/python -m py_compile ...`, reinicia el server, prueba el endpoint / corre la función
  con datos reales (hay videos de prueba en `~/Downloads/`: carpetas de almohadillas / bee venom / plagas).
- Visual: abre http://127.0.0.1:8420 con Chrome MCP y **screenshot**, o extrae un frame con ffmpeg y míralo.
  NO digas "listo" sin verlo.
- Anota en `DEV-LOG.md` + avisos a Juan, y sube (`pull --no-rebase` antes de `push`).

---
_Generado por la sesión Opus 4.8 de jackingshop1-cell para traspaso a la sesión Fable 5.
Archivo local de traspaso (no hace falta commitearlo)._
