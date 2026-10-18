"""Liquidità dinamica: trendline che unisce almeno 2 massimi (SELL) o 2 minimi (BUY).

Regole (utente):
 - almeno 2 tocchi; la retta può essere superata solo dalle ombre (spike), mai dai corpi delle candele;
 - include i massimi/minimi uguali (retta orizzontale); sessione e daily esclusi per ora.
ASSUNZIONI mie, da confermare: tocco = ombra a meno di `tol_atr` x ATR14 M15 dalla retta (utente: 0,15);
punti di appoggio = pivot M5 a 2 barre per lato; distanza minima tra i due punti di appoggio 6 barre;
ricerca dall'inizio della lateralizzazione all'ultima barra; scelta: più tocchi, poi meno spike, poi tocco più recente.
"""
import numpy as np
import pandas as pd

from src.data_loader import resample
from src.range_detector import atr, pivots

TOL_ATR = 0.15
MIN_SEP = 6
MAX_PIVOTS = 80


def find_liquidity_line(m5: pd.DataFrame, t0, t1, side: str, tol_atr: float = TOL_ATR) -> dict | None:
    """side 'sell' -> retta sui massimi (liquidità sopra); 'buy' -> retta sui minimi (liquidità sotto)."""
    w = m5.loc[pd.Timestamp(t0):pd.Timestamp(t1)]
    if len(w) < 20:
        return None
    a15 = atr(resample(m5, "15min")).reindex(w.index, method="ffill").to_numpy()
    tol = tol_atr * float(a15[-1]) if np.isfinite(a15[-1]) else None
    if tol is None:
        return None
    sg = 1 if side == "sell" else -1                  # lavoro "da sell": per i buy specchio i prezzi
    wick = sg * (w["high"] if sg == 1 else w["low"]).to_numpy()
    body = sg * np.where(sg == 1, np.maximum(w["open"], w["close"]), np.minimum(w["open"], w["close"]))
    ph, pl = pivots(w, 2)
    piv = (ph if sg == 1 else pl)[-MAX_PIVOTS:]
    n = len(w)
    best, best_key = None, None
    for a in range(len(piv)):
        for b in range(a + 1, len(piv)):
            i, j = int(piv[a]), int(piv[b])
            if j - i < MIN_SEP:
                continue
            s = (wick[j] - wick[i]) / (j - i)
            k = np.arange(i, n)
            y = wick[i] + s * (k - i)
            if (body[i:] > y + 1e-9).any():           # un corpo oltre la retta la invalida
                continue
            near = np.abs(wick[piv[piv >= i]] - (wick[i] + s * (piv[piv >= i] - i))) <= tol
            touches = piv[piv >= i][near]
            spikes = int((wick[i:] > y + tol).sum())
            key = (len(touches), -spikes, int(touches[-1]))
            if best_key is None or key > best_key:
                best_key = key
                best = {"side": side, "i": i, "j": j, "slope": sg * s, "touches": [w.index[int(t)] for t in touches],
                        "spikes": spikes, "tol": tol, "t_start": w.index[i], "p_start": sg * wick[i],
                        "p_end": sg * (wick[i] + s * (n - 1 - i)), "t_end": w.index[-1]}
    return best
