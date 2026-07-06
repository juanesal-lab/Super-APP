# 🏆 Patrón ganador VALIDADO — el ADN que Jack quiere replicar

> Extraído de 3 creativos que Jack marcó como "así los quiero" (repelente ultrasónico de plagas) +
> confirmado contra ganadores de Foreplay que llevan **499-590 días prendidos** (Bakanoforth-a,
> Superzebra) en Facebook/Instagram. Estos NO son teoría: son ads que llevan >1 año convirtiendo.
> Objetivo: que la salida de "Cortar clips / Mi producto / Crear creativo" se vea Y convierta así.

## La estructura exacta (los 3 ejemplos la comparten)
| Fase | Tiempo | Qué se ve | Qué dice |
|---|---|---|---|
| **HOOK** | 0-3s | Producto + LA PLAGA justo al lado (rata/cucaracha) + texto GIGANTE de beneficio | "¡Elimina plagas de tu casa!" (pill roja) |
| **DOLOR** | 3-8s | B-roll de asco: ratas en la cama/cocina, cucarachas, mugre | "Si tienes ratones en casa…" |
| **PRODUCTO** | 8-13s | La caja EN LA MANO (empaque real, se ve la marca) | "Tu hogar sea incómodo para ellos" |
| **DEMO/PRUEBA** | 13-19s | Dedo presionando el botón · enchufado a la pared brillando · plagas huyendo | "Enchúfalo, emite ultrasonidos…" |
| **CTA** | 19-23s | Producto funcionando + oferta | contraentrega (sin precio) |

## Los 6 elementos que hacen que NO se vean feos y SÍ conviertan
1. **Subtítulos palabra x palabra, keyword resaltada** (pill roja/amarilla/verde, tipo Hormozi). En la
   app: `caption_styles.py` estilo `hormozi`/`yellow_highlight` → YA lo hace. Es el look #1 del patrón.
2. **Hook con producto + plaga JUNTOS en pantalla desde el segundo 0** (no intro lenta). El texto de
   beneficio entra en la 1ª frase.
3. **B-roll de DOLOR real** (ratas/cucarachas/mugre) — es el gancho emocional. En la app: el 🎭 B-roll
   por punto de dolor (`buscar_broll` con Claude) trae justo estas tomas.
4. **Demo tangible**: caja en mano + dedo en el botón + enchufado brillando. Prueba que es real.
5. **9:16 o 1:1 vertical**, UGC crudo (no estudio), ~20-23s, cortes cada 2-3s.
6. **Cero precio en pantalla**, CTA contraentrega (regla de oro de la casa — ya aplicada).

## Cómo SE INTEGRA a la operación (pipeline ya montado)
1. **Fuente = ganadores validados**: pestaña 🔥 Foreplay → orden "Más días corriendo" + **Mín. días 30**
   (ahora es el default) → trae ads con +1 mes prendidos (Bakanoforth-a 499d, etc.).
2. **Selección → clips**: botón "✂️ Cortar seleccionados en clips" (`/api/foreplay-clips`) → la app baja
   el ganador y lo corta en el pool de clips.
3. **Reconstrucción en el patrón**: Cortar clips / Mi producto arma las 8 versiones con hook + dolor +
   producto + demo + subtítulos Hormozi + música/SFX por fase = el look de los 3 ejemplos.
4. **Variación**: 🔁 Variar hook saca 4-8 versiones del gancho sin perder el cuerpo validado.

## Checklist para que CADA salida quede como los ejemplos
- [ ] Hook con producto+plaga+texto grande en los primeros 3s (`narrative` etiqueta HOOK; blueprint guía)
- [ ] Subtítulos Hormozi con keyword resaltada (caption_style = hormozi/yellow_highlight)
- [ ] B-roll de dolor en la fase DOLOR (🎭 B-roll con IA, fase "problema")
- [ ] Demo del producto (caja en mano / botón / enchufado) en la fase PRODUCTO/DEMO
- [ ] Duración 20-23s, cortes cada 2-3s (pacing punchy)
- [ ] Sin precio, CTA contraentrega
- [ ] Banner "Oferta 2x1 · envío gratis" arriba (toggle)

_Generado por la sesión de jackingshop1-cell, 2026-07-06, a partir de los ejemplos de Jack + búsqueda
real en Foreplay (30 ganadores +30 días verificados con su API)._
