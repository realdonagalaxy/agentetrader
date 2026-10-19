"""Lateralizzazione obliqua: canale con due rette (non necessariamente parallele) su massimi e minimi dell'accumulo.

Regole (utente, 19/10/2026): la liquidità dinamica è la retta obliqua dell'accumulo; le rette possono non essere parallele;
la lateralizzazione dura più di 2 ore; la retta può essere superata solo dalle ombre (spike); i corpi al massimo di una tolleranza (rette non perfette); almeno 2 tocchi per retta.
ASSUNZIONI mie, da confermare: tocco = ombra a <= TOL_ATR x ATR14 M15 dalla retta (0,15 come per la liquidità); pivot M5 a 2 barre per lato;
canale "laterale" = ampiezza media tra MIN_W e MAX_W x ATR14 M15 e deriva di ciascuna retta sull'intera durata <= FLAT x ampiezza media;
le rette non si incrociano nella finestra; si valutano finestre da 2 a 12 ore.
"""
import numpy as np
import pandas as pd

from src.data_loader import resample
from src.range_detector import atr, pivots

TOL_ATR = 0.15
MIN_BARS = 25                      # > 2 ore (24 barre M5)
LENGTHS = (25, 30, 36, 42, 48, 60, 72, 96, 120, 144)
STEP = 2
MIN_W, MAX_W = 1.0, 4.0
COVER = 0.6                        # i tocchi di ciascuna retta coprono almeno il 60% della durata del canale
FLAT = 0.5
MIN_SEP = 6


def _best_line(wick, body, piv, sg, tol):
    """Retta su >=2 pivot (SELL: massimi sg=+1) con tutti i corpi dal lato giusto; massimo di tocchi, poi meno spike."""
    best, best_key = None, None
    n = len(wick)
    k = np.arange(n)
    for a in range(len(piv)):
        for b in range(a + 1, len(piv)):
            i, j = int(piv[a]), int(piv[b])
            if j - i < MIN_SEP:
                continue
            s = (wick[j] - wick[i]) / (j - i)
            y = wick[i] + s * (k - i)
            if (body > y + tol).any():                     # un corpo può superare la retta al massimo della tolleranza di tocco (rette imperfette)
                continue
            near = np.abs(wick[piv] - y[piv]) <= tol
            touches = int(near.sum())
            spikes = int((wick > y + tol).sum())
            t_idx = piv[near]
            key = (int(t_idx[-1] - t_idx[0]), touches, -spikes)         # prima la copertura temporale dei tocchi
            if best_key is None or key > best_key:
                best_key, best = key, (int(t_idx[0]), int(t_idx[-1]), s, wick[i] - s * i, touches, spikes)
    return best


def find_channel(w: pd.DataFrame, atr15: float) -> dict | None:
    """Miglior canale nella finestra `w` (M5) oppure None."""
    if len(w) < MIN_BARS or not np.isfinite(atr15):
        return None
    if float(w["high"].max() - w["low"].min()) > (MAX_W + 2 * FLAT * MAX_W) * atr15:
        return None                                    # escursione troppo grande per un canale laterale: scarto subito (velocizza la scansione)
    tol = TOL_ATR * atr15
    ph, pl = pivots(w, 2)
    if len(ph) < 2 or len(pl) < 2:
        return None
    hi, lo = w["high"].to_numpy(), w["low"].to_numpy()
    bt, bb = np.maximum(w["open"], w["close"]).to_numpy(), np.minimum(w["open"], w["close"]).to_numpy()
    up = _best_line(hi, bt, ph, 1, tol)
    dn = _best_line(-lo, -bb, pl, 1, tol)           # specchio: minimi
    if up is None or dn is None:
        return None
    n = len(w)
    x = np.arange(n)
    up_y = up[2] * x + up[3]
    dn_y = -(dn[2] * x + dn[3])
    width = up_y - dn_y
    if (width <= 0).any():
        return None                                    # le rette non devono incrociarsi
    span = min(up[0], dn[0]), max(up[1], dn[1])
    if span[1] - span[0] + 1 < MIN_BARS:
        return None
    L = span[1] - span[0] + 1
    if (up[1] - up[0]) < COVER * L or (dn[1] - dn[0]) < COVER * L:
        return None                                    # entrambe le rette devono essere toccate lungo quasi tutta la durata
    mw = float(width[span[0]:span[1] + 1].mean())
    if not (MIN_W * atr15 <= mw <= MAX_W * atr15):
        return None
    drift_up, drift_dn = abs(up_y[span[1]] - up_y[span[0]]), abs(dn_y[span[1]] - dn_y[span[0]])
    if max(drift_up, drift_dn) > FLAT * mw:
        return None
    return {"t0": w.index[span[0]], "t1": w.index[span[1]], "up": (up_y[span[0]], up_y[span[1]]), "dn": (dn_y[span[0]], dn_y[span[1]]),
            "t_start": w.index[span[0]], "t_end": w.index[span[1]], "up_touch": up[4], "dn_touch": dn[4], "spikes": up[5] + dn[5],
            "width_atr": mw / atr15, "oblique": max(drift_up, drift_dn) / mw, "n": n,
            "up_line": (up_y[span[0]], up_y[span[1]]), "dn_line": (dn_y[span[0]], dn_y[span[1]])}


def scan(m5: pd.DataFrame, t0=None, t1=None) -> list[dict]:
    """Tutti i canali (finestre da 2 a 12 ore) nell'intervallo; sovrapposti: si tiene il più denso di tocchi."""
    a15 = atr(resample(m5, "15min")).reindex(m5.index, method="ffill").to_numpy()
    lo_i = 0 if t0 is None else int(m5.index.searchsorted(pd.Timestamp(t0)))
    hi_i = len(m5) if t1 is None else int(m5.index.searchsorted(pd.Timestamp(t1)))
    found = []
    for e in range(lo_i + max(LENGTHS), hi_i, STEP):
        for L in LENGTHS:
            w = m5.iloc[e - L:e]
            ch = find_channel(w, float(a15[e - 1]))
            if ch:
                ch["score"] = ((ch["up_touch"] + ch["dn_touch"]) / ch["n"], -ch["spikes"], ch["n"])      # densità di tocchi: preferisce il canale più "stretto" al più lungo
                found.append(ch)
    found.sort(key=lambda c: c["score"], reverse=True)
    keep = []
    for c in found:
        if all(c["t1"] <= k["t0"] or c["t0"] >= k["t1"] for k in keep):
            keep.append(c)
    return sorted(keep, key=lambda c: c["t0"])
