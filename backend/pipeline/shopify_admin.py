"""Cliente de la Admin API de Shopify para el módulo CREAR LANDINGS.

REGLAS INQUEBRANTABLES (de Juan):
  - NUNCA editar nada existente en la tienda (temas, plantillas, secciones, productos, páginas).
    Este cliente SOLO crea archivos/recursos NUEVOS con nombres únicos (prefijo "cm-").
  - Multi-tienda: nada hardcodeado; todo sale de la config local (.env) de cada usuario.
  - Nada se sube sin la aprobación explícita del usuario (el gate vive en el flujo, no aquí).

Credenciales (mismo patrón que Gemini/Foreplay — .env vía 🔑 Claves):
  SHOPIFY_STORE_DOMAIN   ej: mitienda.myshopify.com
  SHOPIFY_ADMIN_API_TOKEN token de una custom app (empieza con shpat_)
  SHOPIFY_THEME_ID       opcional; si falta se detecta el tema PUBLICADO automáticamente

Scopes mínimos del token: read_themes, write_themes, read_products, write_products,
read_files, write_files (ver README-LANDINGS.md).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time

import requests

_API_VER = "2026-01"


def _base(domain: str) -> str:
    d = (domain or "").strip().replace("https://", "").replace("http://", "").strip("/")
    return f"https://{d}/admin/api/{_API_VER}"


def _headers(token: str) -> dict:
    return {"X-Shopify-Access-Token": (token or "").strip(), "Content-Type": "application/json"}


def validar(domain: str, token: str) -> dict:
    """Request de prueba a la Admin API. {ok, shop, plan, error} — errores en español claro."""
    if not (domain or "").strip():
        return {"ok": False, "error": "Falta el dominio de la tienda (mitienda.myshopify.com) en 🔑 Claves"}
    if not (token or "").strip():
        return {"ok": False, "error": "Falta el Admin API token de Shopify (shpat_...) en 🔑 Claves"}
    try:
        r = requests.get(f"{_base(domain)}/shop.json", headers=_headers(token), timeout=20)
        if r.status_code == 401:
            return {"ok": False, "error": "Shopify rechazó el token (401). Revisa el Admin API token."}
        if r.status_code == 404:
            return {"ok": False, "error": f"No existe la tienda '{domain}'. Revisa el dominio .myshopify.com"}
        if r.status_code != 200:
            return {"ok": False, "error": f"Shopify respondió HTTP {r.status_code}"}
        shop = (r.json() or {}).get("shop") or {}
        return {"ok": True, "shop": shop.get("name", ""), "dominio": shop.get("myshopify_domain", ""),
                "moneda": shop.get("currency", "")}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": "No se pudo conectar con Shopify (revisa el dominio o tu internet)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Error validando Shopify: {str(e)[:120]}"}


def tema_publicado(domain: str, token: str, theme_id: str | None = None) -> dict:
    """El tema donde se crearán los archivos NUEVOS. Si hay SHOPIFY_THEME_ID lo usa; si no,
    detecta el tema PUBLICADO (role=main). {ok, id, nombre, error}."""
    try:
        r = requests.get(f"{_base(domain)}/themes.json", headers=_headers(token), timeout=20)
        if r.status_code != 200:
            return {"ok": False, "error": f"No pude listar los temas (HTTP {r.status_code}). ¿El token tiene read_themes?"}
        temas = (r.json() or {}).get("themes") or []
        if theme_id and str(theme_id).strip():
            for t in temas:
                if str(t.get("id")) == str(theme_id).strip():
                    return {"ok": True, "id": t["id"], "nombre": t.get("name", ""), "rol": t.get("role", "")}
            return {"ok": False, "error": f"No encontré el tema con id {theme_id} (revisa SHOPIFY_THEME_ID)"}
        for t in temas:
            if t.get("role") == "main":
                return {"ok": True, "id": t["id"], "nombre": t.get("name", ""), "rol": "main"}
        return {"ok": False, "error": "No encontré un tema publicado en la tienda"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Error buscando el tema: {str(e)[:120]}"}


def _slug(texto: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (texto or "").lower().strip()).strip("-")
    return s[:40] or "landing"


def nombre_unico(tipo: str, producto: str) -> str:
    """Nombre ÚNICO para la plantilla nueva (jamás pisa nada): cm-<tipo>-<producto>-<fecha>."""
    return f"cm-{tipo}-{_slug(producto)}-{time.strftime('%Y%m%d-%H%M')}"


def asset_existe(domain: str, token: str, theme_id, key: str) -> bool:
    """Chequeo defensivo: ¿ya existe un asset con ese nombre en el tema? (nunca sobreescribir)."""
    try:
        r = requests.get(f"{_base(domain)}/themes/{theme_id}/assets.json",
                         headers=_headers(token), params={"asset[key]": key, "fields": "key"}, timeout=20)
        return r.status_code == 200 and bool((r.json() or {}).get("asset"))
    except Exception:  # noqa: BLE001
        return False


def crear_asset(domain: str, token: str, theme_id, key: str, contenido: str) -> dict:
    """CREA un archivo nuevo en el tema (secciones/plantillas con prefijo cm-). Se NIEGA a
    sobreescribir: si el key ya existe devuelve error (regla: nunca tocar lo existente)."""
    if asset_existe(domain, token, theme_id, key):
        return {"ok": False, "error": f"El archivo {key} YA existe en el tema — no se sobreescribe nada. "
                                      "Usa otro nombre."}
    try:
        r = requests.put(f"{_base(domain)}/themes/{theme_id}/assets.json", headers=_headers(token),
                         json={"asset": {"key": key, "value": contenido}}, timeout=40)
        if r.status_code in (200, 201):
            return {"ok": True, "key": key}
        return {"ok": False, "error": f"Shopify rechazó {key} (HTTP {r.status_code}): {r.text[:160]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Error subiendo {key}: {str(e)[:120]}"}


def subir_imagen_files(domain: str, token: str, image_path: str, alt: str = "") -> dict:
    """Sube una imagen a Shopify FILES (CDN) vía GraphQL staged upload. {ok, url, error}.
    La imagen debe venir YA optimizada de peso (eso lo garantiza landing_images antes de llegar aquí)."""
    gql = f"https://{(domain or '').strip().replace('https://','').strip('/')}/admin/api/{_API_VER}/graphql.json"
    nombre = os.path.basename(image_path)
    mime = "image/webp" if nombre.lower().endswith(".webp") else \
           "image/png" if nombre.lower().endswith(".png") else "image/jpeg"
    try:
        size = os.path.getsize(image_path)
        # 1) staged upload target
        q1 = {"query": """mutation stagedUploadsCreate($input:[StagedUploadInput!]!){
                stagedUploadsCreate(input:$input){stagedTargets{url resourceUrl parameters{name value}}
                userErrors{message}}}""",
              "variables": {"input": [{"resource": "FILE", "filename": nombre, "mimeType": mime,
                                        "fileSize": str(size), "httpMethod": "POST"}]}}
        r1 = requests.post(gql, headers=_headers(token), json=q1, timeout=30)
        d1 = (r1.json() or {}).get("data", {}).get("stagedUploadsCreate", {})
        errs = d1.get("userErrors") or []
        if errs:
            return {"ok": False, "error": f"Shopify (staged upload): {errs[0].get('message','')[:140]}"}
        tgt = (d1.get("stagedTargets") or [{}])[0]
        # 2) subir el binario al target
        form = [(p["name"], (None, p["value"])) for p in tgt.get("parameters", [])]
        with open(image_path, "rb") as f:
            form.append(("file", (nombre, f.read(), mime)))
        r2 = requests.post(tgt["url"], files=form, timeout=90)
        if r2.status_code not in (200, 201, 204):
            return {"ok": False, "error": f"Upload al CDN falló (HTTP {r2.status_code})"}
        # 3) registrar el archivo en Files
        q2 = {"query": """mutation fileCreate($files:[FileCreateInput!]!){
                fileCreate(files:$files){files{... on MediaImage{id image{url}}} userErrors{message}}}""",
              "variables": {"files": [{"originalSource": tgt["resourceUrl"], "alt": alt or nombre,
                                        "contentType": "IMAGE"}]}}
        r3 = requests.post(gql, headers=_headers(token), json=q2, timeout=30)
        d3 = (r3.json() or {}).get("data", {}).get("fileCreate", {})
        errs = d3.get("userErrors") or []
        if errs:
            return {"ok": False, "error": f"Shopify (fileCreate): {errs[0].get('message','')[:140]}"}
        files = d3.get("files") or []
        url = ((files[0] or {}).get("image") or {}).get("url", "") if files else ""
        # la URL puede tardar unos segundos en procesarse; se devuelve el id igual
        return {"ok": True, "url": url, "id": (files[0] or {}).get("id", "") if files else "",
                "peso_kb": round(size / 1024)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Error subiendo imagen a Files: {str(e)[:140]}"}
