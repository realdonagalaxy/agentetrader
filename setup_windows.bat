@echo off
REM Installazione su Windows 11: ambiente Python e librerie del progetto (MT5 in sola lettura).
REM Prerequisiti: Python 3.11+ da python.org (spunta "Add python.exe to PATH"), Git, MetaTrader 5 installato e collegato al conto DEMO.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist config.env copy config.env.example config.env
echo.
echo Fatto. Ora apri config.env con il Blocco note e compila TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID e MT5_SYMBOL.
echo Poi prova con:  .venv\Scripts\python -m src.live_loop --symbol XAUUSD --once
pause
