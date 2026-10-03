---
fecha_creacion: 2026-10-03
fecha_modificacion: 2026-10-03
tipo: proyecto
categoria: tech
tags: [tech, homelab, agente]
estado: activo
fecha_limite: ~
relacionado: ["Arena LLM"]
---
# Arena LLM — Estado

> Leer al retomar. Última actualización: 03/10/2026.

## Fase actual: F1 — Esqueleto y agente

| # | Hito | Estado |
|---|---|---|
| 1 | Esqueleto del repositorio | ✅ 03/10/2026 |
| 2 | Contrato del agente y servidor HTTP | ✅ 03/10/2026 |
| 3 | Proveedor CPU/RAM | ⏳ siguiente |
| 4 | Proveedor NVIDIA | — |
| 5 | Perfiles de hardware simulados | — |
| 6 | Detección de llama-server | — (necesita llama.cpp instalado) |
| 7 | Lector de cabecera GGUF | — |
| 8 | Cierre de F1 en el PC real | — |

Detalle de cada hito: `docs/PLAN-CONSTRUCCION.md` §6.

## F0 — parcial

- [x] RAM real comprobada: 16 GB (2 × 8 GB a 2400 MHz; XMP desactivado)
- [x] Python, Node y git disponibles
- [ ] XMP activado
- [ ] llama.cpp (CUDA 12.x) instalado en `D:\dev-tools\llama.cpp\`
- [ ] M40 instalada con driver R580 (llega la semana del 05/10/2026)
- [ ] `llama-bench` y `llama-server` verificados en cada tarjeta

## Entorno

- Python del proyecto: `.venv` con 3.12 (`scripts\setup.bat`). El comando `python` de Windows es el atajo de la Store.
- ⚠️ `py -3` apunta a un Python 3.14 registrado en `D:\python.exe` que **ya no existe** (entrada huérfana en `HKCU\Software\Python\PythonCore.14`). Por eso `start-agent.bat` usa `.venv` o `ARENA_PY`. Pendiente de Lucas: reinstalar 3.14 o borrar esa entrada.
- Agente: `/health`, `/info`, `/metrics` con contrato `agent_api: 1`; puerto por defecto 9100; fuera de localhost exige token (`ARENA_AGENT_TOKEN`).
- Remoto: https://github.com/Dallamond/Arena-LLM (privado).
