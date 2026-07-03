# PLANTILLA MAESTRA — LANDING PAGE (stack de 9 imágenes)

Destilada de la landing validada del **Aceite de Ricino** (9 secciones, `referencia-landing/`).
Formato: imágenes apiladas verticalmente en la página Shopify (`page.cm-*.json`), con bloques de
compra (botón/formulario COD) insertados por el theme entre secciones clave.
Las imágenes de referencia son el *style guide* visual: paleta derivada del producto, elementos
del ingrediente flotando, splashes, esquinas orgánicas. Gemini recibe la imagen de referencia de
la sección + las fotos reales del producto nuevo.

---

## SECCIÓN 1 — HERO (2:3 vertical, ref 1696×2528)
**Objetivo:** parar el scroll y prometer el beneficio en 2 segundos.
- Arriba: logo/nombre `{{producto}}` pequeño.
- Headline GIGANTE (3 líneas, mayúsculas, borde blanco): beneficio dual → `{{beneficio_1}} Y {{beneficio_2}}`
  (ej. "CABELLO FUERTE Y PIEL RADIANTE").
- Subheadline corto: `{{promesa_secundaria}}` (ej. "NUTRICIÓN PROFUNDA Y NATURAL").
- Visual: modelo del `{{publico}}` sonriente (mitad izquierda) + envase del producto GRANDE
  (foto real como referencia) + elementos del `{{ingrediente_estrella}}` flotando + splash líquido.
- ★★★★★ + "Más de `{{n_clientes}}` clientes transformadas" (prueba social masiva).
- **Comentario Facebook embebido** (tarjeta blanca): avatar + `{{nombre_mujer}}` + ★★★★★ +
  testimonio 2-3 líneas en primera persona con emojis + `@{{marca}}` + metadata FB
  ("5 sem · Me gusta · Responder · 410 ❤️😮👍").

## SECCIÓN 2 — GRID 4 TESTIMONIOS (16:9 horizontal, ref 2752×1536)
**Objetivo:** cubrir TODOS los segmentos demográficos de una.
- Título: "TRANSFORMACIÓN REAL PARA TU `{{area_beneficio}}`".
- 4 tarjetas blancas (2×2): foto retrato + `{{nombre}}, {{edad}}` + ★★★★★ + testimonio 2 líneas.
  **Regla demográfica fija:** mujer ~40s, hombre ~30s, joven ~25, madura ~55+ — cada testimonio
  ataca un beneficio DISTINTO (`{{beneficio_1..4}}`).
- Centro abajo: envase + tagline "TU ALIADO 100% NATURAL PARA `{{promesa_global}}`" + `{{producto}}`.

## SECCIÓN 3 — MECANISMO + ANTES/DESPUÉS (9:16 vertical, ref 1536×2752)
**Objetivo:** explicar POR QUÉ funciona y probarlo visualmente.
- Headline bicolor (2 colores alternados): "REVITALIZA TU `{{area}}` CON EL PODER NATURAL DE
  `{{ingrediente_estrella}}`".
- Párrafo mecanismo (4 líneas): `{{mecanismo}}` — qué hace desde la raíz/causa, cierre emocional
  ("¡Tu belleza natural renovada!").
- Par antes/después con badges "DÍA 1" / "DÍA `{{dias_resultado}}`": MISMA persona,
  triste/frustrada → radiante. Envase del producto al centro entre ambas fotos.
- Base: elementos naturales del ingrediente.

## SECCIÓN 4 — COMENTARIOS FACEBOOK (9:16, ref 1536×2752)
**Objetivo:** prueba social "espiada" — se siente contenido real, no anuncio.
- Logo ⓕ arriba + título editorial: "Amado por sus resultados en `{{area_beneficio}}`."
- 3 comentarios estilo FB: avatar mujer + `{{nombre}}` + testimonio con emojis y un
  `#hashtag` + tiempos DECRECIENTES ("9 sem", "3 sem", "2 días" → sensación de compras constantes)
  + reacciones decrecientes (532, 198, 48) + "`{{marca}}` respondió · N respuestas".
- Cada comentario ataca un dolor distinto: `{{dolor_1}}`, `{{dolor_2}}`, "usaba muchas cosas y nada".
- **Aviso legal abajo (FIJO, protege la cuenta de ads):** "*Los resultados individuales pueden
  variar. Estas reseñas reflejan la experiencia real de clientes verificados, pero no garantizan
  resultados específicos...*"
- Envase en la esquina inferior.

