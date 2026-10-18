---
fecha_creacion: 2026-10-03
fecha_modificacion: 2026-10-18
tipo: proyecto
categoria: tech
tags: [tech, homelab, agente]
estado: activo
fecha_limite: ~
relacionado: ["Arena LLM"]
---
# Arena LLM — Estado

> Leer al retomar. Última actualización: 18/10/2026 (recomendados por hardware y pulido de la GUI). Las secciones están en orden de más antigua a más reciente salvo esta cabecera; lo último está al final.

## Resumen

| Fase | Estado |
|---|---|
| F0 — Preparación del PC | Parcial: falta XMP y la M40 (llega la semana del 05/10) |
| F1 — Esqueleto y agente | ✅ Cerrada (detecta el llama-server real) |
| F2 — GUI base | ✅ + pulido visual tras la opinión de Lucas (sin `FIG.`, títulos destacados, datos en mono) |
| F3 — Servidores y detección | Casi: ✅ calculadora y alta manual; falta comprobar el criterio relanzando un llama-server real con otro `-c` |
| F4 — Runner | ✅ Criterio cumplido: 33,6 t/s Arena frente a 34,5 t/s llama-bench (−2,7 %) |
| F5 — Telemetría, resumen y estrés | ✅ salvo la prueba real de 5 min (hecha de 60 s) |
| F6 — Rendimiento por componente | ✅ Criterio cumplido con la 3060 real (curva `-ngl`). Reparto `-ts` solo probado en simulado (falta la M40) |
| F8 — Batalla | ✅ núcleo (pedido por Lucas antes de F7): 2–6 lados, paralelo/secuencial, columnas en vivo, marcador. Falta la prueba real con la M40 y el modo guiado |
| F9 — Comparar | Gran parte: insignia, veredictos, métricas, gráficas, diff, respuestas por prompt, export MD/CSV/JSON. Faltan etiquetas/notas, filtros, métricas normalizadas, imagen y paquete de resultados |
| Ideas de Lucas | ✅ Biblioteca de prompts · ✅ comando copiable de llama-server · ✅ ver todas las respuestas · falta recomendaciones por hardware |
| Siguiente | Lucas prueba Batalla/Comparar → recomendaciones por hardware → F7 (calidad) → resto de F9 → F10 |

## Batalla, Comparar y respuestas (04/10/2026, tarde)

Lucas pidió acabar **Batalla** y **Comparar** (adelantadas a F7) y poder **leer todas las respuestas** para revisar la redacción y los errores.

- **Batalla** (`/batalla`, `server/runs/battle.py`). Cada lado es un run `libre` normal con `battle_id` y `side` (migración 6: tabla `battles`, más esas dos columnas en `runs`).
  - Común a todos los lados: prompts (con la biblioteca), semilla, repeticiones y fases. Por lado: temperatura, `max_tokens`, `top_k/top_p/min_p`, `repeat_penalty`, caché de prompt, sistema y `extra`. La semilla por lado se rechaza a propósito.
  - **Paralelo** exige un servidor distinto por lado. **Secuencial** lanza un lado tras otro y vale con el mismo servidor.
  - Vista en vivo: columnas con streaming, t/s, TTFT, tokens, temperatura máxima y minigráfica. Al terminar: marcador (veredictos + métricas con ▲) y respuestas por prompt. Botones: Detener, Repetir, Borrar y Ver en Comparar.
- **Comparar** (`/comparar?runs=…`, `server/compare.py`, `GET /api/compare`). Hasta 12 runs; con uno solo sirve para leer sus respuestas.
  - **Insignia**: *No comparables* si cambia la prueba o su versión. *Parcialmente* si los prompts son distintos, algún run está incompleto o cambian ≥2 factores a la vez (modelo · equipo/GPU · build · contexto · flags · parámetros). *Comparables* si cambia como mucho uno, que es lo que se compara.
  - Además: veredictos (más rápido, responde antes, más frío, más eficiente, con margen), métricas con el mejor valor resaltado, gráficas superpuestas (t/s, °C, W desde el inicio de la carga) y diff de configuración.
  - Las métricas de dispositivo usan **solo las GPU de cada run** (las vigiladas): en una batalla en paralelo en el mismo equipo no se mezclan. La energía del resumen general sí sumaba todas las GPU; aquí no.
  - Exporta Markdown para el vault (YAML de tipo proyecto, tablas y respuestas completas), CSV con `;` y JSON.
