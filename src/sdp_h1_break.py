"""Test: price action H1 - rottura di un massimo/minimo e ingresso sul rintracciamento, SL e TP fissi in pips. Oro, ma funziona su ogni simbolo.

Regole (richiesta utente 23/10/2026): "alla rottura di un max o min prendiamo il rintracciamento. SL e TP 50 pips".
 1. Massimo/minimo H1 = swing a 2 barre per lato (come nei test precedenti), noto 2 barre dopo.
 2. Rottura = prima chiusura H1 oltre il livello (sopra al massimo: BUY; sotto al minimo: SELL). Nota alla chiusura di quella barra.
 3. Ingresso sul rintracciamento con ordine limit (default retest): BUY a limite sul massimo rotto, SELL a limite sul minimo rotto.
    --entry fib50 / fib618: limit al 50% / 61,8% della spinta (da estremo opposto prima della rottura al massimo/minimo raggiunto dalla barra di rottura).
 4. SL e TP a PIPS pips dall'ingresso (R:R 1:1). Su XAUUSD 1 pip = 0,10 (50 pips = 5 $): --pip per cambiarlo.
 5. Ordine valido ORDER_WAIT_BARS barre M5 (24 ore), poi annullato; dopo il fill massimo MAX_BARS (24 ore), poi chiusura a mercato; un trade per livello rotto;
    nella barra del fill si controlla solo lo SL (ordine dei tick ignoto), stessa barra SL/TP: prima lo SL. Costi/spread ignorati (con SL di 5 $ lo spread pesa molto: va stimato a parte).
ASSUNZIONI mie (non specificate): pip oro = 0,10, retest sul livello esatto, scadenza ordine 24 ore, swing a 2 barre. Dichiarate e stampate nel report.
Misura: placebo (stesso lato, ingresso a mercato su barre casuali ±1-30 giorni, 5 ripetizioni), errori standard, IS/OOS 70/30, verdetto automatico (soglia 3 errori).
Uso: python -m src.sdp_h1_break XAUUSD [--entry retest|fib50|fib618] [--pips 50] [--pip 0.10] [--from 2024-01-01] [--to 2025-12-31] [--file path.pkl --label ETICHETTA]
"""
import argparse

import numpy as np
import pandas as pd

from src.data_loader import load_ohlc, resample
from src.range_detector import pivots
from src.verdict import print_verdicts, verdict

ORDER_WAIT_BARS = 288
MAX_BARS = 288
FIB = {"retest": None, "fib50": 0.5, "fib618": 0.618}


def find_signals(m5: pd.DataFrame, entry: str, dist: float, stats: dict) -> pd.DataFrame:
    """Un segnale per livello rotto e poi rintracciato: indice barra del fill, lato, prezzo d'ingresso, SL, TP."""
    h1 = resample(m5, "1h")
    ph, pl = pivots(h1, 2)
    hh, hl, hc = (h1[k].to_numpy() for k in ("high", "low", "close"))
    H, L, C = (m5[k].to_numpy() for k in ("high", "low", "close"))
    n = len(m5)
    cands = [("buy", p, hh[p]) for p in ph] + [("sell", p, hl[p]) for p in pl]
    stats.update(livelli=len(cands), rotti=0, riempiti=0)
    rows = []
    for side, p, lvl in cands:
        buy = side == "buy"
        after = (hc[p + 1:] > lvl) if buy else (hc[p + 1:] < lvl)
        if not after.any():
            continue
        b = p + 1 + int(after.argmax())
        stats["rotti"] += 1
        t_known = h1.index[b] + pd.Timedelta(hours=1)
        f0 = int(m5.index.searchsorted(t_known))
        if f0 >= n - 2:
            continue
        if FIB[entry] is None:
            price = lvl
        else:
            seg = slice(p, b + 1)
            lo_leg, hi_leg = hl[seg].min(), hh[seg].max()
            price = hi_leg - FIB[entry] * (hi_leg - lo_leg) if buy else lo_leg + FIB[entry] * (hi_leg - lo_leg)
        end = min(f0 + ORDER_WAIT_BARS, n - 2)
        touch = (L[f0:end] <= price) if buy else (H[f0:end] >= price)
        if not touch.any():
            continue
        i = f0 + int(touch.argmax())
        stats["riempiti"] += 1
        e = min(price, H[i]) if buy else max(price, L[i])                    # limit eseguito al prezzo (o migliore)
        rows.append({"i": i, "time": m5.index[i], "side": side, "entry": float(e)})
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True) if rows else pd.DataFrame()


