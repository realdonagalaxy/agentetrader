"""Test: chiusura di un'inefficienza (FVG) H1 + ingresso quando il prezzo supera l'EMA 21 (M5). Oro, ma funziona su ogni simbolo.

Regole concordate con l'utente (23/10/2026):
 1. FVG H1 a tre candele: spinta (candela centrale) con corpo >= IMPULSE_ATR x ATR14 H1; rialzista se il minimo della 3ª sta sopra il massimo della 1ª,
    ribassista specchio. Il gap è noto alla chiusura della 3ª candela.
 2. "Chiusura": il prezzo torna nel gap e lo riempie del tutto (raggiunge il bordo opposto, anche solo con l'ombra).
 3. Direzione: FVG rialzista chiuso -> BUY quando una candela M5 chiude sopra l'EMA 21 (incrocio dal basso); ribassista -> SELL (incrocio dall'alto). Entry a mercato alla chiusura.
 4. EMA 21 sul grafico M5.
 5. SL oltre l'estremo toccato dalla chiusura del gap all'ingresso, più SL_MARGIN x ATR14 M15; TP a 2R e a 3R (testati separatamente);
    tempo massimo 24 ore (poi chiusura al prezzo di mercato); un solo trade per gap; costi ignorati; stessa barra SL/TP: prima lo SL.
ASSUNZIONI mie (non specificate): il gap vale per al massimo GAP_WAIT_BARS barre M5 dopo la formazione (5 giorni) e l'incrocio con l'EMA deve avvenire entro
ENTRY_WAIT_BARS barre dalla chiusura del gap (24 ore). Sono dichiarate qui e stampate nel report.
Misura: stessi criteri dei backtest precedenti (placebo su barre casuali con stessa geometria, errori standard, segno dentro/fuori campione, verdetto automatico).
Uso: python -m src.sdp_fvg_ema XAUUSD [--from 2024-01-01] [--to 2025-12-31] [--file path.csv.gz|.pkl --label ETICHETTA]
"""
import argparse

import numpy as np
import pandas as pd

from src.data_loader import load_ohlc, resample
from src.range_detector import atr
from src.verdict import print_verdicts, verdict

IMPULSE_ATR = 1.0
SL_MARGIN = 0.25
GAP_WAIT_BARS = 5 * 288
ENTRY_WAIT_BARS = 288
MAX_BARS = 288
MULTS = (2.0, 3.0)


def find_gaps(m5: pd.DataFrame) -> pd.DataFrame:
    """FVG H1 con spinta forte. Colonne: t_known (chiusura della 3ª candela), side ('bull'/'bear'), lo, hi."""
    h1 = resample(m5, "1h")
    a = atr(h1).to_numpy()
    o, h, l, c = (h1[k].to_numpy() for k in ("open", "high", "low", "close"))
    rows = []
    for k in range(1, len(h1) - 1):
        if not np.isfinite(a[k]) or abs(c[k] - o[k]) < IMPULSE_ATR * a[k]:
            continue
        if c[k] > o[k] and l[k + 1] > h[k - 1]:
            rows.append(("bull", h[k - 1], l[k + 1], h1.index[k + 1] + pd.Timedelta(hours=1)))
        elif c[k] < o[k] and h[k + 1] < l[k - 1]:
            rows.append(("bear", h[k + 1], l[k - 1], h1.index[k + 1] + pd.Timedelta(hours=1)))
    return pd.DataFrame(rows, columns=["side", "lo", "hi", "t_known"])


def find_signals(m5: pd.DataFrame, gaps: pd.DataFrame, stats: dict) -> pd.DataFrame:
    """Un segnale per gap chiuso con incrocio dell'EMA 21 entro ENTRY_WAIT_BARS: indice di barra, lato, rischio in prezzo, SL."""
    H, L, C = (m5[k].to_numpy() for k in ("high", "low", "close"))
    ema = m5["close"].ewm(span=21, adjust=False).mean().to_numpy()
    a15 = atr(resample(m5, "15min")).shift(1).reindex(m5.index, method="ffill").to_numpy()       # ATR dell'ultima M15 già chiusa: nessun dato futuro
    n = len(m5)
    rows = []
    stats.update(gap=len(gaps), chiusi=0, segnali=0)
    for g in gaps.itertuples():
        f0 = int(m5.index.searchsorted(g.t_known))
        if f0 >= n - 2:
            continue
        end = min(f0 + GAP_WAIT_BARS, n - 1)
        bull = g.side == "bull"
        hit = (L[f0:end + 1] <= g.lo) if bull else (H[f0:end + 1] >= g.hi)       # riempimento completo (BUY: il prezzo scende al bordo basso)
        if not hit.any():
            continue
        i_f = f0 + int(hit.argmax())
        stats["chiusi"] += 1
        for i in range(max(i_f, 1), min(i_f + ENTRY_WAIT_BARS, n - 2)):
            cross = (C[i - 1] <= ema[i - 1] and C[i] > ema[i]) if bull else (C[i - 1] >= ema[i - 1] and C[i] < ema[i])
            if not cross or not np.isfinite(a15[i]):
                continue
            extreme = L[i_f:i + 1].min() if bull else H[i_f:i + 1].max()
            sl = extreme - SL_MARGIN * a15[i] if bull else extreme + SL_MARGIN * a15[i]
            risk = (C[i] - sl) if bull else (sl - C[i])
            if risk > 0:
                rows.append({"i": i, "time": m5.index[i], "side": "buy" if bull else "sell", "risk": float(risk), "t_gap": g.t_known})
                stats["segnali"] += 1
            break
    return pd.DataFrame(rows)


