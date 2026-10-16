"""Prezzi in tempo reale da MetaTrader 5 (pacchetto ufficiale `MetaTrader5`).

SOLO LETTURA: il codice scarica le candele M5 e basta, non invia ordini (nessuna chiamata a order_send).
Il pacchetto Python di MetaTrader 5 funziona SOLO su Windows, con il terminale MT5 installato e acceso (account demo o reale, dati sola lettura).

Configurazione in config.env (mai su git):
  MT5_LOGIN, MT5_PASSWORD, MT5_SERVER   (facoltativi se il terminale è già collegato al conto)
  MT5_PATH                              (facoltativo: percorso di terminal64.exe)
  MT5_SYMBOL                            (nome dello strumento sul broker, es. XAUUSD, GOLD, XAUUSD.m)
  MT5_UTC_OFFSET_HOURS                  (facoltativo: differenza tra l'ora del server del broker e UTC, es. 2 o 3; se manca si prova a ricavarla)

Il tempo delle candele MT5 è l'ora del SERVER del broker (non UTC): qui viene convertito in UTC, come i dati usati nel backtest.
"""
import os
import time

import pandas as pd
from dotenv import load_dotenv

load_dotenv("config.env")


def _mt5():
    try:
        import MetaTrader5 as mt5
    except ImportError as e:
        raise RuntimeError("Pacchetto MetaTrader5 non disponibile: funziona solo su Windows (pip install MetaTrader5).") from e
    return mt5


def connect():
    """Collega il terminale MT5 (già installato). Restituisce il modulo mt5."""
    mt5 = _mt5()
    kw = {}
    if os.environ.get("MT5_PATH"):
        kw["path"] = os.environ["MT5_PATH"]
    if os.environ.get("MT5_LOGIN"):
        kw.update(login=int(os.environ["MT5_LOGIN"]), password=os.environ.get("MT5_PASSWORD", ""), server=os.environ.get("MT5_SERVER", ""))
    if not mt5.initialize(**kw):
        raise RuntimeError(f"MT5 non si collega: {mt5.last_error()}")
    return mt5


def utc_offset_seconds(mt5, symbol: str) -> int:
    """Secondi da togliere all'ora del server per avere UTC. Da MT5_UTC_OFFSET_HOURS, oppure dall'ultimo tick se il mercato è aperto."""
    env = os.environ.get("MT5_UTC_OFFSET_HOURS")
    if env not in (None, ""):
        return int(round(float(env) * 3600))
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"Strumento {symbol!r} non trovato su MT5: controlla MT5_SYMBOL e che sia visibile in Market Watch.")
    diff = tick.time - time.time()
    if abs(diff) > 15 * 3600 or abs(diff - round(diff / 1800) * 1800) > 600:
        raise RuntimeError("Non riesco a ricavare l'offset dell'ora del server (mercato chiuso?): imposta MT5_UTC_OFFSET_HOURS in config.env.")
    return int(round(diff / 1800) * 1800)


def rates_to_ohlc(rates, offset_s: int) -> pd.DataFrame:
    """Array di MT5 (time, open, high, low, close, tick_volume, ...) -> DataFrame M5 in UTC con colonna volume = volume tick."""
    df = pd.DataFrame(rates)
    df.index = pd.to_datetime(df["time"] - offset_s, unit="s")
    df.index.name = "time"
    df = df.rename(columns={"tick_volume": "volume"})[["open", "high", "low", "close", "volume"]].astype(float)
    return df[~df.index.duplicated()].sort_index()


def fetch_m5(symbol: str | None = None, bars: int = 8000, mt5=None) -> pd.DataFrame:
    """Ultime `bars` candele M5 CHIUSE (la candela in formazione viene scartata), in UTC."""
    mt5 = mt5 or connect()
    symbol = symbol or os.environ.get("MT5_SYMBOL", "XAUUSD")
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, bars)
    if rates is None or len(rates) < 100:
        raise RuntimeError(f"Nessun dato M5 per {symbol!r}: {mt5.last_error()}")
    df = rates_to_ohlc(rates, utc_offset_seconds(mt5, symbol))
    return df.iloc[:-1]                               # l'ultima è la candela corrente, non ancora chiusa
