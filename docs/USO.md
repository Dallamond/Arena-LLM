# Guía de uso de Arena LLM

Para qué sirve cada pantalla y cómo se encadenan. La instalación y el arranque están en el [`README`](../README.md); cómo añadir una GPU, un equipo, un servidor o una prueba, en [`EXTENDER.md`](EXTENDER.md).

**Menú lateral:** Panel · Servidores · Asistente · Calidad · Rendimiento · Batalla · Historial · Comparar · Ajustes. Se pliega y se abre al pasar el cursor o al enfocarlo con el teclado.

---

## Flujos típicos

### A. «¿Qué tal va este modelo en mi equipo?» (5 minutos)
1. **Servidores → GGUF en disco**: elige el modelo. La etiqueta **★ Mejor para tu hardware** y el veredicto de encaje (cabe en GPU / repartido / en RAM / no cabe) te orientan; todo es `ESTIMADO`.
2. Elige la GPU destino (o «Automático»), contexto y slots, y pulsa **Lanzar en <GPU>**. También puedes **Copiar comando** y lanzarlo tú.
3. Cuando aparezca en **En marcha** como `listo`, pulsa **▶ Probar** → **Calidad** → *Prompt libre* (o *QA*, *Código*, *Contexto*, *Concurrencia*).
4. Mira el resultado del run: t/s, TTFT, temperatura, potencia, energía y la **foto de configuración** guardada.

### B. «¿Qué modelo/GPU/cuantización es mejor?»
- **Dos servidores a la vez** (uno por GPU): **Batalla** en paralelo. Mismos prompts y semilla; columnas en vivo y marcador al final.
- **Un solo servidor, variando un parámetro**: Batalla en modo secuencial (por ejemplo, la temperatura).
- **Muchos modelos × GPU sin vigilar**: **Asistente**. Elige equipo, destinos (Automático, una GPU o repartido), modelos y prueba; Arena arranca cada modelo, lo mide, lo para y pasa al siguiente. Un paso que no cabe o falla se anota y el barrido sigue.
- Después, **Historial → marcar → Comparar**.

### C. «Quiero grabar un vídeo»
Pulsa **Modo vídeo** (barra superior) o la tecla **V**; `?video=1` en la URL también lo activa. Oculta menús y barras, agranda cifras y gráficas y fuerza alto contraste. **Esc** o **V** para salir. En Comparar y en la Batalla puedes descargar el marcador como **PNG de 1920×1080**.

### D. «Quiero comparar con otro PC»
En el otro equipo: **Historial → marcar runs → Exportar paquete** (JSON). En este: **Historial → Importar paquete…**. Los importados llevan la etiqueta `importado` y se comparan como cualquier otro; la insignia dice si son comparables.

---

## Pantallas

### Panel
Telemetría en vivo de cada dispositivo: temperatura (con su límite), potencia (con su límite), uso y VRAM de cada GPU, más CPU y RAM. Las minigráficas guardan 2 min. Un valor que el equipo no expone sale **«sin datos»**, nunca 0.

### Servidores
- **En marcha**: servidores detectados (los lance quien los lance) con modelo, cuantización, contexto por slot × slots, build, flags, GPU que usan y cambios de configuración registrados. **＋ Añadir a mano** para uno que el agente no ve. **■ Parar** solo aparece en los que lanzó Arena.
- **GGUF en disco**: los modelos de las carpetas permitidas del agente, ordenables por tamaño, parámetros, nombre, encaje o recomendado.

### Calidad
Pruebas contra el servidor que elijas. El perfil estándar fija temperatura 0, semilla 42 y `cache_prompt` desactivado; cambiarlos hace que el run deje de ser comparable con el perfil.

| Prueba | Qué mide |
|---|---|
| Estrés GPU/VRAM | Bucle de peticiones largas con reposo, carga y enfriamiento: t/s en el tiempo, temperatura, potencia, reloj, throttling, degradación y energía. Aborta si una GPU llega a su umbral crítico. |
| Prompt libre | Uno o varios prompts (con la biblioteca de 28) y repeticiones: TTFT, t/s y tokens. |
| QA | 12 preguntas con respuesta conocida; el modelo acaba con `RESPUESTA: valor`. |
| Código | 10 problemas de Python en 3 niveles, ejecutados en un sandbox aislado; da pass@1. |
| Contexto | «Aguja en un pajar» por tamaño y profundidad; un tamaño que no cabe queda como resultado (así se conoce el límite). |
| Concurrencia | Escalado de t/s agregados con 1, 2, 4… peticiones a la vez. |

