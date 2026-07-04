# Dropi API — método de conexión (capturado 3 jul 2026)

Cuenta: cuenta dedicada del radar (credenciales en .env: DROPI_EMAIL / DROPI_PASSWORD).

## Autenticación
- Login web: https://app.dropi.co/auth/login
- El login directo por `POST /api/login` devuelve 403 (protección). Se obtiene el token vía navegador:
  tras iniciar sesión, `localStorage['DROPI_LoginResult'].token` (JWT ~373 chars).
- Header de las llamadas: `Authorization: Bearer <token>`.
- ⚠️ OJO: NO es el `DROPI_token` de localStorage (ese da 401). Es el `.token` dentro de `DROPI_LoginResult`.

## Catálogo + stock
`POST https://api.dropi.co/api/products/v4/index`
Body:
```json
{"pageSize":85,"startData":0,"privated_product":false,"userVerified":false,
 "favorite":false,"with_collection":true,"get_stock":true,"no_count":false,
 "search_type":"simple","country":"COLOMBIA","keywords":"<opcional>"}
```
Respuesta: `{isSuccess, objects:[...], count}`. Paginar con `startData` (offset).

### Campos por producto (los útiles)
- `id`, `name`, `sku`, `type` (SIMPLE/VARIABLE)
- `sale_price` (costo proveedor), `suggested_price` (precio sugerido de venta)
- `categories[]` → `.name` (ej. "Moda", "Tecnología", "Salud")
- `user` → proveedor `{id, name}`
- `warehouse_product[]` → `{id, stock, warehouse_id}` ← **STOCK por bodega (la señal clave)**

## Uso en el radar
- **Sourcing**: si un producto del radar hace match aquí → 🟦 Dropi (vender ya).
- **Señal de ventas COD**: snapshot diario del stock por producto → Δstock negativo = unidades vendidas.
- Búsqueda por `keywords` funciona bien para matching on-demand (probado: "trapeador", "cera depiladora" devuelven productos con precio proveedor, sugerido, categoría y stock). Precio sugerido/precio proveedor da el margen para el BEP.

## Arquitectura decidida (3 jul 2026)
- El login por curl/headless da **403 (Cloudflare)**. Desde la sesión del navegador autenticado pasa sin problema.
- El sistema (correctamente) no permite exfiltrar el token JWT al contexto del agente.
- **Decisión MVP:** las consultas a Dropi corren DENTRO del navegador autenticado (Claude-in-Chrome / javascript_tool) o, para Cloud Run, un browser headless con la sesión. El token nunca sale del navegador.
- **No se baja el catálogo completo** (~decenas de miles). Se consulta por nombre solo para los candidatos del radar (decenas/día) → eficiente y respeta el rate limit.
- Para la señal de ventas COD: guardar snapshot de stock SOLO de los candidatos, no de todo el catálogo.

## Flujo de snapshot de stock (stock.py, desde 3 jul 2026)

1. `python3 stock.py preparar` → `docs/stock_pendientes.json` (dropi_id + nombre de los 🟦).
2. En el navegador autenticado (javascript_tool), por cada producto: `POST /api/products/v4/index`
   con `keywords: <nombre>` (o filtrar por id en la respuesta) → armar
   `docs/stock_resultados.json`: `[{dropi_id, nombre, stock, sale_price, suggested_price}]`
   (stock = suma de `warehouse_product[].stock`).
3. `python3 stock.py ingerir` → tabla `dropi_stock` + imprime 🔥 ventas/día vs snapshot anterior.
   El dashboard muestra el chip 🔥 automáticamente cuando hay ≥2 snapshots.

Línea base sembrada el 2026-07-03 (12 productos, desde la tabla sourcing con `stock.py seed`).
