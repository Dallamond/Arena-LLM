---
fecha_creacion: 2026-10-03
fecha_modificacion: 2026-10-03
tipo: proyecto
categoria: tech
tags: [tech, homelab, agente]
estado: activo
fecha_limite: ~
relacionado: ["Arena LLM", "Homelab"]
---
# Arena LLM — Diseño de la interfaz

> 03/10/2026 · Referencia estructural: capturas de **FreeToken Desktop** (v0.2.0-beta.23) que Lucas compartió. Idea: usarla como **inspiración de organización**, no copiarla, y vestirla con un estilo propio **blueprint / sketch con flujo**.
> Se construye en la Fase F2 y se amplía en cada fase posterior. Reglas generales: `CLAUDE.md`.

---

## 1. Qué hay en la referencia (observado en las capturas)

| Zona | Lo que tiene FreeToken |
|---|---|
| Barra superior | Chips de estado a la izquierda (`daemon :19000`, `API :1919`), título al centro, contador a la derecha |
| Menú lateral | Colapsable. Modelos (con contador), Console, Chat, Apps, Logs, Settings. **Pie con barras de VRAM y RAM del sistema** y nombre de la GPU |
| Modelos | Cabecera con recuento (`0 local models · 0 running · 0 downloading · 0.0 GiB used`), buscador, pestañas con contadores (All / Downloaded / Downloading), **lista de filas**: logo, nombre, etiquetas (CHAT, Vision, MoE, "3 versions"), línea de datos (cuantización · parámetros · tamaño · contexto) y a la derecha una **etiqueta de encaje** ("Insufficient VRAM/RAM") y botón. Zona final de arrastrar carpeta para importar |
| Console | Tres tarjetas de cifras, **banner de estado vacío** con borde discontinuo y botón, tarjeta de configuración, nombre del hardware en tipografía mono y **cuatro medidores radiales** (VRAM, utilización GPU, memoria, CPU) con etiquetas pequeñas (CUDA, RAM, 12 CORES) y cifras debajo. Chip `Live · 1s refresh` |
| Settings | Subnavegación a la izquierda; secciones en tarjetas con **rótulo en mayúsculas mono** y estado "Synced" a la derecha; filas con título + ayuda a la izquierda y control a la derecha; deslizadores con lectura (`VRAM budget 85% ≈ 10.2 GiB`), interruptores, campos mono |
| Estética | Fondo casi negro azulado, tarjetas con borde fino, un único azul de acento, tipografía sans para texto y mono para rótulos y números |

---

## 2. Qué tomamos y qué cambiamos

| Tomamos (estructura) | Cambiamos (identidad) |
|---|---|
| Barra superior con chips de estado | Estética **blueprint**: plano técnico sobre rejilla |
| Menú lateral colapsable con medidores de sistema en el pie | Franja del equipo **siempre visible** en todas las pantallas (no solo en una "Console") |
| Etiquetas de encaje por modelo (VRAM/RAM) | Encaje con **cota y rayado** que enseña cuánto se desborda a RAM |
| Medidores radiales y tarjetas de cifras | **Una tarjeta por GPU** con color estable, no un medidor global |
| Ajustes con subnavegación y filas etiqueta+control | Controles con **lectura de unidad** y avisos de aborto |
| Estados vacíos con borde discontinuo y botón de acción | Flujos dibujados como **diagramas con conectores** (prompt → lados → GPUs → métricas) |

**No copiamos:** logotipo, nombre, iconos, textos, el contador de "ahorro", las páginas Chat/Apps ni las proporciones exactas.

---

## 3. Estilo "blueprint sketch con flujo"

Un **plano técnico del equipo**: lo que miras es una máquina dibujada con sus medidas, y los datos circulan por ella.

