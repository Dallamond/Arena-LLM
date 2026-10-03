@echo off
rem Crea .venv con Python 3.11+ e instala las dependencias de desarrollo.
rem Uso: scripts\setup.bat [version]   (por defecto 3.12)
setlocal
cd /d "%~dp0.."
set PYVER=%1
if "%PYVER%"=="" set PYVER=3.12
if not exist .venv\Scripts\python.exe (
    py -%PYVER% -m venv .venv || exit /b 1
)
.venv\Scripts\python.exe -m pip install --no-cache-dir --upgrade pip || exit /b 1
.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements-dev.txt || exit /b 1
echo Entorno listo en .venv
