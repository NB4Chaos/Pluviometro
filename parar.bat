@echo off
rem Encerra o servidor do monitor (processo python/pythonw que roda app.py).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*app.py*' -and $_.Name -like 'python*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('Servidor encerrado (PID ' + $_.ProcessId + ')') }"
timeout /t 2 >nul
