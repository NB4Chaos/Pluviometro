@echo off
rem Inicia o Monitor de calibracao de pluviometros (Elus) e abre o navegador.
rem Pode ser executado de qualquer lugar: usa a pasta onde este arquivo esta.
setlocal
cd /d "%~dp0"
title Elus - Monitor de calibracao de pluviometros
set "PY="
if exist "..\.venv\Scripts\python.exe" set "PY=..\.venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if defined PY goto run
echo Nao encontrei o ambiente Python .venv nesta pasta nem na pasta acima.
echo Crie com:  python -m venv .venv  e depois  .venv\Scripts\python.exe -m pip install -r requirements.txt
pause
exit /b 1
:run
echo Servidor: %PY% app.py
echo Abrindo http://127.0.0.1:5000 em 3 segundos. Feche esta janela para parar o servidor.
start /min "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:5000"
"%PY%" app.py
echo.
echo O servidor parou. Veja as mensagens acima.
pause
