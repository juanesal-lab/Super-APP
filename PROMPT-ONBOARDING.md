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
- `run.sh` es un SUPERVISOR con AUTO-ACTUALIZACIÓN: revisa GitHub cada 30s y baja solo los
  cambios (los de frontend/docs aplican al instante; los de backend reinician el server, pero
  NUNCA a mitad de un render — consulta `/api/busy` con doble chequeo). Si el server se cae,
  lo revive. Cuando Juan sube algo, a Jack le llega SOLO.
- Entorno Python:  ./venv/bin/python  (instalar deps:  ./venv/bin/pip install -r requirements.txt)
- APIs que usa la app EN EJECUCIÓN:  Gemini (google-genai, gemini-2.5-flash — el cerebro)
  +  ElevenLabs (voz, subtítulos, SFX, música, dubbing)  +  Claude/Anthropic (guiones, copy
  de landings, conceptos de ads imagen, 2º juez de búsquedas — cuando hay key)  +  Foreplay
  (ads ganadores)  +  Pexels/Pixabay (b-roll de stock, gratis)  +  ScrapeCreators (📡 Radar).
  Si un flujo falla, casi siempre es una key sin cuota: 🔑 Claves valida Gemini EN VIVO y la
  pill dice la verdad ("sin cuota (429)" / "key inválida"), nunca un "configurada ✓" mentiroso.
- Las API keys se ponen desde la web (pestaña 🔑 Claves) o en .env. NUNCA subir el .env a git.
- El modelo EAST (models/east.pb, ~92MB) se descarga solo la 1ª vez (sirve para detectar y
  tapar los textos del proveedor).
- Formato por defecto: 9:16 VERTICAL (Reels/TikTok). También hay 1:1, 4:5, 16:9.
- Los trabajos corren en segundo plano (jobs). Se consultan con /api/status/{id}. Los videos
  quedan en  work/<job_id>/  y se sirven por /api/file.

════════════════════════════════════════════════════════════════════
## 3) LAS PESTAÑAS (qué hace cada una HOY)
════════════════════════════════════════════════════════════════════
La barra lateral va en grupos: 🔎 Buscar creativos · 🎬 Crear videos · 🎬 Montador ads ·
🛍️ Crear landing · ⚙️ Ajustes.

🔎 **BUSCAR:**
- 🔍 **Buscar creativos** → subo FOTO o VIDEO (saca los 5 mejores frames) + nombre del producto
  y encuentra creativos de ese MISMO producto. Responde RÁPIDO con Foreplay y TikTok sigue en
  2º plano (job). Resultados por NIVELES: ✅ confirmados primero; si faltan, sección ámbar
  aparte "🟡 candidatos sin confirmar — revísalos tú". CERO relleno (match=false jamás entra);
  si no hay nada, lo dice honesto (y dice cuántos descartó el juez). Botón "traer más" sin repetir.
- 🔥 **Foreplay** → ads GANADORES validados (+30 días corriendo) por defecto, Colombia excluida.
  Si el español no llena el pedido, completa con otros idiomas (badge "🌎 otro idioma — dóblalo").
  Botones por tarjeta: "✂️ Cortar en clips", "🎙️ Doblar" (abre Doblar con el video precargado)
  y "🧬 Usar estructura" (salta a Cortar clips clonando el arco/orden/ritmo de ese ganador).
- 📡 **Radar** → radar de ganadores (motor radar/ de Juan). Se configura DESDE LA APP, cero
  terminal: key de ScrapeCreators en 🔑 Claves + botón "🛰️ Escanear ahora" (gasta ~69 créditos
  → SOLO manual, nunca automático).