1. **Fondo de plano.** Rejilla fina (16 px) y rejilla mayor (80 px) en azul muy tenue sobre azul tinta.
2. **Tarjetas como láminas.** Borde de 1 px, **marcas de registro** en las cuatro esquinas (pequeñas "L") en lugar de esquinas redondeadas, título en sans seminegrita con una muestra del color del dispositivo (`■ RTX 3060`). *(03/10/2026: se quitan los rótulos `FIG.` a petición de Lucas: ensuciaban.)*
3. **Líneas de cota.** Cada barra de memoria lleva su cota (`├──── 12.0 GiB ────┤`). Lo ocupado va **sólido**; lo que se desborda a RAM va **rayado diagonal**. Es el lenguaje visual de toda la app.
4. **Flujo.** Conectores discontinuos con flecha que unen prompt → lado A/B → servidor:puerto → GPU → métricas. Los guiones **avanzan solo mientras hay tokens**. Con `prefers-reduced-motion` quedan estáticos.
5. **Efecto croquis (sketch).** Un filtro SVG (`feTurbulence` + `feDisplacementMap`, desplazamiento ≈ 1 px) da un trazo ligeramente irregular a los bordes destacados y a los ejes de las gráficas. **Nunca** al texto ni a las líneas de datos. Se apaga con reducción de movimiento y con una opción en Ajustes.
6. **Anotaciones.** Sobre las gráficas aparecen notas pequeñas con flecha curva generadas por los eventos reales (`← empieza el throttling`, `← VRAM llena`, `← aborto a 85 °C`).
7. **Sellos.** Etiquetas con borde discontinuo y ligera inclinación (±1°) para estados: `ESTIMADO`, `ABORTADO`, `SIN DATOS`, `CONFIG CAMBIADA`.
8. **Tipografía.** Texto fijo (títulos, rótulos, nombres de campo, botones y frases) en sans (Inter); **solo los datos que cambian** (cifras, rutas, flags) en mono (JetBrains Mono, cifras tabulares) y un tono más claro, para que se distingan de un vistazo. Ambas **autoalojadas** (sin CDN). Una fuente manuscrita opcional solo para anotaciones.

### Tokens (propuesta inicial; ajustar al verlo)

| Token | Valor | Uso |
|---|---|---|
| `--bg` | `#0a111c` | Fondo |
| `--grid-minor` / `--grid-major` | `rgba(110,160,255,.06)` / `rgba(110,160,255,.12)` | Rejilla |
| `--panel` | `#0f1828` | Tarjetas |
| `--line` / `--line-strong` | `#2a4a7a` / `#5b8fd6` | Bordes y trazos de plano |
| `--ink` / `--ink-dim` / `--ink-faint` | `#e8f0ff` / `#93a8c8` / `#5c7396` | Texto |
| `--accent` | `#6cb4ff` | Acción principal |
| `--dev-1` … `--dev-6` | `#4cc9f0`, `#ff9f43`, `#f472b6`, `#a3e635`, `#facc15`, `#60a5fa` | Paleta de **dispositivos**. Se asigna automáticamente a cada GPU detectada y **se guarda por UUID**, así cada tarjeta conserva su color en todas las pantallas y en el historial |
| `--dev-cpu` | `#b794f6` | CPU |
| `--dev-ram` | `#6ee7b7` | RAM |
| `--warn` | `#ffe066` con icono ▲ | Aviso (80 °C, throttling) |
| `--crit` | `#ff6b6b` con icono ✕ | Crítico (85 °C, error) |

Reglas: **color estable por dispositivo en todas las pantallas** (no por lado A/B), asignado al detectarlo y nunca escrito en el código para una tarjeta concreta; nunca comunicar estado **solo con color** (icono + texto); contraste AA; comprobar con una simulación de daltonismo (el amarillo de aviso y el de la paleta de dispositivos no deben confundirse: el aviso lleva siempre el icono ▲).

> **Independencia del hardware.** Todos los nombres de GPU, cifras y puertos que aparecen en los esquemas de este documento (RTX 3060, M40, `:8081`…) son **ejemplos del equipo de Lucas**. La interfaz se construye a partir de lo que detecta el agente: 1 GPU, 4 GPU o ninguna; NVIDIA hoy, otros fabricantes mañana.

---

## 4. Estructura general

```
┌ [agente ● :9100] [servidor ● :8080] ─────── ARENA LLM ───── [⚠ 1 aviso] [Modo vídeo] ┐
├──────────┬───────────────────────────────────────────────────────────────────────────┤
│ ▢ Panel  │ ┌ FRANJA DEL EQUIPO (siempre visible, plegable a una línea) ──────────────┐│
│ ▢ Servi- │ │ ■ RTX 3060        ■ M40             ■ CPU           ■ RAM              ││
│   dores  │ │ 62°C 118W         71°C 205W ▲       12% 3.6GHz      11.8/15.9 GiB      ││
│ ▢ Rendi- │ │ ▓▓▓▓▓░ 8.1/12 GiB ▓▓▓▓▓▓▓▓▓░ 19/24  ▁▂▃▅▃▂▁         ▓▓▓▓▓▓▓░░░         ││
│   miento │ └────────────────────────────────────────────────────────────────────────┘│
│ ▢ Cali-  │                                                                           │
│   dad    │                  (contenido de la pantalla activa)                        │
│ ▢ Batalla│                                                                           │
│ ▢ Histo- │                                                                           │
│   rial   │                                                                           │
│ ▢ Compa- │                                                                           │
│   rar    │                                                                           │
│ ▢ Regis- │                                                                           │
│   tros   │                                                                           │
│ ▢ Ajustes│                                                                           │
│ VRAM ▓▓░ │                                                                           │
│ RAM  ▓▓▓ │                                                                           │
└──────────┴───────────────────────────────────────────────────────────────────────────┘
```

