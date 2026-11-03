@echo off
setlocal
REM Crea sul Desktop il collegamento "Gestione Conti" che avvia il programma. Da lanciare una volta sola.
set CARTELLA=%~dp0
set DESTINAZIONE=%CARTELLA%avvia_gestione_conti.bat
if not exist "%DESTINAZIONE%" (
  echo ERRORE: non trovo %DESTINAZIONE%
  pause
  exit /b 1
)
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Gestione Conti.lnk'); $s.TargetPath='%DESTINAZIONE%'; $s.WorkingDirectory='%CARTELLA%'; $s.Description='Avvia Gestione Conti'; $s.Save()"
if errorlevel 1 (
  echo ERRORE nella creazione del collegamento.
  pause
  exit /b 1
)
echo Fatto: sul Desktop trovi il collegamento "Gestione Conti". Fai doppio clic per avviare il programma.
pause