## SECCIÓN 5 — CASO INDIVIDUAL ANTES/DESPUÉS (1:1, ref 2048×2048)
**Objetivo:** el testimonio-historia con el que el público se identifica.
- Par de fotos grandes DÍA 1 / DÍA `{{dias_resultado_2}}` (badge del "después" en color acento).
- `{{nombre_completo}}, {{ciudad}}` + ★★★★★ + badge "EDAD: `{{edad}}`" (edad = centro del target).
- Testimonio 4-5 líneas primera persona: dolor → uso → resultado → "¡Es mi rutina esencial!".
- Envase lateral, fondo con el producto/ingrediente difuminado.

## SECCIÓN 6 — OFERTA / BUNDLES (2:3, ref 1696×2528) 💰
**Objetivo:** la decisión de compra con ancla de precio.
- Título script/cursiva: "Elige tu plan de `{{categoria}}`".
- Subcopy 2 líneas: beneficio + "Ahorra más cuando llevas más."
- 3 tarjetas lado a lado (layout FIJO):
  1. "1 `{{unidad}}`" → `{{precio_1}}`
  2. "2 `{{unidad}}s`" + badge naranja "`{{desc_2}}` OFF" + "Más vendido" → `{{precio_2}}`
  3. "3 `{{unidad}}s`" + badge verde "`{{desc_3}}` OFF" + banner "Mejor opción" + borde verde → `{{precio_3}}`
- **PRECIOS EXACTOS DE JUAN. Si Juan da otra estructura de oferta (2x1, etc.) se adapta el layout
  a SU oferta, nunca al revés.**

## SECCIÓN 7 — BONOS GRATIS + PUENTE (2:3, ref 1696×2528)
**Objetivo:** inflar el valor percibido justo después del precio.
- Badge cinta: "PLAN DE `{{tema}}`".
- Mockups de 2 bonos digitales (`{{bono_1}}`, `{{bono_2}}` — guías/ebooks relacionados).
- Caja verde "¡Gratis!": "Con tu compra recibe completamente GRATIS... todo valorado en más de
  `{{valor_bonos}}`" (valor alto anclado en COP).
- Headline derecho: "REVITALIZA TU `{{area}}` AL INSTANTE" + párrafo del diseño/fórmula.
- Banda verde con quote: "Ideal para quienes buscan `{{solucion}}` desde el primer uso."
- Cierre-puente: título "TRANSFORMACIONES REALES QUE SE SIENTEN Y SE VEN" + 2 envases con splash.

## SECCIÓN 8 — COMPARATIVA VS (9:16, ref 1536×2752)
**Objetivo:** justificar el precio matando a las alternativas.
- Headline pregunta: "¿TU MEJOR SOLUCIÓN PARA `{{resultado_deseado}}`?".
- Envase (foto real) vs ícono "ALTERNATIVAS GENÉRICAS".
- Tabla 2 columnas, 8 filas c/u: ✅ verdes del producto (precio por unidad, natural, desde la raíz,
  uso simple...) vs ❌ de las alternativas (`{{rango_precio_alternativas}}` por tratamiento, químicos,
  rutinas complejas, trata síntomas no la causa...). El PRIMER ✅ es el precio.
- Base: 3 sellos circulares FIJOS: "CALIDAD PREMIUM" / "RESULTADOS EFECTIVOS ★1★" /
  "GARANTÍA DE SATISFACCIÓN ✓".

## SECCIÓN 9 — CÓMO UTILIZAR + INGREDIENTES (9:16, ref 1536×2752)
**Objetivo:** matar la objeción "¿y esto cómo se usa?" y cerrar con transparencia.
- Título serif grande: "CÓMO UTILIZAR".
- 3 pasos **ILUSTRADOS** (estilo ilustración/cartoon, NO foto — contraste visual con el resto):
  - PASO 01 `{{modo_uso_diario}}` (aplícalo diariamente...)
  - PASO 02 `{{momento_ideal}}` (por la noche, absorción...)
  - PASO 03 "POTENCIA TUS RESULTADOS" con 3 bullets de hábitos complementarios.
- Cierre: "INGREDIENTES" + 1 línea: `{{ingredientes}}` 100% natural + micro-promesa.

---

## Notas de producción
- Paleta: TODA la landing hereda los colores del producto/ingrediente (aceite → dorados/oliva).
  Derivar paleta de las fotos reales del producto nuevo antes de generar.
- Entre secciones el theme inserta los bloques de compra/CTA (fase Shopify) — las imágenes NO
  llevan botón dibujado.
- Reseñas adicionales estilo AliExpress: van en el bloque HTML de la página (no en imágenes) —
  pendiente detalle en secciones 3-7 del superprompt de Juan.
