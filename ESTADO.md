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

> Leer al retomar. Última actualización: 03/10/2026 (noche, 2.ª sesión).

## Resumen

| Fase | Estado |
|---|---|
| F0 — Preparación del PC | Parcial: falta XMP y la M40 (llega la semana del 05/10) |
| F1 — Esqueleto y agente | ✅ Cerrada (detecta el llama-server real) |
| F2 — GUI base | ✅ + pulido visual tras la opinión de Lucas (sin `FIG.`, títulos destacados, datos en mono) |
| F3 — Servidores y detección | Casi: ✅ calculadora y alta manual; falta comprobar el criterio relanzando un llama-server real con otro `-c` |
| F4 — Runner | ✅ Criterio cumplido: 33,6 t/s Arena frente a 34,5 t/s llama-bench (−2,7 %) |
| F5 — Telemetría, resumen y estrés | ✅ salvo la prueba real de 5 min (hecha de 60 s) |
| Siguiente | Lucas revisa la GUI (pulido, GGUF, alta manual) y relanza su llama-server con otro `-c` (criterio F3) → F6 (llama-bench por componente) |

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
- **Tests:** 155 de Python (incluye un laboratorio completo sin GPU y la calculadora de encaje) y 10 de la web.

## Calculadora de encaje (03/10/2026)

Servidores → pestaña **GGUF en disco**. Para cada GGUF: pesos reales por capa (offsets de los tensores), KV de las capas de atención (en `qwen35` solo 8 de 32), estado recurrente F32 por slot, búfer de cómputo y reserva de 512 MiB por GPU. Veredicto frente a la VRAM y RAM **libres ahora**: cabe en X · cabe repartido · necesita X GiB de RAM (con `-ngl` sugerido) · solo CPU · no cabe. Todo con el sello ESTIMADO.

Con c=8192 en la 3060 (11,6 GiB libres) caben los tres modelos. El 7B Q8 estima 8,3 GiB frente a 9,2 GiB de pico medido (que incluye el escritorio). El 14B Q4_K_M a 32K necesitaría unos 4,2 GiB de RAM con `-ngl 38`.

Limitaciones: ventana deslizante (cota superior), MoE sin `--cpu-moe` y búfer de cómputo aproximado (supone flash attention).

## Alta manual de endpoints (03/10/2026)

Servidores → **＋ Añadir a mano**: equipo (de él sale la telemetría), URL, alias y GPU opcionales. La URL se normaliza (`localhost` → `127.0.0.1`, sin `/v1`) para que coincida con la detectada. Se sondea cada 5 s aunque el agente no vea el proceso y no se borra al parar: queda "sin respuesta". Si además se detecta como proceso, se fusiona (conserva pid y flags). Cualquier servidor admite **GPU a mano** (mandan sobre la detección y cuentan como cambio de configuración). Se pueden quitar los manuales y los detenidos. BD: migración 4 (`manual`, `device_ids`).

## Pendiente (orden propuesto)

1. Lucas revisa el pulido visual (sin `FIG.`, títulos y rótulos en Inter seminegrita, datos vivos en mono más clara) y la pestaña GGUF. No se pudo revisar con capturas: la extensión de Chrome no estaba conectada.
2. F3:
   - Criterio: relanzar el llama-server real con otro `-c` y ver el cambio en menos de 10 s.
   - Opcional: asociar GPU por aumento de VRAM cuando `compute-apps` no la dé (de momento se asigna a mano desde la tarjeta del servidor).
3. F6: `llama-bench` desde el agente, por componente. Servirá para investigar el procesado de prompt lento.
4. F5: prueba real de 5 min y prueba de la M40 cuando llegue (driver R580).

## README con capturas (03/10/2026)

En `docs/img/` hay capturas y GIF hechos en modo simulado con Playwright: `panel.png`, `panel-telemetria.gif`, `deteccion-servidores.gif`, `calculadora-gguf.gif`, `estres-en-vivo.gif`, `resultado-run.png`, `prompt-libre-streaming.gif` y `ajustes-apariencia.png`.

**Pendiente para mañana:**
- Capturas estáticas de **Servidores** (`servidores.png`, con la cabecera de la página visible) e **Historial** (`historial.png`), y añadirlas al README en sus secciones. El primer intento salió mal: en Servidores el desplazamiento cortaba la cabecera, y en Historial a 1280 px se veía el fallo de abajo.
- Repetir `panel.png` con la página abierta 2 min antes, para que las minigráficas "2 MIN" salgan llenas.
- Herramientas ya instaladas en `D:\dev-tools\`: `readme-tools\` (venv con Playwright, Pillow y httpx) y `ms-playwright\` (Chromium; usar `PLAYWRIGHT_BROWSERS_PATH=D:\dev-tools\ms-playwright`). Los scripts de captura están en `D:\dev-tools\readme-tools\capturas\`: `e_static.py` hace justo lo pendiente. Esperan los datos en `D:\dev-tools\arena-readme-tmp\`, que se borró, así que hay que recrear esa carpeta. Usan el servidor en 8190, agentes simulados en 9201/9202 vía `sim_agent.py` (desplaza los llama simulados a 18181/18182) y GGUF falsos de `make_gguf.py` montados con `subst M:`.

Detalles visuales vistos al capturar (sin arreglar):
- Calculadora GGUF: los veredictos usan punto decimal ("Necesita 9.2 GiB de RAM") y el resto coma ("9,7 GiB"). El rótulo y el campo "Slots (-np)" quedan más altos que los de contexto y caché KV.
- Resumen del run: "temperatura reposo → máx 52 → 52 °C (+-1)" muestra "+-1". En la columna de la GPU, las unidades (`W`, `(+30)`) bajan a otra línea.
- Prompt libre en marcha: la fase marca "carga · 0 s" y "0 peticiones" aunque ya lleguen tokens. Estrés en marcha: "Peticiones (4)" en la tabla frente a "6 peticiones" en la tarjeta (cuenta las que están en curso).
- Servidor sin respuesta: "sin datos por slot × sin datos slots (total sin datos)"; mejor un solo "sin datos". La tarjeta se mueve unos 12 px al cambiar de estado (aparece o desaparece "Probar").
- Eje Y de velocidad: "0,0" y "5,0" frente a enteros en el resto de gráficas.
- Minigráficas "2 MIN" del Panel: empiezan vacías al abrir la página (no cargan el histórico).
- **A 1280 px de ancho**, la franja de dispositivos pasa a dos filas (RAM sola abajo) y ocupa media pantalla. La tabla del Historial se corta por la derecha (la columna de energía no se ve).
- Si se elige un contexto mayor que el entrenado (p. ej. 131.072 en un modelo de 32.768), no aparece ningún aviso.

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
