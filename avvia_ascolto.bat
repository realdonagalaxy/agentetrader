@echo off
setlocal
title Ascolto segnali - non chiudere questa finestra
REM Tiene sempre acceso il listener dei segnali (canale Telegram -> conti demo). Se si ferma o va in errore lo riavvia dopo 15 secondi.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERRORE: non trovo l'ambiente Python del progetto ^(.venv^). Lancia prima setup_windows.bat
  pause
  exit /b 1
)
set PYTHONUTF8=1
:ciclo
echo [%date% %time%] Avvio ascolto segnali...
".venv\Scripts\python.exe" -m src.mt5_orders %*
echo [%date% %time%] Ascolto fermato o in errore: riparto tra 15 secondi. Chiudi la finestra per fermarlo.
timeout /t 15 /nobreak >nul
goto ciclo
