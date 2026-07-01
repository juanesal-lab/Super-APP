# 📊 BLUEPRINT DE CREATIVOS GANADORES — Guía Maestra para el Gusanito

> **Qué es esto:** el destilado de qué estructuras de anuncios DE VERDAD convierten en
> ecommerce mundial (USA y mercados top), sacado de fuentes reales 2026 — incluyendo un
> estudio de **4.994 anuncios etiquetados a mano** en 364 marcas DTC.
>
> **Para qué sirve:** que el gusanito (Super-APP) arme creativos basados en lo que
> funciona HOY, no en teoría vieja. Esta es la referencia que deben leer `narrative.py`,
> `phase_effects.py`, el generador de guiones y el de hooks.
>
> **Regla de oro del proyecto:** basarse en lo que convierte AHORA. Este doc es la base
> teórica; `sonar-auto` + `tiktok-creative-scout` traen los ejemplos reales actuales.

---

## 🎯 LA VERDAD CENTRAL (lo que hay que grabarse)

**El creativo es ~56% del resultado de la campaña** — más que targeting, puja y ubicación
JUNTOS (dato de Meta). O sea: el gusanito ataca la palanca correcta. No importa cuán bueno
sea el targeting si el creativo no para el scroll.

**Los primeros 3 segundos deciden todo.** El 71% de las decisiones de retención pasan en
esa ventana. El 65% de los que se van, se van antes del segundo 3. Si el hook falla, el
resto del anuncio no importa porque nadie lo vio.

**Lo auténtico gana a lo pulido.** El formato UGC (parece contenido real, no anuncio)
convierte mejor en tráfico frío en TODAS las categorías. Ojo: NO es licencia para hacer
videos mal hechos — funciona porque evita el reflejo de "saltar anuncio", pero solo si
mantiene audio claro, subtítulos legibles y narrativa coherente.

---

## 🧱 LA ESTRUCTURA MADRE (el esqueleto de TODO anuncio ganador)

Todos los anuncios DTC que convierten comparten este marco. **Estas son las fases que
`narrative.py` debe etiquetar y que guían todo el gusanito:**

| Fase | Tiempo | Qué hace | Regla clave |
|------|--------|----------|-------------|
| **HOOK** | 0–3s | Para el scroll. Patrón roto, problema, o prueba social. | No mentir sobre lo que sigue. Impacto en <3s. |
| **PROBLEMA (agitación)** | 3–10s | Nombra el dolor con especificidad. Agita. Conecta emocional. | Específico, no genérico. El cliente se debe reconocer. |
| **SOLUCIÓN** | 10–20s | Presenta el producto como LA solución al problema establecido. | La transición problema→solución debe sentirse ganada, no abrupta. |
| **PRUEBA** | 15–25s | Reviews, cantidad de clientes, demostración, o evidencia. | Concreta, no superlativa. "Llevo 6 semanas y mi X cambió." |
| **CTA** | 22–30s | Llamado a la acción claro y específico. | Verbal + texto en pantalla. Corte duro a producto en los últimos 3s. |

**Nota crítica para tráfico frío:** los anuncios ganadores son **problem-aware** (nombran
el dolor ANTES de nombrar el producto), no product-first.

---

## 🎣 LOS 9 HOOKS QUE DOMINAN EL MERCADO (de 4.994 anuncios reales)

Más del 70% de TODOS los anuncios DTC activos en 2026 usan uno de estos 9:

1. **OFERTA COMO HOOK (19%)** — precio/descuento/bundle en los primeros 1-2s. ⚠️ Colombia/COD:
   sin número; adaptar a "oferta especial", "2x1", "solo hoy".
2. **"EN 30 SEGUNDOS…" + STACK DE BENEFICIOS (14%)** — promesa concreta y finita.
3. **PREGUNTA PROBLEMA-CONSCIENTE (13%)** — "¿Cansado de despertar adolorido?"
4. **BOLD CLAIM** — afirmación específica y contestable que activa curiosidad.
5. **DIRECT ADDRESS** — nombra la situación del espectador: "Si tienes más de 40 y…"
6. **PATRÓN ROTO VISUAL** — algo inesperado en el primer frame.
7. **PRUEBA SOCIAL / FOMO** — "Más de 10.000 ya lo usan…"
8. **CURIOSITY GAP** — tensión sin revelar todo.
9. **TRANSFORMACIÓN / ANTES-DESPUÉS (UGC testimonial)** — persona real, auténtica. Falla si
   está demasiado pulido/guionado.

---

## 🎬 TÉCNICAS DE HOOK VISUAL

1. **Post-It Reveal** (pregunta en post-it tapando el producto → se quita → revela).
2. **Reflejo en gafas** (mensaje reflejado, zoom al reflejo).
3. **Blur → Focus** (texto borroso que se enfoca).
4. **Texto que aparece en el teléfono** rodeando el producto.

---

## 📐 ESPECIFICACIONES TÉCNICAS (para descargador + render)

