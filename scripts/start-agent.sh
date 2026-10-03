#!/usr/bin/env sh
# Arranca el agente. Solo necesita Python 3.11+ (sin .venv). Ejemplo: scripts/start-agent.sh --simulate nvidia2
cd "$(dirname "$0")/.."
exec python3 -m agent "$@"
