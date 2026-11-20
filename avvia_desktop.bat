@echo off
setlocal
title Gestione Conti (desktop)
REM Avvia l'app desktop con la finestra nera visibile (utile per vedere gli errori). L'uso normale e il collegamento sul Desktop, senza finestra nera.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERRORE: non trovo l'ambiente Python del progetto ^(.venv^). Lancia prima setup_windows.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
".venv\Scripts\python.exe" -m src.desktop_app %*
echo.
echo L'app si e fermata. Se vedi un errore qui sopra, copialo e mandamelo.
pause
