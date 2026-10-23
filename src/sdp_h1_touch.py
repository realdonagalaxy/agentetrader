"""Test: price action H1 con struttura HH+HL / LH+LL, ingresso CONTRO al tocco dell'estremo, SL e TP fissi in pips (richiesta utente 23/10/2026).

Regole: swing H1 a 2 barre (noti 3 ore dopo il pivot). Struttura rialzista = ultimo massimo > massimo precedente (HH) e ultimo minimo > minimo precedente (HL);
ribassista = LH e LL. Quando si conferma un nuovo HH in struttura rialzista, il suo livello diventa l'obiettivo: al primo ritorno del prezzo sul livello (massimo M5 >= livello)
si vende con ordine limit; nel caso speculare (LL in struttura ribassista) si compra al tocco. SL e TP a PIPS pips (oro: 1 pip = 0,10), R:R 1:1.
ASSUNZIONI mie: ordine valido 5 giorni, un trade per livello, ordine annullato se prima del tocco si forma un nuovo swing opposto che spezza la struttura non è gestito (resta valido),
nella barra del fill si controlla solo lo SL, stessa barra SL/TP: prima lo SL, max 24 ore dopo il fill, costi ignorati.
Uso: python -m src.sdp_h1_touch XAUUSD [--pips 50] [--pip 0.10] [--from 2024-01-01] [--file path.pkl --label ETICHETTA]
"""
import argparse

import numpy as np
import pandas as pd

from src.data_loader import load_ohlc, resample
from src.range_detector import pivots
from src.sdp_h1_break import simulate
from src.verdict import print_verdicts, verdict

WAIT_BARS = 5 * 288


def find_signals(m5: pd.DataFrame, stats: dict) -> pd.DataFrame:
    h1 = resample(m5, "1h")
    ph, pl = pivots(h1, 2)
    hi, lo = h1["high"].to_numpy(), h1["low"].to_numpy()
    H, L = m5["high"].to_numpy(), m5["low"].to_numpy()
    n = len(m5)
    stats.update(hh=0, ll=0, trade=0)
    rows = []
    for side, mine, other in (("sell", ph, pl), ("buy", pl, ph)):
        up = side == "sell"
        px, ox = (hi, lo) if up else (lo, hi)
        for q in range(1, len(mine)):
            p, pp = mine[q], mine[q - 1]
            if not ((px[p] > px[pp]) if up else (px[p] < px[pp])):                       # HH (o LL)
                continue
            t_conf = h1.index[p] + pd.Timedelta(hours=3)
            oc = [o for o in other if h1.index[o] + pd.Timedelta(hours=3) <= t_conf]     # swing opposti già confermati
            if len(oc) < 2 or not ((ox[oc[-1]] > ox[oc[-2]]) if up else (ox[oc[-1]] < ox[oc[-2]])):    # HL (o LH)
                continue
            stats["hh" if up else "ll"] += 1
            lvl = px[p]
            f0 = int(m5.index.searchsorted(t_conf))
            if f0 >= n - 2:
                continue
            end = min(f0 + WAIT_BARS, n - 2)
            touch = (H[f0:end] >= lvl) if up else (L[f0:end] <= lvl)
            if not touch.any():
                continue
            i = f0 + int(touch.argmax())
            rows.append({"i": i, "time": m5.index[i], "side": side, "entry": float(lvl)})
            stats["trade"] += 1
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True) if rows else pd.DataFrame()


def report(label: str, m5: pd.DataFrame, pips: float, pip: float) -> None:
    dist, st = pips * pip, {}
    sig = find_signals(m5, st)
    print(f"{label} · SL e TP {pips:g} pips = {dist:g} · dati {m5.index[0]} → {m5.index[-1]}\n"
          f"HH in struttura rialzista: {st['hh']} · LL in struttura ribassista: {st['ll']} · toccati entro 5 giorni (trade): {st['trade']}\n"
          f"Assunzioni mie da confermare: pip={pip:g}, limit sul livello, validità 5 giorni, un trade per livello, costi ignorati", flush=True)
    if sig.empty:
        print("nessun segnale")
        return
    res = simulate(m5, sig, dist)
    pl = pd.concat([simulate(m5, sig, dist, np.random.default_rng(sd).choice([-1, 1], len(sig)) * np.random.default_rng(sd + 100).integers(288, 288 * 30, len(sig)), True) for sd in range(5)])
    groups = {"tutti": sig.side.notna(), "SELL al tocco dell'HH": sig.side == "sell", "BUY al tocco dell'LL": sig.side == "buy"}
    rows = []
    for g, mask in groups.items():
        ks = set(sig.index[mask])
        rows.append((g, verdict(res[res.k.isin(ks)][["time", "R"]], pl[pl.k.isin(ks)]["R"], z_min=3.0)))
    print_verdicts(rows, f"{label} | SL=TP={pips:g} pips, max 24 ore | placebo sugli stessi segnali, soglia 3 errori")
    print("\n--- Stabilità per anno e direzione ---")
    for y, g in res.groupby(res.time.dt.year):
        print(f"{y}: " + " | ".join(f"{nm} n={len(x):4d} media {x.R.mean():+.3f}R" for nm, x in (("tutti", g), ("SELL", g[g.side == "sell"]), ("BUY", g[g.side == "buy"]))))
    print("\n--- Deriva e placebo (ingresso a mercato a caso, stessa direzione) ---")
    for sd in ("buy", "sell"):
        x = pl[pl.side == sd].R
        print(f"{sd.upper():4s} a caso: n={len(x)} media {x.mean():+.3f}R (±{x.std() / np.sqrt(len(x)):.3f}) win {np.mean(x > 0):.3f}")
    print(f"Win rate dei trade reali: {np.mean(res.R > 0):.3f} (a 1:1 serve > 0.500 prima dei costi; spread oro ~0,3 = {0.3 / dist:.2f}R per trade)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default="XAUUSD")
    ap.add_argument("--file")
    ap.add_argument("--label")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--pips", type=float, default=50.0)
    ap.add_argument("--pip", type=float, default=0.10)
    a = ap.parse_args()
    if a.file:
        m5 = pd.read_pickle(a.file) if a.file.endswith(".pkl") else pd.read_csv(a.file, index_col=0, parse_dates=True)
        if m5.index.tz is not None:
            m5.index = m5.index.tz_convert("UTC").tz_localize(None)
    else:
        m5 = load_ohlc(f"data/{a.symbol}_BID_M5.csv.gz")
    report(a.label or a.symbol, m5.loc[a.start:a.end], a.pips, a.pip)
