@echo off
setlocal
REM Crea un collegamento nella cartella Esecuzione automatica di Windows: l'ascolto dei segnali parte da solo quando accedi al PC (finestra ridotta a icona).
cd /d "%~dp0"
set "DEST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Ascolto segnali.lnk"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:DEST); $s.TargetPath='%~dp0avvia_ascolto.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
if exist "%DEST%" (
  echo Fatto: l'ascolto dei segnali partira da solo ad ogni accesso a Windows.
  echo Per toglierlo cancella il file:  %DEST%
) else (
  echo ERRORE: collegamento non creato.
)
pause
