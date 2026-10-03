@echo off
rem Para los procesos de Arena (agentes, servidor y llama-server simulados: "python -m agent|server...").
rem No toca llama-server reales.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match ' -m (agent|server)( |$|\.fakes)' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('parado ' + $_.ProcessId) }"
