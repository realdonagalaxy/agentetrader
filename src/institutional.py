"""Candela istituzionale con imbalance ancora da fillare (zona verso cui il prezzo può tornare).

Regole (utente): candela da M5 in su, quasi solo corpo (poche o nulle ombre), che lascia un imbalance e contiene ordini da fillare;
per un SELL la zona sta sopra il prezzo, per un BUY sotto.
ASSUNZIONI mie, da confermare: corpo >= BODY_ATR x ATR14 del suo timeframe; ombre totali <= WICK_FRAC del range;
timeframe M5..M30 (tutti i minuti se ci sono dati M1: M6, M7...; solo multipli di 5 con dati M5) + H1; imbalance = gap a 3 candele (FVG) lasciato dalla candela; "da fillare" = il prezzo non l'ha ancora coperto del tutto
(se già toccato in parte resta la parte non coperta); ricerca negli ultimi 5 giorni, si prende la zona più vicina al prezzo.
"""
import numpy as np
import pandas as pd

from src.data_loader import resample
from src.range_detector import atr

BODY_ATR = 1.5
WICK_FRAC = 0.20
TF_MIN = tuple(range(5, 31))                 # M5..M30 minuto per minuto (anche TF "nascosti" M6, M7...) + H1
TF_MIN_M5ONLY = (5, 10, 15, 20, 25, 30)      # senza dati M1 si possono costruire solo i multipli di 5
LOOKBACK = pd.Timedelta(days=5)


def find_zone(m5: pd.DataFrame, t_end, side: str, m1: pd.DataFrame | None = None) -> dict | None:
    """SELL -> candela ribassista con FVG ancora aperto sopra il prezzo; BUY -> candela rialzista con FVG sotto. Restituisce la più vicina."""
    t_end = pd.Timestamp(t_end)
    last = float(m5["close"].iloc[-1])
    best = None
    src = m1.loc[:t_end + pd.Timedelta(minutes=4)] if m1 is not None else m5
    tfs = [(f"M{n}", f"{n}min") for n in (TF_MIN if m1 is not None else TF_MIN_M5ONLY)] + [("H1", "1h")]
    for name, rule in tfs:
        df = src if rule == "1min" else resample(src, rule)
        step = pd.Timedelta(rule)
        df = df[df.index + step <= t_end + pd.Timedelta(minutes=5)]           # solo candele chiuse
        if len(df) < 20:
            continue
        a = atr(df).to_numpy()
        o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        idx = df.index
        for k in range(1, len(df) - 1):
            if idx[k] < t_end - LOOKBACK or not np.isfinite(a[k]):
                continue
            body, rng = abs(c[k] - o[k]), h[k] - l[k]
            if rng <= 0 or body < BODY_ATR * a[k] or (rng - body) > WICK_FRAC * rng:
                continue
            if side == "sell" and c[k] < o[k] and h[k + 1] < l[k - 1]:       # SELL: gap ribassista sopra il prezzo (offerta da fillare)
                g_lo, g_hi = h[k + 1], l[k - 1]
                reach = m5.loc[idx[k + 1] + step:, "high"].max() if idx[k + 1] + step <= m5.index[-1] else -np.inf
                lo = max(g_lo, reach) if np.isfinite(reach) else g_lo
                if lo >= g_hi or g_lo <= last:
                    continue
                zone = {"tf": name, "t": idx[k], "lo": float(max(lo, last)), "hi": float(g_hi), "dist": float(max(lo, last) - last)}
            elif side == "buy" and c[k] > o[k] and l[k + 1] > h[k - 1]:     # BUY: gap rialzista sotto il prezzo (domanda da fillare)
                g_lo, g_hi = h[k - 1], l[k + 1]
                reach = m5.loc[idx[k + 1] + step:, "low"].min() if idx[k + 1] + step <= m5.index[-1] else np.inf
                hi = min(g_hi, reach) if np.isfinite(reach) else g_hi
                if hi <= g_lo or g_hi >= last:
                    continue
                zone = {"tf": name, "t": idx[k], "lo": float(g_lo), "hi": float(min(hi, last)), "dist": float(last - min(hi, last))}
            else:
                continue
            if best is None or zone["dist"] < best["dist"]:
                best = zone
    return best