def simulate(m5: pd.DataFrame, sig: pd.DataFrame, shift: np.ndarray | None = None) -> pd.DataFrame:
    """R per segnale e per multiplo di TP. shift = spostamento (in barre) per il placebo: stesso lato e rischio su un'altra barra."""
    H, L, C = (m5[k].to_numpy() for k in ("high", "low", "close"))
    n = len(m5)
    rows = []
    for r_i, r in enumerate(sig.itertuples()):
        i = r.i + (int(shift[r_i]) if shift is not None else 0)
        if not 0 <= i < n - 2:
            continue
        buy = r.side == "buy"
        e = C[i]
        end = min(i + MAX_BARS, n - 1)
        hi, lo = H[i + 1:end + 1], L[i + 1:end + 1]
        row = {"time": m5.index[i], "side": r.side}
        for k in MULTS:
            sl, tp = (e - r.risk, e + k * r.risk) if buy else (e + r.risk, e - k * r.risk)
            hs, ht = (lo <= sl, hi >= tp) if buy else (hi >= sl, lo <= tp)
            isl, itp = (int(hs.argmax()) if hs.any() else 10**9), (int(ht.argmax()) if ht.any() else 10**9)
            if isl == 10**9 and itp == 10**9:                                           # tempo scaduto: chiusura al prezzo di mercato
                row[f"R{k:g}"] = ((C[end] - e) if buy else (e - C[end])) / r.risk
            else:
                row[f"R{k:g}"] = -1.0 if isl <= itp else k
        rows.append(row)
    return pd.DataFrame(rows)


def placebo(m5: pd.DataFrame, sig: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    shift = rng.choice([-1, 1], len(sig)) * rng.integers(288, 288 * 30, len(sig))
    return simulate(m5, sig, shift)


def report(label: str, m5: pd.DataFrame) -> None:
    st: dict = {}
    gaps = find_gaps(m5)
    sig = find_signals(m5, gaps, st)
    print(f"{label} · dati {m5.index[0]} → {m5.index[-1]}\n"
          f"FVG H1 con spinta >= {IMPULSE_ATR:g} ATR: {st['gap']} · chiusi entro {GAP_WAIT_BARS // 288} giorni: {st['chiusi']} · con incrocio EMA 21 M5 entro {ENTRY_WAIT_BARS // 12} ore: {st['segnali']}\n"
          f"Parametri miei da confermare: attesa gap {GAP_WAIT_BARS // 288} giorni, attesa incrocio {ENTRY_WAIT_BARS // 12} ore, margine SL {SL_MARGIN:g} ATR M15", flush=True)
    if sig.empty:
        print("nessun segnale")
        return
    res = simulate(m5, sig)
    pl = pd.concat([placebo(m5, sig, s) for s in range(5)])
    groups = {"tutti": None, "BUY (FVG rialzista chiuso)": "buy", "SELL (FVG ribassista chiuso)": "sell"}
    z_min = 3.0                                                       # 3 gruppi x 2 uscite guardati: la soglia dei 2 errori standard darebbe falsi positivi
    for k in MULTS:
        col = f"R{k:g}"
        rows = []
        for g, sd in groups.items():
            t = res if sd is None else res[res.side == sd]
            p = pl if sd is None else pl[pl.side == sd]               # placebo della STESSA direzione: toglie la deriva del mercato
            rows.append((g, verdict(t[["time", col]].rename(columns={col: "R"}), p[col], z_min=z_min)))
        print_verdicts(rows, f"{label} | TP {k:g}R, max 24 ore | placebo della stessa direzione, soglia {z_min:g} errori")
    print("\n--- Stabilità per anno e direzione (TP 3R): se il segno cambia, non è un vantaggio ---")
    for y, g in res.groupby(res.time.dt.year):
        print(f"{y}: " + " | ".join(f"{nm} n={len(x):4d} media {x['R3'].mean():+.3f}R" for nm, x in (("tutti", g), ("BUY", g[g.side == "buy"]), ("SELL", g[g.side == "sell"]))))
    print("\n--- Deriva del mercato (placebo per direzione, TP 3R): quanto rende comprare o vendere a caso ---")
    for sd in ("buy", "sell"):
        x = pl[pl.side == sd]["R3"]
        print(f"{sd.upper():4s} a caso: n={len(x)} media {x.mean():+.3f}R (±{x.std() / np.sqrt(len(x)):.3f})")
    print("\n--- PLACEBO (barre casuali, 5 ripetizioni) ---")
    for k in MULTS:
        r = pl[f"R{k:g}"]
        print(f"TP {k:g}R: n={len(r)} media {r.mean():+.3f}R (±{r.std() / np.sqrt(len(r)):.3f}) win {np.mean(r > 0):.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default="XAUUSD")
    ap.add_argument("--file")
    ap.add_argument("--label")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    a = ap.parse_args()
    if a.file:
        m5 = pd.read_pickle(a.file) if a.file.endswith(".pkl") else pd.read_csv(a.file, index_col=0, parse_dates=True)
        if m5.index.tz is not None:
            m5.index = m5.index.tz_convert("UTC").tz_localize(None)
    else:
        m5 = load_ohlc(f"data/{a.symbol}_BID_M5.csv.gz")
    report(a.label or a.symbol, m5.loc[a.start:a.end])
