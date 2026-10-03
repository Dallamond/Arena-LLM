@echo off
rem Arranca todo para probar: agente real (9100), agente simulado nvidia2 (9101) con dos llama-server simulados (18081, 18082) y servidor (8090).
rem Uso: scripts\demo.bat [carpeta de modelos GGUF]
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe ( echo Falta .venv: ejecuta scripts\setup.bat & exit /b 1 )
if not exist web\dist\index.html ( echo Falta la web compilada: ejecuta scripts\build-web.bat & exit /b 1 )
set MODELS=
if not "%~1"=="" set MODELS=--models-dir "%~1"
start "Arena - agente" .venv\Scripts\python.exe -m agent --port 9100 %MODELS%
start "Arena - agente simulado" .venv\Scripts\python.exe -m agent --port 9101 --simulate nvidia2
start "Arena - llama simulado 18081" /min .venv\Scripts\python.exe -m server.fakes.fake_llama --port 18081 --tps 45 --ctx 8192 --slots 2
start "Arena - llama simulado 18082" /min .venv\Scripts\python.exe -m server.fakes.fake_llama --port 18082 --tps 18 --ctx 16384 --slots 1
ping -n 3 127.0.0.1 >nul
start "Arena - servidor" .venv\Scripts\python.exe -m server --agent http://127.0.0.1:9100 --agent http://127.0.0.1:9101
ping -n 4 127.0.0.1 >nul
if not defined ARENA_NO_BROWSER start "" http://127.0.0.1:8090/
echo Arena en http://127.0.0.1:8090 - cierra las ventanas de Arena para parar.
