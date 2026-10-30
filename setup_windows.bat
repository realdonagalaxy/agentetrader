@echo off
REM Installazione su Windows 11: ambiente Python e librerie del progetto (MT5 in sola lettura).
REM Prerequisiti: Python 3.12 da python.org (NON 3.13 o superiori) (spunta "Add python.exe to PATH"), Git, MetaTrader 5 installato e collegato al conto DEMO.
cd /d "%~dp0"
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo ERRORE: serve Python 3.12 ^(il pacchetto MetaTrader5 non supporta le versioni piu recenti^). Installalo da python.org/downloads/release/python-3129/ e rilancia.
  pause
  exit /b 1
)
if not exist .venv py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo ERRORE nell'installazione: copia le ultime righe e mandale.
  pause
  exit /b 1
)
if not exist config.env copy config.env.example config.env
echo.
echo Fatto. Ora apri config.env con il Blocco note e compila TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID e MT5_SYMBOL.
echo Poi prova con:  .venv\Scripts\python -m src.live_loop --symbol XAUUSD --once
pause
