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

> Leer al retomar. Última actualización: 03/10/2026.

## Resumen

- **F1 (esqueleto y agente):** hecha salvo el paso 8. Falta verificar la detección con un `llama-server` real, porque llama.cpp aún no está instalado.
- **F2 (GUI base):** hecha. Pendiente de la opinión de Lucas sobre el diseño. Ajustes con subnavegación llega en F3.
- **Siguiente:** F3 (servidores, modelos y detección), cuando Lucas revise la GUI e instale llama.cpp.

## F1 — Esqueleto y agente

| # | Hito | Estado |
|---|---|---|
| 1 | Esqueleto del repositorio | ✅ |
| 2 | Contrato del agente y servidor HTTP | ✅ |
| 3 | Proveedor CPU/RAM | ✅ |
| 4 | Proveedor NVIDIA | ✅ probado con la RTX 3060 |
| 5 | Perfiles de hardware simulados | ✅ |
| 6 | Detección de llama-server | ✅ con procesos simulados · ⏳ falta uno real |
| 7 | Lector de cabecera GGUF | ✅ probado con Qwen2.5 7B/14B, Qwen3.5 9B y un mmproj |
| 8 | Cierre de F1 en el PC real | ⏳ necesita llama.cpp |

## F2 — GUI base

- Servidor FastAPI en el **puerto 8090** (8080 es el de llama-server). Sondea cada agente cada segundo y retransmite por SSE.
- Web Vue 3 + Vite + TS, con estilo blueprint y fuentes locales.
- Pantallas y elementos:
  - Franja del equipo plegable.
  - Barra superior con chips de estado y selector de equipo.
  - Menú lateral plegable con VRAM/RAM en el pie.
  - Panel con ficha del equipo, medidores radiales y servidores detectados.
  - Resto de pantallas como marcadores de su fase.
- Capturas revisadas a 1440 px y 1100 px, con agente real, agente simulado y agente caído.

## F0 — parcial

- [x] RAM real comprobada: 16 GB (2 × 8 GB Kingston Fury 3200 a 2400 MHz; XMP desactivado)
- [x] Python 3.12, Node 24 y git disponibles (Python y Node están en `C:`; los entornos, en `D:`)
- [x] `nvidia-smi --query-compute-apps` en WDDM: da la GPU por proceso, pero la VRAM sale `[N/A]` (plan B confirmado)
- [ ] XMP activado
- [ ] llama.cpp (CUDA 12.x) instalado en `D:\dev-tools\llama.cpp\`
- [ ] M40 instalada con driver R580 (llega la semana del 05/10/2026)
- [ ] `llama-bench` y `llama-server` verificados en cada tarjeta

## Cómo probar

```bat
scripts\setup.bat            :: .venv con dependencias (una vez)
scripts\build-web.bat        :: compila la web (una vez y tras cambios en web/)
scripts\demo.bat D:\ollama\models
```

`demo.bat` arranca:
- El agente real (9100).
- Un agente simulado con dos GPU (9101).
- El servidor (8090).

Después abre http://127.0.0.1:8090.

Desarrollo de la web con recarga en caliente: `npm run dev --prefix web` (http://127.0.0.1:5173, con el servidor en marcha).

## Entorno y avisos

- `.venv` usa Python 3.12. El comando `python` de Windows es el atajo de la Store.
- ⚠️ `py -3` apunta a un Python 3.14 registrado en `D:\python.exe` que **ya no existe**. Es una entrada huérfana en `HKCU\Software\Python\PythonCore\3.14`, y por eso los scripts usan `.venv` o `ARENA_PY`. Pendiente de Lucas: reinstalar 3.14 o borrar esa entrada.
- npm: Claude usó `npm_config_cache=D:/dev-tools/npm-cache` para no llenar `C:`. Para dejarlo fijo: `npm config set cache D:\dev-tools\npm-cache`.
- TypeScript fijado en 5.9 por precaución: no he comprobado si la 7 (compilador nativo) funciona con `vue-tsc`.
- Remoto: https://github.com/Dallamond/Arena-LLM (privado).

## Aprendido (para F3 y siguientes)

- Los modelos híbridos (`qwen35`) tienen KV solo en algunas capas (`full_attention_interval`). La calculadora de encaje no puede suponer KV en todas.
- Los `mmproj` (`general.type = mmproj`) no son modelos.
- Listar procesos con PowerShell CIM tarda unos 0,5 s; el agente lo cachea 2 s.
- `nvidia-smi` tarda unos 60 ms por muestra, sin problema a 1 Hz.
