# Arena LLM

Banco de pruebas **independiente del hardware** para modelos de IA locales (llama.cpp). Una web local para **medir, enfrentar y comparar modelos** en cualquier equipo y tarjeta, con la telemetría del equipo (cada GPU, CPU y RAM) siempre a la vista.

![Panel de Arena LLM: dos GPU, CPU y RAM en vivo, con medidores y aviso de throttling](docs/img/panel.png)

> Estado: fases F1–F5 (telemetría, detección de servidores, calculadora de encaje, pruebas de estrés y prompt libre). Ver [`ESTADO.md`](ESTADO.md) y [`docs/HOJA-DE-RUTA.md`](docs/HOJA-DE-RUTA.md).
>
> Todas las capturas están hechas con el **modo simulado** (perfiles `nvidia2` y `cpu-only`, `llama-server` simulados y GGUF falsos): no hay datos ni rutas reales.

## Qué hace

1. **Muestra siempre el estado del equipo** (cada GPU, CPU y RAM) para ver de un vistazo que no pasa nada raro.
2. **Detecta solo** qué modelo, contexto y flags tiene cada `llama-server` y lo guarda con cada prueba.
3. **Prueba y compara**: estrés, prompt libre y, en próximas fases, rendimiento por componente, calidad, batallas A contra B y comparación de resultados.

## Funcionalidades

### Telemetría en vivo

Temperatura, potencia, VRAM, uso, relojes, ventilador, estado P y throttling de cada GPU, más CPU y RAM, cada segundo por SSE. Cada tarjeta conserva su color en toda la interfaz y los avisos salen de los umbrales de cada dispositivo.

![Panel en vivo: las GPU pasan de reposo a carga y suben temperatura, potencia y uso](docs/img/panel-telemetria.gif)

<sub>Acelerado ×2.</sub>

### Detección de servidores

Arena detecta los `llama-server` que lanzas tú (proceso, `/props`, `/slots`, `/v1/models`): modelo, cuantización, contexto por slot, flags y en qué GPU corre. Cada 5 s vuelve a mirar y registra cualquier cambio de configuración con su diff.

![Un servidor se cae, vuelve a cargar con otro contexto y Arena anota el cambio](docs/img/deteccion-servidores.gif)

<sub>Acelerado ×1,5. El servidor se para ("sin respuesta"), vuelve a arrancar con otro contexto y el cambio queda registrado con su diff.</sub>

También se pueden **dar de alta endpoints a mano** (por ejemplo, un servidor que el agente no ve como proceso) y **asignar GPU a mano** cuando la detección no puede.

### Calculadora de encaje de GGUF

Pestaña **GGUF en disco**: lee la cabecera de cada GGUF de las carpetas permitidas y estima pesos por capa, caché KV, búfer de cómputo y reserva por GPU. El veredicto se compara con la VRAM y la RAM **libres ahora**: cabe en una GPU, cabe repartido, necesita RAM (con el `-ngl` sugerido), solo CPU o no cabe. Todo lleva el sello `ESTIMADO`.

![Cambiar contexto, slots y caché KV recalcula al momento el encaje de cada modelo](docs/img/calculadora-gguf.gif)

### Prueba de estrés

Peticiones largas en bucle durante el tiempo elegido, con fases de reposo, carga y enfriamiento. Gráficas de t/s, temperatura, potencia de placa y reloj sincronizadas, y aborto automático si una GPU llega a su umbral crítico.

![Run de estrés en marcha: velocidad, temperatura, potencia y reloj en vivo](docs/img/estres-en-vivo.gif)

<sub>Acelerado ×4.</sub>

Al terminar queda el resultado completo: resumen (mediana de t/s, TTFT, degradación, energía y tokens por Wh, throttling), la **foto de configuración** guardada con el run (servidor, flags, modelo y parámetros) y cada petición.

![Resultado de un run de estrés con resumen, gráficas, configuración guardada y peticiones](docs/img/resultado-run.png)

### Prompt libre en streaming

Uno o varios prompts propios con repeticiones. La respuesta llega en streaming y se miden TTFT, t/s del cliente y del servidor y tokens.

![Se escribe un prompt, se lanza y la respuesta llega en streaming con sus métricas](docs/img/prompt-libre-streaming.gif)

