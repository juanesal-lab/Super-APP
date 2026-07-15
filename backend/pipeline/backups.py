"""backups.py — Respaldo automático de lo IRREEMPLAZABLE que vive FUERA de git.

Por qué existe: la app guarda cosas que git NO versiona y que, si se corrompe el disco o
pasa un `rm` accidental, Jack pierde para siempre: los `.env` con sus 7+ API keys (app y
montador), y el estado del Radar (radar.db, config.json, .env, privado.json). Sin key no
hay app; sin la db del Radar se pierden semanas de escaneos (que cuestan créditos).

Qué hace: copia esos archivos a  ~/Backups/creativemaxing/<YYYY-MM-DD>/  conservando la
estructura del repo (así el restore es obvio: mismo path). Rota a 14 días como máximo
(borra SOLO carpetas con nombre de fecha DENTRO de ~/Backups/creativemaxing). chmod 700 en
las carpetas y 600 en los archivos porque contienen secretos.

NO respalda work/ ni uploads/ ni venvs ni models/ (pesados y regenerables).

Diseño de seguridad (lo probamos en tests/):
  - La rotación SOLO borra subcarpetas cuyo nombre calza  ^\\d{4}-\\d{2}-\\d{2}$  y que están
    contenidas en la carpeta de backups (doble verificación con os.path.commonpath). Jamás
    toca nada fuera de ~/Backups/creativemaxing, ni archivos, ni carpetas con otro nombre.
  - best-effort total: `respaldar()` NUNCA lanza (devuelve dict con error) para no frenar el
    arranque de la app.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import time
from datetime import datetime

# Raíz del repo: este archivo vive en backend/pipeline/backups.py → 3 niveles arriba.
_DEFAULT_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Carpeta de respaldos FUERA del repo git (en el HOME del usuario). Nunca dentro del repo.
_BACKUP_SUBDIR = os.path.join("Backups", "creativemaxing")

# Nombre de carpeta diaria: exactamente YYYY-MM-DD (lo usa la rotación como filtro de seguridad).
_FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Archivos CRÍTICOS a respaldar (rutas relativas a la raíz del repo). Se copian SOLO si existen.
# Curados a mano: secretos (.env) + estado del Radar. Todos chicos e irreemplazables.
_CRITICOS = [
    ".env",                    # 7+ API keys de la app (Gemini, ElevenLabs, Claude, Foreplay, Pexels/Pixabay, ScrapeCreators, Shopify)
    "montador/.env",           # keys de la app Montador (server aparte :8440)
    "radar/.env",              # key de ScrapeCreators que lee el motor del Radar (se crea al guardarla)
    "radar/radar.db",          # base de datos del Radar: semanas de escaneos (cuestan créditos)
    "radar/config.json",       # config del Radar editada desde la app
    "radar/privado.json",      # datos privados del Radar (si existen)
]

# Carpetas que NUNCA se recorren en el escaneo defensivo de .env (pesadas / regenerables).
_EXCLUIR_DIRS = {"venv", "work", "uploads", "models", "incoming", "projects",
                 "biblioteca", "resultado", "__pycache__", ".git", "node_modules",
                 ".claude", "assets", "logs"}


def _backup_root(home: str | None = None) -> str:
    """~/Backups/creativemaxing (respetando un HOME simulado en tests)."""
    h = home or os.environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(h, _BACKUP_SUBDIR)


def _chmod_700(path: str) -> None:
    try:
        os.chmod(path, stat.S_IRWXU)   # rwx------ (solo el dueño; contienen keys)
    except OSError:
        pass


def _chmod_600(path: str) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)   # rw------- (archivos con secretos)
    except OSError:
        pass


def _buscar_envs_extra(base: str) -> list[str]:
    """Escaneo defensivo: cualquier archivo `.env` del repo que no esté ya en la lista curada
    (así, si mañana aparece otro .env, igual se respalda). Ignora carpetas pesadas."""
    encontrados: list[str] = []
    ya = {os.path.normpath(os.path.join(base, p)) for p in _CRITICOS}
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _EXCLUIR_DIRS and not d.startswith(".claude")]
        for f in files:
            if f == ".env":
                full = os.path.normpath(os.path.join(root, f))
                if full not in ya:
                    encontrados.append(os.path.relpath(full, base))
    return encontrados


def _rotar(root: str, keep_dias: int) -> None:
    """Borra las carpetas diarias más viejas dejando como máximo `keep_dias`.

    SEGURIDAD: solo borra subcarpetas DIRECTAS de `root` cuyo nombre calza ^YYYY-MM-DD$ y que,
    resueltas, siguen contenidas en `root`. Nunca toca archivos, symlinks, ni carpetas con otro
    nombre, ni nada fuera de `root`."""
    try:
        entradas = os.listdir(root)
    except OSError:
        return
    dias = []
    for name in entradas:
        if not _FECHA_RE.match(name):
            continue
        p = os.path.join(root, name)
        # No seguir symlinks (un symlink llamado "2020-01-01" NO debe borrar su destino).
        if os.path.islink(p) or not os.path.isdir(p):
            continue
        dias.append(name)
    dias.sort(reverse=True)          # más nuevas primero (orden lexicográfico == cronológico)
    for name in dias[keep_dias:]:
        p = os.path.join(root, name)
        rp = os.path.realpath(p)
        # Doble check: el path real DEBE estar dentro de root real (blindaje anti-symlink/escape).
        try:
            if os.path.commonpath([os.path.realpath(root), rp]) != os.path.realpath(root):
                continue
        except ValueError:
            continue
        shutil.rmtree(p, ignore_errors=True)


def respaldar(base: str | None = None, home: str | None = None, keep_dias: int = 14) -> dict:
    """Respalda los archivos críticos del repo a ~/Backups/creativemaxing/<hoy>/ y rota a
    `keep_dias`. Best-effort: nunca lanza (devuelve el error en el dict).

    Devuelve {ok, respaldados:[rutas relativas], bytes, error}."""
    base = base or _DEFAULT_BASE
    respaldados: list[str] = []
    total = 0
    try:
        root = _backup_root(home)
        os.makedirs(root, exist_ok=True)
        _chmod_700(root)
        # Asegura 700 también en el padre ~/Backups (contiene la carpeta con keys).
        _chmod_700(os.path.dirname(root))

        hoy = datetime.now().strftime("%Y-%m-%d")
        destino = os.path.join(root, hoy)
        os.makedirs(destino, exist_ok=True)
        _chmod_700(destino)

        rutas = list(_CRITICOS) + _buscar_envs_extra(base)
        vistos = set()
        for rel in rutas:
            if rel in vistos:
                continue
            vistos.add(rel)
            src = os.path.join(base, rel)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(destino, rel)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                _chmod_700(os.path.dirname(dst))
                shutil.copy2(src, dst)
                _chmod_600(dst)
                total += os.path.getsize(dst)
                respaldados.append(rel)
            except OSError:
                continue

        _rotar(root, keep_dias)
        return {"ok": True, "respaldados": respaldados, "bytes": total, "error": None}
    except Exception as e:  # noqa: BLE001 — best-effort: jamás frenar el arranque
        return {"ok": False, "respaldados": respaldados, "bytes": total, "error": str(e)}


def estado(home: str | None = None) -> dict:
    """Estado para la UI: último respaldo, hace cuánto, y qué días hay guardados.

    Devuelve {ok, ultimo:'YYYY-MM-DD'|None, hace_segundos:int|None, dias:[...], root}."""
    try:
        root = _backup_root(home)
        dias = []
        try:
            for name in os.listdir(root):
                if _FECHA_RE.match(name) and os.path.isdir(os.path.join(root, name)):
                    dias.append(name)
        except OSError:
            pass
        dias.sort(reverse=True)
        ultimo = dias[0] if dias else None
        hace = None
        if ultimo:
            try:
                mt = os.path.getmtime(os.path.join(root, ultimo))
                hace = max(0, int(time.time() - mt))
            except OSError:
                hace = None
        return {"ok": True, "ultimo": ultimo, "hace_segundos": hace, "dias": dias, "root": root}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "ultimo": None, "hace_segundos": None, "dias": [], "root": "", "error": str(e)}
