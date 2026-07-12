#!/bin/bash
# Lanzador de Montador (solo este Mac)
cd "$(dirname "$0")"
echo "🎬  Montador · Vidaria"
OLD_PIDS=$(lsof -ti:8440 2>/dev/null)
[ -n "$OLD_PIDS" ] && echo "Cerrando server anterior..." && kill -9 $OLD_PIDS 2>/dev/null
echo "Abriendo en http://127.0.0.1:8440 ..."
sleep 1 && (open http://127.0.0.1:8440 2>/dev/null || true) &
# Sin --reload a propósito: un cambio de archivo NO corta un render a la mitad.
exec ./venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8440
