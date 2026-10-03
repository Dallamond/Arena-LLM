#!/usr/bin/env sh
# Crea .venv con Python 3.11+ e instala las dependencias de desarrollo.
# Uso: scripts/setup.sh [python]   (por defecto python3)
set -e
cd "$(dirname "$0")/.."
PY="${1:-python3}"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --no-cache-dir --upgrade pip
.venv/bin/python -m pip install --no-cache-dir -r requirements-dev.txt
echo "Entorno listo en .venv"
