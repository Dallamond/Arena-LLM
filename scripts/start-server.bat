@echo off
rem Arranca el servidor Arena (API + web compilada). Ejemplo: scripts\start-server.bat --agent http://127.0.0.1:9100
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (
    echo Falta .venv: ejecuta scripts\setup.bat
    exit /b 1
)
.venv\Scripts\python.exe -m server %*
