@echo off
setlocal
title Installazione terminali MT5 portable
REM Crea terminali MT5 PORTABLE separati, uno per conto, copiando SEMPRE la stessa installazione di origine.
REM L'installazione originale NON viene toccata. Se la cartella di destinazione esiste gia, viene saltata.
REM Uso:  installa_terminali.bat                      crea FundedNext e ActivTrades
REM       installa_terminali.bat Nome1 Nome2 Nome3    crea i terminali con i nomi indicati (uno per conto)
set SORGENTE=C:\Program Files\MetaTrader 5
set BASE=C:\MT5
set LOG=%~dp0installa_terminali.log
echo Inizio %date% %time% > "%LOG%"

echo Cartella di destinazione: %BASE%
if not exist "%BASE%" mkdir "%BASE%" 2>>"%LOG%"
if not exist "%BASE%" (
  echo Non riesco a creare %BASE%. Provo con %USERPROFILE%\MT5
  set BASE=%USERPROFILE%\MT5
  mkdir "%USERPROFILE%\MT5" 2>>"%LOG%"
)
if not exist "%BASE%" (
  echo ERRORE: non riesco a creare nessuna cartella di destinazione. Prova a lanciare il file come amministratore.
  echo ^(tasto destro sul file ^> Esegui come amministratore^)
  pause
  exit /b 1
)

set NOMI=%*
if "%NOMI%"=="" set NOMI=FundedNext ActivTrades
for %%N in (%NOMI%) do call :copia %%N "%SORGENTE%"

echo.
echo ================= FINE =================
echo Terminali creati in: %BASE%
dir /b "%BASE%"
echo.
echo Percorsi da scrivere in Gestione Conti ^(Modifica conto, campo Percorso del terminale^):
echo   FundedNext : %BASE%\FundedNext\terminal64.exe
echo   ActivTrades: %BASE%\ActivTrades\terminal64.exe
echo.
echo Passi successivi:
echo   1. Apri dal Desktop "MT5 FundedNext" e accedi al conto ^(File ^> Accedi al conto di trading, spunta Salva password^). Poi chiudilo.
echo   2. Fai lo stesso con "MT5 ActivTrades".
echo   3. In Gestione Conti metti per ogni conto il percorso qui sopra.
echo.
echo Registro dettagliato: %LOG%
pause
exit /b 0

:copia
set "NOME=%~1"
set "SRC=%~2"
set "DST=%BASE%\%NOME%"
echo.
echo [%NOME%] origine: %SRC%
if not exist "%SRC%\terminal64.exe" (
  echo [%NOME%] ERRORE: non trovo terminal64.exe in "%SRC%". Correggi il percorso in questo file.
  echo [%NOME%] origine non trovata >> "%LOG%"
  exit /b 1
)
if exist "%DST%\terminal64.exe" goto :gia
echo [%NOME%] copio in %DST% ^(puo richiedere un minuto^)...
robocopy "%SRC%" "%DST%" /E /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1
if errorlevel 8 (
  echo [%NOME%] ERRORE durante la copia. Vedi %LOG%
  exit /b 1
)
goto :marca
:gia
echo [%NOME%] gia presente in %DST%: salto la copia.
:marca
echo portable> "%DST%\portable.flag"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\MT5 %NOME%.lnk'); $s.TargetPath='%DST%\terminal64.exe'; $s.Arguments='/portable'; $s.WorkingDirectory='%DST%'; $s.Save()" >> "%LOG%" 2>&1
echo [%NOME%] pronto: collegamento "MT5 %NOME%" sul Desktop.
exit /b 0
