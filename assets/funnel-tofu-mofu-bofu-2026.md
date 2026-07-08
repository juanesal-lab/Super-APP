# TOFU / MOFU / BOFU + diversificación creativa (2026) — para "cortar clips"

Investigación (agente, 2026-07-08). Basado en el video FORMATOS de Meta (diversificación creativa) +
fuentes DTC. La idea: al pedir creativos, generar **2 TOFU + 2 MOFU + 2 BOFU** (seleccionable), porque
un solo formato/ángulo ya no escala — Meta (Andromeda) lee el CONTENIDO y agrupa los anuncios parecidos,
así que hay que darle ángulos/temperaturas DISTINTAS.

## Las 3 etapas (temperatura del público)
| | TOFU (frío) | MOFU (tibio) | BOFU (caliente) |
|---|---|---|---|
| Objetivo | frenar el scroll, que el desconocido SE INTERESE | construir CREENCIA (por qué funciona, confianza) | CONVERTIR: quitar la última fricción y empujar la compra |
| Hook | pattern-interrupt / dolor relatable / claim audaz / curiosidad / POV "no es un anuncio" | "probé N y solo una…" / "por qué no te ha funcionado" / objeción / número específico | objeción directa / oferta / escasez / "¿lo pensaste y no lo pediste?" |
| Arco | HOOK → PROBLEMA/agitación (~60%) → GIRO + vistazo del producto → cierre SUAVE | HOOK → MECANISMO/DEMO → PRUEBA (reseñas/antes-después/comparación) → CTA medio | RECORDATORIO/objeción → OFERTA + reversión de riesgo → CTA DURO con urgencia |
| Producto | se nombra TARDE, una vez | protagonista con demo/prueba | héroe + oferta/garantía/estrellas |
| CTA | **SUAVE** (nada de contraentrega dura): "te dejo el link", "búscalo" | MEDIO: "mira las reseñas", "decídelo tú" | **DURO**: contraentrega + envío + 2x1 + "antes de que se agote" |
| Texto en pantalla (≤6) | "NADIE TE DICE ESTO" | "MIRA LA DIFERENCIA" / "4.8★ 12.000 RESEÑAS" | "2X1 SOLO HOY" / "PAGA AL RECIBIR" |
| Largo | 15-25s | 20-40s | 8-20s |

## Diversificación creativa (video FORMATOS)
Diversificar ≠ cambiar el copy/color. Es CONCEPTOS distintos: múltiples ángulos, formatos y formas de
vender lo MISMO. Cuentas que escalan usan 8-15 anuncios conceptualmente distintos; ~1 anuncio nuevo por
cada ~$3.000/mes. La etapa del embudo es el eje más fuerte de diversificación (cambia hook, arco y CTA).

## LATAM COD (Colombia/Ecuador)
"Pagas al recibir" es un ARMA de reversión de riesgo → fuerte en BOFU, insinuado en MOFU, FUERA de TOFU
(que queda suave). TikTok 15-30s de producto en uso ~3x CTR.

## Qué cambiar en el código
1. `scripts.generate_scripts(mix={"TOFU":2,"MOFU":2,"BOFU":2})`: asigna etapa por índice, inyecta un
   bloque por etapa (arco + familias de hook + dureza de CTA + largo), etiqueta cada guion con `stage`/`temp`.
2. CTA por etapa: `CTA_OBLIGATORIO` SOLO en BOFU; TOFU suave; MOFU medio. `_con_cta`/`_ajustar_largo`
   conscientes de la etapa (que TOFU no se ampute por meterle el CTA duro de 17 palabras).
3. Diversidad: prohibir repetir familia de hook en el lote.
4. `hook_gen.generate_hook(stage=...)`: overlay según etapa (TOFU curiosidad/problema, MOFU prueba, BOFU oferta).
5. UI: elegir cuántos de cada etapa (3 steppers o presets: 2/2/2 · 6/0/0 · 3/0/3 · 0/3/3). Mostrar la etiqueta de etapa en cada guion.

## Por qué mejora el CPA
Más formatos reales = más clusters de targeting = escalar sin subir el CPA; el mensaje correcto a la
temperatura correcta reduce desperdicio (BOFU/retargeting rinde 4-8x ROAS vs 2-4x de prospecting).

Fuentes: TikAdSuite, marketingtothemax (creative diversification), Jon Loomer (Andromeda), Curtis Howland,
adlibrary.com, ugchumans, MHI Growth Engine, metamktgagency, dropi.co. (Meta Ad Library/TikTok Creative
Center requieren login; patrones triangulados de breakdowns públicos.)
