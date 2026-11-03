@echo off
setlocal
title Gestione Conti - non chiudere questa finestra
REM Avvia Gestione Conti (server locale) e apre il browser. Se e gia in esecuzione, apre solo il browser.
cd /d "%~dp0"
set PORTA=47951

curl -s -o nul --max-time 2 http://127.0.0.1:%PORTA%/ >nul 2>&1
if not errorlevel 1 (
  echo Gestione Conti e gia in esecuzione: apro il browser.
  start "" http://127.0.0.1:%PORTA%
  exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
  echo ERRORE: non trovo l'ambiente Python del progetto ^(.venv^).
  echo Lancia prima  setup_windows.bat  nella cartella del progetto.
  pause
  exit /b 1
)

echo Avvio Gestione Conti su http://127.0.0.1:%PORTA% ...
echo Lascia aperta questa finestra: chiudendola il programma si ferma.
echo.
".venv\Scripts\python.exe" -m src.accounts_web --port %PORTA%
echo.
echo Gestione Conti si e fermato. Se vedi un errore qui sopra, copialo e mandamelo.
pause
