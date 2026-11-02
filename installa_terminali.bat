@echo off
setlocal
REM Crea terminali MT5 PORTABLE separati, uno per conto, copiando le installazioni che hai gia.
REM Le installazioni originali NON vengono toccate. Se la cartella di destinazione esiste gia, viene saltata.
REM Modifica le due righe qui sotto se i tuoi percorsi sono diversi:   call :copia NOME "CARTELLA ORIGINALE"
set BASE=C:\MT5

if not exist "%BASE%" mkdir "%BASE%"
call :copia FundedNext "C:\Program Files\MetaTrader 5"
call :copia ActivTrades "C:\Program Files\ActivTrades Markets MetaTrader 5"

echo.
echo ================= FATTO =================
echo Percorsi da scrivere in Gestione Conti (Modifica conto, campo Percorso del terminale):
echo   FundedNext : %BASE%\FundedNext\terminal64.exe
echo   ActivTrades: %BASE%\ActivTrades\terminal64.exe
echo.
echo Passi successivi:
echo   1. Apri dal Desktop il collegamento "MT5 FundedNext" e accedi al conto (File ^> Accedi al conto di trading, spunta "Salva password"). Poi chiudilo.
echo   2. Fai lo stesso con "MT5 ActivTrades".
echo   3. In Gestione Conti metti per ogni conto il percorso qui sopra.
pause
exit /b 0

:copia
set NOME=%~1
set SRC=%~2
set DST=%BASE%\%NOME%
if not exist "%SRC%\terminal64.exe" (
  echo [%NOME%] ERRORE: non trovo "%SRC%\terminal64.exe". Correggi il percorso in questo file.
  exit /b 1
)
if exist "%DST%\terminal64.exe" (
  echo [%NOME%] gia presente in %DST%: salto la copia.
) else (
  echo [%NOME%] copio "%SRC%" in "%DST%" ...
  robocopy "%SRC%" "%DST%" /E /NFL /NDL /NJH /NJS /NP >nul
  if errorlevel 8 (
    echo [%NOME%] ERRORE durante la copia.
    exit /b 1
  )
)
REM marcatore: dice a Gestione Conti di avviare questo terminale in modalita portable
if not exist "%DST%\portable.flag" echo portable> "%DST%\portable.flag"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\MT5 %NOME%.lnk'); $s.TargetPath='%DST%\terminal64.exe'; $s.Arguments='/portable'; $s.WorkingDirectory='%DST%'; $s.Save()"
echo [%NOME%] pronto: collegamento "MT5 %NOME%" sul Desktop.
exit /b 0