- **Respuestas**: componente `ResponsesMatrix` (una fila por prompt y repetición, una columna por run). Incluye la referencia de la biblioteca, tokens, palabras, t/s y TTFT, avisa de «cortada por tokens máximos», tiene buscador, razonamiento opcional y desplegar/plegar todo. Está en la vista de cada run (sección «Respuestas»; plegada en estrés), en Batalla y en Comparar.
- **Historial**: casillas, bandeja «Comparar (N)» («Ver respuestas» con uno) y enlace ⚔ a la batalla de cada lado. Calidad y Batalla comparten `PromptPicker`.
- Probado de punta a punta en simulado con Playwright (batalla en paralelo con 2 GPU simuladas → marcador → Comparar → Historial → run), sin errores en consola. Arreglado al verlo: temperatura máxima «sin datos» al terminar un lado y enteros con decimal en el diff.
- Tests: 5 de batalla de punta a punta (`test_battle.py`: paralelo con mismos prompts y semilla en lo que recibe cada servidor, secuencial, validaciones, cancelar/borrar), 11 de `compare.py` y 3 de la web (filas, Markdown y CSV). `ruff` limpio en todo el repo.

## Comando de llama-server (04/10/2026)

Servidores → GGUF en disco → **Ver comando** en cada GGUF que cabe. Lo compone `server/launch.py` (devuelto en `/api/hosts/{id}/fit` como `command`) a partir del veredicto de la calculadora:

- `-m`, `-c`, `-ngl` sugerido, `-np` si es mayor que 1, `-ctk/-ctv` si la KV no es f16, `-ub` si no es 512, `-fa on` y `--port`. El puerto es el primero desde 8080 que no usa ningún servidor vivo del equipo ni el propio Arena.
- Si cabe en varias GPU, se elige una (`-dev CUDAn`, la de más memoria libre primero). Si va repartido o parcial con varias GPU, se usa `-ts` según la memoria aprovechable. Solo CPU: `-ngl 0 -dev none`. Si no cabe o faltan datos, no se propone comando.
- Con `-dev`/`-ts`, el comando fija `CUDA_DEVICE_ORDER=PCI_BUS_ID`. Los prefijos de backend van en una tabla por proveedor (`nvidia → CUDA`); otro proveedor deja el reparto automático con un aviso.
- Binario, por orden: `llama_server` de `agent.json` → `llama-server` junto a `llama_bench` (el agente lo publica en `/info` → `tools`) → último llama-server detectado → `llama-server` del PATH, con aviso.
- Sintaxis cmd y PowerShell en Windows, bash en Linux. Avisa si el contexto por slot supera el de entrenamiento.
- **Probado de verdad**: el comando del Qwen 7B Q8 (`-c 8192 -ngl 29 -fa on --port 8080`) arrancó a la primera con b11379 en la 3060 (70 s de carga; 8,5 GiB de VRAM usada frente a 8,3 GiB estimados más 0,65 GiB del escritorio) y Arena lo detectó como listo.
- Tests: 13 de `server/launch.py` y 1 de la configuración del agente.

Otros arreglos de esta sesión:
- Historial: rotulaba todo lo que no era estrés como "Libre" (también los bench); ahora usa el nombre de la suite y, en los bench, muestra el GGUF y la mejor tg del barrido.
- Calculadora: «Slots (-np)» ya se alinea con los otros controles.
- llama-bench simulado: devuelve tantas muestras como repeticiones (antes, como mucho 2).
- README repasado: puesta en marcha paso a paso, configuración del agente con `llama_server`, secciones de Rendimiento, biblioteca y comando, y capturas nuevas en simulado (`servidores.png`, `historial.png`, `comando-llama-server.png`, `prompt-biblioteca.png`, `rendimiento.png`).

## Biblioteca de prompts (04/10/2026)

