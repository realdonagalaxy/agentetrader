"""Estremi della struttura = doppi massimi / doppi minimi (equal highs / equal lows).

Doppio massimo: due swing high (pivot a `n` barre per lato) con differenza <= tol * ATR(14) al secondo pivot,
distanti tra min_sep e max_sep barre, senza nessun massimo intermedio più alto di entrambi oltre la tolleranza.
Il secondo pivot è confermato solo `n` barre dopo (nessun look-ahead): `confirmed` è il tempo di conferma.
Parametri tol/min_sep/max_sep PROVVISORI, da decidere guardando i dati.
"""
import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def pivots(df: pd.DataFrame, n: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Indici (posizionali) dei pivot high e low confermati."""
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    ph, pl = [], []
    for i in range(n, len(df) - n):
        if hi[i] == hi[i - n:i + n + 1].max() and (hi[i - n:i] < hi[i]).all():
            ph.append(i)
        if lo[i] == lo[i - n:i + n + 1].min() and (lo[i - n:i] > lo[i]).all():
            pl.append(i)
    return np.array(ph), np.array(pl)


def double_extremes(df: pd.DataFrame, n: int = 2, tol: float = 0.25, min_sep: int = 4, max_sep: int = 48) -> pd.DataFrame:
    """Una riga per ogni doppio massimo/minimo: kind, level, t1, t2, confirmed.

    Per ogni pivot j si cerca il pivot precedente più vicino i (a distanza min_sep..max_sep barre) con livello entro
    la tolleranza e senza nessuna barra intermedia oltre il livello (+ tolleranza): equal highs/lows anche con
    pivot minori in mezzo.
    """
    a = atr(df).to_numpy()
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    ph, pl = pivots(df, n)
    rows = []
    for kind, piv, arr in (("top", ph, hi), ("bottom", pl, lo)):
        sign = 1 if kind == "top" else -1
        for k, j in enumerate(piv):
            if np.isnan(a[j]):
                continue
            tolerance = tol * a[j]
            for m in range(k - 1, -1, -1):
                i = piv[m]
                if j - i > max_sep:
                    break
                if j - i < min_sep:
                    continue
                level = max(arr[i], arr[j]) if kind == "top" else min(arr[i], arr[j])
                if abs(arr[i] - arr[j]) > tolerance:
                    continue
                between = arr[i + 1:j]
                if len(between) and (sign * (between.max() if kind == "top" else between.min()) > sign * level + tolerance):
                    continue
                rows.append({"kind": kind, "level": level, "t1": df.index[i], "t2": df.index[j],
                             "confirmed": df.index[min(j + n, len(df) - 1)]})
                break
    return pd.DataFrame(rows)
