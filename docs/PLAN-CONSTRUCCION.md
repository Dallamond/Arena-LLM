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
# Arena LLM — Plan de construcción

> 03/10/2026 · Cómo se ejecuta la [[03 - PROYECTOS TEC/Arena LLM/docs/HOJA-DE-RUTA|HOJA-DE-RUTA]] v2. La hoja de ruta dice **qué** y en qué fases; este documento dice **cómo**: módulos, contratos de datos, orden de hitos y lo que ya se ha comprobado en el PC.
> Si este documento choca con la hoja de ruta, manda la hoja de ruta.

---

## 1. Comprobado en el PC el 03/10/2026 (adelanto de F0)

| Elemento | Resultado | Consecuencia |
|---|---|---|
| **RAM** | **16 GB** (2 × 8 GB Kingston Fury `KF3200C16D4/8GX`) **a 2400 MHz** | Se confirma el riesgo: 16 GB, no 32 GB. Además, los módulos son de 3200 MHz CL16 y van a 2400: **el XMP/DOCP está desactivado**. Activarlo en la BIOS da ~33 % más de ancho de banda de RAM (afecta a las pruebas CPU e híbridas) |
| GPU | RTX 3060 12 GB, índice 0, bus `08:00.0`, modo **WDDM** | Lo esperado. Por proceso, `--query-compute-apps` puede dar N/A (plan B de la hoja de ruta) |
| **Driver** | **591.74** | ⚠️ La rama **580 es la última que soporta Maxwell**. Con 591 la M40 probablemente no funcionará. Al llegar la M40 hay que instalar un driver R580 (sirve también para la 3060). Confirmar en F0 |
| Límites térmicos | `nvidia-smi -q` da *Slowdown* 95 °C, *Shutdown* 98 °C, *Target* 83 °C | Los umbrales derivados del dispositivo son viables. El driver habla de *Clocks Event Reasons* (nombre nuevo de *throttle reasons*): el descubrimiento de campos debe probar los dos nombres |
| Python | `py -3.14` (en `D:\python.exe`) y `py -3.12` (en `C:`). El comando `python` es el atajo de la Microsoft Store (no funciona) | Scripts con `py -3`, nunca `python`. Entorno del servidor con 3.12 (ruedas de FastAPI/pydantic seguras); el agente se prueba con 3.12 y 3.14 |
| Node | v24.14.0 (en `C:`) | Válido. Mover la caché de npm a `D:` (`npm config set cache D:\dev-tools\npm-cache`) |
| Disco | `C:` 5,8 GB libres · `D:` 399 GB libres | Todo en `D:` |
| llama.cpp | No está en el PATH ni en `D:\`, `E:\`, `F:\` (3 niveles) | Pendiente de Lucas: descargar la build CUDA 12.x |
| GGUF | `D:\ollama\models\` (Qwen 2.5 Coder 7B Q8_0 y 14B Q4_K_M) | Sirven para probar el lector de cabecera GGUF y el primer `llama-bench` |
| Git | `Arena LLM/` está dentro del repo del vault | Para tener **repo propio** hay que excluir la carpeta en el `.gitignore` del vault (decisión abajo) |

---

## 2. Decisiones de arranque (cerradas 03/10/2026)

1. **F0 parcial.** La M40 llega la semana del 05/10/2026. Se trabaja ya en F1 con perfiles simulados y la 3060; las tareas de F0 de la M40 (driver R580 incluido) se hacen cuando llegue.
2. **Repo propio.** `git init` (rama `main`) dentro de `Arena LLM/`; la carpeta se excluye en el `.gitignore` del vault. Los `docs/` siguen visibles en Obsidian.
3. **Remoto.** Se sube a **GitHub** (repo privado) a medida que avance.

---

## 3. Estructura del repositorio

```
Arena LLM/
├── agent/                    # solo biblioteca estándar
│   ├── __main__.py           # argparse: --host --port --token --simulate --config
│   ├── api.py                # ThreadingHTTPServer, rutas, token, JSON
│   ├── config.py             # fichero JSON local (rutas permitidas, carpeta GGUF, intervalo)
│   ├── model.py              # dataclasses del contrato (HostInfo, DeviceInfo, DeviceSample…)
│   ├── sampler.py            # hilo de muestreo a 1 Hz con caché del último valor
│   ├── providers/
│   │   ├── base.py           # interfaz TelemetryProvider
│   │   ├── nvidia.py         # nvidia-smi con descubrimiento de campos
│   │   ├── cpu_ram.py        # Windows (ctypes) / Linux (/proc)
│   │   └── null.py
│   ├── throttle.py           # decodificación de la máscara de clocks event reasons
│   ├── processes.py          # localizar llama-server y su línea de comandos
│   ├── cmdline.py            # parser tolerante de flags de llama-server
│   ├── gguf.py               # lector de cabecera GGUF + hash de cabecera
│   ├── bench.py              # (F6) llama-bench con lista cerrada
│   └── simulate/             # perfiles nvidia2 · cpu-only · partial
├── server/                   # FastAPI + httpx + sqlite3   (F2+)
│   ├── __main__.py · app.py · settings.py (ARENA_DATA_DIR)
│   ├── db/ (schema.sql + migraciones numeradas)
│   ├── agents.py             # cliente de agentes, sondeo 1 Hz, reconexión
│   ├── sse.py                # difusión de eventos en vivo
│   ├── detect.py             # /props /slots /health /v1/models + /servers del agente (F3)
│   ├── runner/ · suites/ · eval/ · sandbox/   (F4–F8)
│   └── fakes/fake_llama.py   # llama-server simulado (tests y desarrollo sin GPU)
├── web/                      # Vue 3 + Vite + TS (F2+)
├── tests/
│   ├── agent/ · server/
│   └── fixtures/             # CSV reales de nvidia-smi, JSON de /props de varias builds, GGUF mínimos
├── scripts/                  # start-agent.bat/.sh, start-server.bat/.sh, dev.bat/.sh
├── docs/ · README.md · ESTADO.md · pyproject.toml (config de pytest y ruff)
```

---

## 4. Contrato agente ↔ servidor (se fija en F1, versionado)

Toda respuesta lleva `agent_api: 1` y `agent_version`. Valores ausentes = `null`, nunca 0.

**`GET /info`** → ficha normalizada
```json
{
  "host": { "host_id": "…", "hostname": "…", "os": "windows|linux", "os_version": "…",
            "cpu_model": "…", "cpu_cores": 6, "cpu_threads": 12, "ram_total_mib": 16384 },
  "devices": [
    { "device_id": "nvidia:GPU-6607…", "provider": "nvidia", "kind": "gpu", "index": 0,
      "name": "…", "uuid": "…", "pci_bus_id": "…", "memory_total_mib": 12288,
      "power_limit_w": …, "power_limit_max_w": …, "temp_slowdown_c": 95, "temp_shutdown_c": 98,
      "driver": "591.74", "driver_model": "WDDM", "compute_capability": "8.6",
      "fields_unavailable": ["fan.speed"] },
    { "device_id": "cpu:<host_id>", "provider": "cpu", "kind": "cpu", "name": "…" }
  ]
}
```
- `host_id`: `MachineGuid` del registro (Windows, `winreg`) o `/etc/machine-id` (Linux). Estable entre reinicios.
- `device_id` = proveedor + identificador estable (UUID en GPU). Es la clave para el color por dispositivo y los umbrales.

**`GET /metrics`** → último muestreo en caché (no lanza `nvidia-smi` por petición)
```json
{ "t": 1759512345.12, "interval_s": 1.0,
  "devices": { "nvidia:GPU-…": { "temp_c": 62, "power_w": 118.4, "util_gpu_pct": 97, "util_mem_pct": 54,
                "mem_used_mib": 8291, "clock_sm_mhz": 1777, "clock_mem_mhz": 7300, "fan_pct": null,
                "pstate": "P2", "throttle_mask": 0, "throttle": [], "pcie_gen": 3, "pcie_width": 16 },
               "cpu:…": { "util_pct": 12.3, "freq_mhz": null } },
  "ram": { "used_mib": 12083, "total_mib": 16384 } }
