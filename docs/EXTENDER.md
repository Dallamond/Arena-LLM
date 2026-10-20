# Cómo ampliar Arena LLM

Cuatro extensiones habituales, de la más frecuente a la menos: **añadir un servidor (endpoint)**, **añadir un equipo**, **añadir una GPU de otro fabricante** y **añadir una prueba**. Para todas rige el principio rector: nada de nombres de GPU, puertos, rutas ni umbrales escritos en el código; se detecta o se configura.

---

## 1. Añadir un servidor (endpoint)

Un *endpoint* es un `llama-server` (API compatible con OpenAI) al que Arena puede lanzar pruebas.

### Si el agente lo ve (lo normal)
Basta con lanzar `llama-server` en un equipo con agente. En unos 5 segundos aparece en **Servidores → En marcha** con su configuración (`/props`, `/slots`, línea de comandos del proceso y cabecera del GGUF). Lo mismo si lo lanza Arena desde **Servidores → GGUF en disco**.

### Si el agente no lo ve (otro equipo sin agente, contenedor, `--api-key`…)
1. **Servidores → ＋ Añadir a mano**.
2. Elige el equipo, escribe la URL (`http://host:puerto`), un alias opcional y, si quieres, las GPU que usa.
3. Arena lo sondea en cada ciclo. Como no ve el proceso, no hay línea de comandos ni flags: contexto, slots, modelo y build salen de la API del servidor, y lo que no responda queda como «sin datos».

Por API: `POST /api/endpoints` con `{"host_id": 1, "base_url": "http://127.0.0.1:8080", "alias": "mi-servidor", "device_ids": ["nvidia:GPU-…"]}`.

Los servidores detectados que se paran desaparecen de la lista; los manuales se quedan hasta que pulsas **Quitar**. Arena solo para los que lanzó ella.

---

## 2. Añadir un equipo (agente)

1. En el equipo nuevo, instala Python 3.11+ y copia la carpeta `agent/` (solo usa la biblioteca estándar; no hay `pip install`).
2. Crea su configuración (`%APPDATA%\ArenaLLM\agent.json` en Windows, `~/.config/arena-llm/agent.json` en Linux, o `--config` / `ARENA_AGENT_CONFIG`):
   ```json
   { "model_dirs": ["/modelos"], "llama_bench": "/opt/llama.cpp/llama-bench", "llama_server": "/opt/llama.cpp/llama-server" }
   ```
3. Arráncalo. Fuera de localhost **exige token**:
   ```bash
   ARENA_AGENT_TOKEN=un-token-largo python -m agent --host 0.0.0.0 --port 9100
   ```
4. En el servidor Arena: **Ajustes → Equipos → Añadir equipo** con la URL del agente (`http://IP:9100`) y el token. También `POST /api/hosts` o `python -m server --agent <url>`.

El agente no es una shell remota: solo ejecuta `llama-bench` y `llama-server` de su configuración, con flags de una lista cerrada y modelos dentro de `model_dirs`.

---

## 3. Añadir una GPU de otro fabricante (AMD, Intel, Apple…)

La telemetría es un **proveedor enchufable**; el resto del agente solo habla con la interfaz `TelemetryProvider` (`agent/providers/base.py`). Añadir un fabricante **no debe tocar nada fuera de `providers/`**, salvo los dos puntos de «Extras» más abajo.

### Pasos
1. **Crea `agent/providers/<fabricante>.py`** con una clase que herede de `TelemetryProvider`:
   - `name`: prefijo corto y estable (`"amd"`); formará el `device_id` (`"amd:<id estable>"`).
   - `available()` (classmethod): ¿existe la herramienta o el SO es compatible? Sin efectos secundarios.
   - `devices() -> list[DeviceInfo]`: la ficha de cada GPU, una vez al arrancar (nombre, `index`, `uuid`, memoria total, límites de potencia, driver…). `kind="gpu"`.
   - `sample() -> dict[device_id, GpuSample]`: lectura actual, **rápida** (se llama cada intervalo).
   - Opcional: `processes()` (qué pid usa qué GPU, para asociar un `llama-server` a su tarjeta) y `ram()` (solo si mide la memoria del sistema; hoy lo hace el proveedor CPU/RAM).
2. **Regístrala** añadiendo la clase a `GPU_PROVIDERS` en `agent/providers/__init__.py`. Si no hay ningún proveedor disponible se usa `NullProvider` y el equipo funciona igual.
3. **Reglas del contrato** (`agent/model.py`):
   - Un valor que el equipo no expone es **`None`** (JSON `null`), nunca 0. La GUI lo muestra como «sin datos».
   - Anota en `DeviceInfo.fields_unavailable` los campos que el driver rechazó.
   - Cambiar un campo de forma incompatible exige subir `AGENT_API`.
