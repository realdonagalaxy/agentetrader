"""Vantaggio dei filtri discrezionali dell'utente sui trade UT/UTAD dell'oro/indici (stesso metro dei backtest precedenti).

Gruppi (flag calcolati solo con dati fino al segnale, nessun look-ahead):
 - lateralizzazione: obliqua (canale a rette non parallele, >2 h) oppure massimi/minimi uguali;
 - candela istituzionale: esiste, nella fascia della Reversal Zone (+25%), una candela con corpo mai toccato dal prezzo (src/institutional.py);
 - orario: CHoCH tra le 15:30 e le 18:30 Roma.
Per ogni gruppo: n, media R, placebo (barre casuali, 5 ripetizioni), differenza, errori standard, segno IS/OOS e verdetto automatico (src/verdict.py).
Uso: python -m src.sdp_edge XAUUSD            (legge data/XAUUSD_BID_M5.csv.gz)
     python -m src.sdp_edge --file data/export/XAUUSD_M5_x.csv.gz [--label XAUUSD]
     python -m src.sdp_edge XAUUSD --from 2024-01-01 --to 2025-12-31     (periodo più corto = più veloce)
Con meno di 300 trade per gruppo il verdetto sarà sempre "no": servono molti dati (anni) per concludere qualcosa.
"""
import argparse

import numpy as np
import pandas as pd

from src.data_loader import load_ohlc
from src.institutional import find_zone
from src.sdp_gold import GoldParams, _line, filters, generate_gold, placebo, simulate_gold
from src.verdict import print_verdicts, verdict


def load(args) -> tuple[str, pd.DataFrame]:
    if args.file:
        m5 = pd.read_pickle(args.file) if args.file.endswith(".pkl") else pd.read_csv(args.file, index_col=0, parse_dates=True)
        if m5.index.tz is not None:
            m5.index = m5.index.tz_convert("UTC").tz_localize(None)
        return args.label or args.file, m5
    return args.symbol, load_ohlc(f"data/{args.symbol}_BID_M5.csv.gz")


def run(label: str, m5: pd.DataFrame) -> None:
    st: dict = {}
    sig = generate_gold(m5, GoldParams(struct_tf_min=5), st)
    print(f"{label} - Funnel: {st}\ndati: {m5.index[0]} → {m5.index[-1]} · segnali: {len(sig)}", flush=True)
    fs = filters(sig)
    if fs.empty:
        print("nessun trade UT/UTAD")
        return
    fs["obl"] = [isinstance(v, (tuple, list)) for v in fs.obl_up]
    zones = []
    for t, r in fs.iterrows():
        z = find_zone(m5.loc[:t], t, r.side, None, (r.kz_lo, r.kz_hi))
        zones.append(z is not None)
    fs["inst"] = zones
    res = simulate_gold(m5, fs)
    key = lambda df: list(zip(df.index, df.kind, df.side))
    flags = {k: (o, i, n_) for k, o, i, n_ in zip(key(fs), fs.obl, fs.inst, fs.in_ny)}
    for j, c in enumerate(("obl", "inst", "in_ny")):
        res[c] = [flags[(t, k, s_)][j] for t, k, s_ in zip(res.time, res.kind, res.side)]
    pl = pd.concat([simulate_gold(m5, placebo(m5, sig, sd)) for sd in range(5)])
    allm = pd.Series(True, index=res.index)
    groups = {"tutti i trade": allm, "lateralizzazione OBLIQUA": res.obl, "lateralizzazione a livelli uguali": ~res.obl,
              "con candela istituzionale": res.inst, "senza candela istituzionale": ~res.inst,
              "obliqua + candela istituzionale": res.obl & res.inst, "orario 15:30-18:30": res.in_ny,
              "orario + candela istituzionale": res.in_ny & res.inst}
    for col, nm in (("R_tp1", "uscita tutta a TP 2,5R"), ("R", "gestita 60% a 2,5R + BE")):
        rows = [(g, verdict(res[m][["time", col]].rename(columns={col: "R"}), pl[col])) for g, m in groups.items()]
        print_verdicts(rows, f"{label} | {nm}")
    print(f"\n--- {label} | PLACEBO ---")
    for col, nm in (("R_tp1", "tutto a TP1 (2,5R)"), ("R", "gestita 60% a 2,5R + BE")):
        print(_line(nm, pl.sort_values("time"), col))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default="XAUUSD")
    ap.add_argument("--file")
    ap.add_argument("--label")
    ap.add_argument("--from", dest="start", help="solo dati da questa data (es. 2024-01-01): la scansione delle lateralizzazioni oblique è lenta (circa 8 s ogni 5 giorni)")
    ap.add_argument("--to", dest="end")
    a = ap.parse_args()
    lab, data = load(a)
    run(lab, data.loc[a.start:a.end])
