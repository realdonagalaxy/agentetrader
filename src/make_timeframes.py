"""Unisce i CSV annuali M1 (data/raw) e crea M5, M15, H1, H4 compressi in data/.

Uso: python -m src.make_timeframes EURUSD [--side BID]
Output: data/EURUSD_BID_M5.csv.gz, _M15, _H1, _H4 (+ data/EURUSD_BID_M1.csv.gz con --keep-m1)
"""
import argparse
import glob
from pathlib import Path

import pandas as pd

RULES = {"M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}


def main(sym: str, side: str, keep_m1: bool, raw: str = "data/raw", out: str = "data") -> None:
    files = sorted(glob.glob(f"{raw}/{sym}_{side}_M1_*.csv"))
    if not files:
        raise SystemExit(f"Nessun file in {raw} per {sym} {side}")
    m1 = pd.concat((pd.read_csv(f, parse_dates=["time"]) for f in files))
    m1["time"] = pd.to_datetime(m1["time"], utc=True).dt.tz_localize(None)
    m1 = m1.drop_duplicates("time").set_index("time").sort_index()
    print(f"M1: {len(m1)} barre, {m1.index[0]} -> {m1.index[-1]}")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    Path(out).mkdir(exist_ok=True)
    for name, rule in RULES.items():
        df = m1.resample(rule).agg(agg).dropna(subset=["close"])
        p = f"{out}/{sym}_{side}_{name}.csv.gz"
        df.to_csv(p)
        print(f"{name}: {len(df)} barre -> {p} ({Path(p).stat().st_size / 1e6:.1f} MB)")
    if keep_m1:
        m1.to_csv(f"{out}/{sym}_{side}_M1.csv.gz")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--side", default="BID")
    ap.add_argument("--keep-m1", action="store_true")
    a = ap.parse_args()
    main(a.symbol, a.side, a.keep_m1)
