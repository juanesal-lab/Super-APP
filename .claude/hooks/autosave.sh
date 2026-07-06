#!/usr/bin/env bash
# Auto-guardado de la Super-APP.
# Al TERMINAR cada tarea (Stop hook de Claude Code) commitea lo que haya sin guardar
# y lo sube a GitHub. Lo comparten las dos sesiones (Juan y jackingshop1) vía
# .claude/settings.json, así el trabajo de cualquiera de los dos nunca se pierde.
#
# Reglas que respeta:
#  - .env y demás secretos NO se suben (están en .gitignore; git add -A los respeta).
#  - pull --no-rebase antes de push (conserva ambas historias, evita rechazos).
#  - Si hay conflicto o falla el push: deja el commit LOCAL y avisa (no rompe nada).
#  - Si no hay nada que guardar ni subir: no hace nada.

export GIT_TERMINAL_PROMPT=0

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$root" 2>/dev/null || exit 0

# ¿Es un repo git con upstream?
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

changes="$(git status --porcelain 2>/dev/null)"
ahead="$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)"

# Nada sin commitear y nada sin subir -> salir en silencio
if [ -z "$changes" ] && [ "$ahead" = "0" ]; then
  exit 0
fi

if [ -n "$changes" ]; then
  git add -A
  git commit -q -m "auto-guardado (Stop hook): cambios sin commitear" >/dev/null 2>&1
fi

# Traer lo de la otra sesion antes de subir
git pull --no-rebase --no-edit -q >/dev/null 2>&1
pull_rc=$?

if git push -q >/dev/null 2>&1; then
  echo '{"systemMessage": "✅ Auto-guardado: subido a GitHub."}'
elif [ "$pull_rc" != "0" ]; then
  echo '{"systemMessage": "⚠️ Auto-guardado: quedó commit LOCAL pero hay CONFLICTO al traer de GitHub. Pídeme que lo resuelva (no se subió)."}'
else
  echo '{"systemMessage": "⚠️ Auto-guardado: commit local hecho, pero el push falló (conexión/permiso). Pídeme que reintente."}'
fi
exit 0
