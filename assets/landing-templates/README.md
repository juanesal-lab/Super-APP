# 🛍️ Plantillas maestras — Módulo Crear Landings

Estructuras VALIDADAS de Juan (ya le vendieron) destiladas a plantilla. El pipeline Gemini
adapta estas plantillas al producto nuevo — **JAMÁS inventa una estructura distinta**.

## Los 2 tipos
| Tipo | Plantilla | Origen (ejemplo real de Juan) |
|---|---|---|
| **Landing Page** | `landing-page.md` | 9 imágenes apiladas del Aceite de Ricino (`referencia-landing/seccion-01..09.jpg`) |
| **Advertorial** | `advertorial.md` | Página viva: buenatienda.com.co/products/crema-veneno-de-abeja-2x1 (destilada 2026-07-03) |

**Diferencia clave de formato:** la Landing Page es un *stack de imágenes generadas* (el texto va
DENTRO de las imágenes, secciones apiladas verticalmente + bloques de compra entre ellas). El
Advertorial es *página de texto HTML* estilo artículo/informe editorial con reseñas.

## Convención de variables
Todo lo que va entre `{{llaves}}` lo llena el pipeline con los insumos de Juan o lo genera Gemini:
- `{{producto}}`, `{{marca}}`, `{{ingrediente_estrella}}`, `{{beneficio_1}}`, `{{beneficio_2}}`
- `{{precio_1}}`, `{{precio_2}}`, `{{precio_3}}`, `{{oferta}}` → **EXACTOS como los dé Juan, prohibido inventar/redondear**
- `{{publico}}` (edad/género objetivo), `{{dolor}}`, `{{mecanismo}}` (por qué funciona)
- `{{n_clientes}}`, `{{dias_resultado}}` → cifras de prueba social (Gemini propone, Juan aprueba en el gate)
Lo que NO está entre llaves es ESTRUCTURA FIJA: mismo orden, mismo layout, misma psicología.

## Reglas duras de generación (imágenes)
1. **Producto real siempre**: cada imagen que muestre el producto usa las FOTOS REALES de Juan
   como referencia de Gemini. Prohibido dejar etiquetas con texto inventado/garbled (en el ejemplo
   original Gemini escribió "Paro la plai y el cápeiio" — eso NO puede pasar en producción; si la
   etiqueta no sale legible, se recompone con la foto real encima).
2. **Texto dentro de la imagen en español colombiano COD**, sin errores de ortografía. Verificar
   cada render antes del gate (OCR o revisión Gemini del propio render).
3. **Aspect ratios por sección** (ver cada plantilla). Se generan al tamaño nativo de Gemini y se
   optimizan de peso ANTES de subir a Shopify Files (regla del módulo).
4. **Personas**: variedad demográfica realista del público objetivo (edades/géneros de la plantilla),
   expresiones antes=frustrada / después=feliz, misma persona en cada par antes/después.
5. Nada sube a Shopify sin pasar el GATE de aprobación de Juan (regla de oro del módulo).

## Psicología del orden (por qué NO se reordena)
Promesa → prueba social masiva → mecanismo + transformación → prueba social íntima (FB) →
caso individual con fechas → OFERTA anclada en bundles → bonos que inflan valor →
comparativa que justifica el precio → instrucciones + ingredientes (mata objeciones finales).
El advertorial sigue su propio arco editorial (ver su plantilla).
