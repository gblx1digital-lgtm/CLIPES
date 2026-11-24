@echo off
title Clipes - Instalacao
cd /d "%~dp0"
echo.
echo ================================================
echo   CLIPES - Instalacao (so precisa fazer 1 vez)
echo ================================================
echo.

set PRECISA_REABRIR=
where py >nul 2>nul
if errorlevel 1 (
  echo Instalando Python...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  set PRECISA_REABRIR=1
)
where node >nul 2>nul
if errorlevel 1 (
  echo Instalando Node.js...
  winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
  set PRECISA_REABRIR=1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo Instalando FFmpeg...
  winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
  set PRECISA_REABRIR=1
)
if defined PRECISA_REABRIR (
  echo.
  echo ------------------------------------------------
  echo  Programas instalados.
  echo  FECHE esta janela e clique duas vezes em
  echo  "instalar.bat" DE NOVO para continuar.
  echo ------------------------------------------------
  pause
  exit /b
)

echo [1/4] Preparando o Python...
if not exist .venv (
  py -3 -m venv .venv || goto erro
)
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r backend\requirements.txt || goto erro

echo [2/4] Preparando o painel...
cd frontend
call npm install || goto erro_front
call npm run build || goto erro_front
cd ..

echo [3/4] Criando arquivo de configuracao...
if not exist .env copy .env.example .env >nul

echo [4/4] Pronto!
echo.
echo ================================================
echo  INSTALACAO CONCLUIDA
echo.
echo  Vai abrir o Bloco de Notas com as configuracoes.
echo  Cole sua chave da Anthropic depois de
echo  ANTHROPIC_API_KEY=   , salve (Ctrl+S) e feche.
echo.
echo  Depois clique duas vezes em "iniciar.bat".
echo ================================================
echo.
pause
notepad .env
exit /b

:erro_front
cd ..
:erro
echo.
echo *** Algo deu errado. Tire um print desta janela e envie. ***
pause