```

**`GET /servers`** → procesos `llama-server` con `pid`, `cmdline` cruda, `flags` parseados (`model`, `ngl`, `ctx`, `ts`, `parallel`, `fa`, `batch`, `ubatch`, `cache_type_k/v`, `threads`, `port`, `host`, `override_tensor`…, más `unknown: []`), `port` deducido y GPU asociada si se puede (`gpu_link: "compute-apps" | "vram-delta" | "manual" | null`).

**`GET /gguf?path=`** → solo rutas dentro de las carpetas permitidas: arquitectura, capas, cabezas, `n_embd`, contexto de entrenamiento, tipo de cuantización, tamaño, `header_sha256`.

**Seguridad:** escucha en `127.0.0.1`; si `--host` no es localhost, arranca solo con `--token` (cabecera `X-Token`, comparación en tiempo constante).

---

## 5. Decisiones técnicas internas (por defecto, sin necesidad de preguntar)

- **Muestreo:** un hilo del agente lanza `nvidia-smi --query-gpu=… --format=csv,noheader,nounits` cada intervalo y guarda el resultado; `/metrics` devuelve la caché. Si el coste en Windows molesta, pasar a `nvidia-smi -lms` (un proceso vivo). NVML por `ctypes` queda como mejora opcional (sigue siendo stdlib).
- **Descubrimiento de campos NVIDIA:** al arrancar se prueba la lista completa; si `nvidia-smi` rechaza un campo, se quita y se reintenta (bisección). Alias por campo: `clocks_event_reasons.active` → `clocks_throttle_reasons.active`. La lista de campos válidos se guarda en `/info` (`fields_unavailable`).
- **Temperaturas límite:** de `nvidia-smi -q -d TEMPERATURE` (parseo tolerante). Si no hay, valores por defecto por proveedor. Umbral por defecto = *slowdown* − 10 °C aviso / *slowdown* − 5 °C aborto (editable; la M40 de Lucas se fija en 80/85 en Ajustes, no en código).
- **CPU/RAM sin dependencias:** Windows → `GetSystemTimes` y `GlobalMemoryStatusEx` vía `ctypes`; Linux → `/proc/stat` y `/proc/meminfo`.
- **Procesos:** Windows → `powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like 'llama-server%'\" | Select ProcessId,CommandLine | ConvertTo-Json"`; Linux → `/proc/*/cmdline`. Parser de flags tolerante con alias cortos/largos y flags desconocidos guardados tal cual.
- **GGUF:** leer solo la cabecera (magic, versión, metadatos KV, info de tensores) sin tocar los pesos; `header_sha256` sobre esos bytes. SHA-256 completo en segundo plano (F3).
- **Simulación:** los perfiles sustituyen proveedores, procesos y GGUF por versiones falsas deterministas (series de temperatura/potencia con ruido con semilla). `partial` = GPU sin ventilador, sin *throttle reasons* y sin límite de potencia. Los tests de contrato se parametrizan con los tres perfiles.
- **Base de datos (F2+):** `sqlite3` con WAL, migraciones numeradas en `server/db/`, ruta `ARENA_DATA_DIR` (por defecto `data/`). Tablas de la hoja de ruta §7.
- **Fixtures reales:** guardar en `tests/fixtures/` salidas reales de `nvidia-smi` de este PC (y de la M40 cuando llegue) para que los tests reproduzcan drivers reales sin hardware.

---

## 6. F1 — hitos y commits

| # | Commit | Contenido | Test que lo cierra |
|---|---|---|---|
| 1 | `chore: esqueleto del repositorio` | estructura, `pyproject.toml`, scripts `.bat/.sh`, `README`, `ESTADO.md`, venv en `.venv` con `pytest` | `pytest` corre (0 tests) en Windows |
| 2 | `feat: contrato del agente y servidor HTTP` | `model.py`, `api.py`, `/health`, proveedor nulo, token | tests de rutas, token y localhost |
| 3 | `feat: proveedor CPU/RAM` | Windows + Linux | parseo de `/proc` con fixtures; prueba real en Windows |
| 4 | `feat: proveedor NVIDIA` | descubrimiento de campos, alias, N/A → `null`, límites térmicos, decodificación de la máscara | fixtures CSV (incluido un campo rechazado), tests de la máscara |
| 5 | `feat: perfiles de hardware simulados` | `nvidia2`, `cpu-only`, `partial` | tests de contrato × 3 perfiles |
| 6 | `feat: detección de llama-server` | `processes.py` + `cmdline.py`, `/servers` | parser con líneas de comandos reales y raras |
| 7 | `feat: lector de cabecera GGUF` | `/gguf`, rutas permitidas | GGUF mínimo generado en el test + prueba manual con los Qwen de `D:\ollama\models` |
| 8 | `chore: cierre de F1` | verificación en el PC real, `ESTADO.md`, criterios marcados, línea en `log.md` | criterio de la hoja de ruta |

**Criterio de F1 (de la hoja de ruta):** en el PC real devuelve todas las GPUs presentes y detecta un `llama-server` en marcha con su línea de comandos; con cada perfil simulado la API devuelve datos coherentes y la suite pasa. → El paso 6 necesita llama.cpp instalado (pendiente de Lucas).

---

## 7. Vista rápida de las fases siguientes

| Fase | Primer paso técnico | Depende de |
|---|---|---|
| F2 GUI base | `server/` mínimo (FastAPI, registro de un agente, sondeo 1 Hz → SSE) + Vite con tokens, `BlueprintCard`, `GpuCard`, franja del equipo | F1 |
| F3 Detección | `fake_llama.py` con `/props` de varias builds; `detect.py`; tabla `config_changes`. **Calculadora de KV:** no suponer KV en todas las capas — hay modelos híbridos (p. ej. `qwen35`: capas SSM + atención completa cada `full_attention_interval`), `head_count_kv` puede ser un array por capa y `key_length`/`value_length` pueden faltar (usar `embedding_length / head_count`). Los `mmproj` (`general.type = mmproj`) no son modelos | F2 + llama.cpp real |
| F4 Runner | streaming SSE de `/v1/chat/completions`, TTFT/t/s cliente y `timings` | F3 |
| F5 Telemetría en runs | `samples`/`tps_series`, resumen (energía trapezoidal, degradación), aborto térmico | F4 |
| F6 llama-bench | `agent/bench.py` con lista cerrada de flags, `-o json` | F1 + llama.cpp real |
| F7–F9 | calidad, batalla, comparación (según hoja de ruta) | anteriores |

F6 solo depende del agente: si conviene para vídeo, se puede adelantar tras F3 (lo decide Lucas).

---

## 8. Tareas de Lucas (actualizadas)

- [ ] **Activar XMP/DOCP** en la BIOS (RAM a 3200 MHz) y confirmar con `Get-CimInstance Win32_PhysicalMemory`.
- [ ] Descargar llama.cpp (build Windows **CUDA 12.x**) a `D:\dev-tools\llama.cpp\` y decir la ruta.
- [ ] Cuando llegue la M40: instalar **driver R580** antes de nada (el actual 591.74 probablemente no la soporta).
- [ ] Carpeta definitiva de GGUF (¿`D:\ollama\models` o una nueva?).
- [ ] Modelos para la primera tabla. Con 16 GB de RAM y 36 GB de VRAM: 8B, 14B, ~32B Q4, 70B Q3 (muy justo, sin RAM de sobra) y un MoE mediano.
- [ ] Crear el repo privado en GitHub y conectarlo (ver `README` cuando exista).