Calidad → Prompt libre → **Biblioteca**: 28 prompts en 7 categorías (lógica, tipo test de CI, matemáticas, código, seguir instrucciones, redacción, explicar). Un clic añade o quita el prompt de la lista (el primero sustituye al prompt por defecto); "añadir esta categoría" mete todos los visibles. «Tokens máximos» pasa al mayor sugerido. Los que tienen respuesta objetiva llevan `ref`: en el run aparece el título junto a la petición y la **respuesta de referencia** bajo la respuesta (sin corrección automática; eso es F7).

- Datos en `server/catalog/prompts.json` (versión `1`); `GET /api/prompts`. Para añadir prompts propios sin tocar el repo: `prompts.json` con la misma forma en la carpeta de datos (`data/` o `ARENA_DATA_DIR`); un `id` repetido sustituye al de la base, y un fichero roto se ignora con aviso en la página.
- El run sigue siendo la suite `libre`: los prompts van en los parámetros y en el hash, así que dos runs con la misma selección son comparables.
- Tests: 8 de Python (`tests/server/test_library.py`) y 4 de la web (`web/tests/library.test.ts`).

## F6 · llama-bench desde el agente (03/10/2026, 22:55)

Página **Rendimiento**: 4 pruebas (un dispositivo · solo CPU/RAM con barrido de hilos · curva `-ngl` · reparto `-ts`), perfil estándar v1 (pp512, tg128, 3 repeticiones) con versión y hash, barridos por defecto derivados del modelo y del equipo, aviso previo (servidor ocupando la tarjeta, modelo que no cabe; "Lanzar igualmente"), telemetría y aborto térmico durante el bench. El run muestra la curva t/s frente a la variable, tabla con % de capas en GPU y ancho de banda efectivo (ESTIMADO).

- Agente: `agent/bench.py`. Solo ejecuta el `llama_bench` de su configuración, con lista cerrada de flags validados uno a uno, sin shell, modelos dentro de `model_dirs`, un trabajo cada vez, rechaza POST con cabecera `Origin` (navegador). `CUDA_DEVICE_ORDER=PCI_BUS_ID` para que `CUDA0…` = índice de `nvidia-smi`. En `--simulate` hay un llama-bench simulado.
- Configuración creada en este PC: `%APPDATA%\ArenaLLM\agent.json` con `model_dirs: D:/ollama/models` y `llama_bench: D:/dev-tools/llama.cpp/b11379/llama-bench.exe` (también vale `--llama-bench`).
- BD: migración 5 (`bench_rows`).

**Curva real** (3060 · Qwen2.5-Coder 7B Q8_0 · b11379 · 2 repeticiones):

| `-ngl` (de 29) | 0 | 7 | 14 | 22 | 29 |
|---|---|---|---|---|---|
| tg128 (t/s) | 3,2 | 3,6 | 4,4 | 8,8 | **38,7** |
| pp512 (t/s) | 117 | 192 | 657 | 1151 | **2282** |
| Ancho de banda ef. (ESTIMADO) | 26 GB/s | | | | **313 GB/s** |

- El **pp lento de la primera prueba (162 t/s) no era la GPU**: con la tarjeta libre da 2282 t/s. Era el llama-server cargado a la vez.
- La RAM rinde unos 26 GB/s efectivos: cuadra con DDR4 sin XMP. Activar el XMP debería subir la parte de CPU.
- Pico de 75 °C y 169 W (límite 170 W).

Detalles encontrados y corregidos: `--list-devices` tarda unos segundos (carga CUDA): el agente lo precalienta y lo cachea. La primera lectura de una cabecera GGUF de 8 GB tarda más de 3 s en `D:`: más margen de espera. Un proceso en el puerto 9931 (`LlamaApp`) responde como llama-server **sin modelo**; ya no bloquea el bench.

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
- **Rendimiento (F6):** llama-bench por componente, ver arriba.
- **Tests:** 220 de Python (laboratorio completo sin GPU, calculadora de encaje y llama-bench real con un ejecutable falso y simulado) y 17 de la web.

## Calculadora de encaje (03/10/2026)

