@echo off
rem Abre o monitor como aplicativo (janela propria, sem barra de endereco) no Edge ou no Chrome.
rem O servidor precisa estar rodando (iniciar.bat).
set "URL=http://127.0.0.1:5000"
set "B=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if exist "%B%" goto go
set "B=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if exist "%B%" goto go
set "B=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%B%" goto go
set "B=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if exist "%B%" goto go
start "" %URL%
exit /b 0
:go
start "" "%B%" --app=%URL%
