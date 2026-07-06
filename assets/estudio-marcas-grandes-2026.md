# 📊 Estudio: cómo hacen creativos las marcas grandes (USA/Europa) — 2025-2026

> Investigación pedida por Jack: mirar a escala cómo pautan las marcas grandes en USA/Europa y
> traducirlo a mejoras para CreativeMaxing. Complementa (no reemplaza) `blueprint-creativos-ganadores.md`
> y `ads-estaticos-validados.md`. Aquí va lo NUEVO: números duros 2025-2026 + brechas reales de la app.

## Metodología (honesta)
Fuentes públicas agregadas 2025-2026: estudios de Motion, Segwise, Trendtrack, ATTN Agency, Billo,
Sink-or-Swim, benchmarks de Benly/Sepia, y el estudio de **67.852 ads estáticos de 106 marcas DTC**
(Curtis Howland). No son 1000 ads que yo miré uno a uno — son estudios que agregan **decenas de miles**
de ads reales con métricas. Los números de abajo están citados de ahí.

---

## 1) HOOK — lo que más mueve la aguja (el 80% del resultado está en los primeros 3s)
- **Hook rate objetivo 2026:** 28% en Meta, 33% en TikTok. Top 10%: **45% Meta, 55% TikTok**. Abajo de
  20% = el hook está malo.
- **El payoff DEBE caer en ≤3s.** Si la promesa tarda más, el rendimiento se desploma.
- **UGC gana:** +31% hook rate y +33% CTR vs. ads pulidos. TikTok premia lo que se ve NATIVO (crudo,
  rápido, hook en 2-3s).
