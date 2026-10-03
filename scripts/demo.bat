@echo off
rem Arranca todo para probar: agente real (9100), agente simulado nvidia2 (9101) y servidor (8090).
rem Uso: scripts\demo.bat [carpeta de modelos GGUF]
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe ( echo Falta .venv: ejecuta scripts\setup.bat & exit /b 1 )
if not exist web\dist\index.html ( echo Falta la web compilada: ejecuta scripts\build-web.bat & exit /b 1 )
set MODELS=
if not "%~1"=="" set MODELS=--models-dir "%~1"
start "Arena - agente" .venv\Scripts\python.exe -m agent --port 9100 %MODELS%
start "Arena - agente simulado" .venv\Scripts\python.exe -m agent --port 9101 --simulate nvidia2
timeout /t 2 /nobreak >nul
start "Arena - servidor" .venv\Scripts\python.exe -m server --agent http://127.0.0.1:9100 --agent http://127.0.0.1:9101
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8090/
echo Arena en http://127.0.0.1:8090 - cierra las tres ventanas para parar.