🎬 **CREAR VIDEOS:**
- ✂️ **Cortar clips** → LA PRINCIPAL. Videos de proveedor (o links) → detecta escenas, puntúa,
  prioriza dónde se ve el producto y PRIORIZA CLIPS SIN TEXTO quemado (menos blur feo).
  El flujo es: genero **1 DE PRUEBA** → la apruebo → "genera N más" (1-7). Si algo está mal:
  panel "❌ ¿Algo mal?" con chips → "🔧 Corregir y volver a probar" o "📝 Mandar a Claude"
  (queda en feedback-jack.md para la terminal). Con voz: **AVATARES + ESTRUCTURAS VALIDADAS**
  — cada versión ataca un avatar distinto (deportista lesionado, abuela con artrosis...) con
  una estructura probada y duración propia; badge "🎯 avatar · estructura" en guiones y videos.
  Extras: 🧬 estructura de referencia (de Foreplay o archivo), **HOOK POR VERSIÓN** (pastilla
  blanca 0-3s coherente con cada guion, EDITABLE + "🔁 Re-aplicar"), 🎁 oferta personalizada
  (mi texto tipo "3X2 · 50% OFF", o vacío = solo "ENVÍO GRATIS · PAGAS AL RECIBIR"), banner
  con "aparece al seg N · dura M" (obedece), 🏁 end-card CTA final (1.5s, "PAGAS AL RECIBIR"),
  blur suave/medio/fuerte, música por fase, mezcla TOFU/MOFU/BOFU, audio SIEMPRE a -14 LUFS.
- 📦 **Mi producto** → igual que Cortar clips pero partiendo de MIS videos de producto.
- ✨ **Crear creativo** → automático: de un ganador a creativo terminado en español, un botón.
  "Modo Ganador" (clona el patrón validado) con 2x1 OPCIONAL. Si la IA cae, error honesto.
- 🎯 **Clon con mi producto** → clona un ad ganador metiendo MI producto.
- 🔁 **Variar hook** → variaciones del gancho para escalar sin ad-fatigue.
- 🔄 **Reemplazar producto** → detecta el producto viejo del ad y mete el mío, conservando el audio.
- 🎙️ **Doblar** → AHORA EN 2 PASOS: **① Traducir** (barato, NO gasta voz: me da original +
  traducción frase por frase en cajitas EDITABLES) → **② Escoger voz**: Juan Carlos, Kate, o
  🎯 Doblaje exacto (conserva la voz ORIGINAL del video, ElevenLabs Dubbing). Opcional: que la
  voz mencione el 2x1 (mi texto o el default). El doblaje exacto no menciona 2x1 (avisa).
- 🎬 **Editor** → editor manual de los clips generados (reordenar, exportar).
- 🎨 **Ads imagen** → ads estáticos/advertorial con Nano Banana (modelo elegible: 1 barata /
  2 pro). Texto en español nítido (barra+titular con PIL, sin errores de ortografía).
- 📸 **Variar imagen** → le paso una imagen GANADORA y me da variaciones (mismo producto y
  ángulo, distinto estilo/escenario/fondo).
- 📥 **Descargar** → baja videos de TikTok / links.