- **Ganadores medidos:** "POV. You found the white swim for your bachelorette" → 74% hook rate, 3.8% CTR.
- **Tipos de hook que rotan los grandes:** problema/dolor crudo · negativo ("Stop using X, you're
  wrecking your Y") · POV · handwriting (sticky manuscrito) · pattern interrupt (movimiento brusco) ·
  social proof numérico · humor. **Regla clave: ROTAR triggers, nunca un solo estilo.**

## 2) ESTRUCTURA ganadora (video corto)
- **0-3s HOOK** (visual arrestante o frase de curiosidad) → **3-10s CONTEXTO** (dolor/situación
  relatable) → **10-18s REVELACIÓN** (producto/demostración/transformación) → CTA.
- **Duración total ganadora: ≤18s** en el corte principal. Cortes rápidos.

## 3) FORMATOS de imagen estática (los 5 que pautan los grandes)
Del estudio de 67.852 ads: **Us vs. Them · Problema-Solución · Product Demo · Testimonios · Reasons Why.**
- **Testimonios** = el que más convierte (la gente confía en clientes, no en marcas). Formato flexible:
  quote overlay, captura de mensaje de cliente, entrevista. **Números/tiempos específicos ganan** a
  superlativos genéricos ("en 2 semanas" > "increíble").
- **Antes/Después:** funciona cuando es aspiracional y con empatía, NO clínico ni de vergüenza.
- **Benefit-stack** (una imagen con 3-4 beneficios apilados): pre-responde objeciones antes del clic.
- **Advertorial / "reply to comment"** estilo nativo: resuelve objeciones sintiéndose auténtico.
- Dato 2026: las marcas ganadoras corren video Y estático 90%+ del tiempo. Meta (update Andromeda, oct
  2025) ahora matchea por CONTENIDO del creativo → el formato importa más que nunca.

## 4) VOLUMEN (la palanca escondida)
- Una creatividad top dura **7-10 días** antes de fatigarse; la conversión cae 30-40% cuando la
  frecuencia pasa de 2.5x.
- **Con el MISMO presupuesto, quien lanza más creativos gana ~2x más ganadores.** Cuentas top: **31 ads/
  semana → 5.99 ganadores/mes** vs. 1.75 de las cuentas promedio. Marcas >$10k/mes: 3-5 conceptos nuevos
  por semana.

## 5) USA vs EUROPA
- Estructura casi igual; cambia el idioma y el compliance (Europa más estricta con claims de salud).
- Para Jack (LATAM/España, contraentrega): el patrón USA/EU aplica; la ventaja es que muchos ganadores
  gringos/europeos AÚN no están en español → clonar su estructura es oro (justo lo que hace la app).

---

## 🎯 PLAYBOOK — mapeo a la app (qué ya está ✅ y qué falta)

| Área | Hallazgo | Estado en la app | Acción |
|---|---|---|---|
| Hook ≤3s con payoff | 80% del resultado; payoff en 3s | ✅ narrative.py etiqueta HOOK; blueprint lo guía | 🟡 reforzar en `scripts.py`: el hook DEBE cerrar su promesa en la 1ª frase (≤3s) |
| Rotar tipos de hook | negativo/POV/handwriting/pattern-interrupt/social-proof | 🟡 `creative_variator.py` varía ángulos | 🟡 darle a `creative_variator` los 7 tipos como catálogo explícito |
| Duración ≤18s | corte principal | ✅ target 15s, pacing punchy | ✅ ok |
| UGC nativo | +31% hook, +33% CTR | ✅ Cortar clips usa clips UGC reales | ✅ ok |
| Subtítulos | palabra x palabra, keyword resaltada | ✅ 10 estilos (hormozi, karaoke…) | ✅ ok |
| Us vs Them / Testimonios / Antes-Después / Benefit-stack / Reasons Why | los 5 estáticos ganadores | ✅ `disruptive_images.py` tiene los 8 motores (incluye estos) | 🔵 agregar plantilla FIJA "benefit-stack" (pre-responde objeciones) |
| Testimonio con números específicos | "en 2 semanas" > "increíble" | 🟡 prompts genéricos | 🟡 pedir número/tiempo concreto en el prompt de testimonios |
| Volumen (2x ganadores) | 31 ads/sem → 5.99 winners | ✅ 8 versiones/corrida + Variar hook (4-8 variantes) | ✅ ok — ya es la filosofía correcta |
| Video + estático 90% | correr ambos | ✅ Cortar clips + Ads imagen | ✅ ok |

## 🏆 Top quick-wins (impacto/esfuerzo) — para implementar cuando el repo esté libre
1. **[chico] Hook que cierra en 3s**: en `scripts.py`, regla dura "la 1ª frase del guion ES el hook y
   debe entregar su promesa completa" (hoy a veces el gancho se estira 2 frases).
2. **[chico] Catálogo de 7 tipos de hook en `creative_variator.py`**: que cada variación use un tipo
   DISTINTO (negativo, POV, handwriting, pattern-interrupt, social-proof numérico, humor, contrarian).
3. **[chico] Testimonios con dato concreto**: en `disruptive_images.py`, la plantilla de prueba social
   debe exigir número + tiempo ("−7kg en 30 días", no "resultados increíbles").
4. **[mediano] Plantilla fija "benefit-stack"** en Ads imagen: 1 imagen, 3-4 beneficios apilados que
   pre-responden objeciones (el estudio de 67k ads la marca como top).
5. **[chico] Meta objetivo de hook visible en la UI**: mostrarle a Jack el recordatorio "apunta a >30%
   de retención a los 3s" al elegir el hook (educativo, cero backend).

⚠️ Todos estos tocan `scripts.py` / `creative_variator.py` / `disruptive_images.py`, que la otra sesión
(Juan) está editando activamente. Aplicar coordinando para no pisar su trabajo en curso.

_Generado por la sesión Fable 5/Opus 4.8 de jackingshop1-cell, 2026-07-06. Fuentes: Motion, Segwise,
Trendtrack, ATTN Agency, Billo, Benly, Sepia, estudio de 67.852 ads DTC (C. Howland)._