Servidores → pestaña **GGUF en disco**. Para cada GGUF: pesos reales por capa (offsets de los tensores), KV de las capas de atención (en `qwen35` solo 8 de 32), estado recurrente F32 por slot, búfer de cómputo y reserva de 512 MiB por GPU. Veredicto frente a la VRAM y RAM **libres ahora**: cabe en X · cabe repartido · necesita X GiB de RAM (con `-ngl` sugerido) · solo CPU · no cabe. Todo con el sello ESTIMADO.

Con c=8192 en la 3060 (11,6 GiB libres) caben los tres modelos. El 7B Q8 estima 8,3 GiB frente a 9,2 GiB de pico medido (que incluye el escritorio). El 14B Q4_K_M a 32K necesitaría unos 4,2 GiB de RAM con `-ngl 38`.

Limitaciones: ventana deslizante (cota superior), MoE sin `--cpu-moe` y búfer de cómputo aproximado (supone flash attention).

## Alta manual de endpoints (03/10/2026)

Servidores → **＋ Añadir a mano**: equipo (de él sale la telemetría), URL, alias y GPU opcionales. La URL se normaliza (`localhost` → `127.0.0.1`, sin `/v1`) para que coincida con la detectada. Se sondea cada 5 s aunque el agente no vea el proceso y no se borra al parar: queda "sin respuesta". Si además se detecta como proceso, se fusiona (conserva pid y flags). Cualquier servidor admite **GPU a mano** (mandan sobre la detección y cuentan como cambio de configuración). Se pueden quitar los manuales y los detenidos. BD: migración 4 (`manual`, `device_ids`).

## Pendiente (orden propuesto)

0. **Ideas de Lucas (03/10/2026)**, ver la hoja de ruta: ~~biblioteca de prompts~~ y ~~comando copiable de `llama-server`~~ (hechos 04/10) · recomendaciones de modelos según el hardware. Después F7 → F8 → F9 → F10.
0. ~~README con capturas y GIFs~~: ya está en `main` (merge 82986d9). Quedan las capturas de Servidores e Historial (ver abajo).

1. Lucas revisa el pulido visual (sin `FIG.`, títulos y rótulos en Inter seminegrita, datos vivos en mono más clara) y la pestaña GGUF. No se pudo revisar con capturas: la extensión de Chrome no estaba conectada.
2. F3:
   - Criterio: relanzar el llama-server real con otro `-c` y ver el cambio en menos de 10 s.
   - Opcional: asociar GPU por aumento de VRAM cuando `compute-apps` no la dé (de momento se asigna a mano desde la tarjeta del servidor).
3. F6: `llama-bench` desde el agente, por componente. Servirá para investigar el procesado de prompt lento.
4. F5: prueba real de 5 min y prueba de la M40 cuando llegue (driver R580).

## README con capturas (03/10/2026)

En `docs/img/` hay capturas y GIF hechos en modo simulado con Playwright: `panel.png`, `panel-telemetria.gif`, `deteccion-servidores.gif`, `calculadora-gguf.gif`, `estres-en-vivo.gif`, `resultado-run.png`, `prompt-libre-streaming.gif` y `ajustes-apariencia.png`.

