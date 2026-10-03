# Arena LLM

Banco de pruebas **independiente del hardware** para modelos de IA locales (llama.cpp). Sirve para medir, enfrentar y comparar modelos en cualquier equipo y tarjeta, y siempre muestra la telemetría del equipo.

> Estado: F1–F5 (pruebas de estrés y prompt libre reales). Ver [`ESTADO.md`](ESTADO.md) y [`docs/HOJA-DE-RUTA.md`](docs/HOJA-DE-RUTA.md).

## Componentes

| Carpeta | Qué es | Requisitos |
|---|---|---|
| `agent/` | Agente por equipo: telemetría (GPU, CPU, RAM), detección de `llama-server`, cabeceras GGUF y, más adelante, `llama-bench` | Python 3.11+, **solo biblioteca estándar** |
| `server/` | API, sondeo de agentes, eventos en vivo (SSE) y base de datos SQLite | Python 3.11+, FastAPI, uvicorn, httpx |
| `web/` | Interfaz en Vue 3 + Vite + TypeScript | Node 20+ |

## Puesta en marcha (Windows)

```bat
scripts\setup.bat                  :: crea .venv (Python 3.12) con las dependencias
scripts\build-web.bat              :: compila la web en web\dist
scripts\demo.bat D:\mis\modelos    :: agente real + agente simulado (con 2 llama-server simulados) + servidor
scripts\stop.bat                   :: para todo lo de Arena (no toca llama-server reales)
```

Lanza tus `llama-server` como siempre: Arena los detecta solo (modelo, contexto, flags, GPU) y desde
**Calidad** se lanzan pruebas de estrés o de prompt libre con telemetría completa.

En Linux, los mismos scripts terminan en `.sh`.

### Por piezas

```bash
# Agente (cada equipo con GPUs). Solo escucha en localhost salvo que haya token.
python -m agent --port 9100 --models-dir D:/modelos
python -m agent --simulate nvidia2        # perfiles: nvidia2 | cpu-only | partial
ARENA_AGENT_TOKEN=... python -m agent --host 0.0.0.0   # fuera de localhost exige token

# Servidor (puerto 8090; 8080 lo usa llama-server)
python -m server --agent http://127.0.0.1:9100

# llama-server simulado (sin GPU), para desarrollar o probar
python -m server.fakes.fake_llama --port 18081 --tps 40

# Web en desarrollo con recarga en caliente (necesita el servidor en marcha)
npm run dev --prefix web

# Tests
pytest && npm test --prefix web
```

### Configuración del agente

Sin configuración, el agente funciona igual pero no lee GGUF. La configuración se busca, por este orden, en:
1. `--config <fichero>`.
2. La variable `ARENA_AGENT_CONFIG`.
3. `%APPDATA%\ArenaLLM\agent.json` en Windows, o `~/.config/arena-llm/agent.json` en Linux.

```json
{ "model_dirs": ["D:/modelos"], "llama_bench": "D:/dev-tools/llama.cpp/llama-bench.exe" }
```

## Datos

La base de datos vive en `data/` o en la ruta de `ARENA_DATA_DIR`. `data/` está excluida de git y de Syncthing, y los datos nunca se suben al repositorio.

## Documentación

- [`docs/HOJA-DE-RUTA.md`](docs/HOJA-DE-RUTA.md): decisiones y fases.
- [`docs/PLAN-CONSTRUCCION.md`](docs/PLAN-CONSTRUCCION.md): módulos, contrato entre agente y servidor, e hitos.
- [`docs/GUI-DISENO.md`](docs/GUI-DISENO.md): interfaz.
- [`docs/VIABILIDAD.md`](docs/VIABILIDAD.md): riesgos, métricas y datasets de pruebas.
