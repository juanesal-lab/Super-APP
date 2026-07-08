# Hooks ganadores 2026 — US · UK · Alemania · Francia (para "cortar clips")

Investigación (agente, 2026-07-08) de los ganchos (primeros ~3s) que más venden y más DURAN
(+30 días activos = proxy de ganador) en direct-response/dropshipping de 4 mercados. Foco en las 3
capas que la app quema: **voz + visual + TEXTO en pantalla**.

## Estructura universal (repite en los 4 mercados)
`interrupción visual (0-1s) → línea de dolor/curiosidad que nombra el problema EXACTO del comprador
(1-3s) → producto como respuesta + prueba/demo`. Fórmula: **Hook → Valor → Emoción → CTA**.

Mecánicas que repiten en US/UK/DE/FR y correlacionan con longevidad:
1. **Dolor exacto** (problema-agitación) — la más confiable. "¿Cansado de X?"
2. **Curiosidad / secreto** — "Nadie habla de esto", "Lo que nadie te dice de X".
3. **Contrario / advertencia** — "No compres X hasta ver esto", "Deja de comprar X".
4. **Error** — "Lo estás haciendo mal", "No cometas este error".
5. **Antes/después · lo probé N días** — "Día 1 vs Día 30".
6. **Dato impactante** — "Tu X está más sucio que Y".
7. **Escéptico primero** — "Yo tampoco creía… hasta que".
8. **Prueba social** — "Todos me preguntan cómo".
Registro informal (tú/vos, du, tu) SIEMPRE; nada corporativo. Especificidad > vaguedad.

## 20 plantillas adaptadas a LATAM (voz + TEXTO en pantalla ≤8 palabras, MAYÚSCULAS)
1. Dolor exacto — VOZ "¿Cansado de que [problema] te pase todos los días?" · TEXTO `¿CANSADO DE [PROBLEMA]?`
2. Lo que desperdicié — "Gasté un montón antes de encontrar esto" · `GASTÉ DE MÁS ANTES DE ESTO`
3. No compres hasta ver — "No compres [categoría] hasta ver esto" · `NO COMPRES [X] SIN VER ESTO`
4. El error — "Estás usando [X] mal y nadie te lo dijo" · `LO ESTÁS HACIENDO MAL`
5. Ojalá lo hubiera sabido — · `OJALÁ LO HUBIERA SABIDO ANTES`
6. Yo tampoco creía — "…hasta que lo probé" · `NO CREÍA QUE FUNCIONARA`
7. Lo probé N días — · `LO USÉ 14 DÍAS — MIRA`
8. Día 1 vs Día 30 — · `DÍA 1 VS DÍA 30`
9. Nadie habla de esto — · `NADIE HABLA DE ESTO`
10. ¿Sabías que…? — "Tu [objeto] está más sucio que [comparación]" · `TU [OBJETO] MÁS SUCIO QUE…`
11. Para el scroll — "Para. Mira esto un segundo" · `PARA DE SCROLLEAR`
12. POV por fin lo encontraste — · `POV: POR FIN LO ENCONTRASTE`
13. Deja de comprar X — · `DEJA DE COMPRAR [X]`
14. La gente me pregunta — · `TODOS ME PREGUNTAN CÓMO`
15. 3 cosas que debes saber — · `3 COSAS QUE NADIE TE DIJO`
16. El problema en cámara — "¿Te pasa esto?" (mostrándolo) · `¿TE PASA ESTO?`
17. Respondiendo a… — · `RESPONDIENDO: ¿SÍ FUNCIONA?`
18. Truco de 30 segundos — · `EL TRUCO DE 30 SEGUNDOS`
19. Antes de gastar en… — · `ANTES DE GASTAR EN [X]`
20. Se está agotando (usar poco) — · `SE AGOTA EN HORAS`

## TEXTO en pantalla — buenas prácticas
- Presente en el **frame 0** (sube retención 3s ~50%). 5-8 palabras máx, una sola idea.
- Pregunta o afirmación audaz. Alto contraste. Zona segura: centro/centro-alto, evita top ~120px
  (handle) y bottom ~120px (barra de like/share). Dura ≥2s.
- El overlay = titular punzante; la voz = la versión conversacional. Que se refuercen, no se repitan.

## Integración en el generador (hook_gen.py / creative_variator)
- Darle el MENÚ de mecánicas (no una hoja en blanco): elige la que calza con la categoría, luego
  llena el hueco con el dolor EXACTO del producto (de la página).
- Ruteo por categoría: belleza→8/7/6 · hogar/limpieza→10/18/16 · salud/dolor→1/5 · gadgets→4/3 ·
  categoría cara→19/13.
- Prohibir clichés de IA en español: "increíble", "revolucionario", "descubre el secreto",
  "cambia tu vida", "el mejor del mundo", "imperdible", "atención", "no lo vas a creer" (solo),
  "mira esto" (solo). Registro informal LATAM. Sin precio.
- Al generar N variaciones, que cada una use una MECÁNICA distinta (una de dolor, una de curiosidad,
  una contraria, una de prueba social) para que el A/B test cubra tipos de hook.

Fuentes: Motion, Segwise, UGC Humans, adlibrary.com, advertace.de, takema-studio, Minea FR,
The Translatery, TikTok Ad Awards UK 2025, overlaytext.com. (Meta Ad Library / TikTok Creative
Center requieren login; los patrones se triangularon de swipe files y breakdowns públicos.)
