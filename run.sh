#!/bin/bash
# Lanzador de CreativeMaxing · Vidaria — CON AUTO-ACTUALIZACIÓN.
# Revisa GitHub cada 30s y, cuando Juan (u otra IA) sube algo a main, lo BAJA y actualiza
# la app SOLA — sin que Jack haga nada. Regla de oro ("siempre que no falle"):
#   • NUNCA reinicia a mitad de un render: pregunta /api/busy y espera a que esté libre.
#   • Si el pull choca (conflicto), NO rompe nada: sigue con lo que hay y avisa.
#   • Cambios de frontend/docs se aplican SOLOS sin reiniciar (index.html se sirve sin caché).
#   • Solo los cambios de BACKEND (código Python) piden reinicio del server.
cd "$(dirname "$0")"
PORT=8420
BRANCH=main

echo "🎬  CreativeMaxing · Vidaria"

kill_port(){ local p; p=$(lsof -ti:$PORT 2>/dev/null); [ -n "$p" ] && kill -9 $p 2>/dev/null; return 0; }

# --- pull SEGURO (best-effort): si avanza, imprime el rango "OLD..NEW"; si no o si falla, nada ---
safe_pull(){
  git fetch origin "$BRANCH" --quiet 2>/dev/null || return 1
  local before remote after
  before=$(git rev-parse HEAD 2>/dev/null)
  remote=$(git rev-parse "origin/$BRANCH" 2>/dev/null)
  [ -z "$remote" ] && return 1
  [ "$before" = "$remote" ] && return 1          # ya estamos al día
  if git merge --ff-only "origin/$BRANCH" --quiet 2>/dev/null; then
    :                                            # avance limpio (Jack no había divergido)
  else
    # Jack tiene cambios propios sin subir → merge con autostash; si choca, aborta y sigue vivo
    if ! git -c core.editor=true pull --no-rebase --autostash origin "$BRANCH" >/dev/null 2>&1; then
      git merge --abort 2>/dev/null
      echo "⚠️  No pude auto-actualizar (conflicto con tus cambios) — sigo con lo que tengo." >&2
      return 1
    fi
  fi
  after=$(git rev-parse HEAD 2>/dev/null)
  [ "$before" = "$after" ] && return 1
  echo "$before..$after"
}

echo "Buscando lo último en GitHub..."
kill_port
safe_pull >/dev/null 2>&1                        # traer lo de Juan ANTES de arrancar

echo "Abriendo en http://127.0.0.1:$PORT ..."
sleep 1 && (open http://127.0.0.1:$PORT 2>/dev/null || true) &

start_server(){
  ./venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port $PORT &
  SRV_PID=$!
}
start_server
echo "✅ App corriendo (PID $SRV_PID). 🔄 Auto-actualización ACTIVA (revisa GitHub cada 30s)."

cleanup(){ echo ""; echo "Cerrando..."; kill "$SRV_PID" 2>/dev/null; kill_port; exit 0; }
trap cleanup INT TERM

app_busy(){                                      # ¿hay un render en curso? (para no cortarlo)
  curl -s -m 3 "http://127.0.0.1:$PORT/api/busy" 2>/dev/null | grep -q '"busy":[[:space:]]*true'
}

PENDING=0                                         # hay update de backend esperando a que la app esté libre
while true; do
  sleep 30

  if ! kill -0 "$SRV_PID" 2>/dev/null; then       # si el server se cayó solo, lo revivo
    echo "⚠️  El server se cerró — reiniciando..."
    kill_port; start_server
  fi

  RANGE=$(safe_pull)
  if [ -n "$RANGE" ]; then
    if git diff --name-only $RANGE 2>/dev/null | grep -qE '\.py$|requirements\.txt'; then
      PENDING=1
      echo "🔄 Juan subió cambios de BACKEND — se aplican apenas la app esté libre (sin cortar renders)."
    else
      echo "🔄 App actualizada con los cambios de Juan (frontend/docs — al instante, sin reiniciar)."
    fi
  fi

  if [ "$PENDING" = "1" ] && ! app_busy; then     # reinicia SOLO si toca y NO hay render corriendo
    echo "🔁 Aplicando la actualización (reiniciando el server)..."
    kill "$SRV_PID" 2>/dev/null; kill_port
    start_server
    PENDING=0
    echo "✅ App actualizada y corriendo (PID $SRV_PID)."
  fi
done
