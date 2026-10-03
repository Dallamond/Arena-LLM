# Arena LLM

Banco de pruebas **independiente del hardware** para modelos de IA locales (llama.cpp): mide, enfrenta y compara modelos en cualquier equipo y tarjeta, con la telemetría del equipo siempre visible.

> Estado: en construcción (Fase 1). Ver [`ESTADO.md`](ESTADO.md) y [`docs/HOJA-DE-RUTA.md`](docs/HOJA-DE-RUTA.md).

## Componentes

| Carpeta | Qué es | Requisitos |
|---|---|---|
| `agent/` | Agente por equipo: telemetría (GPU, CPU, RAM), detección de `llama-server`, cabeceras GGUF, `llama-bench` | Python 3.11+, **solo biblioteca estándar** |
| `server/` | API, runner de pruebas y base de datos (SQLite) | Python 3.11+, FastAPI, httpx (desde la Fase 2) |
| `web/` | Interfaz (Vue 3 + Vite + TypeScript) | Node 20+ (desde la Fase 2) |

## Puesta en marcha

```bash
# Windows
scripts\setup.bat          # crea .venv (Python 3.12 por defecto) e instala pytest y ruff
scripts\test.bat

# Linux
scripts/setup.sh
scripts/test.sh
```

El agente no necesita entorno virtual:

```bash
scripts\start-agent.bat --simulate nvidia2     # perfiles: nvidia2 | cpu-only | partial
```

## Datos

La base de datos y los resultados viven en `data/` (ignorada por git y Syncthing) o en la ruta de la variable `ARENA_DATA_DIR`. Nunca se suben al repositorio.

## Documentación

- [`docs/HOJA-DE-RUTA.md`](docs/HOJA-DE-RUTA.md) — decisiones y fases
- [`docs/PLAN-CONSTRUCCION.md`](docs/PLAN-CONSTRUCCION.md) — módulos, contrato agente↔servidor e hitos
- [`docs/GUI-DISENO.md`](docs/GUI-DISENO.md) — interfaz
- [`docs/VIABILIDAD.md`](docs/VIABILIDAD.md) — riesgos, métricas y datasets de pruebas