- **Franja del equipo:** una tarjeta por GPU (temperatura, potencia, barra de VRAM con cota, reloj, etiqueta de throttling), más CPU y RAM. Actualiza cada 1 s. Si una GPU supera el umbral de aviso, su tarjeta cambia de trazo (rayado ▲); si llega al crítico, se marca ✕ y se muestra el motivo. Se puede **plegar a una línea** con las cifras clave.
- **Pie del menú lateral:** barras mini de VRAM y RAM (como la referencia), útiles cuando la franja está plegada.
- **Chips de la barra superior:** estado del agente y del servidor con texto (`conectado`, `sin respuesta`), no solo un punto de color.
- **Selector de equipo (host):** en la barra superior, junto a los chips. Cambia entre las máquinas registradas; la franja del equipo, los servidores y las pruebas se refieren al equipo elegido. El historial y Comparar mezclan equipos y muestran la **insignia de comparabilidad**.
- **Franja dinámica:** se dibuja una tarjeta por cada dispositivo detectado (una, varias o ninguna GPU). En un equipo sin GPU solo aparecen CPU y RAM. Los campos que un dispositivo no expone (por ejemplo el ventilador de una tarjeta pasiva) se muestran como "sin datos", nunca como 0.

---

## 5. Pantallas

### 5.1 Panel (equivalente a la Console de la referencia)
Resumen del momento: servidores detectados (modelo · contexto · GPU), última prueba, medidores radiales de cada dispositivo con su cifra (`8.1 / 12.0 GiB`, `62 °C · 118 W`), y estado vacío con borde discontinuo cuando no hay nada cargado ("Ningún servidor detectado · Detectar ahora").

### 5.2 Servidores y modelos
```
Servidores y modelos       3 detectados · 2 en marcha · 41.2 GiB en disco        [Buscar…]
[ En marcha 2 ] [ GGUF en disco 14 ] [ Cambios 5 ]
┌ llama-server :8081 ─ RTX 3060 ───────────────────────────────────────────────────────┐
│ Qwen… 8B · Q4_K_M · 4.9 GiB   ctx 8192 (×4 slots)   -ngl 99   -fa on   KV f16        │
│ VRAM  ├▓▓▓▓▓▓▓▓░░░░┤ 8.1/12 GiB      [Detectado hace 3 s]   [Ver flags] [Probar]      │
└──────────────────────────────────────────────────────────────────────────────────────┘
┌ llama-server :8082 ─ Tesla M40 ──────────────────────────────────────────────────────┐
│ …                                                                                    │
└──────────────────────────────────────────────────────────────────────────────────────┘
GGUF en disco:  modelo · cuant. · tamaño · ENCAJE:  [Cabe en M40] [Necesita 6.2 GiB de RAM ▨▨] [No cabe]
```
- Las filas de GGUF imitan la lista de modelos de la referencia, con **etiqueta de encaje** y la barra con cota: sólido = VRAM, rayado = RAM. Todas las cifras de encaje llevan el sello `ESTIMADO`.
- Cada servidor muestra **todos los flags detectados**, y el historial de cambios de configuración.

### 5.3 Rendimiento (llama-bench)
Selector de familia: **Solo GPU · Solo CPU/RAM · Híbrido · Reparto entre GPUs**. Formulario con modelo, tamaños de prompt/generación, repeticiones y barrido (por ejemplo `-ngl` de 0 a máx. en pasos). Resultado principal: **curva t/s frente a % de capas en GPU** con la cota de ancho de banda efectivo, y tabla pp/tg con desviación.

### 5.4 Calidad
Tarjeta por prueba (razonamiento, código, contexto largo, concurrencia, estrés) con sus opciones editables, última puntuación y botón lanzar. Al ejecutar, vista en vivo de la prueba con progreso por ítem.

