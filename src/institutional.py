"""Candela istituzionale con imbalance ancora da fillare (zona verso cui il prezzo può tornare).

Regole (utente, documento Strategia_SDP → Aggiornamento Strategia): candela da M5 in su, quasi solo corpo (poche o nulle ombre), che lascia un imbalance e contiene ordini da fillare;
per un SELL è una candela BUY (prima del sell) il cui imbalance non è ancora stato chiuso dal prezzo, per un BUY una candela SELL;
si trova nella fascia della Reversal Zone (1.272–1.618 della Leg 1), a volte anche oltre, anche a sinistra nel grafico.
Gli ordini pendenti si attivano quando il prezzo, anche solo con l'ombra, tocca il CORPO della candela: "da fillare" = corpo non ancora toccato dopo la candela che chiude l'imbalance.
Esempio dell'utente (SOLUSD 1D): la candela sta mesi a sinistra, sopra il prezzo (SELL), nella fascia della Reversal Zone; la spike che ne tocca il corpo attiva gli ordini e parte il reversal.
ASSUNZIONI mie, da confermare: corpo >= BODY_ATR x ATR14 del suo timeframe; ombre totali <= WICK_FRAC del range;
timeframe M5..M30 + H1, H4, D1 (tutti i minuti se ci sono dati M1: M6, M7...; solo multipli di 5 con dati M5); imbalance = gap a 3 candele (FVG) lasciato dalla candela;
ricerca negli ultimi 90 giorni, si prende la zona più vicina al prezzo.
"""
import numpy as np
import pandas as pd

from src.data_loader import resample
from src.range_detector import atr

BODY_ATR = 1.5
WICK_FRAC = 0.20
TF_MIN = tuple(range(5, 31))                 # M5..M30 minuto per minuto (anche TF "nascosti" M6, M7...) + H1
TF_MIN_M5ONLY = (5, 10, 15, 20, 25, 30)      # senza dati M1 si possono costruire solo i multipli di 5
LOOKBACK = pd.Timedelta(days=90)           # la candela può stare molto a sinistra nel grafico (esempio SOLUSD: mesi prima)


BAND_MARGIN = 0.25                           # "alle volte anche oltre il range": margine = 25% dell'ampiezza della Reversal Zone (ASSUNZIONE mia)


def find_zone(m5: pd.DataFrame, t_end, side: str, m1: pd.DataFrame | None = None, band: tuple[float, float] | None = None) -> dict | None:
    """SELL -> candela BUY SOPRA il prezzo con corpo non ancora toccato; BUY -> candela SELL SOTTO il prezzo. Solo nella fascia `band`. Restituisce la più vicina al prezzo."""
    t_end = pd.Timestamp(t_end)
    last = float(m5["close"].iloc[-1])
    best = None
    if band is not None:                                  # Reversal Zone (Kill Zone 1.272-1.618 della Leg 1) + margine
        b_lo, b_hi = sorted(band)
        m = BAND_MARGIN * (b_hi - b_lo)
        b_lo, b_hi = b_lo - m, b_hi + m
    src = m1.loc[:t_end + pd.Timedelta(minutes=4)] if m1 is not None else m5
    tfs = [(f"M{n}", f"{n}min") for n in (TF_MIN if m1 is not None else TF_MIN_M5ONLY)] + [("H1", "1h"), ("H4", "4h"), ("D1", "1D")]
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
            fut = m5.loc[idx[k + 1] + step:]                                  # barre dopo quella che chiude l'imbalance (k+1)
            b_lo_c, b_hi_c = min(o[k], c[k]), max(o[k], c[k])                  # corpo = ordini pendenti
            if side == "sell" and c[k] > o[k] and l[k + 1] > h[k - 1]:       # SELL: candela BUY SOPRA il prezzo, corpo mai toccato (nemmeno con l'ombra) dopo di essa
                if b_lo_c <= last or (len(fut) and float(fut["high"].max()) >= b_lo_c):
                    continue
                zone = {"tf": name, "t": idx[k], "lo": float(b_lo_c), "hi": float(b_hi_c), "dist": float(b_lo_c - last)}
            elif side == "buy" and c[k] < o[k] and h[k + 1] < l[k - 1]:      # BUY: candela SELL SOTTO il prezzo, corpo mai toccato
                if b_hi_c >= last or (len(fut) and float(fut["low"].min()) <= b_hi_c):
                    continue
                zone = {"tf": name, "t": idx[k], "lo": float(b_lo_c), "hi": float(b_hi_c), "dist": float(last - b_hi_c)}
            else:
                continue
            if band is not None and (zone["hi"] < b_lo or zone["lo"] > b_hi):
                continue                                  # l'imbalance deve stare dentro la fascia della Reversal Zone
            if best is None or zone["dist"] < best["dist"]:
                best = zone
    return best
