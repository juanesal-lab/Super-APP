# 🛍️ Módulo Crear Landings — configuración de Shopify

Módulo privado multi-tienda: cada persona corre la app LOCAL con las credenciales de SU tienda.
**Regla de oro: la app NUNCA edita nada existente en tu tienda** — solo crea archivos nuevos con
prefijo `cm-`, y NADA se sube sin tu aprobación explícita en el paso de preview.

## 1. Crear la custom app en Shopify
1. En tu admin: **Configuración → Apps y canales de venta → Desarrollar apps → Crear una app**.
2. Nombre sugerido: `CreativeMaxing Landings`.
3. En **Configuración de la API de administrador**, activa estos scopes (mínimos):
   - `read_themes`, `write_themes`   (crear la plantilla/secciones NUEVAS en el tema)
   - `read_products`, `write_products` (opcional: crear el producto con variantes)
   - `read_files`, `write_files`     (subir las imágenes optimizadas a Files/CDN)
4. Instala la app y copia el **Admin API access token** (empieza con `shpat_...`). Solo se muestra
   una vez.

## 2. Configurar en la app
Pestaña **🔑 Claves → 🛍️ Shopify · Crear Landings**:
- **Dominio**: `mitienda.myshopify.com`
- **Admin API token**: `shpat_...`
- **Theme ID** (opcional): si lo dejas vacío, se detecta automáticamente el tema PUBLICADO.

(Quedan en tu `.env` local, que está en `.gitignore` — jamás se suben a ningún repo.)

## 3. Verificar
En el módulo **🛍️ Crear Landings** → botón **"Verificar conexión"**: hace un request de prueba y
muestra tu tienda + el tema detectado. Si algo falla, el error sale en español claro.

## Qué crea la app en tu tienda (y qué NO)
- ✅ Crea: `templates/page.cm-<tipo>-<producto>-<fecha>.json` + secciones `sections/cm-*.liquid`
  nuevas + imágenes en **Files** (CDN), todas optimizadas de peso.
- ✅ Opcional (si lo pides): un producto nuevo con variantes.
- ❌ Jamás: editar/borrar temas, plantillas, secciones, productos o páginas existentes. Si un nombre
  ya existe, la app se NIEGA a sobreescribir y te avisa.
