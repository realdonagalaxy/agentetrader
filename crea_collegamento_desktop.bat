@echo off
setlocal
REM Crea sul Desktop il collegamento "Gestione Conti" (app desktop, con il logo, senza finestra nera). Da lanciare una volta sola, dopo setup_windows.bat.
set CARTELLA=%~dp0
if not exist "%CARTELLA%.venv\Scripts\pythonw.exe" (
  echo ERRORE: non trovo l'ambiente Python del progetto ^(.venv^). Lancia prima setup_windows.bat
  pause
  exit /b 1
)
"%CARTELLA%.venv\Scripts\python.exe" -m pip install -q -r "%CARTELLA%requirements.txt"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Gestione Conti.lnk'); $s.TargetPath='%CARTELLA%.venv\Scripts\pythonw.exe'; $s.Arguments='-m src.desktop_app'; $s.WorkingDirectory='%CARTELLA%'; $s.IconLocation='%CARTELLA%src\web\app.ico'; $s.Description='Gestione Conti'; $s.Save()"
if errorlevel 1 (
  echo ERRORE nella creazione del collegamento.
  pause
  exit /b 1
)
echo Fatto: sul Desktop trovi il collegamento "Gestione Conti". Doppio clic per aprire l'app.
echo Se non si apre, lancia avvia_desktop.bat: mostra l'errore.
pause
