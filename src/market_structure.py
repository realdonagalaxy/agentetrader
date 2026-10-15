"""Trend dalla struttura di mercato (HH/HL, LH/LL) su H4 e H1.

Swing = pivot frazionale: massimo/minimo della barra i su una finestra di
`swing_n` barre per lato. Un pivot è noto solo `swing_n` barre dopo (nessun look-ahead).
Trend: ultimi due swing high e ultimi due swing low
  HH + HL -> "UP" | LH + LL -> "DOWN" | altrimenti "RANGE".
swing_n=2 è un valore PROVVISORIO, da confermare.
"""
import pandas as pd

SWING_N = 2


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """df con colonne open/high/low/close e indice datetime -> barre `rule` (es. '1h', '4h')."""
    return df.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()


def swing_points(df: pd.DataFrame, n: int = SWING_N) -> tuple[list[float], list[float]]:
    """(swing_highs, swing_lows) in ordine temporale, solo pivot confermati."""
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    highs, lows = [], []
    for i in range(n, len(df) - n):
        if hi[i] == hi[i - n:i + n + 1].max() \
                and (hi[i - n:i] < hi[i]).all():
            highs.append(hi[i])
        if lo[i] == lo[i - n:i + n + 1].min() and (lo[i - n:i] > lo[i]).all():
            lows.append(lo[i])
    return highs, lows


def trend(df: pd.DataFrame, n: int = SWING_N) -> str:
    highs, lows = swing_points(df, n)
    if len(highs) < 2 or len(lows) < 2:
        return "RANGE"
    hh, hl = highs[-1] > highs[-2], lows[-1] > lows[-2]
    lh, ll = highs[-1] < highs[-2], lows[-1] < lows[-2]
    return "UP" if hh and hl else "DOWN" if lh and ll else "RANGE"


def multi_tf_trend(df_h1: pd.DataFrame, n: int = SWING_N) -> dict:
    """df_h1: barre OHLC H1 fino all'istante di analisi. H4 ottenuto per resample."""
    h4, h1 = trend(resample_ohlc(df_h1, "4h"), n), trend(df_h1, n)
    bias = h4 if h4 == h1 else "MISTO"
    return {"H4": h4, "H1": h1, "bias": bias}


def is_countertrend(side: str, bias: str) -> bool:
    """True se il trade è contro il bias (buy in DOWN, sell in UP). MISTO/RANGE -> False."""
    return (side.lower() == "buy" and bias == "DOWN") or (side.lower() == "sell" and bias == "UP")