### 5.5 Batalla (la pantalla estrella)
```
        ┌────────────── PROMPT / PRUEBA ───────────────┐
        │  "Escribe un resumen de…"   [Prueba ▾]       │
        └──────────────┬───────────────┬───────────────┘
              ┈┈┈┈┈┈┈┈▶│               │◀┈┈┈┈┈┈┈┈           ← conectores con flujo
   ┌ LADO A ─ :8081 ─ RTX 3060 ────┐  ┌ LADO B ─ :8082 ─ M40 ─────────┐
   │   62 t/s     TTFT 0.3 s       │  │   34 t/s     TTFT 0.9 s       │
   │   (respuesta en streaming…)   │  │   (respuesta en streaming…)   │
   │   ░░ t/s ░░ °C ░░ W (gráfica) │  │   ░░ t/s ░░ °C ░░ W (gráfica) │
   └───────────────┬───────────────┘  └───────────────┬───────────────┘
                   └──────────▶  MARCADOR  ◀──────────┘
 [Configurar ▾]  parámetros por lado · paralelo/secuencial · umbrales            [▶ Lanzar]
```
- Parámetros por lado en un cajón plegable: **sencillo** (temperatura, `max_tokens`, semilla) y **avanzado** (top_k, min_p, penalizaciones, caché de prompt, JSON `extra`, prompt de sistema). Presets, "Copiar A→B" y "variar solo este parámetro".
- La configuración detectada de cada servidor (modelo, contexto, flags) aparece fija en la cabecera de cada lado y **se guarda con el run**.
- Al terminar, marcador con mejor valor resaltado y botón "Ver en Comparar".

### 5.6 Historial
Tabla filtrable (prueba, **equipo, dispositivo**, texto) con t/s, % de acierto, temperatura máxima y potencia media. Botones de **importar/exportar paquete de resultados** para traer runs de otra instalación. Casillas de selección y bandeja inferior **Comparar (N)**. Etiquetas y notas editables.

### 5.7 Comparar
Arriba, la **insignia de comparabilidad** (Comparables / Parcialmente / No comparables, con los motivos desplegables) y las **tarjetas de veredicto** (más rápido · más frío · más eficiente · más acertado), con interruptor para ver métricas normalizadas (por GiB de VRAM, por W, por Wh) cuando los dispositivos son muy distintos. Debajo: tabla de métricas con el mejor valor resaltado, gráficas superpuestas (t/s, °C, W, VRAM, reloj frente al tiempo), curva de la RAM si procede, matriz por ítem y **diff de configuración** entre runs. Botones de exportar (JSON, CSV, Markdown para el vault, imagen).

### 5.8 Ajustes (según el patrón de la referencia)
Subnavegación: **Equipos · Servidores · Umbrales · Carpeta de modelos · Apariencia · Datos**. En *Equipos* se registran agentes de otras máquinas; en *Umbrales*, el aviso y el aborto térmico **por dispositivo detectado** (con el valor derivado de su temperatura de *slowdown* como punto de partida). Secciones en tarjetas con rótulo mono y estado `SINCRONIZADO`. Ejemplos de filas: *Aviso de temperatura* (deslizador 80 °C), *Aborto automático* (85 °C, por GPU), *Intervalo de muestreo* (1 s), *Efecto croquis* (interruptor), *Carpeta de GGUF*, *Ruta de llama-bench*.

### 5.9 Modo vídeo
Oculta menú y chips, agranda cifras y fuentes, fija 16:9, mantiene la franja del equipo en tamaño grande y permite exportar el marcador como imagen.

---

## 6. Componentes (biblioteca propia, en SVG/CSS)

`BlueprintCard` (esquinas de registro, título destacado) · `GpuCard` · `RadialGauge` · `BarWithOverflow` (sólido + rayado + cota) · `DimensionLine` · `Sparkline` · `LineChart` (varias series, ejes con trazo croquis, marcadores de eventos, selección de rango) · `StatCard` · `StatusChip` · `Stamp` (sello) · `FlowConnector` (guiones animados) · `ParamField` (control + lectura de unidad + ayuda) · `StreamPane` (respuesta en streaming) · `ConfigDiff` · `VerdictCard` · `FitBadge`.

Las gráficas se dibujan **con SVG propio** (los volúmenes son pequeños: 1 punto por segundo). Si el rendimiento lo exigiera con series muy largas, valorar `uPlot` solo para eso.

---

## 7. Orden de construcción

1. Tokens, fuentes, rejilla y `BlueprintCard`.
2. Esqueleto: barra superior, menú lateral y rutas vacías.
3. `GpuCard` + franja del equipo + Panel con medidores (F2).
4. `BarWithOverflow` y `FitBadge` con Servidores y modelos (F3).
5. `LineChart` con marcadores para los runs en vivo (F4–F5).
6. Resto de pantallas según las fases.

## 8. Criterios de calidad de la GUI

- [ ] Se lee bien en 1440 px y en un portátil pequeño (≥ 1100 px); menú colapsable.
- [ ] Ningún estado depende solo del color.
- [ ] `prefers-reduced-motion` desactiva animaciones de flujo y el efecto croquis.
- [ ] Foco visible y navegación por teclado en formularios y tabla.
- [ ] Sin dependencias externas en producción (fuentes y librerías locales).
- [ ] Datos ausentes se muestran como "sin datos" (nunca 0).
- [ ] Capturas de cada pantalla revisadas antes de dar la fase por cerrada.
