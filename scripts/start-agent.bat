@echo off
rem Arranca el agente. Solo necesita Python 3.11+ (sin .venv). Ejemplo: scripts\start-agent.bat --simulate nvidia2
cd /d "%~dp0.."
py -3 -m agent %*
