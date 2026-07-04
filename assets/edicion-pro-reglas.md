# EDICIÓN PRO — Reglas destiladas de 4 ads ganadores reales (2026-07-03)

Dos agentes analizaron frame a frame y onda a onda 4 referencias profesionales de Juan
(ads de dropshipping 9:16, ~23s, mismo producto). Métricas: cortes por diferencia de frames +
optical flow + Gemini 2.5 Pro (video nativo) para lo visual; ebur128/RMS/onsets + Gemini para
el audio. **Estas reglas están implementadas en `pro_mix.py` + `assemble.py`** — si se ajustan
números, ajustar allá.

## VISUAL

**Ritmo** (implementado en `plan_variations` + `_slot_plan` de build_variations):
- 22-25s total, 15-20 planos, mediana ~1.4s/plano. NINGÚN plano >2.2s; mínimo útil 0.45s.
- La curva DESACELERA: ancla 1.1-2.2s → ráfaga hook 2-3 planos de 0.45-0.9s → crucero 1.0-1.7s
  → últimos 3 planos (CTA) 1.8-2.2s: el cierre se calma para que la oferta se LEA.
- Hook: 3-4 planos en los primeros 3s, de fuentes visualmente MUY distintas; el plano 1 arranca
  YA en acción con caption en pantalla desde el frame 0.
- Cortar en límites de FRASE de la voz en off, NO al beat de la música (medido: la sincronía
  corte↔beat es puro azar en los 4 ads).

**Transiciones** (implementado en `concat_clips_xfade`):
- Default = DISSOLVE de 4-6 frames (0.13-0.20s, usamos 0.17): es el 70-85% de las transiciones
  y el pegamento que unifica clips de cámara/luz distintas.
- Corte (casi) duro solo 1 de cada ~5, reservado al plano de IMPACTO (producto/before-after).
- CERO whip pans, flashes blancos, slides, wipes, circles. El único efecto es el dissolve.

**Movimiento** (implementado en `_motion_chain`):
- PROHIBIDO el plano 100% estático: Ken Burns zoom-in 1.5-3%/s en ~60% de planos, alternando
  2-3 in : 1 out (el out abre/revela, típico del hook).
- Zoom PUNCH 15-23%/s (1.0→~1.2 en <1s): solo 1-2 por video, en el plano del producto.
- Sin speed ramps ni slow motion: la energía viene del ritmo de corte + zooms.

**Captions**: capa CONTINUA que sobreviva los cortes (río sincronizado a UNA voz), karaoke
palabra a palabra, 3-5 palabras por pantalla, base a ~80% de altura, franja central 30-70% libre.

## AUDIO (implementado en `pro_mix.py`)

**Master**: −18 LUFS integrado (NO −14), true peak ≤ −1.5, LRA 7-9 (`loudnorm=I=-18:TP=-1.5:LRA=8`).
La sensación pro viene del RANGO dinámico (saltos de 20-27dB entre valle y acento), no del volumen.

**Música**: UNA cama upbeat plana ~120-125 BPM, SIN drops/risers/build-ups (ninguno de los 4 los
usa). Vive 12-15dB bajo la voz + DUCKING dinámico de 3-5dB cuando habla (sidechaincompress
ratio 4:1, attack 25ms, release 400ms). Arranca al 100% en 0.0s (hot-start, sin fade-in) y hace
fade-out de 1.5s al final. Jamás cortarla en seco.

**SFX** — el error nº1 amateur es ponerlos MUY fuertes y en TODOS los cortes:
- Presupuesto: ~1 cada 1.8s (mediana real: 13 en 23s). Solo 40-60% de las transiciones llevan
  whoosh; el resto lo sostiene la música.
- Jerarquía de volumen: 80-90% SUTILES (pico ~−8dBFS, ≈8-12dB bajo la voz: se SIENTEN, no se
  OYEN) y solo 1-3 PROTAGONISTAS por video (+9-12dB): el chime del producto, la caja
  registradora de la oferta, la acción física clave.
- Timing: el whoosh arranca ~150ms ANTES del corte (su pico aterriza EN el corte). Chime/pop de
  texto: exacto al aparecer el texto. Nunca >300ms tarde.
- Mapa semántico (mínimo 5 tipos por video): transición→whoosh · texto→pop/swoosh corto ·
  producto/claim→chime/sparkle · precio→cash-register · acción física→diegético · problema→SFX
  feo, solución→brillo. En DOLOR no se celebra nada (sin SFX).
- Nunca el mismo sample 2 veces seguidas; jitter de ±1.5dB entre usos.

**Voz**: entra a 0.2-0.3s (nunca frame 0, nunca >0.5s), dominante absoluta. 1 "respiro" por
video (~0.4s de valle bajo −35dB, pausa de voz sin SFX) al ~70-75% de la duración, antes del CTA.

## Hallazgos NO implementados (decisión pendiente de Juan)
- Los ads pro REPITEN un clip ancla 2-3 veces como columna vertebral del mashup — choca con la
  regla dura "jamás repetir clips en el mismo video", así que NO se implementó.
- Split screen remedio-vs-producto, mascota AI como pattern interrupt, y conservar los captions
  EN originales del clip fuente (look UGC nativo): recursos de contenido, no de edición — se
  podrían agregar como features aparte.

Reportes crudos de los agentes (timestamps por video, tablas completas): sesión 2026-07-03,
carpetas `agente-visual/` y `agente-audio/` del scratchpad (efímeras) — lo esencial está arriba.
