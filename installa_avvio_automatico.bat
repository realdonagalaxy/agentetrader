@echo off
setlocal
REM L'app desktop parte da sola quando accedi a Windows, ridotta nell'area di notifica (con l'ascolto dei segnali).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo ERRORE: non trovo l'ambiente Python del progetto ^(.venv^). Lancia prima setup_windows.bat
  pause
  exit /b 1
)
set "DEST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Gestione Conti.lnk"
set "OLD=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Ascolto segnali.lnk"
if exist "%OLD%" del "%OLD%"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:DEST); $s.TargetPath='%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments='-m src.desktop_app --nascosto'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0src\web\app.ico'; $s.Save()"
if exist "%DEST%" (
  echo Fatto: l'app partira da sola ad ogni accesso a Windows, ridotta nell'area di notifica.
  echo Il vecchio avvio dell'ascolto ^(Ascolto segnali.lnk^) e stato tolto: l'app avvia gia l'ascolto da sola.
  echo Per toglierlo cancella il file:  %DEST%
) else (
  echo ERRORE: collegamento non creato.
)
pause
