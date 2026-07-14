# 🔥 tests/smoke.py — Suite de humo de la Super-APP

**Para qué:** este repo lo construyen dos IAs fusionando rápido, y ya hubo breaks silenciosos
(un merge dejó `/api/config` devolviendo `null`). Esta suite protege los flujos críticos:
si después de un merge/cambio un check da ❌, se rompió algo REAL. Correrla es gratis.

## Cómo correrla

```bash
./venv/bin/python tests/smoke.py
```

- Corre en **~1 segundo** (presupuesto: <60s), **100% offline**, **$0 de APIs**.
- Imprime un ✅/❌ por check y al final el resumen `N/N`. Exit code `!= 0` si algo falló.
- `⏭️ SKIP` = falta una herramienta local en esta máquina (ffmpeg o node); no cuenta como falla.
- **Cuándo correrla:** antes de commitear cambios de backend, y SIEMPRE después de un
  `git pull` que trajo cambios del otro (es el detector de merges rotos).

## Qué protege (28 checks)

1. **Import + rutas** — la app importa entera y registran ≥60 endpoints (con lista de rutas críticas).
2. **`/api/config`** — dict completo con todos los `has_*` y `gemini_key_status` (el bug del null, nunca más).
3. **Básicos** — `/api/busy`, `/api/status/{id}` (job fake + 404), `/api/shopify-check` sin credenciales.
4. **Flujos crean job** (runner real mockeado): process (9:16 default, cap de versiones),
   scripts (con `reference_url` de Foreplay mockeada + rechazo de dominios ajenos), dub-preview,
   dub-generar, reaplicar-hook, landing-generate (gates de precio/foto/key), landing-publicar
   (gate sin Shopify), variar-imagen, radar/scan (sin key → error honesto), montador/status.
5. **Unidades puras** — `video_ok`, `normalize_loudness` (fixture real con ffmpeg local),
   `_dub_2x1_line`, `asignar_estructuras` fallback (8 estructuras distintas),
   `landing_agent._limpiar_cifras` (cifras inventadas fuera, las de Jack intactas),
   `offer_banner.render_banner` (línea 2 vacía), hooks genéricos con la IA caída (sin cifras).
6. **Frontend** — los 17+ bloques `<script>` de `frontend/index.html` pasan `node --check`.

## La guardia anti-red 🚨

Antes de importar nada, la suite bloquea **todos los sockets salientes** (`socket.connect`,
`create_connection`, `getaddrinfo`). Si un check —o un refactor futuro— intenta salir a
internet, explota con `FugaDeRed` y el check da ❌. Así detectamos fugas de red (llamadas a
Gemini/ElevenLabs/etc. que se cuelan donde no deben) sin gastar un centavo.

Además el entorno queda limpio: las env vars de API keys se purgan y el `.env` de la app se
redirige a un sandbox temporal → el resultado es determinista en cualquier máquina.

## Convención para AGREGAR checks (léela antes de tocar la suite)

- Un check = una función con `@check("nombre claro en español de QUÉ protege")`. Se registra sola.
- **CERO red y CERO servers**: usa el `client` (TestClient in-process) y mockea lo pesado.
  La guardia anti-red te delata si se te escapa una llamada.
- **Mocks que no se filtran**: usa `with patched(objeto, "attr", fake): ...` (restaura siempre).
  Para endpoints que lanzan threads, mockea el runner con `_runner_fake(caps)` y espera con
  `wait_for(lambda: caps)`.
- **Disco solo en `TMP`**: `appmod.UPLOAD_DIR/WORK_DIR/ENV_FILE` ya apuntan al sandbox; si creas
  archivos propios, créalos bajo `TMP` (se borra al final).
- Si el check necesita una herramienta local que puede faltar, `raise Skip("motivo")`.
- ffmpeg local SÍ se puede usar (es gratis): `_fixture_mp4()` da un mp4 real de 2s cacheado.
- Si un check falla contra el código actual y confirmaste que es un **bug real**: NO lo
  "arregles" aflojando el assert — repórtalo, y si hay que dejarlo temporalmente, márcalo con
  un comentario `# KNOWN-FAIL:` explicando el bug.
- Mantén la suite por debajo de 60s (hoy: ~1s).