**Pendiente para mañana:**
- ~~Capturas de Servidores e Historial~~: hechas el 04/10, junto con las del comando, la biblioteca y el rendimiento.
- Repetir `panel.png` con la página abierta 2 min antes, para que las minigráficas "2 MIN" salgan llenas.
- Herramientas ya instaladas en `D:\dev-tools\`: `readme-tools\` (venv con Playwright, Pillow y httpx) y `ms-playwright\` (Chromium; usar `PLAYWRIGHT_BROWSERS_PATH=D:\dev-tools\ms-playwright`). Los scripts de captura están en `D:\dev-tools\readme-tools\capturas\`: `e_static.py` hace justo lo pendiente. Esperan los datos en `D:\dev-tools\arena-readme-tmp\`, que se borró, así que hay que recrear esa carpeta. El 04/10 se recreó y se volvió a borrar al terminar. El agente simulado necesita un `agent.json` con `"model_dirs": ["M:/"]` (y un `llama_server` ficticio para el comando). Usan el servidor en 8190, agentes simulados en 9201/9202 vía `sim_agent.py` (desplaza los llama simulados a 18181/18182) y GGUF falsos de `make_gguf.py` montados con `subst M:`.

Detalles visuales vistos al capturar (sin arreglar):
- ~~Calculadora GGUF: punto decimal en los veredictos y «Slots (-np)» desalineado~~ (arreglados el 03/10 y el 04/10).
- Resumen del run: "temperatura reposo → máx 52 → 52 °C (+-1)" muestra "+-1". En la columna de la GPU, las unidades (`W`, `(+30)`) bajan a otra línea.
- Prompt libre en marcha: la fase marca "carga · 0 s" y "0 peticiones" aunque ya lleguen tokens. Estrés en marcha: "Peticiones (4)" en la tabla frente a "6 peticiones" en la tarjeta (cuenta las que están en curso).
- Servidor sin respuesta: "sin datos por slot × sin datos slots (total sin datos)"; mejor un solo "sin datos". La tarjeta se mueve unos 12 px al cambiar de estado (aparece o desaparece "Probar").
- Eje Y de velocidad: "0,0" y "5,0" frente a enteros en el resto de gráficas.
- Minigráficas "2 MIN" del Panel: empiezan vacías al abrir la página (no cargan el histórico).
- **A 1280 px de ancho**, la franja de dispositivos pasa a dos filas (RAM sola abajo) y ocupa media pantalla. La tabla del Historial se corta por la derecha (la columna de energía no se ve).
- Si se elige un contexto mayor que el entrenado (p. ej. 131.072 en un modelo de 32.768), no aparece ningún aviso. Desde el 04/10 el aviso sale en el comando propuesto, pero todavía no en el veredicto.

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

## Rediseño visual minimalista (14/10/2026)

Pedido por Lucas: GUI más moderna, minimalista y fácil de leer, centrada en gráficas en vivo y cifras claras.

- **Estilo** alineado con el hub del homelab (iOS monocromo): fondo negro, superficies `#1c1c1e`, esquinas de 16 px, botones en cápsula, sin rejilla ni marcas de registro ni efecto croquis; color solo para estado y para identificar cada dispositivo. Acento por defecto blanco (configurable en Ajustes).
- **Panel**: cifras grandes (clase `.num`, Inter tabular) y tres gráficas de 2 min por GPU (temperatura con límite crítico, potencia con su límite, uso + VRAM), más CPU y RAM (`LiveGpu.vue`, `LiveSystem.vue`). En el Panel la franja de equipo se oculta porque ya es la propia página; en el resto de pantallas sigue arriba, con las mismas cifras grandes.
- `LineChart` con relleno degradado (`area`), etiquetas de eje configurables (`xFormat`) y sin marco; `Sparkline` con relleno.
- Pendiente: ajustar Ajustes → Apariencia (las opciones de rejilla y croquis ya no hacen nada) y actualizar `docs/GUI-DISENO.md` §3.

## Servidores: lanzar desde la GUI y tarjetas más grandes (14/10/2026)

Pedido por Lucas (como en LocalHarness): elegir la GPU y lanzar el modelo directamente, ordenar por tamaño o B de parámetros y ver las características en grande. **Cambia el principio 4 de CLAUDE.md** (antes la GUI solo detectaba).

- **Agente** (`agent/launcher.py`): `POST /launch`, `POST /launch/stop`, `GET /launched`. Lista cerrada de flags validados, modelo dentro de `model_dirs`, `--host 127.0.0.1`, puerto libre, sin shell, rechaza `Origin`; solo para lo que lanzó él. Registro de cada servidor en `%TEMP%arena-llama-<puerto>.log` y últimas líneas en `/launched`. Equipos simulados: no lanzan (`capabilities.launch = false`).
- **Servidor**: `POST /api/hosts/{id}/launch` recalcula el encaje con la memoria libre de ahora y envía solo la `spec` de la opción elegida; `/launch/stop` y `/launched`. Cada opción de `server/launch.py` lleva ahora `spec` y `device_id`; el comando copiable incluye `--host 127.0.0.1` y un test comprueba que la spec del agente reproduce exactamente ese comando.
- **Web** (`GgufList.vue`): fichas de GPU destino («Automático» o cada GPU con su memoria libre), botón **Lanzar en <GPU>** (desactivado con el motivo si no cabe entero ahí), **Parar** para lo lanzado desde Arena, estado «arrancando / cargando / en marcha :puerto» con el registro mientras carga, orden por Tamaño · Parámetros (B) · Nombre · Encaje (asc/desc, se recuerda). Tarjetas con cifras grandes (parámetros, cuantización, tamaño, contexto, capas), veredicto y barra de encaje más grandes. «Copiar comando» sigue como botón secundario.
- Probado de verdad: Qwen3.5-0.8B Q8_0 lanzado en la Tesla M40 (`-dev CUDA0`, orden PCI) desde la GUI, detectado como cargando y parado; la VRAM volvió al valor inicial. Tests: 8 del lanzador del agente y 1 de coherencia spec ↔ comando.
- Pendiente: probar `Repartido` (`-ts`) con las dos GPU libres, y mostrar los lanzados en la pestaña «En marcha».


