@echo off
title Clipes
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Rode primeiro o arquivo "instalar.bat".
  pause
  exit /b
)
echo Iniciando o Clipes...
start "Clipes - Servidor (nao feche)" /min cmd /k "cd backend && ..\.venv\Scripts\python -m uvicorn app.main:app --port 8000"
start "Clipes - Processador (nao feche)" /min cmd /k "cd backend && ..\.venv\Scripts\python -m app.worker.main"
timeout /t 6 /nobreak >nul
start "" http://localhost:8000
echo.
echo O painel abriu no navegador: http://localhost:8000
echo Para desligar, feche as janelas "Clipes - Servidor" e "Clipes - Processador".
timeout /t 8 >nul
