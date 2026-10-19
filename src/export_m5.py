"""Scarica da Dukascopy (BID) un intervallo di giorni per uno o più simboli e salva M5 e M1 in file compressi pronti da condividere.

Uso:  python -m src.export_m5 XAUUSD 2026-10-12 2026-10-18
      python -m src.export_m5 XAUUSD USATECHIDXUSD USA500IDXUSD USA30IDXUSD --start 2026-10-12 --end 2026-10-18
Output: data/export/<SIMBOLO>_M5_<inizio>_<fine>.csv.gz e <SIMBOLO>_M1_<inizio>_<fine>.csv.gz (UTC, colonne time,open,high,low,close,volume).
Solo lettura di dati pubblici: nessun ordine, nessuna credenziale. Il giorno in corso non è ancora disponibile: usa come fine ieri.
"""
import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from src.dukascopy_fetch import CRYPTO, fetch_day


def export(sym: str, start: date, end: date, out: Path, rounds: int = 4) -> bool:
    days = [start + timedelta(n) for n in range((end - start).days + 1)
            if sym.startswith(CRYPTO) or (start + timedelta(n)).weekday() != 5]
    cache = out / "raw"
    rows, pending = {}, list(days)
    for rnd in range(1, rounds + 1):
        with requests.Session() as s:
            for d in list(pending):
                r = fetch_day(sym, d, "BID", s, cache)
                if r is not None:
                    rows[d] = r
                    pending.remove(d)
        if not pending:
            break
        if rnd < rounds:
            print(f"{sym}: {len(pending)} giorni non scaricati, riprovo tra 60 secondi...", flush=True)
            time.sleep(60)
    if pending:
        print(f"{sym}: giorni mancanti {[str(d) for d in pending]} (rete bloccata o giorno non ancora disponibile)", file=sys.stderr)
        return False
    data = [r for d in sorted(rows) for r in rows[d]]
    if not data:
        print(f"{sym}: nessun dato nell'intervallo", file=sys.stderr)
        return False
    m1 = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume"]).set_index("time").sort_index()
    m1.index = m1.index.tz_convert("UTC").tz_localize(None)                     # UTC senza fuso esplicito, come il resto del progetto
    m5 = m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
    tag = f"{start:%Y%m%d}_{end:%Y%m%d}"
    out.mkdir(parents=True, exist_ok=True)
    m1.to_csv(out / f"{sym}_M1_{tag}.csv.gz")
    m5.to_csv(out / f"{sym}_M5_{tag}.csv.gz")
    print(f"{sym}: {len(m5)} barre M5 ({m5.index[0]} → {m5.index[-1]}) -> {out}/{sym}_M5_{tag}.csv.gz", flush=True)
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("items", nargs="+", help="simboli; se non usi --start/--end: SIMBOLO INIZIO FINE")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--out", default="data/export")
    a = ap.parse_args()
    if a.start and a.end:
        syms, s0, e0 = a.items, a.start, a.end
    else:
        if len(a.items) != 3:
            ap.error("senza --start/--end servono esattamente: SIMBOLO INIZIO FINE")
        syms, s0, e0 = a.items[:1], a.items[1], a.items[2]
    ok = all([export(sym, date.fromisoformat(s0), date.fromisoformat(e0), Path(a.out)) for sym in syms])
    sys.exit(0 if ok else 1)