## Recomendados por hardware y pulido (18/10/2026)

Pedido por Lucas: una etiqueta de **recomendado para tu hardware** en la lista de GGUF y cerrar los pendientes de la GUI.

- **Recomendados** (`web/src/lib/recommend.ts`, usado por `GgufList.vue`). Candidatos: modelos de chat que caben **enteros** en la GPU destino (o en cualquiera con «Automático»; o repartidos entre varias) ocupando como mucho el 90 % de su memoria libre, y cuyo contexto entrenado cubre el contexto por slot elegido. Puntuación = parámetros × calidad de la cuantización (tabla por familia: F16 1,0 · Q8 0,99 · Q6 0,97 · Q5 0,95 · Q4_K 0,92 · Q4_0 0,89 · Q3 0,75–0,8 · Q2 0,5 · IQ1 0,35 · desconocida 0,85). De cada familia solo la mejor cuantización; se etiquetan hasta 3 que lleguen al 75 % del mejor: «★ Mejor para tu hardware» y «★ Recomendado» (el motivo sale al pasar el cursor). Nuevo orden «Recomendado». Se recalcula al cambiar GPU destino, contexto, slots o caché KV, y sin umbrales de hardware escritos en el código.
  - **Limitaciones**: es una heurística sobre la cabecera, no una medida. Con «Automático» no distingue GPU rápidas de lentas (una M40 con más memoria puede ganar a la 3060): usar el ancho de banda de F6 para desempatar queda pendiente, igual que el catálogo editable. Los MoE cuentan todos sus parámetros.
  - Tests: 6 de web (`web/tests/recommend.test.ts`).
- **Ajustes → Apariencia**: quitadas las opciones de rejilla y croquis (no hacían nada). Los ajustes antiguos guardados se descartan al leer.
- **Historial**: la columna del modelo se recorta con puntos suspensivos (el nombre completo sale al pasar el cursor) y las celdas se compactan por debajo de 1400 px, de modo que la energía y la duración caben a 1280 px.
- **Franja de dispositivos**: tarjetas de 230 px como mínimo (antes 280), así que GPU, CPU y RAM caben en una sola fila a 1280 px.
- **Panel**: las minigráficas de 2 min ya salen llenas al abrir la página. El servidor guarda las últimas 120 lecturas de cada equipo (`HostState.recent`) y las reenvía al conectar el SSE como evento `backlog`, que solo rellena el historial (no cuenta como dato fresco ni entra en las muestras de un run). El cliente ignora lecturas repetidas.
- **Run**: la tarjeta dice «N peticiones completadas» y la tabla de peticiones se refresca mientras corre, así que ya no marca menos que la tarjeta.
- **Servidores**: el contexto muestra solo lo que hay («N por slot × M slots», «N en total» o un único «sin datos») y la cabecera de la tarjeta tiene alto fijo para que no salte al aparecer «Probar».
- Ya estaban hechos antes: «+-1» (ahora «+3», «−1») y el eje de velocidad con enteros. El aviso de contexto mayor que el entrenado sale ahora también en la tarjeta del GGUF.
- Tests: 243 de Python y 23 de la web; `ruff` limpio.

**Sin comprobar**: no he abierto la GUI con capturas esta sesión; el aspecto de la etiqueta, el Historial a 1280 px y la franja de dispositivos están sin revisar a ojo. Los criterios de `docs/GUI-DISENO.md` §8 siguen sin marcar.
