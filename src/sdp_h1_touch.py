"""Test: price action H1 con struttura HH+HL / LH+LL, ingresso CONTRO al tocco dell'estremo, SL e TP fissi in pips (richiesta utente 23/10/2026).

Regole: swing H1 a 2 barre (noti 3 ore dopo il pivot). Struttura rialzista = ultimo massimo > massimo precedente (HH) e ultimo minimo > minimo precedente (HL);
ribassista = LH e LL. Quando si conferma un nuovo HH in struttura rialzista, il suo livello diventa l'obiettivo: al primo ritorno del prezzo sul livello (massimo M5 >= livello)
si vende con ordine limit; nel caso speculare (LL in struttura ribassista) si compra al tocco. SL e TP a PIPS pips (oro: 1 pip = 0,10), R:R 1:1.
ASSUNZIONI mie: ordine valido 5 giorni, un trade per livello, ordine annullato se prima del tocco si forma un nuovo swing opposto che spezza la struttura non è gestito (resta valido),
nella barra del fill si controlla solo lo SL, stessa barra SL/TP: prima lo SL, max 24 ore dopo il fill, costi ignorati.
Uso: python -m src.sdp_h1_touch XAUUSD [--sl 150 --tp 50 100 150] [--pip 0.10] [--from 2024-01-01] [--file path.pkl --label ETICHETTA]
"""
import argparse

import numpy as np
import pandas as pd

from src.data_loader import load_ohlc, resample
from src.range_detector import pivots
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


def _managed(row: dict, buy: bool, e: float, sl_d: float, tps: tuple, hi: np.ndarray, lo: np.ndarray, c_end: float, isl: int, w: tuple) -> float:
    """Gestione: quota w[0] chiusa al TP1 e SL spostato a pareggio (ingresso); il resto ai TP2/TP3 con le quote w[1], w[2]. Stessa barra: prima lo stop."""
    if row["TP1"] == -1.0:
        return -1.0
    ht1 = (hi >= e + tps[0]) if buy else (lo <= e - tps[0])
    if not ht1.any():
        return row["TP1"]                                                    # tempo scaduto prima del TP1: chiusura a mercato (stessa uscita del TP1 singolo)
    j = int(ht1.argmax())
    if isl <= j:
        return -1.0
    out = w[0] * tps[0] / sl_d
    for q, t in ((1, tps[1]), (2, tps[2])):
        if not w[q]:
            continue
        hb, ht = ((lo[j:] <= e), (hi[j:] >= e + t)) if buy else ((hi[j:] >= e), (lo[j:] <= e - t))
        ib, it = (int(hb.argmax()) if hb.any() else 10**9), (int(ht.argmax()) if ht.any() else 10**9)
        if ib == 10**9 and it == 10**9:
            out += w[q] * (((c_end - e) if buy else (e - c_end)) / sl_d)
        elif it < ib:
            out += w[q] * t / sl_d
    return out


def simulate(m5: pd.DataFrame, sig: pd.DataFrame, sl_d: float, tps: tuple, shift: np.ndarray | None = None, market: bool = False) -> pd.DataFrame:
    """R per segnale e per TP (in unità di SL: -1 se SL, tp/sl se TP) + colonna MIX = 1/3 della posizione a ciascun TP, SL sempre fisso. Nella barra del fill solo SL; SL prima di TP."""
    H, L, C = (m5[k].to_numpy() for k in ("high", "low", "close"))
    n, rows = len(m5), []
    for r_i, r in enumerate(sig.itertuples()):
        i = r.i + (int(shift[r_i]) if shift is not None else 0)
        if not 0 <= i < n - 2:
            continue
        buy = r.side == "buy"
        e = C[i] if market else r.entry
        sl = e - sl_d if buy else e + sl_d
        end = min(i + 288, n - 1)
        hi, lo = H[i + 1:end + 1], L[i + 1:end + 1]
        row = {"time": m5.index[i], "side": r.side, "k": r_i}
        isl_g, itp1_g = 10**9, 10**9
        if not market and ((L[i] <= sl) if buy else (H[i] >= sl)):
            row.update({f"TP{j + 1}": -1.0 for j in range(len(tps))})
        else:
            hs = (lo <= sl) if buy else (hi >= sl)
            isl = int(hs.argmax()) if hs.any() else 10**9
            isl_g = isl
            for j, t in enumerate(tps):
                ht = (hi >= e + t) if buy else (lo <= e - t)
                itp = int(ht.argmax()) if ht.any() else 10**9
                if isl == 10**9 and itp == 10**9:
                    row[f"TP{j + 1}"] = ((C[end] - e) if buy else (e - C[end])) / sl_d
                else:
                    row[f"TP{j + 1}"] = -1.0 if isl <= itp else t / sl_d
        if len(tps) == 3:
            row["GESTITO"], row["GESTITO_T3"] = (_managed(row, buy, e, sl_d, tps, hi, lo, C[end], isl_g, w) for w in ((0.6, 0.2, 0.2), (0.6, 0.0, 0.4)))
        row["MIX"] = float(np.mean([row[f"TP{j + 1}"] for j in range(len(tps))]))
        rows.append(row)
    return pd.DataFrame(rows)


