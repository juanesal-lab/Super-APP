# 🛠️ Mejoras de UX — que Jack produzca más rápido y con menos fricción (2026-07-13)

Área tocada: **backend/app.py** + **frontend/index.html** SOLAMENTE. No se tocó `backend/pipeline/*`
(es de otro agente). Todo es **ADITIVO**: ningún endpoint ni flujo viejo cambió de comportamiento.

## Qué le faltaba a la app (lo que encontré recorriéndola)
- Los **trabajos eran invisibles**: cada pestaña tenía su propio poll y su propia barrita; si te
  cambiabas de pestaña, "perdías de vista" qué estaba corriendo. Y si algo fallaba, el error quedaba
  enterrado en esa pestaña. No había forma de ver TODO junto ni de **reintentar** sin rearmar todo.
- Los **errores de las keys** (Gemini sin créditos, Foreplay sin plata, falta ElevenLabs/Claude)
  recién aparecían cuando le dabas Generar y explotaba — o escondidos en una pill de la pestaña Claves.
- Los **resultados** (videos/imágenes terminados) quedaban dispersos: cada uno vive en la pestaña
  donde lo lanzaste. No había una vista de "todo lo que hice" ni forma de mandarlo al Telegram del dueño.
- La **bitácora `work/_eventos.jsonl`** ya guardaba cada búsqueda de creativos, pero NADIE la veía.

## Lo que implementé

### 1. 🗂 Panel de trabajos flotante (siempre a la vista)
Botón flotante abajo a la derecha (al lado del 🤖). Muestra en vivo, para todos los trabajos:
- **Qué corre**, con **% y mensaje**, más "lleva X min · suele tardar Y" (sacado de las duraciones
  típicas que ya conocía el asistente) y aviso ⚠️ si lleva más del doble.
- **Qué falló y POR QUÉ** (el error concreto del backend, no un "error" seco).
- **Qué terminó** y qué produjo (ej. "8 versiones de video", "3 creativos ok").
- Botón **🔄 Reintentar** en los que fallaron (relanza con los MISMOS insumos y ajustes, 1 clic) y
  **↗ ir a la pestaña** para relanzar a mano.
- El botón muestra un contador cuando hay trabajos corriendo. Sondea suave: 5s si hay algo activo o
  el panel abierto, 20s si no (no machaca el backend).
- Backend: `GET /api/jobs` (foto en vivo) + `POST /api/retry`. El reintento funciona porque ahora los
  lanzamientos de job pasan por un helper `_lanzar_job(...)` que guarda la "receta" (función + inputs)
  en el propio job. Cubrí los **19 flujos principales** (cortar clips, más versiones, guiones, render,
  clon, reemplazar, doblar 1 y 2, descargar, mi producto, foreplay producto/clips, buscar creativos,
  crear creativo, variar hook, landing…). Los pocos que quedan sin reintento-de-1-clic (render con voz,
  regenerar versión, ads imagen, variar imagen, tiktok en 2º plano) igual **se ven** en el panel y
  ofrecen "↗ ir a la pestaña" — es honesto, no promete un botón que no anda.

### 2. 🩺 Barra de salud arriba (errores de keys visibles y accionables)
Una barra arriba de la app que aparece SOLO si hay algo que arreglar. Cada aviso dice **qué pasa +
qué hacer + "Arreglar →"** que te lleva a la pestaña:
- Gemini sin key / **sin créditos (429)** / inválida.
- ElevenLabs o Claude sin configurar (con qué te quedás sin poder hacer).
- **Foreplay sin créditos** o key inválida.
Backend: `GET /api/salud` — reusa los caches de 10 min de Gemini y Foreplay, así que es barato
(no le pega a las APIs en cada refresh). Se refresca al abrir y cada 2 min.

### 3. 🗃️ Pestaña "Resultados" (galería) con "📲 Mandar al Telegram del dueño"
Nueva pestaña que junta **todo lo producido**, agrupado por trabajo (con su producto y fecha), con
preview de cada video/imagen y dos botones: **⬇️ Abrir** y **📲 Telegram**.
- Backend `GET /api/galeria`: primero mira los jobs en memoria (result completo); si el server se
  reinició, **escanea `work/`** con heurística (agarra el archivo FINAL de cada versión/creativo/ad
  aunque encadene sufijos `_vo_of_mx_ln`, y los doblajes/swaps/exports/imagenes sueltas).
