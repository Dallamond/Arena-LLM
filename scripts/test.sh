#!/usr/bin/env sh
# Ejecuta la suite de tests de Python.
set -e
cd "$(dirname "$0")/.."
.venv/bin/python -m pytest "$@"
