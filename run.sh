#!/bin/bash
# Lanzador del Cortador de Clips
cd "$(dirname "$0")"
echo "🎬  Cortador de Clips · Vidaria"
echo "Abriendo en http://127.0.0.1:8420 ..."
sleep 1 && (open http://127.0.0.1:8420 2>/dev/null || true) &
exec ./venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8420
