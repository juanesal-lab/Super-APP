# 🤖 Mejoras de inteligencia del asistente — 2026-07-10

## El problema que contaste

Le preguntaste a la IA si tu búsqueda de creativos del veneno de abeja tenía resultados y
te contestó *"no puedo confirmarte desde mi lado... revisá vos la sección"*. Inaceptable.

**Por qué pasaba (lo que encontré):**
1. **La app no tenía ningún asistente adentro.** No existía ningún chat en la app que pudiera
   mirar el backend — la IA que te contestó eso no tenía acceso a nada de la app.
2. **"Buscar creativos" no dejaba rastro.** La búsqueda corría, te mostraba los resultados en
   la pantalla... y listo. No quedaba guardado NADA en disco: ni cuántos encontró, ni si
   Foreplay falló, ni si Gemini se cayó. Aunque una IA quisiera mirar, no había qué mirar.

## Qué hice

### 1. Asistente NUEVO adentro de la app (botón 🤖 abajo a la derecha)
- Le preguntás lo que sea ("¿cómo va mi búsqueda?", "¿por qué falló el doblaje?") y **antes de
  responder mira el estado REAL del backend**: los trabajos corriendo (con % y cuánto llevan),
  los terminados (qué produjeron), los que fallaron (el error exacto) y el estado de tus keys.
- **Prohibido el "revisá vos"**: responde con evidencia. Si un trabajo falló te dice QUÉ falló
  (ej: "Foreplay sin créditos (429) — dale de nuevo al botón" o "la key de Gemini venció —
  cambiala en 🔑 Claves"). Si sigue corriendo te dice cuánto lleva y cuánto suele tardar.
- **Si hasta Gemini está caído, igual te responde** con el estado real (armado sin IA) y te
  dice por qué el motor no anda. Nunca queda mudo.

### 2. Bitácora de todo (para que siempre haya evidencia)
- Ahora CADA búsqueda de creativos y CADA trabajo (inicio y fin, con error o con lo que
  produjo) queda anotado en `work/_eventos.jsonl`. Sobrevive reinicios del server.
- Cada trabajo quedó etiquetado con su tipo (doblaje, cortar clips, ads de imagen...) para que
  el asistente hable claro: "tu doblaje de hace 5 min falló por X".

### 3. Puente con Claude (lo que pediste)
- Cuando el asistente detecta algo que lo excede (key vencida, bug raro, decisión de plata),
  **anota la duda en `/Users/jaca/Vidaria/data/dudas-superapp.jsonl`** y te avisa:
  *"le dejé la duda anotada a Claude"*. Claude (la terminal) la lee y la resuelve.
- Si es **urgente** (plata en riesgo, app rota), además te manda un Telegram al toque por el
  bot del negocio (@Jacabuenashopbot).

### 4. Pipelines más robustos
- **Foreplay**: si tira 429 (límite de tasa), error de red o timeout, ahora **reintenta solo
  una vez** (espera 2s) antes de rendirse; y los errores dicen qué hacer ("key inválida (401)
  — revísala en 🔑 Claves").
- **Gemini rápido**: cuando falla, ahora queda registrado el MOTIVO real (antes se tragaba el
  error en silencio), para que el asistente pueda contártelo.

## ⚠️ Para que entre TODO esto: reiniciá la app

El server corre sin auto-recarga (y el que está corriendo es viejito). Cuando NO tengas un
render en curso:

```bash
cd /Users/jaca/Transcriptor/Super-APP
kill $(lsof -ti:8420)
./run.sh
```

(O cerrá la terminal donde corre y volvé a darle `./run.sh`.)

## Cómo se verificó (sin gastar casi nada)
- `py_compile` de los 4 .py tocados: OK. JS del frontend: 16/16 bloques OK.
- Pruebas offline del módulo del asistente (bitácora, snapshot, fallback sin IA, parser,
  puente con Claude): 6/6 OK.
- Prueba REAL de punta a punta (1 llamada baratita a Gemini flash): le pregunté al asistente
  por una búsqueda del veneno de abeja y por un doblaje fallado → contestó con los números y
  el error exactos, y anotó la duda para Claude. Cero "revisá vos".
