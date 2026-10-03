@echo off
rem Arranca el agente. Solo necesita Python 3.11+ (stdlib). Ejemplo: scripts\start-agent.bat --simulate nvidia2
rem Usa .venv si existe; si no, el lanzador py (variable ARENA_PY para elegir version, p. ej. 3.12).
cd /d "%~dp0.."
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe -m agent %*
) else if defined ARENA_PY (
    py -%ARENA_PY% -m agent %*
) else (
    py -3 -m agent %*
)