def report(label: str, m5: pd.DataFrame, sl_pips: float, tp_pips: tuple, pip: float) -> None:
    sl_d, tps, st = sl_pips * pip, tuple(t * pip for t in tp_pips), {}
    sig = find_signals(m5, st)
    print(f"{label} · SL {sl_pips:g} pips ({sl_d:g}) · TP {' / '.join(f'{t:g}' for t in tp_pips)} pips · dati {m5.index[0]} → {m5.index[-1]}\n"
          f"HH in struttura rialzista: {st['hh']} · LL in struttura ribassista: {st['ll']} · toccati entro 5 giorni (trade): {st['trade']}\n"
          f"Assunzioni mie: pip={pip:g}, limit sul livello, validità 5 giorni, un trade per livello, costi ignorati. R in unità di SL (TP1 = +{tps[0] / sl_d:.2f}R). "
          f"GESTITO = 60% al TP1, SL a pareggio, 20% al TP2 e 20% al TP3; GESTITO_T3 = 60% al TP1 e 40% al TP3; MIX = 1/3 a ciascun TP senza pareggio", flush=True)
    if sig.empty:
        print("nessun segnale")
        return
    res = simulate(m5, sig, sl_d, tps)
    pl = pd.concat([simulate(m5, sig, sl_d, tps, np.random.default_rng(sd).choice([-1, 1], len(sig)) * np.random.default_rng(sd + 100).integers(288, 288 * 30, len(sig)), True) for sd in range(5)])
    groups = {"tutti": sig.side.notna(), "SELL al tocco dell'HH": sig.side == "sell", "BUY al tocco dell'LL": sig.side == "buy"}
    for col in ["GESTITO", "GESTITO_T3", "TP1", "MIX"]:
        rows = []
        for g, mask in groups.items():
            ks = set(sig.index[mask])
            rows.append((g, verdict(res[res.k.isin(ks)][["time", col]].rename(columns={col: "R"}), pl[pl.k.isin(ks)][col], z_min=3.0)))
        print_verdicts(rows, f"{label} | uscita {col} | placebo sugli stessi segnali, soglia 3 errori")
    print("\n--- Stabilità per anno (MIX) ---")
    for y, g in res.groupby(res.time.dt.year):
        print(f"{y}: " + " | ".join(f"{nm} n={len(x):4d} media {x.MIX.mean():+.3f}R" for nm, x in (("tutti", g), ("SELL", g[g.side == "sell"]), ("BUY", g[g.side == "buy"]))))
    print("\n--- Frequenza di arrivo ai TP (trade reali) ---")
    for j, t in enumerate(tp_pips):
        print(f"TP{j + 1} {t:g} pips: {np.mean(res[f'TP{j + 1}'] > 0):.3f} · SL: {np.mean(res['TP1'] == -1):.3f} (serve > {1 / (1 + t / sl_pips):.3f} per pareggiare prima dei costi)")
    print("\n--- Deriva e placebo (mercato a caso, MIX) ---")
    for sd in ("buy", "sell"):
        x = pl[pl.side == sd].MIX
        print(f"{sd.upper():4s} a caso: n={len(x)} media {x.mean():+.3f}R (±{x.std() / np.sqrt(len(x)):.3f})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default="XAUUSD")
    ap.add_argument("--file")
    ap.add_argument("--label")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--sl", type=float, default=150.0)
    ap.add_argument("--tp", type=float, nargs="+", default=[50.0, 100.0, 150.0])
    ap.add_argument("--pip", type=float, default=0.10)
    a = ap.parse_args()
    if a.file:
        m5 = pd.read_pickle(a.file) if a.file.endswith(".pkl") else pd.read_csv(a.file, index_col=0, parse_dates=True)
        if m5.index.tz is not None:
            m5.index = m5.index.tz_convert("UTC").tz_localize(None)
    else:
        m5 = load_ohlc(f"data/{a.symbol}_BID_M5.csv.gz")
    report(a.label or a.symbol, m5.loc[a.start:a.end], a.sl, tuple(a.tp), a.pip)
