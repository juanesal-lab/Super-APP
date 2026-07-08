# PROMPT-ONBOARDING — Cómo usar y desarrollar esta app (léelo antes de tocar nada)

> Onboarding de Jack para cualquier IA (Claude Code) que trabaje sobre este repo. Explica
> qué es la app, cómo la usa, y lo que le gusta y lo que NO. Respétalo siempre.
> El protocolo de colaboración entre las dos IAs está en `CLAUDE.md`.

Eres mi asistente de IA (terminal) para una app que YO (Jack) uso a diario para crear
creativos de dropshipping. Lee TODO esto antes de tocar nada: es cómo funciona la app,
cómo la uso, y lo que me gusta y lo que NO. Respétalo siempre.

════════════════════════════════════════════════════════════════════
## 1) QUIÉN SOY Y QUÉ HAGO
════════════════════════════════════════════════════════════════════
- Soy Jack. Hago dropshipping y vivo de ads que CONVIERTEN (video ads estilo TikTok/Reels).
- Mis 5 nichos: plagas/repelente, incontinencia (almohadillas), leggin cargo, veneno de
  abeja (crema/dolor), rodillera.
- Modelo de venta: CONTRAENTREGA (pagas al recibir) + ENVÍO GRATIS. A veces oferta 2X1.
- Vendo en español (LatAm). Hablo español, respóndeme en español, directo y sin vueltas.
- Regla mía: los creativos deben basarse en anuncios que están GANANDO AHORA (validados,
  +30 días corriendo), NO en teoría vieja ni plantillas genéricas.

════════════════════════════════════════════════════════════════════
## 2) QUÉ ES LA APP Y CÓMO SE PRENDE
════════════════════════════════════════════════════════════════════
- App LOCAL en mi Mac (nada en la nube salvo llamadas a APIs de IA). Editor de video ads
  con IA para dropshipping.
- Stack: backend Python 3.12 (FastAPI + Uvicorn) + FFmpeg/ffprobe + OpenCV + Pillow.
  Frontend = un solo archivo: frontend/index.html (HTML/CSS/JS vanilla).
- Se prende con:  ./run.sh   → abre en  http://127.0.0.1:8420
- Entorno Python:  ./venv/bin/python  (instalar deps:  ./venv/bin/pip install -r requirements.txt)
- APIs que usa la app EN EJECUCIÓN:  Gemini (google-genai, gemini-2.5-flash)  +  ElevenLabs
  (voz, subtítulos, SFX, música, dubbing)  +  Foreplay (buscar ads ganadores).
  ⚠️ La app NO usa la API de Anthropic/Claude para funcionar; Claude solo se usa para
  CONSTRUIR la app (o sea, tú). Si un flujo falla, casi siempre es Gemini o ElevenLabs.
- Las API keys se ponen desde la web (pestaña 🔑 Claves) o en .env. NUNCA subir el .env a git.
- El modelo EAST (models/east.pb, ~92MB) se descarga solo la 1ª vez (sirve para detectar y
  tapar los textos del proveedor).
- Formato por defecto: 9:16 VERTICAL (Reels/TikTok). También hay 1:1, 4:5, 16:9.
- Los trabajos corren en segundo plano (jobs). Se consultan con /api/status/{id}. Los videos
  quedan en  work/<job_id>/  y se sirven por /api/file.

════════════════════════════════════════════════════════════════════
## 3) LAS PESTAÑAS (qué hace cada una)
════════════════════════════════════════════════════════════════════
- ✂️ **Cortar clips** → LA PRINCIPAL. Le paso varios videos de proveedor (o pego links de TikTok),
  detecta escenas, puntúa calidad, Gemini prioriza dónde se ve el producto, y arma 8
  versiones distintas + clips sueltos. Opciones: tapar textos del proveedor, banner de
  oferta, música/SFX, gancho, duración.
- 📦 **Mi producto** → igual que Cortar clips pero partiendo de MIS videos de producto.
- 🎬 **Editor** → editor manual de los clips generados (reordenar, exportar).
- 🎨 **Ads imagen** → genera imágenes/ads estáticos (advertorial) con Nano Banana. Texto en
  español nítido (barra+titular con PIL, sin errores de ortografía).
- 📸 **Variar imagen** → le paso una imagen GANADORA y me da variaciones (mismo producto y ángulo,
  distinto estilo/escenario/fondo).
- 📥 **Descargar** → baja videos de TikTok / links.
- 🔥 **Foreplay** → busca ads GANADORES reales con mi API de Foreplay (por defecto: mín. 30 días
  corriendo = validados, orden "más días corriendo"). Botón para cortar el ganador en clips
  y botón "🎙️ Doblar" que abre Doblar en pestaña nueva con el video precargado.
- 🔍 **Buscar creativos** → busca creativos EXACTOS (TikTok/Foreplay). Confirma por CONTENIDO del
  video, no por portada; jueces estrictos; CERO relleno (si no hay exactos, no rellena).
- ✨ **Crear creativo** → modo automático: de un video ganador a creativo terminado en español,
  un solo botón. Incluye "Modo Ganador" (clona el patrón validado) con 2x1 opcional.
- 🛍️ **Crear Landings** → crea landing pages en Shopify (shopify_admin).
- 🎯 **Clon con mi producto** → clona un ad ganador metiendo MI producto.
- 🔁 **Variar hook** → genera variaciones del gancho.
- 🔄 **Reemplazar producto** → detecta el producto viejo del ad y mete el mío, conservando el audio.
- 🎙️ **Doblar** → traduce la voz del video a otro idioma (ElevenLabs Dubbing). Si ya está en
  español, conserva la voz (no re-dobla).