🎬 **MONTADOR:**
- 🎬 **Montar ad (voz + clips)** → app APARTE de Juan (server propio en :8440) que viaja en la
  carpeta `montador/` del repo y se ve embebida en un iframe. Botón "▶️ Prender Montador" (la
  1ª vez instala sola su venv, 1-2 min; keys propias en `montador/.env`). Tiene **agente
  B-ROLL**: lee el guion y trae de Pexels/Pixabay el clip que ilustra cada frase ("inflamada
  como un hipopótamo" → hipopótamo); el PRODUCTO siempre con mis tomas, jamás b-roll genérico.

🛍️ **LANDING:**
- 🛍️ **Crear Landings** → YA FUNCIONA de punta a punta. 2 tipos con las estructuras de mis
  referencias reales: 📰 Advertorial (16 bloques editoriales, oferta tardía) y 🛍️ Landing
  (11 bloques visuales, precio arriba). Copy con Claude usando MI precio/oferta EXACTOS (las
  cifras que la IA invente se BORRAN), imágenes por sección con Nano Banana (si falla → foto
  real + aviso), y PREVIEW con **GATE de aprobación**: NADA sube a Shopify sin mi clic
  "✅ Aprobar y subir". Reviews/testimonios = placeholders para pegar los MÍOS reales (jamás
  inventados, sin doctores con nombre). Sube como assets cm-* (no toca lo existente de la tienda).

⚙️ **AJUSTES:**
- 🔑 **Claves** → Gemini (validada EN VIVO: genera 1 token de prueba; la pill dice "sin cuota
  429" si no hay créditos), ElevenLabs, Claude, Foreplay, Shopify, Pexels/Pixabay (b-roll
  stock), ScrapeCreators (Radar).
- 📚 **Guía** → ayuda paso a paso dentro de la app (con el flujo ganador completo).

Y en TODA la app: botón flotante 🤖 **Asistente** — responde con EVIDENCIA real (estado de los
jobs, bitácora de búsquedas, keys en vivo); tiene PROHIBIDO el "revisá vos". Si algo lo excede,
le deja la duda anotada a Claude terminal. El gesto "Atrás" vuelve a la pestaña ANTERIOR (no
al home) sin perder nada.

════════════════════════════════════════════════════════════════════
## 4) MI FLUJO GANADOR (cómo lo uso de verdad)
════════════════════════════════════════════════════════════════════
1. 🔥 Foreplay → busco ganadores VALIDADOS (+30 días corriendo) de mi nicho, sin Colombia.
2. En el ganador que me convence → **"🧬 Usar estructura"** (me lleva a Cortar clips con la
   estructura de ese ad clonada). También puedo: ✂️ Cortar en clips / 🎙️ Doblar / ✨ Crear creativo.
3. ✂️ Cortar clips CON VOZ: la app clona el arco validado — HOOK (texto 0-3s) → DOLOR →
   PRODUCTO (en mano) → DEMO → CTA (contraentrega, envío gratis) — y asigna a cada versión
   un AVATAR distinto con una estructura probada (badge "🎯 avatar · estructura").
4. Le pongo: subtítulos estilo TikTok, tapar los textos del proveedor, banner de oferta
   (con mi texto si tengo otra oferta), voz en off en español colombiano, música por fase,
   🏁 end-card.
5. Genero **1 DE PRUEBA** → si algo no me gusta, feedback desde la app y vuelvo a probar →
   cuando queda, "genera N más".
6. Testeo en Meta POR AVATAR (el badge me dice qué avatar es cada video) y ESCALO el que venda.
7. Al ganador le armo la página con 🛍️ Crear Landings (reviso el preview y apruebo antes de subir).

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
- Blur de los textos del proveedor: DESENFOQUE tipo vidrio esmerilado — ilegible pero se ve
  como blur REAL (se transparenta el fondo), QUIETO (caja fija). NO bloque de color sólido
  (horrible, no testeable) y NO mosaico que se desliza/parpadea.
- Mejor aún que un buen blur: PRIORIZAR clips SIN texto quemado (o con texto chico) — si hay
  tomas limpias, no elijas las cargadas de texto.
- B-roll de bancos de STOCK (Pexels/Pixabay): clips limpios y al grano. NO b-roll de TikTok
  (salen memes/comedia/ads completos = basura).
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
- En LANDINGS: usa el precio y la oferta EXACTOS que yo doy — NUNCA inventes precios,
  descuentos ni "ahorros" (la app los borra si la IA los cuela; mantenlo así).
- NUNCA inventar reviews/testimonios ni "doctores" con nombre: placeholders para que YO
  pegue mis reseñas reales. Protege mi cuenta de Meta/Shopify.
- NUNCA publicar/subir nada (Shopify) sin mi aprobación explícita — el gate de "✅ Aprobar"
  es sagrado.

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
- Reiniciar el server tras cambios de backend para probar. OJO: ./run.sh NO usa --reload a
  propósito (para no cortar renders); es un supervisor con auto-pull que reinicia solo cuando
  la app está libre (/api/busy). En desarrollo: mata el uvicorn de :8420 y relanza.
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
