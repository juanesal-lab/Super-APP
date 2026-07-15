# QA de creativos automático — que la app haga cumplir las reglas del dueño sola

**Qué se pidió:** que la app OBLIGUE a cumplir las reglas de creativos (CLAUDE.md §7 de Vidaria)
en vez de depender de que alguien se acuerde. Área tocada: `backend/pipeline/*` + un archivo nuevo.
No se tocó `backend/app.py` ni `frontend/`. No se reinició la app. No se mandó Telegram.

---

## 1. Violaciones encontradas y CORREGIDAS en el código

### a) Blur cuadriculado (`boxblur`) en vez de gaussiano (`gblur`) — regla 2
El dueño exige tapado suave con **gblur**, nunca boxblur (se ve pixelado/cuadriculado). Estaba mal en
3 lugares de `backend/pipeline/assemble.py` (los que tapan los subtítulos viejos del proveedor):
- `blur_caption()` (banda arriba/abajo): `boxblur=24:4` → `gblur=sigma=22:steps=2`
- `blur_boxes()` (cajas puntuales): `boxblur=26:5` → `gblur=sigma=24:steps=2`
- `blur_boxes_timed()` (cajas que siguen el caption): `boxblur=28:6` → `gblur=sigma=26:steps=2`

(`auto_studio._verticalize` y `text_translate` ya usaban gblur — quedaron como estaban.)

### b) Subtítulos que se metían en la zona muerta inferior — regla 7
En `backend/pipeline/caption_styles.py` el bloque de subtítulos de TikTok se centraba en **0.80 de
altura** y solo se limitaba a `H − SAFE`, o sea podía caer por debajo de **y=1500** (los últimos ~420px
que tapa la UI). Corregido:
- Centro TikTok bajado 0.80 → **0.70** (centro de la franja segura 55-78%).
- Nuevo tope DURO `_y_max(H) = 0.78125·H` (= **1500/1920**): la base del bloque **nunca** baja de ahí.
- Piso de fuente subido a **≥48px escalados** (`_min_sub`) en `render_caption` y `_render_wordgroup`
  (antes bajaba a ~30px, ilegible en celular).

### c) Margen lateral / zona muerta derecha — regla 7
`SAFE` era 120px. La columna de botones de TikTok/Reels tapa los ~130px de la **derecha**. Subido a
**132px** para que ninguna letra caiga bajo esos botones (cubre lateral ≥64px y la zona derecha).

### d) Banners de oferta sin garantía de zona segura — regla 3 y 7
En `backend/pipeline/offer_banner.py` los banners usaban tamaños/posiciones fijas sin pisos:
- `render_banner` (banner superior clásico): ahora arranca a **≥90px** del borde, respeta margen
  lateral **≥64px**, padding interno **≥24px**, fuente **≥44px**, y **achica la letra si la pill no
  cabe** en el ancho útil (nunca se corta por el borde).
- `render_hook_top` (banner HOOK del modo ganador): margen ≥64px, padding ≥24px, fuente ≥44px,
  arranca a ≥90px.
- `render_offer_bottom` (banner inferior naranja): default bajado 0.815 → 0.72 y **clamp a y≤1500**
  (antes su tope era 0.97·H = dentro de la zona muerta que tapa la UI).
- `safe_top_y` (IA que elige la altura): piso duro 0.048 (~92px), ya no puede devolver 0.02.

### e) Pastilla de hook y end-card sin pisos legibles — regla 7
- `backend/pipeline/text_overlay.py` `_render_pill_png`: piso de fuente ≥44px, padding ≥24px, ancho
  máx respeta margen ≥64px. (El `_render_png` principal ya usaba las constantes de zona segura.)
- `backend/pipeline/end_card.py`: pisos de fuente ≥48px (título) / ≥44px (línea 2 y CTA), margen ≥64px.

> Las constantes de zona segura ya vivían en `text_overlay.py` (SAFE_SIDE_PX=64, SAFE_TOP_PX=90,
> SAFE_BOTTOM_DEAD=0.78125, etc.). Se reusaron como **única fuente de verdad** en offer_banner y en
> el QA nuevo, para no tener números duplicados que se desincronicen.

---

## 2. QA automático nuevo — `backend/pipeline/qa_creativos.py`

