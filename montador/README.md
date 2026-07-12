# 🎬 Montador · Vidaria

App local (solo este Mac) que monta ads automáticamente: subes **1 voz en off + tus clips crudos**
y la IA transcribe, **ve** los videos, decide qué clip va en cada beat de la voz, y entrega el
video con efectos + karaoke + guion de montaje.

## Prender
```bash
cd ~/montador-ads && ./run.sh
```
Se abre en **http://127.0.0.1:8440**

## Cómo se usa
1. Escribe el nombre del proyecto.
2. Arrastra las **voces en off** (1 o VARIAS — se monta un ad por cada voz, mismo paquete de clips) y los **videos** (mínimo 2). Los ads de una tanda comparten los clips en disco (enlaces duros) y el catálogo visual se calcula UNA vez (los hermanos lo heredan: cada ad extra solo cuesta el plan).
   Opcional: arrastra una **música de fondo** (cama a 0.22 con ducking automático bajo la voz,
   hot-start en t=0 y fade-out de 1.5s — jamás se corta en seco).
3. Elige el **estilo de subtítulos** (karaoke / caja amarilla Hormozi / minimal blanco)
   y la **plataforma** (Meta = subs al centro 0.62 · TikTok = más abajo 0.80).
4. `🎬 Montar mi ad` → mira el progreso en vivo (si hay otro render, queda **en cola**:
   máximo 1 render a la vez).
5. Al terminar: previews + **guion visual** (miniatura por corte con tiempo, subtítulo, clip,
   fase y razón) + descargas de `corte-base.mp4` (limpio, para CapCut), `corte-base-SUBS.mp4`
   (subtítulos preview), `guion-montaje.md`, `subtitulos.srt` y **todo en ZIP**.
6. `🎲 Otra versión` → re-renderiza con otro ritmo de cortes (misma selección de clips,
   sin llamar a Claude) y la guarda en `resultado/version-N/` con su preview en la UI.
7. ¿Algo no te gustó? Escribe el ajuste (ej. *"cambia el corte 3 por un clip de textura"*)
   y `🔁 Aplicar ajuste` — re-monta solo el plan (rápido, no re-analiza los clips).
8. `🗑 Eliminar` borra el proyecto completo (pide confirmación).

## 🏆 Clonar ganador
Sube un **ad ganador** (tuyo o de la competencia) + tus clips → la app:
1. Transcribe su narración y analiza su **ADN** (estructura por tramos, ángulo, ritmo, elementos) → `adn-ganador.md`.
2. Escribe **guiones variación beat a beat** (mismo arco y duraciones, palabras nuevas) siguiendo el framework de guiones de Juan (anti-baneo, CTA COD).
3. Genera las voces con **ElevenLabs** (Kate/Juan Carlos) — si no hay créditos, los guiones quedan guardados y con 🔁 Reintentar solo genera lo que falta.
4. Monta cada variación (+ una con el **audio original** del ganador) como proyectos hijos: clips compartidos, catálogo heredado, agentes, cola.

## Cómo funciona por dentro
1. **Transcripción**: faster-whisper (local, gratis) con tiempos por palabra → beats.
2. **Catálogo visual**: extrae frames de cada clip y Claude los describe
   (qué se ve, momentos buenos, textos quemados que puedan chocar con el ad).
3. **Plan de montaje**: Claude asigna clip + segundo exacto + efecto a cada beat.
   Reglas duras en código: **jamás la misma toma dos veces** (si hay más beats que clips,
   reusa variando el segmento), evitar clips con precios/teléfonos ajenos, gancho fuerte al inicio.
4. **Render**: ffmpeg con zoom in/out por clip y *punch* en gancho/precio/CTA, 1080×1920 30fps.
5. **Karaoke**: subtítulos palabra-por-palabra estilo CapCut (Pillow), + SRT importable.

## Config (`.env`)
- `ANTHROPIC_API_KEY` — la key de Claude (ya configurada).
- `MONTADOR_MODEL` — modelo para ver/planear (default `claude-sonnet-5`).

## Estructura
```
backend/app.py       ← server FastAPI (puerto 8440)
backend/pipeline.py  ← el motor (whisper + Claude + ffmpeg + karaoke)
frontend/index.html  ← la interfaz
projects/<id>/       ← cada proyecto: clips, voz, work/ (caches), resultado/
```

## Notas
- La transcripción y el catálogo se **cachean** por proyecto: reintentos, ajustes y
  "otra versión" son rápidos y baratos ("otra versión" no llama a Claude en absoluto).
- Costo aprox. por proyecto: céntimos (frames comprimidos + 2 llamadas de texto).
- El ffmpeg de Homebrew de este Mac no trae `drawtext`; por eso los subtítulos se hacen con Pillow + overlay.
- **Blindaje**: todo archivo subido se valida con ffprobe (corruptos se rechazan con mensaje claro),
  cada segmento de render tiene 1 reintento si ffmpeg tropieza, y hay un semáforo global de render.
