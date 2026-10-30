@echo off
rem Cria na Area de Trabalho os atalhos "Elus Monitor" (inicia e abre) e "Parar Elus Monitor", com o icone da Elus.
set "P=%~dp0"
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($d+'\Elus Monitor.lnk'); $s.TargetPath='wscript.exe'; $s.Arguments='\"%P%iniciar_oculto.vbs\"'; $s.WorkingDirectory='%P%'; $s.IconLocation='%P%static\img\elus.ico'; $s.Description='Monitor de calibracao de pluviometros'; $s.Save(); $s=$w.CreateShortcut($d+'\Parar Elus Monitor.lnk'); $s.TargetPath='%P%parar.bat'; $s.WorkingDirectory='%P%'; $s.IconLocation='%P%static\img\elus.ico'; $s.WindowStyle=7; $s.Save(); Write-Host 'Atalhos criados na Area de Trabalho.'"
pause