Es el "portero" al final de los pipelines. Dado un video final devuelve
`{"aprobado": bool, "motivos": [...], "checks": {...}, "resolucion": "WxH"}`. Tres controles:

- **(a) Formato 9:16 exacto** (`check_formato`) — determinista, $0. Rechaza 1:1, 4:5, horizontal o
  cualquier aspecto que no sea 9:16 (tolerancia 0.02). Nombra el aspecto que encontró.
- **(b) Zonas seguras por coordenadas** (`check_zonas_texto`) — si el pipeline pasa las cajas de
  texto que colocó (`{tipo,x,y,w,h,font_px}`), valida márgenes ≥64px, banner ≥90px arriba, subtítulos
  en 55-78% sin pasar y=1500, zona muerta derecha ~130px, y tamaños mínimos (sub ≥48px, banner ≥44px).
- **(c) Revisión visual con Gemini** (`check_visual`) — SOLO si hay key de Gemini. Saca **máx 3 frames**
  (arranque, medio, final, escalados a 540px = barato), y con un prompt-checklist de las reglas del
  dueño (simulando la UI de TikTok/Reels encima) pide un JSON `{aprobado, motivos}`. Detecta lo que el
  código no puede ver: texto cortado por el borde o por la caja de blur, texto ilegible, texto tapado
  por la UI, blur cuadriculado. Si no hay key o la IA no responde → se omite (no bloquea, no rompe).

Veredicto final = APROBADO solo si todos los checks que corrieron aprueban.

### Enganchado al final de los pipelines de video
- `auto_studio.generar_creativo_auto` → corre `qa_video` (con visión) antes de terminar. Si rechaza,
  el resultado sale con `ok=False`, `estado="rechazado por QA"` y `error` con los motivos — **no se
  reporta "listo OK"**.
- `winner_clone.clonar_ganador` → igual (con visión).
- `hook_variator.variar_hook` → QA por cada variación; una variación con QA rechazado no cuenta como OK.
- `orchestrator.render_versions` (pipeline central, muchas versiones) → QA **solo de formato** por
  versión (determinista, sin costo de IA); si una no es 9:16 se marca `qa_aviso`/`qa_creativos` en el
  manifest. La revisión visual se deja para los flujos de 1 salida, para no disparar costos de Gemini.

---

## 3. Verificación (real)

- `py_compile` OK en los 10 archivos tocados: assemble, offer_banner, caption_styles, text_overlay,
  end_card, qa_creativos, auto_studio, winner_clone, hook_variator, orchestrator.
- **Video real** `work/76ab898b1346/clip_52_1370_punch_hook.mp4` (1080×1920) → **APROBADO** (exit 0).
- **Prueba de formato con ffmpeg** (color sólido):
  - 1080×1920 → **APROBADO** (exit 0)
  - 1080×1080 (1:1) → **RECHAZADO**: "El video NO es vertical… SOLO 9:16" (exit 2)
  - 1080×1350 (4:5) → **RECHAZADO**: "El aspecto es 4:5, no 9:16" (exit 2)
- **Zonas por coordenadas**: un layout bueno pasa; uno malo devuelve 8 motivos correctos (banner
  pegado arriba, fuera del margen izq/der, fuente chica, subtítulo bajo y=1500, texto en la zona de
  botones derecha).
- **Visión Gemini** sobre el video real: extrajo exactamente **3 frames** (tope respetado), Gemini
  devolvió veredicto (aprobado). Camino completo funciona de punta a punta.
- **Render de zonas**: banner superior re-clampado arranca en **y=90** exacto; banner inferior termina
  en **y=1500** exacto; `_y_max` del subtítulo = 1500. Ninguna key impresa en ningún log.

---

## Notas / pendientes
- El QA visual cuesta llamadas a Gemini (máx 3 frames/video). Está activado en los 3 flujos de salida
  única; en el orquestador de N versiones queda solo el check gratis de formato a propósito.
- `auto_studio._sub_png` quedó sin tocar: es código muerto (los subtítulos reales pasan por
  `render_caption`, que ya cumple zonas). Si algún día se usa, habría que darle los mismos pisos.
- Si en el futuro el pipeline expone las coordenadas exactas de cada texto que quema, se le pueden
  pasar a `qa_video(textos=[...])` para que el check (b) actúe en producción (hoy valida cuando se le
  pasan; las funciones de render ya garantizan las zonas por construcción).
