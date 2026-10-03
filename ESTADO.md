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

> Leer al retomar. Última actualización: 03/10/2026 (noche).

## Resumen

| Fase | Estado |
|---|---|
| F0 — Preparación del PC | Parcial: falta XMP y la M40 (llega la semana del 05/10) |
| F1 — Esqueleto y agente | ✅ Cerrada (detecta el llama-server real) |
| F2 — GUI base | ✅ (Ajustes con subnavegación hecho en esta sesión) |
| F3 — Servidores y detección | Casi: falta alta manual de endpoints y la **calculadora de encaje de GGUF** |
| F4 — Runner | ✅ Criterio cumplido: 33,6 t/s Arena frente a 34,5 t/s llama-bench (−2,7 %) |
| F5 — Telemetría, resumen y estrés | ✅ salvo la prueba real de 5 min (hecha de 60 s) |
| Siguiente | Opinión de Lucas tras probar → F3 (calculadora) → F6 (llama-bench por componente) |

## Primera prueba real (03/10/2026, 21:01)

RTX 3060 · llama.cpp **b11379** (CUDA 12.4) en `D:\dev-tools\llama.cpp\b11379\` · Qwen2.5-Coder 7B Instruct **Q8_0** · `-ngl 99 -c 8192 -np 2 -fa on` · driver 591.74 WDDM.

| Métrica | Valor |
|---|---|
| Generación (mediana, estrés 60 s, 1 petición en paralelo) | **33,6 t/s** (cliente = timings del servidor) |
| llama-bench tg128 / pp512 | 34,5 ± 0,7 / **162 ± 49 t/s** |
| TTFT mediana | 0,39 s |
| Temperatura reposo → máx | 46 → 71 °C |
| Potencia media / máx (placa) | 134 / 162 W (límite 170 W) |
| Throttling | 22 % del tiempo, **todo por límite de potencia** (`sw_power_cap`) |
| Energía | 2,30 Wh → **779 tokens/Wh** |
| VRAM pico | 9,2 GiB |

**Hallazgos que conviene investigar** (anotados, no resueltos):
- **Procesado de prompt muy bajo**: 162 t/s en pp512, cuando en esta GPU lo normal son miles, y con mucha variación. Posibles causas: PCIe, WDDM, la GPU también mueve la pantalla u otro proceso. Lo indicado es medirlo con F6 (llama-bench por componente).
- **RAM al límite**: durante la prueba estaban en uso 15,4 de 15,9 GiB. Con 16 GB, el modelo mapeado y el resto de programas no queda margen; activar el XMP no lo arregla, solo da ancho de banda.
- **Carga lenta del modelo**: unos 100 s para 8 GB desde `D:`, que parece un disco lento.

## Cómo probar

```bat
scripts\setup.bat                  :: .venv con dependencias (una vez)
scripts\build-web.bat              :: compila la web (una vez y tras cambios en web/)
scripts\demo.bat D:\ollama\models  :: agente real, agente simulado con 2 llama-server simulados y servidor
scripts\stop.bat                   :: para todo lo de Arena (no toca llama-server reales)
```

Para un servidor real, lanza `llama-server` como siempre; Arena lo detecta en unos 5 s. Ejemplo usado:

```bat
D:\dev-tools\llama.cpp\b11379\llama-server.exe -m D:\ollama\models\Qwen\qwen2.5-coder-7b-instruct-q8_0.gguf -ngl 99 -c 8192 -np 2 -fa on --port 8081
```

Después: **Calidad** → elegir servidor → Lanzar estrés o prompt libre.

## Qué hay

- **Agente:** telemetría NVIDIA y de CPU/RAM, detección de `llama-server`, cabeceras GGUF y tres perfiles simulados.
- **Servidor (puerto 8090):**
  - Sondea los agentes cada segundo y emite eventos en vivo por SSE.
  - Detecta los servidores cada 5 s (`/health`, `/props`, `/slots`, `/v1/models`) y registra los cambios de configuración.
  - Runner con streaming y suites "libre" y "estrés" (con versión y hash).
  - Fases reposo → carga → enfriamiento, resumen y aborto térmico por dispositivo.
- **Web:**
  - Panel y Servidores.
  - Calidad: lanzar pruebas.
  - Vista de run en vivo con gráficas y resultado completo.
  - Historial básico.
  - Ajustes: apariencia (acento, contraste, tamaño, rejilla, croquis), equipos, umbrales y datos.
- **Tests:** 129 de Python (incluye un laboratorio completo sin GPU: llama-server simulado + agente simulado + servidor) y 10 de la web.

## Pendiente (orden propuesto)

1. Opinión de Lucas sobre la GUI de pruebas.
2. F3:
   - Calculadora de encaje de GGUF. Atención a los modelos híbridos (`qwen35`) y a los arrays de cabezas KV por capa.
   - Alta manual de endpoints.
   - Asociar GPU por aumento de VRAM cuando `compute-apps` no la dé.
3. F6: `llama-bench` desde el agente, por componente. Servirá para investigar el procesado de prompt lento.
4. F5: prueba real de 5 min y prueba de la M40 cuando llegue (driver R580).

## Entorno y avisos

- `.venv` usa Python 3.12. El comando `python` de Windows es el atajo de la Store.
- ⚠️ `py -3` apunta a un Python 3.14 huérfano (`HKCU\Software\Python\PythonCore\3.14` → `D:\python.exe`, que no existe). Los scripts usan `.venv`.
- npm: caché en `D:\dev-tools\npm-cache` (vía `npm_config_cache`). TypeScript fijado en 5.9 por precaución con `vue-tsc`.
- Los perfiles simulados usan los puertos 18081/18082 para no chocar con servidores reales.
- Remoto: https://github.com/Dallamond/Arena-LLM (privado).

## Aprendido

- `/props` da `n_ctx` **por slot**, junto con `build_info` y `model_ftype`. `/health` devuelve 503 "Loading model" mientras carga.
- Los `timings` y el `usage` llegan en el último chunk si se pide `stream_options.include_usage`.
- Los modelos híbridos (`qwen35`) solo tienen KV en algunas capas (`full_attention_interval`). Los `mmproj` no son modelos.
- Un servidor se identifica por equipo + URL: dos equipos pueden usar el mismo puerto local.
- PowerShell CIM tarda unos 0,5 s (cacheado 2 s) y `nvidia-smi` unos 60 ms por muestra.
- Datos curiosos de PowerShell 5.1:
  - `ConvertFrom-Json` con un array muestra filas vacías al pasarlo a `Select-Object`.
  - curl en Git Bash rompe el UTF-8 del cuerpo de la petición; para eso usar Python/httpx.
