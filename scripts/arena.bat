@echo off
rem Un clic: arranca el agente real y el servidor de Arena (si no estan ya) y abre la GUI en Chrome.
rem Cierra las dos ventanas minimizadas "Arena - agente" y "Arena - servidor" para parar (o scripts\stop.bat).
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe ( echo Falta .venv: ejecuta scripts\setup.bat & pause & exit /b 1 )
if not exist web\dist\index.html ( echo Falta la web compilada: ejecuta scripts\build-web.bat & pause & exit /b 1 )

netstat -ano | findstr /R /C:":9100 .*LISTENING" >nul || start "Arena - agente" /min .venv\Scripts\python.exe -m agent --port 9100
netstat -ano | findstr /R /C:":8090 .*LISTENING" >nul || (
    ping -n 3 127.0.0.1 >nul
    start "Arena - servidor" /min .venv\Scripts\python.exe -m server --agent http://127.0.0.1:9100
)

rem Espera a que el servidor responda (hasta ~20 s) y abre Chrome
for /L %%i in (1,1,20) do (
    curl -s -o nul http://127.0.0.1:8090/ && goto abrir
    ping -n 2 127.0.0.1 >nul
)
:abrir
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
    start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" http://127.0.0.1:8090/
) else (
    start "" http://127.0.0.1:8090/
)
