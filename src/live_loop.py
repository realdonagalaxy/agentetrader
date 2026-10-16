"""Ciclo in tempo reale: ogni 5 minuti legge le candele M5 da MetaTrader 5 e manda gli avvisi su Telegram.

Uso (su Windows, con il terminale MT5 acceso):
  python -m src.live_loop --symbol XAUUSD --send
  python -m src.live_loop --symbol XAUUSD --once          # un solo controllo, senza ripetere

--symbol è il nome usato nel journal e nei messaggi; il nome sul broker (es. GOLD, XAUUSD.m) va in MT5_SYMBOL di config.env.
Gli avvisi sono registrati una sola volta nel journal (niente doppioni se il ciclo riparte).
"""
import argparse
import os
import time
import traceback
from pathlib import Path

import pandas as pd

from src import alert_journal as aj
from src.assistant import run_once
from src.mt5_feed import connect, fetch_m5


def seconds_to_next_bar(now: float | None = None, lag: int = 8) -> float:
    """Secondi fino a `lag` secondi dopo la prossima chiusura di candela M5."""
    now = time.time() if now is None else now
    return (300 - now % 300) + lag


def check(sym: str, bot, journal: Path, mt5, broker_symbol: str, tf: int = 5, chart_dir=None) -> list[str]:
    m5 = fetch_m5(broker_symbol, mt5=mt5)
    return run_once(sym, m5, tf, journal, bot, True, chart_dir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--journal", default=str(aj.PATH))
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--chart-dir")
    a = ap.parse_args()
    bot = None
    if a.send:
        from src.telegram_bot import TelegramBot
        bot = TelegramBot()
    mt5 = connect()
    broker_symbol = os.environ.get("MT5_SYMBOL", a.symbol)
    print(f"Collegato a MT5. Strumento: {broker_symbol}. Controllo ogni 5 minuti (Ctrl+C per fermare).", flush=True)
    while True:
        try:
            for m in check(a.symbol, bot, Path(a.journal), mt5, broker_symbol, chart_dir=a.chart_dir):
                print(f"\n[{pd.Timestamp.utcnow():%Y-%m-%d %H:%M} UTC]\n{m}", flush=True)
        except Exception as e:                      # un errore (rete, terminale chiuso...) non deve fermare il ciclo
            print(f"[{pd.Timestamp.utcnow():%H:%M} UTC] errore: {e}", flush=True)
            if os.environ.get("LIVE_LOOP_TRACE"):
                traceback.print_exc()
        if a.once:
            break
        time.sleep(seconds_to_next_bar())
