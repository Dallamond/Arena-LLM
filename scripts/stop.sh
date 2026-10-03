#!/usr/bin/env sh
# Para los procesos de Arena (agentes, servidor y llama-server simulados). No toca llama-server reales.
pkill -f -- " -m (agent|server)( |$|\.fakes)" && echo "Arena parado" || echo "Nada que parar"
