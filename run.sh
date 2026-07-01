#!/bin/bash
# Lanzador del Cortador de Clips
cd "$(dirname "$0")"
echo "🎬  Cortador de Clips · Vidaria"
# Cierra cualquier server anterior atascado en el puerto 8420 (evita "puerto ocupado"
# y que quede corriendo código viejo). Solo mata si hay algo escuchando.
OLD_PIDS=$(lsof -ti:8420 2>/dev/null)
[ -n "$OLD_PIDS" ] && echo "Cerrando server anterior..." && kill -9 $OLD_PIDS 2>/dev/null
echo "Abriendo en http://127.0.0.1:8420 ..."
sleep 1 && (open http://127.0.0.1:8420 2>/dev/null || true) &
# Server SIN --reload a propósito: así un git pull o un cambio de archivo NO reinicia el
# server a mitad de un render y le corta el trabajo. ¿Código nuevo? Cierra y corre ./run.sh
# otra vez: arriba ya mata el server viejo, así que siempre arranca limpio y con lo último.
exec ./venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8420
