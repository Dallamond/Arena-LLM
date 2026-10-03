#!/usr/bin/env sh
# Arranca todo para probar: agente real (9100), agente simulado nvidia2 (9101) con dos llama-server
# simulados (18081, 18082) y servidor (8090).
# Uso: scripts/demo.sh [carpeta de modelos GGUF]   — Ctrl+C para parar.
set -e
cd "$(dirname "$0")/.."
MODELS=""
[ -n "$1" ] && MODELS="--models-dir $1"
.venv/bin/python -m agent --port 9100 $MODELS &
A1=$!
.venv/bin/python -m agent --port 9101 --simulate nvidia2 &
A2=$!
.venv/bin/python -m server.fakes.fake_llama --port 18081 --tps 45 --ctx 8192 --slots 2 &
F1=$!
.venv/bin/python -m server.fakes.fake_llama --port 18082 --tps 18 --ctx 16384 --slots 1 &
F2=$!
trap 'kill $A1 $A2 $F1 $F2 2>/dev/null' EXIT INT TERM
sleep 2
.venv/bin/python -m server --agent http://127.0.0.1:9100 --agent http://127.0.0.1:9101
