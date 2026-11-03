@echo off
setlocal
title Gestione Conti - non chiudere questa finestra
REM Avvia Gestione Conti (server locale) e apre il browser. Se e gia in esecuzione, apre solo il browser.
cd /d "%~dp0"
set PORTA=8080

curl -s --max-time 2 http://127.0.0.1:%PORTA%/ 2>nul | findstr /c:"Gestione Conti" >nul
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

echo Avvio Gestione Conti: provo la porta %PORTA%, se e occupata ne usa un'altra e apre il browser da solo ...
echo Lascia aperta questa finestra: chiudendola il programma si ferma.
echo.
".venv\Scripts\python.exe" -m src.accounts_web
echo.
echo Gestione Conti si e fermato. Se vedi un errore qui sopra, copialo e mandamelo.
pause