- Backend `POST /api/enviar-telegram`: manda el archivo al **mismo bot del negocio**
  (@Jacabuenashopbot). Lee el token del `.env` de Vidaria (NUNCA se imprime) y el chat del dueño de
  `Vidaria/data/.telegram-owner` — mismo esquema que `scripts/telegram-bot.js`. Elige solo
  `sendPhoto`/`sendVideo`/`sendDocument` según extensión. Rechaza con mensaje honesto si el archivo
  pesa >49MB (tope de Telegram por bot) o si el bot no está configurado en esta máquina.

### 4. 🕘 Historial de búsquedas (en Buscar creativos)
Toggle "🕘 Historial de búsquedas" que muestra las últimas corridas con producto, fuente, cuántos
encontró y si falló (por qué). Backend `GET /api/historial-busquedas` — le da por fin una vista a la
bitácora `work/_eventos.jsonl` que ya existía.

## Cómo lo probé (sin tocar la app viva del 8420)
- `py_compile backend/app.py` → OK. Los 20 bloques `<script>` del frontend parsean limpios (node vm).
- Levanté un **uvicorn de prueba en :8421** (la app viva de :8420 nunca se tocó; el :8440 es el
  Montador y lo dejé quieto).
- **Endpoints nuevos:** `/api/jobs` (vacío OK), `/api/salud` (detecta keys OK sin avisos falsos),
  `/api/historial-busquedas` (30 búsquedas reales), `/api/galeria` (3 grupos desde disco, cada item
  se sirve 200 `video/mp4`). `/api/retry` happy-path: lancé un job real de descarga → `ok:true` con
  job_id nuevo. Validaciones: `/api/enviar-telegram` con path fuera de `work/` → **403**; `/api/retry`
  con job inexistente → **404**. (No mandé ningún Telegram de prueba al dueño, como se pidió.)
- **Endpoints viejos (sin regresión):** `/` (200, 335KB), `/api/config` (gemini ok, 2 voces),
  `/api/foreplay-usage` (200), `/api/status/{inexistente}` (404 honesto), `/api/last-project` (404).
- Filtro de ruido: los contextos intermedios (status `angles` del paso 1 de Ads imagen) ya NO
  ensucian el panel de trabajos (verificado tras forzar la carga desde disco).

## ¿Hay que reiniciar la app?
**SÍ.** Los cambios de `backend/app.py` (endpoints nuevos) recién viven cuando se reinicie el uvicorn
de :8420 (corre sin `--reload`). El frontend es solo servir el `index.html` nuevo, pero conviene el
reinicio para que backend y front queden en la misma versión. **No lo reinicié yo** (regla: app en
producción local). Que lo haga el que administra el server: matar el uvicorn de :8420 y relanzar
(`./run.sh` / el supervisor lo levanta con el código nuevo).

## Notas para la otra IA (Juan)
- `backend/app.py` ganó: helper `_lanzar_job` + los 5 endpoints nuevos al final del archivo
  (`/api/jobs`, `/api/retry`, `/api/salud`, `/api/historial-busquedas`, `/api/galeria`,
  `/api/enviar-telegram`). Los `threading.Thread(target=_run_*_job…)` de los 19 flujos principales
  ahora pasan por `_lanzar_job` (misma semántica, + guarda receta de retry). Los sub-jobs internos
  (tiktok 2º plano, render, regen, disruptive_v2, variar_imagen, la closure de descubrir) quedaron
  con su `threading.Thread` de siempre.
- `frontend/index.html`: pestaña "🗃️ Resultados", barra `#saludBar`, panel flotante `#jobsBtn/#jobsPanel`,
  historial en Buscar creativos. Todo con su propio JS al final (antes del bloque del asistente).
  No toqué la lógica de ninguna pestaña existente.
