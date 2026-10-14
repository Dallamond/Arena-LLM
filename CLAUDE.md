---
tipo: sistema
agente: claude
fecha_modificacion: 2026-10-03
---
# ARENA LLM — guía para Claude Code

Banco de pruebas **independiente del hardware** para modelos de IA locales (llama.cpp): mide, enfrenta y compara modelos en cualquier equipo y tarjeta, con la telemetría del equipo siempre visible.

**Lee primero, en este orden:** este archivo → `docs/HOJA-DE-RUTA.md` (decisiones y fases) → `docs/GUI-DISENO.md` (interfaz) → `docs/VIABILIDAD.md` §2, §6 y §7 (riesgos, métricas, datasets). Al retomar, lee `ESTADO.md` (cuando exista).
Esta carpeta está dentro del vault de Lucas: antes de tocar nada fuera de ella, lee el `CLAUDE.md` del vault (raíz de `Lukaton1/`).

## Stack

- **Agente** (`agent/`): Python 3.11+, **solo biblioteca estándar** + `nvidia-smi`. Sin `pip install`.
- **Servidor** (`server/`): Python 3.11+, FastAPI, httpx, SQLite (stdlib). Eventos en vivo por SSE.
- **Web** (`web/`): Vue 3 + Vite + TypeScript. Gráficas propias en SVG. Sin CDN en producción: fuentes y librerías vendorizadas.
- Pruebas: `pytest` (servidor/agente) y `vitest` (web).

## Principios no negociables

1. **Independiente del hardware.** Prohibido escribir en el código nombres de GPU, índices, puertos, rutas, cantidades de VRAM/RAM, umbrales de temperatura o modelos concretos. Todo se **autodetecta** o se **configura** y se guarda. El PC de Lucas (RTX 3060 + Tesla M40 + Ryzen 5 3600) es solo el primer equipo de pruebas.
2. **Proveedores de telemetría enchufables** (interfaz común; v1: NVIDIA y CPU/RAM; un proveedor nulo para equipos sin GPU). Añadir AMD/Intel/Apple no debe tocar el resto del código.
3. **Reproducible y comparable.** Cada prueba tiene versión y hash de contenido; el perfil estándar fija semilla, temperatura 0, `cache_prompt` desactivado y los mismos prompts en cualquier equipo. Cada run guarda **su foto de configuración completa** (equipo, dispositivos, servidor detectado, modelo con hash de cabecera GGUF, versión de prueba, parámetros). Al comparar, mostrar la insignia **Comparables / Parcialmente / No comparables** con los motivos.
4. **Detectar siempre; lanzar solo lo pedido.** Arena detecta modelo, contexto y flags de cualquier `llama-server` (`/props`, `/slots`, línea de comandos del proceso, cabecera del GGUF) y los guarda, lo haya lanzado quien lo haya lanzado. Desde 14/10/2026, a petición de Lucas, la GUI también **lanza y para `llama-server`** en la GPU elegida (Servidores → GGUF en disco) y puede copiar el comando. Solo para y modifica los que lanzó Arena. El agente también lanza `llama-bench`.
5. **No inventar datos.** Un valor no disponible es `null` y se muestra como "sin datos", nunca 0. Estimaciones (encaje, ancho de banda efectivo, potencia de placa) llevan el sello `ESTIMADO`.
6. **Parar y preguntar** si algo de la hoja de ruta choca con la realidad (campo ausente, flag distinto en esa build de llama.cpp…) o si falta un dato que solo tiene Lucas.

## Seguridad

- El agente escucha en `127.0.0.1` por defecto; fuera de localhost **exige token**.
- El agente **no es una shell remota**: solo ejecuta `llama-bench` y `llama-server` (los de su configuración local) con lista cerrada de flags validados uno a uno, modelos dentro de `model_dirs`, `llama-server` siempre en `127.0.0.1`, sin shell y sin aceptar peticiones con cabecera `Origin`. La GUI envía una `spec` estructurada, nunca una línea de comandos libre; solo puede parar procesos que el agente lanzó.
- El código generado por los modelos se ejecuta **siempre aislado** (subproceso, timeout, sin stdin, directorio temporal, sin red). Nunca `exec()` en el servidor.
- No subir al repositorio: base de datos, resultados reales, modelos, rutas personales, tokens.

## Entorno y sincronización

- El vault se sincroniza con **Syncthing**. `.venv`, `node_modules`, `dist`, `data/` y `*.db*` van en `.gitignore` **y** en `.stignore`. La base de datos vive en `data/` (ignorada) o fuera del vault con `ARENA_DATA_DIR`.
- `C:` tiene poco espacio: instalar Python, Node, entornos y modelos en `D:` (como la toolchain de Rust en `D:\dev-tools\`).
- Funciona en **Windows y Linux**: `pathlib`, sin rutas con `\` fijas, scripts `.bat` y `.sh`.

## Forma de trabajar

1. Una fase cada vez, en orden. No pasar de fase sin cumplir sus criterios de aceptación.
2. Un commit por hito, en español (`feat:`, `fix:`, `chore:`). Tests para los cálculos (energía, degradación, normalización de respuestas, comparabilidad) y para los tres **perfiles de hardware simulados**.
3. Sin GPU, desarrollar con el agente simulado y un `llama-server` simulado.
4. Interfaz: seguir `docs/GUI-DISENO.md`. Revisar capturas en 1440 px y en un portátil pequeño; `prefers-reduced-motion`, foco visible, contraste AA y estados que no dependan solo del color.
5. Al cerrar cada fase: actualizar `ESTADO.md`, marcar los criterios en `docs/HOJA-DE-RUTA.md` y **añadir una línea a `log.md` del vault**:
   `- [YYYY-MM-DD HH:MM] — Claude → 03 - PROYECTOS TEC/Arena LLM/…: qué se hizo.`

## Comandos (rellenar en la Fase 1)

```bash
# agente
python -m agent --simulate nvidia2     # perfiles: nvidia2 | cpu-only | partial
# servidor
python -m server
# web
npm run dev --prefix web
# tests
pytest && npm test --prefix web
```
