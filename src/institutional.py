"""Candela istituzionale con ordini pendenti ancora da attivare (zona verso cui il prezzo può tornare).

Regole (utente, documento Strategia_SDP → Aggiornamento Strategia + esempio SOLUSD 1D):
 - SELL: l'ultima candela BUY prima di una spinta ribassista che lascia imbalance (gap a 3 candele); BUY: specchio;
 - la candela è quasi solo corpo (poche o nulle ombre) e vale su ogni timeframe da M5 in su (anche M6, M7...);
 - gli ordini pendenti sono nel CORPO e si attivano quando il prezzo, anche con la sola ombra, lo tocca: "da fillare" = corpo mai toccato dopo la spinta;
 - sta nella fascia della Reversal Zone (1.272–1.618 della Leg 1, a volte oltre), anche molto a sinistra nel grafico; SELL: sopra il prezzo, BUY: sotto.
ASSUNZIONI mie, da confermare con la galleria di casi: spinta con corpo >= IMPULSE_ATR x ATR14 del timeframe; ombre della candela <= WICK_FRAC del range;
timeframe M5..M30 + H1, H4, D1 (tutti i minuti con dati M1: M6, M7...; solo multipli di 5 con dati M5); margine 25% oltre la fascia; ricerca negli ultimi 90 giorni;
si prende la zona più vicina al prezzo.
"""
import numpy as np
import pandas as pd

from src.data_loader import resample
from src.range_detector import atr

IMPULSE_ATR = 1.0
WICK_FRAC = 0.40
TF_MIN = tuple(range(5, 31))                 # M5..M30 minuto per minuto (anche TF "nascosti" M6, M7...)
TF_MIN_M5ONLY = (5, 10, 15, 20, 25, 30)      # senza dati M1 si possono costruire solo i multipli di 5
LOOKBACK = pd.Timedelta(days=90)             # la candela può stare molto a sinistra nel grafico (esempio SOLUSD: mesi prima)
BAND_MARGIN = 0.25                           # "alle volte anche oltre il range": 25% dell'ampiezza della Reversal Zone


def find_zone(m5: pd.DataFrame, t_end, side: str, m1: pd.DataFrame | None = None, band: tuple[float, float] | None = None) -> dict | None:
    """SELL -> candela BUY prima di una spinta ribassista con imbalance, corpo mai toccato, sopra il prezzo; BUY -> specchio, sotto il prezzo.
    Solo nella fascia `band` (se data). Restituisce la più vicina al prezzo."""
    t_end = pd.Timestamp(t_end)
    last = float(m5["close"].iloc[-1])
    best = None
    if band is not None:
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
        for j in range(2, len(df) - 1):
            k = j - 1
            if idx[k] < t_end - LOOKBACK or not np.isfinite(a[j]):
                continue
            bj = abs(c[j] - o[j])
            if bj < IMPULSE_ATR * a[j]:
                continue
            rng_k, body_k = h[k] - l[k], abs(c[k] - o[k])
            if rng_k <= 0 or (rng_k - body_k) > WICK_FRAC * rng_k:
                continue
            bl, bh = min(o[k], c[k]), max(o[k], c[k])                          # corpo = ordini pendenti
            fut = m5.loc[idx[j] + step:]                                      # barre dopo la spinta
            if side == "sell" and c[k] > o[k] and c[j] < o[j] and h[j + 1] < l[k]:
                if bl <= last or (len(fut) and float(fut["high"].max()) >= bl):
                    continue
                zone = {"tf": name, "t": idx[k], "lo": float(bl), "hi": float(bh), "dist": float(bl - last)}
            elif side == "buy" and c[k] < o[k] and c[j] > o[j] and l[j + 1] > h[k]:
                if bh >= last or (len(fut) and float(fut["low"].min()) <= bh):
                    continue
                zone = {"tf": name, "t": idx[k], "lo": float(bl), "hi": float(bh), "dist": float(last - bh)}
            else:
                continue
            if band is not None and (zone["hi"] < b_lo or zone["lo"] > b_hi):
                continue                                  # il corpo deve stare dentro la fascia della Reversal Zone
            if best is None or zone["dist"] < best["dist"]:
                best = zone
    return best
