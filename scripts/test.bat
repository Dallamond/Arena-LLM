@echo off
rem Ejecuta la suite de tests de Python.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m pytest %*