4. **Pruebas**: copia el patrón de `tests/agent/test_nvidia.py`: una función que ejecuta la herramienta del fabricante (inyectable), con salidas reales guardadas en `tests/fixtures/<fabricante>/` y casos de campos `N/A`. Prueba también que el proveedor nulo y los otros perfiles simulados (`nvidia2`, `cpu-only`, `partial` en `agent/simulate/`) siguen funcionando.
5. **Comprueba en la GUI** con un equipo real (o con un perfil simulado nuevo en `agent/simulate/__init__.py` si no tienes la tarjeta): tarjeta de la GPU, color por dispositivo, gráficas, umbrales.

### Extras que dependen del fabricante
- **Lanzar y medir con `llama.cpp`**: `server/launch.py` traduce cada proveedor al nombre de dispositivo de llama.cpp con `BACKEND_PREFIX = {"nvidia": "CUDA"}`. Añade ahí tu prefijo (`"Vulkan"`, `"ROCm"`, `"SYCL"`, `"Metal"`…) para que el comando propuesto y el lanzador pasen `-dev`/`-ts`. Sin él, Arena detecta y mide la GPU pero deja el reparto en automático y lo avisa. Ten en cuenta que el orden de dispositivos de llama.cpp debe coincidir con el `index` que guarda tu proveedor (en NVIDIA se fija con `CUDA_DEVICE_ORDER=PCI_BUS_ID`, que también fijan `agent/launcher.py` y `agent/bench.py`: revisa ambos si tu backend necesita otra variable).
- **Umbrales térmicos**: los valores por defecto por proveedor están en `server/thresholds.py` (`PROVIDER_DEFAULTS`) y se repiten en `web/src/lib/thresholds.ts`. Mantén ambos iguales. Sin entrada se usa el genérico (aviso 80 °C, aborto 85 °C) y cada usuario puede ajustarlos en **Ajustes → Umbrales**, que es el sitio correcto para valores específicos de una tarjeta.
- **Potencia y energía**: si tu proveedor solo da potencia de placa, deja que la GUI la marque `ESTIMADO`; no la presentes como medida de la toma.

---

## 4. Añadir una prueba (suite)

Las pruebas viven en `server/runs/suites.py`, en el diccionario `SUITES`. Cada una es un `Suite` con **versión y hash de contenido**: el hash cubre prompts, semilla, muestreo y opciones propias, y es lo que permite al comparador decir «No comparables» cuando algo cambia.

1. **Define la suite**: `id`, `name`, `version`, `mode` (`"items"` lista de prompts, `"duration"` bucle durante X s, `"concurrency"` niveles de paralelismo), `description` y `defaults`. Los valores comunes (temperatura 0, semilla 42, `cache_prompt` desactivado) vienen de `COMMON_DEFAULTS`; no los cambies por suite sin motivo.
2. **Con corrección automática**: pon `graded=True` y una función `cases(params) -> list[Case]`. Cada `Case` lleva el prompt y un `spec` (`kind`, esperado/tests/nivel…) que consume el corrector (`server/quality/grading.py`). Los datos (preguntas, problemas, generadores) van en `server/quality/datasets.py`.
3. **Formulario de la GUI**: declara `fields` (`key`, `label`, `type`: `number`, `choices`, `pairs`…, `help`). La GUI lo dibuja sola (`SuiteForm.vue`); no hace falta tocar la web.
4. **Si añades una opción propia que cambia el resultado**, añade su clave a `SUITE_PARAM_KEYS` para que entre en el hash.
5. **Versión**: cambiar prompts, semillas o valores por defecto de una suite exige **subir `version`**. Nunca edites una suite publicada sin subirla: los runs antiguos dejarían de ser reproducibles.
6. **Código generado por modelos**: se ejecuta **siempre** en el sandbox (`server/quality/sandbox.py`: subproceso, timeout, sin stdin, directorio temporal, sin red). Nunca `exec()` en el servidor.
7. **Resumen**: si la suite produce métricas propias, añádelas en `server/quality/summary.py` y, si quieres compararlas, en `METRICS`/`run_metrics` de `server/compare.py`.
8. **Pruebas**: un test en `tests/server/` con el `llama-server` simulado (`server/fakes/fake_llama.py`), como `test_quality_runs.py`.

### Pruebas de rendimiento (`llama-bench`)
Son otra familia (`server/runs/bench.py`, `BENCH_SUITES`): el agente lanza `llama-bench` y Arena guarda sus filas. Siguen la misma regla de versión y hash.

---

## Antes de abrir un commit

```bash
ruff check .
pytest -q -p no:warnings
npm run typecheck --prefix web
npm test --prefix web
```

Un commit por hito, en español (`feat:`, `fix:`, `docs:`). Al cerrar una fase: actualiza `ESTADO.md`, marca los criterios en `docs/HOJA-DE-RUTA.md` y añade una línea a `log.md` del vault.
