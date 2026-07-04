# Manual Maestro → qué adoptó la app (2026-07-04)

Fuente: `manual-maestro-videos-ia.md` (el manual completo de Juan, copiado a este repo).
Este doc mapea CADA regla importante del manual a dónde vive en el código, y registra los
CONFLICTOS entre el manual (mejores prácticas genéricas) y lo MEDIDO en los 4 ads ganadores
reales de Juan (`edicion-pro-reglas.md`). **Regla de la casa: lo medido en ads reales de Juan
gana sobre lo genérico, salvo que Juan diga lo contrario.**

## ✅ Adoptado YA (implementado en esta sesión)

| Regla del manual | Dónde quedó |
|---|---|
| §6 Locución 1.1-1.2× (más enérgica, retiene mejor) | `voiceover.acelerar()` a 1.12× con atempo + timings re-escalados; cableado en Mi producto y Cortar clips (guiones) |
| §6 Primera línea A MITAD de pensamiento, jamás "Hola" | prompt de `generate_scripts` (ARRANQUE EN CALIENTE) |
| §3.8 Hook stacking (micro-gancho por fase) | prompt de `generate_scripts` |
| §3 Producto después del gancho + test anti-anuncio | ya existía (guion-framework.md); reforzado con la regla 🏷️ de nombrar el producto |
| §7.4 Ducking sidechain música bajo VO | ya implementado ayer en `pro_mix.py` (medido en refs) |
| §8 Subtítulos word-by-word 3-5 palabras, bold, karaoke | ya existía (`caption_styles`, estilos + tamaño elegible) |
| §9.3 Motion floor (nada estático >1.5-2s, Ken Burns alternado) | ya implementado (`assemble._motion_chain` + `_slot_plan`) |
| §9.1 Hook shots 0.5-1s, cuerpo 1.5-3s | curva de ritmo de `_slot_plan` (ráfaga 0.9s → crucero 1.7s) |
| §3.4 Hook overlay ≤8 palabras | `hook_gen` ya usa máx 6 ✓ |
| §11.4 Compliance (sin claims médicos, sin antes/después corporal, sin urgencia falsa) | ya existía (diccionario anti-baneo en guion-framework + reglas del prompt) |

## ⚔️ CONFLICTOS manual vs. medido (decisión actual: gana lo MEDIDO — Juan puede voltearlo)

1. **Loudness**: manual dice −14 LUFS; los 4 ads reales miden −18 LUFS ±0.6 (el rango dinámico
   es lo que suena pro). → Nos quedamos en **−18** (`pro_mix.LOUDNORM`).
2. **Drop musical en el reveal**: manual lo pide; NINGUNA de las 4 referencias usa drops — cama
   plana 120-125 BPM + chime protagonista en el producto. → Nos quedamos con **cama plana +
   chime** (el chime cumple el rol del acento).
3. **Transición default**: manual dice hard cut backbone; las referencias usan **dissolve de 4-6
   frames en el 70-85%** de transiciones (+ corte casi-duro 1 de cada ~5). → Nos quedamos con
   el dissolve medido.
4. **⚠️ PRECIO EN EL GUION (decisión pendiente de Juan)**: el manual exige ANCLA DE PRECIO
   SIEMPRE ("99 mil vs carro de 40 millones") y varias fórmulas F1-F8 la traen; pero la regla
   actual del módulo (dictada por Juan) PROHÍBE toda cifra de dinero en los guiones. Hoy manda
   la regla de Juan (sin precio). Si Juan quiere anclas de precio, se agrega un toggle "ancla
   de precio" que las permita (comparativa sí, cifra sola jamás).

## 📋 Adoptable a corto plazo (aún NO implementado)

- **SFX faltantes en el banco** (§7.3): cash-register/cha-ching (para reveal de oferta 2x1 —
  medido también en la ref 72 como el SFX más fuerte del video) y notification pop. Generarlos
  con ElevenLabs SFX y meterlos a `assets/sfx/` (gasta créditos → pedir OK a Juan).
- **Safe zones por plataforma** (§10.1): hoy los captions van al ~78-80% de altura (como las
  referencias TikTok). Para Meta Reels el manual pide el 35% inferior LIBRE → exponer un toggle
  "destino: TikTok / Meta" que suba los captions en el cut de Meta.
- **Master 9:16 → dos cuts** (§10.2): export TikTok (crudo) + Meta (4:5 + 9:16, safe zone
  estricta). Hoy solo exportamos el formato elegido.
- **QA gate de video** (§11.1): checklist automático post-render (producto visible ≤s3, captions
  en safe zone, mezcla ok). Hoy hay verificación de ortografía en imágenes; falta el de video.
- **Headline card 0-3s** (§9.5): el hook overlay existe (`burn_hook`); falta el estilo "card"
  con animación pop.

## 🚀 El módulo grande que propone el manual (Partes 2, 5, 12-14): GENERACIÓN 100% IA

Pipeline nuevo: producto → ángulo → guion → shotlist (8-12 planos ≤5s, hooks visuales V1-V14) →
imagen real del SKU → keyframes (Nano Banana Pro) → image-to-video (Kling 3.0 volumen / Veo 3.1
Fast hero) → avatar UGC (HeyGen/Arcads) → voz clonada CO → música licenciada → ensamblaje FFmpeg
(este mismo motor pro) → QA gate anti-AI-look → 10-25 variantes diversas (Andromeda).
Sería el 4º módulo de la app (nivel de Buscar/Crear/Landings). Reglas clave si se construye:
- JAMÁS text-to-video puro del producto: siempre imagen real → image-to-video (fidelidad SKU).
- Bloque anti-AI-look en TODOS los prompts (messy real room, phone-camera look, no studio).
- Mismo avatar + misma voz por campaña; entorno LATAM real (bodega/casa), no showroom.
- Clips ≤5s; si QA rechaza un plano se regenera SOLO ese plano.
- PROHIBIDO Sora (API deprecada sep-2026). Acceso unificado vía fal.ai.