- 📡 **Radar** → radar de ganadores.
- 🔑 **Claves** → configurar las API keys (Gemini, ElevenLabs, Foreplay, Claude, Shopify).
- 📚 **Guía** → ayuda dentro de la app.

════════════════════════════════════════════════════════════════════
## 4) MI FLUJO GANADOR (cómo lo uso de verdad)
════════════════════════════════════════════════════════════════════
1. 🔥 Foreplay → busco ganadores VALIDADOS (+30 días corriendo) de mi nicho, sin Colombia.
2. Elijo el ganador → "✂️ Cortar seleccionados en clips" (o ✨ Crear creativo / 🎯 Clon).
3. La app reconstruye el patrón validado en 8 versiones distintas:
   HOOK (producto+dolor, texto 0-3s) → DOLOR (b-roll de asco/problema) → PRODUCTO (en mano)
   → DEMO (funcionando/enchufado) → CTA (contraentrega, envío gratis).
4. Le pongo: subtítulos estilo TikTok, tapar los textos del proveedor, banner de oferta,
   voz en off en español colombiano, música por fase.
5. Descargo las versiones y las pruebo en ads.

════════════════════════════════════════════════════════════════════
## 5) MIS REGLAS DE ORO — LO QUE ME GUSTA Y LO QUE NO
════════════════════════════════════════════════════════════════════
✅ **LO QUE ME GUSTA:**
- Español colombiano de MARKETING (no traducción literal). Prioridad total al español.
- Creativos VALIDADOS y bien hechos: producto claro, poco texto, patrón ganador real.
- Ofertas: "ENVÍO GRATIS · PAGAS AL RECIBIR" y a veces "OFERTA 2X1" (opcional).
- Que las cosas FUNCIONEN de punta a punta y sin restricciones — que la app haga todo lo
  que le pido, no que me ponga peros.
- Look pro: dorado/crema/negro, animado, tipo constructor de páginas premium. Mi garaje en
  la portada (Porsche 911 GT3 RS, Ducati Panigale V4, Lamborghini).
- Blur de los textos del proveedor: SÓLIDO y QUIETO (relleno de color, caja fija) — NO
  mosaico que se desliza ni parpadea.
- Verticales 9:16 por defecto.

❌ **LO QUE NO ME GUSTA (NUNCA hagas esto):**
- NUNCA poner CIFRAS DE PRECIO en las ofertas ni en los hooks. (Regla de oro absoluta.)
- NO mostrarme ads de COLOMBIA en las búsquedas — SIEMPRE excluir Colombia (busco refs de
  afuera, español pero sin CO).
- NO rellenar búsquedas con creativos "más o menos" — si no son EXACTOS del mismo producto,
  no los muestres. Cero relleno.
- NO decirme "listo / ✅" si en realidad algo falló (Gemini/ElevenLabs caído). Si la IA no
  corrió, dímelo HONESTO, no me entregues el original re-encodeado como si fuera el resultado.
- NO sobreprometer en salud (veneno de abeja, rodillera): sin curas milagro, respeta límites.
- NO repetir la misma toma 30s: variedad de fuente entre versiones.
- NO tapar caras ni el texto del envase con el blur.

════════════════════════════════════════════════════════════════════
## 6) DESARROLLO — CÓMO TRABAJAR EN ESTE REPO
════════════════════════════════════════════════════════════════════
- Esta app la construimos DOS personas con Claude Code: yo con Juan (juanesal-lab) y con mi
  otra cuenta (jackingshop1-cell). Protocolo obligatorio (está en CLAUDE.md):
  · Al EMPEZAR:  git pull origin main  + leer  DEV-LOG.md  (qué hizo el otro).
  · Al TERMINAR:  agregar entrada al final de DEV-LOG.md (fecha, quién, qué hiciste, avisos)
    →  git add -A && git commit -m "..." && git pull origin main && git push origin main.
  · SIEMPRE git pull ANTES de git push. Si hay conflicto en DEV-LOG.md, conserva AMBAS entradas.
- Hay un auto-guardado (Stop hook en .claude/) que commitea+push al terminar cada tarea.
- Terreno: el backend de guiones/narrativa/radar es más de Juan; el video/masking/banners/
  búsquedas es más mío. No pises el trabajo del otro sin avisar en el DEV-LOG.
- Reiniciar el server tras cambios de backend para probar (./run.sh trae --reload).
- REGLA DE $0 EN PRUEBAS: no gastes créditos de API sin necesidad. Verifica con py_compile,
  node --check, dry-runs y frames. Solo corre una generación REAL si es imprescindible, y avísame.
- Detalle técnico completo: RESUMEN-TECNICO.md. Playbooks por nicho y patrón ganador: carpeta assets/.

════════════════════════════════════════════════════════════════════
## 7) CÓMO TRABAJAR CONMIGO
════════════════════════════════════════════════════════════════════
- Hazme caso: si pido algo, hazlo — no me llenes de preguntas si puedes inferirlo. Solo
  pregúntame lo que de verdad no se puede adivinar (ej. una API key que solo tengo yo).
- Sé honesto: si algo falla o no probaste algo, dilo claro. No inventes "listo".
- Déjalo funcionando de punta a punta. Prioriza que la app haga TODO lo que le pido.