| Parámetro | Valor ganador 2026 |
|-----------|-------------------|
| **Formato** | 9:16 vertical, 1080×1920 |
| **Duración óptima** | **9–15 segundos** (direct-response ecommerce) |
| Duración extendida | 21–34s SOLO si el hook aguanta (testimonios) |
| **Safe zone** | 120px de margen en cada borde (UI de TikTok) |
| **Texto en pantalla** | 90% opacidad, tercio superior (evita UI) |
| **Timing del hook** | TikTok <1.5s · Reels <2s · Meta feed hasta 4s |
| **CTA** | Verbal + texto, seg 22-25. Corte duro a producto los últimos 3s, sin fade |
| **Cierre de loop** | Direct-response: cerrar el arco al seg 15. Front-load el valor |

**Métrica que manda:** el algoritmo premia **% de completación**, NO watch time total.

---

## 🔊 AUDIO — EL 50% DEL RESULTADO (para phase_effects.py)

1. **Nunca sin audio.**
2. **La música NO es fondo, es narrativa** — cambia de energía según la fase (hook alto,
   problema bajo/tenso, solución sube, clímax en resultado). ← esto es `phase_effects.py`.
3. **Ducking obligatorio** — la música baja sola cuando habla la voz (sidechain).
4. **Sonidos con tendencia** (Commercial Music Library de TikTok para anuncios).
5. **Efectos en los cambios de fase** (whoosh/zoom en hook→problema, problema→solución).

**SUBTÍTULOS = CRÍTICO:** sin subtítulos pierdes hasta el 85% de los espectadores. El texto
debe REFORZAR el hook hablado, no repetirlo verbatim.

---

## 🌳 EL ÁRBOL DE VARIANTES (lo más importante para escalar)

> El objetivo del gusanito NO es un buen video. Es un **árbol de variantes.**

- Hook A + Plataforma + CTA = Variante 1. Un brief con 3 hooks × 4 plataformas × 2 CTAs = 24.
- Meta Advantage+ necesita **mínimo 8 variantes**; los equipos top mantienen **10–25**.
- **Menos de 5** = fatiga creativa y CPM subiendo.
- Los ganadores mueren en **2-4 semanas** → refrescar semanalmente (20-30% menor costo/compra).

**Conclusión:** el gusanito debe producir **mínimo 8 variantes** distintas por producto
(distinto hook, música, orden de clips). Subir las "6 versiones" de Super-APP a 8+.

---

## 🧪 SISTEMA DE TESTING (regla anti-error)

- **UNA sola variable por test** (hook O imagen O oferta O CTA — uno a la vez).
- **Documenta elementos ganadores**, no solo anuncios ganadores.
- **Repurpose:** un ganador de Meta suele servir en TikTok con solo cambiar el crop.

**Scorecard:**
| Métrica | Alarma | Significa |
|---------|--------|-----------|
| Hook rate (3s views/impresiones) | <25% | El primer frame no para el scroll |
| Hold rate (50% views/3s views) | <35% | La historia pierde gente tras el hook |
| CTR | <1% (Meta feed) | Reemplazar creativo |
| Frecuencia | >2.5 (7 días) | Fatiga creativa; refrescar |

---

## ✅ CHECKLIST — QUÉ INCORPORAR AL GUSANITO

### Ya lo tienen (validado por la data) ✅
- [x] Verticalizar 9:16.
- [x] `narrative.py` etiqueta HOOK→PROBLEMA→SOLUCIÓN→(PRUEBA)→DESEO→CTA = la estructura madre.
- [x] `phase_effects.py` música/efectos por fase (el audio es 50% del resultado).
- [x] Subtítulos karaoke (sin ellos se pierde 85%).
- [x] Ducking (música bajo voz).
- [x] Basarse en ganadores reales (sonar-auto / tiktok-creative-scout).
- [x] Traducir texto en pantalla (`text_translate.py`).

### Para AGREGAR / MEJORAR 🔨
- [ ] **Mínimo 8 variantes** por producto (no 6), con distinto hook/música/orden.
- [ ] **Duración objetivo 9-15s** en el corte principal.
- [ ] **Los 9 hooks** como plantillas seleccionables en el módulo de hooks.
- [ ] **Problem-aware first:** el guion nombra el dolor ANTES del producto (tráfico frío).
- [ ] **Safe zone 120px:** subtítulos/CTA fuera de la UI de TikTok.
- [ ] **CTA con corte duro a producto** en los últimos 3s, sin fade.
- [ ] **Marcar elementos ganadores** (qué hook/música funcionó) para aprender.

---

## 📚 FUENTES (2026)
BrandMov (4.994 anuncios DTC, 364 marcas) · MHI Growth Engine · AdGPT · AdLibrary.com ·
Creatify / Stackmatix / MBADV · EcomStacked · Influencers-time.

*Referencia estratégica para Super-APP. Actualizar cuando cambien las tendencias (los
creativos ganadores mutan cada 2-4 semanas). La teoría es estable; los ejemplos reales los
traen sonar-auto y tiktok-creative-scout en tiempo real.*