def simulate(m5: pd.DataFrame, sig: pd.DataFrame, dist: float, shift: np.ndarray | None = None, market: bool = False) -> pd.DataFrame:
    """R per segnale (SL = -1, TP = +1). shift/market: placebo = ingresso a mercato alla chiusura di una barra casuale."""
    H, L, C = (m5[k].to_numpy() for k in ("high", "low", "close"))
    n = len(m5)
    rows = []
    for r_i, r in enumerate(sig.itertuples()):
        i = r.i + (int(shift[r_i]) if shift is not None else 0)
        if not 0 <= i < n - 2:
            continue
        buy = r.side == "buy"
        e = C[i] if market else r.entry
        sl, tp = (e - dist, e + dist) if buy else (e + dist, e - dist)
        end = min(i + MAX_BARS, n - 1)
        hi, lo = H[i + 1:end + 1], L[i + 1:end + 1]
        first_sl = (L[i] <= sl) if buy else (H[i] >= sl)                      # barra del fill: solo SL
        if first_sl and not market:
            R = -1.0
        else:
            hs, ht = (lo <= sl, hi >= tp) if buy else (hi >= sl, lo <= tp)
            isl, itp = (int(hs.argmax()) if hs.any() else 10**9), (int(ht.argmax()) if ht.any() else 10**9)
            if isl == 10**9 and itp == 10**9:
                R = ((C[end] - e) if buy else (e - C[end])) / dist
            else:
                R = -1.0 if isl <= itp else 1.0
        rows.append({"time": m5.index[i], "side": r.side, "k": r_i, "R": R})
    return pd.DataFrame(rows)


def report(label: str, m5: pd.DataFrame, entry: str, pips: float, pip: float) -> None:
    dist = pips * pip
    st: dict = {}
    sig = find_signals(m5, entry, dist, st)
    print(f"{label} · entry {entry} · SL e TP {pips:g} pips = {dist:g} (1 pip = {pip:g}) · dati {m5.index[0]} → {m5.index[-1]}\n"
          f"Livelli H1 (swing 2 barre): {st['livelli']} · rotti a chiusura H1: {st['rotti']} · rintracciati entro 24 ore (trade): {st['riempiti']}\n"
          f"Assunzioni mie da confermare: pip={pip:g}, ordine limit sul livello, validità 24 ore, spread/costi ignorati", flush=True)
    if sig.empty:
        print("nessun segnale")
        return
    res = simulate(m5, sig, dist)
    pl = pd.concat([simulate(m5, sig, dist, np.random.default_rng(sd).choice([-1, 1], len(sig)) * np.random.default_rng(sd + 100).integers(288, 288 * 30, len(sig)), True) for sd in range(5)])
    groups = {"tutti": sig.side.notna(), "BUY (rottura di un massimo)": sig.side == "buy", "SELL (rottura di un minimo)": sig.side == "sell"}
    rows = []
    for g, mask in groups.items():
        ks = set(sig.index[mask])
        t, p = res[res.k.isin(ks)], pl[pl.k.isin(ks)]
        rows.append((g, verdict(t[["time", "R"]], p["R"], z_min=3.0)))
    print_verdicts(rows, f"{label} | SL=TP={pips:g} pips, max 24 ore | placebo sugli stessi segnali, soglia 3 errori")
    print("\n--- Stabilità per anno e direzione: se il segno cambia, non è un vantaggio ---")
    for y, g in res.groupby(res.time.dt.year):
        print(f"{y}: " + " | ".join(f"{nm} n={len(x):4d} media {x.R.mean():+.3f}R" for nm, x in (("tutti", g), ("BUY", g[g.side == "buy"]), ("SELL", g[g.side == "sell"]))))
    print("\n--- Deriva e placebo (ingresso a mercato a caso, stessa direzione) ---")
    for sd in ("buy", "sell"):
        x = pl[pl.side == sd].R
        print(f"{sd.upper():4s} a caso: n={len(x)} media {x.mean():+.3f}R (±{x.std() / np.sqrt(len(x)):.3f}) win {np.mean(x > 0):.3f}")
    print(f"Win rate dei trade reali: {np.mean(res.R > 0):.3f} (a 1:1 serve > 0.500 prima dei costi; spread oro tipico ~0,3 = {0.3 / dist:.2f}R per trade)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default="XAUUSD")
    ap.add_argument("--file")
    ap.add_argument("--label")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--entry", choices=tuple(FIB), default="retest")
    ap.add_argument("--pips", type=float, default=50.0)
    ap.add_argument("--pip", type=float, default=0.10, help="valore di 1 pip in prezzo (oro: 0.10)")
    a = ap.parse_args()
    if a.file:
        m5 = pd.read_pickle(a.file) if a.file.endswith(".pkl") else pd.read_csv(a.file, index_col=0, parse_dates=True)
        if m5.index.tz is not None:
            m5.index = m5.index.tz_convert("UTC").tz_localize(None)
    else:
        m5 = load_ohlc(f"data/{a.symbol}_BID_M5.csv.gz")
    report(a.label or a.symbol, m5.loc[a.start:a.end], a.entry, a.pips, a.pip)
