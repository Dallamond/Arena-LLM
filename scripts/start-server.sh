#!/usr/bin/env sh
# Arranca el servidor Arena (API + web compilada). Ejemplo: scripts/start-server.sh --agent http://127.0.0.1:9100
set -e
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Falta .venv: ejecuta scripts/setup.sh"; exit 1; }
exec .venv/bin/python -m server "$@"
