@echo off
rem Instala dependencias de la web y la compila en web\dist (la sirve el servidor).
cd /d "%~dp0..\web"
call npm install || exit /b 1
call npm run build || exit /b 1
echo Web compilada en web\dist