### Rendimiento
`llama-bench` lanzado por el agente: curva de capas en GPU (`-ngl`), comparación de dispositivos, hilos de CPU y reparto entre GPU (`-ts`). Incluye el ancho de banda efectivo (`ESTIMADO`), que además usan las recomendaciones para desempatar entre GPU.

### Batalla y Asistente
Ver flujo B. Cada lado guarda su propio run; **Ver en Comparar**, **Repetir** y **Borrar** al terminar.

- **Paquetes de batalla**: 8 pruebas predeterminadas (Duelo rápido, Razonamiento, Programador, Programador calentamiento, Memoria larga, Velocidad pura, Lectura y Seguir instrucciones). Un clic carga la prueba, sus opciones y los pesos de la nota; solo queda elegir los lados. Los tuyos van en `battles.json` dentro de la carpeta de datos.
- **Nota 0-100** por lado: calidad (absoluta, solo si la prueba se corrige sola), velocidad y eficiencia (relativas al mejor lado) y estabilidad (throttling térmico y degradación). Sin datos en una dimensión, se omite y su peso se reparte. La nota solo es comparable dentro de la batalla; la calidad vale en cualquier sitio.
- **Ranking por paquete**: al cargar un paquete se ve el ranking acumulado por modelo y GPU, solo con batallas del mismo hash del paquete.

### Historial
Todos los runs con sus métricas principales.
- **Buscar** por prueba, nombre, etiqueta, nota, modelo o estado.
- **Filtros**: equipo, dispositivo, prueba, estado y etiqueta (se recuerdan). «N de M» y **Quitar filtros**.
- **Etiquetas, nombre y notas** se editan en la vista de cada run.
- Casillas → bandeja inferior: **Comparar (N)** (con un solo run, «Ver respuestas»), **Exportar paquete** y **Vaciar**.

### Comparar
Hasta 12 runs. Cabecera con la **insignia de comparabilidad** y sus motivos:
- **Comparables**: misma prueba y versión, y un solo factor cambiado (o ninguno).
- **Parcialmente**: prompts distintos, runs incompletos o más de un factor cambiado a la vez.
- **No comparables**: otra prueba u otra versión de prueba.

Pestañas: *Resumen* (veredictos y cifras clave), *Prompts* (respuestas lado a lado), *Métricas* (todas, con ▲ en el mejor valor; casilla **normalizar** para t/s por GiB de VRAM, por W y Wh por 1000 tokens, con sello `ESTIMADO` cuando usan potencia de placa) y *Gráficas*. La configuración diferente entre runs aparece en una tabla de diferencias.

**Exportar**: Markdown para el vault (YAML válido, etiquetas, notas, tablas y respuestas), `.md`, CSV (separador `;`), JSON, **imagen PNG del marcador** (1280×720 o 1920×1080) y copiar imagen.

### Ajustes
- **Apariencia**: acento, contraste y tamaño de la interfaz.
- **Equipos**: añadir o quitar agentes (URL y token; el token es obligatorio fuera de localhost).
- **Umbrales térmicos** por dispositivo (aviso y aborto) o «Automático». Es el sitio para valores específicos de una tarjeta.
- **Datos**: runs guardados y dónde está la base de datos.

---

## Atajos de teclado

| Tecla | Acción |
|---|---|
| `Tab` / `Shift+Tab` | Recorrer los controles (el foco siempre es visible) |
| `←` `→` | Cambiar de pestaña en Comparar y Servidores |
| `V` | Activar o salir del modo vídeo (no actúa si escribes en un campo) |
| `Esc` | Salir del modo vídeo |

## Reglas que conviene recordar
- **Un valor no disponible es «sin datos», nunca 0.** Las estimaciones llevan el sello `ESTIMADO`.
- **Comparar runs de configuraciones distintas** sin leer la insignia es el error más fácil; los motivos de «Parcialmente» y «No comparables» dicen exactamente qué cambió.
- **Arena solo para lo que lanzó ella.** Tus `llama-server` no se tocan.
- **La base de datos, los resultados reales, los modelos y los tokens no se suben al repositorio** (`data/` está en `.gitignore` y `.stignore`).
- **Una medida con otro proceso usando la misma GPU no es fiable** (t/s, temperatura y energía). Los aciertos de calidad no dependen de ello.