### Historial

Todos los runs guardados, con su servidor, modelo, suite (versión y hash) y métricas principales.
### Ajustes

Apariencia (color de acento, contraste, tamaño de la interfaz, rejilla y efecto croquis), equipos, umbrales térmicos por dispositivo y datos.

![Ajustes de apariencia](docs/img/ajustes-apariencia.png)
## Principios

- **Independiente del hardware.** Nada cableado: ni nombres de GPU, ni puertos, ni rutas, ni VRAM, ni umbrales. Todo se autodetecta o se configura. Los proveedores de telemetría son enchufables (v1: NVIDIA y CPU/RAM; un equipo solo con CPU también funciona).
- **Detecta, no controla.** Tú lanzas `llama-server` como siempre; Arena lo detecta y guarda su configuración. Arrancar y parar servidores está en el backlog.
- **No inventa datos.** Lo que no se puede medir sale como "sin datos", nunca como 0. Las estimaciones (encaje, potencia de placa…) llevan el sello `ESTIMADO`.
- **Reproducible y comparable.** Cada prueba tiene versión y hash; el perfil estándar fija semilla, temperatura 0 y `cache_prompt` desactivado; cada run guarda su foto de configuración completa.

## Componentes

| Carpeta | Qué es | Requisitos |
|---|---|---|
| `agent/` | Agente por equipo: telemetría (GPU, CPU, RAM), detección de `llama-server`, cabeceras GGUF y `llama-bench` | Python 3.11+, **solo biblioteca estándar** |
| `server/` | API, sondeo de agentes, eventos en vivo (SSE), runner de pruebas y base de datos SQLite | Python 3.11+, FastAPI, uvicorn, httpx |
| `web/` | Interfaz en Vue 3 + Vite + TypeScript, con gráficas propias en SVG | Node 20+ |

## Puesta en marcha (Windows)

```bat
scripts\setup.bat                  :: crea .venv (Python 3.12) con las dependencias
scripts\build-web.bat              :: compila la web en web\dist
scripts\demo.bat D:\mis\modelos    :: agente real + agente simulado (con 2 llama-server simulados) + servidor
scripts\stop.bat                   :: para todo lo de Arena (no toca llama-server reales)
```

Abre `http://127.0.0.1:8090`. Lanza tus `llama-server` como siempre: Arena los detecta solo (modelo, contexto, flags, GPU) y desde **Calidad** se lanzan pruebas de estrés o de prompt libre con telemetría completa.

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

## Estado por fases

| Fase | Qué | Estado |
|---|---|---|
| F1 | Esqueleto y agente (telemetría, detección, perfiles simulados) | ✅ |
| F2 | GUI base y plano del equipo | ✅ |
| F3 | Servidores, modelos y detección (calculadora de encaje, alta manual) | Casi: falta un criterio con un servidor real |
| F4 | Runner núcleo (prompt libre) | ✅ |
| F5 | Telemetría sincronizada, resumen y estrés | ✅ salvo la prueba real de 5 min |
| F6 | Rendimiento por componente (`llama-bench`) | Siguiente |
| F7 | Pruebas de calidad (razonamiento, código aislado, contexto largo, concurrencia) | Pendiente |
| F8 | Batalla: el mismo prompt en dos o más lados | Pendiente |
| F9 | Historial, comparación (insignia de comparabilidad) y exportación | Pendiente |
| F10–F12 | Modo vídeo, despliegue en Linux y backlog | Pendiente |

## Datos

La base de datos vive en `data/` o en la ruta de `ARENA_DATA_DIR`. `data/` está excluida de git y de Syncthing, y los datos nunca se suben al repositorio.

## Documentación

- [`docs/HOJA-DE-RUTA.md`](docs/HOJA-DE-RUTA.md): decisiones y fases.
- [`docs/PLAN-CONSTRUCCION.md`](docs/PLAN-CONSTRUCCION.md): módulos, contrato entre agente y servidor, e hitos.
- [`docs/GUI-DISENO.md`](docs/GUI-DISENO.md): interfaz.
- [`docs/VIABILIDAD.md`](docs/VIABILIDAD.md): riesgos, métricas y datasets de pruebas.
