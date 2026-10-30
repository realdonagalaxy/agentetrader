"""Profitti e perdite per settimana dallo storico di MetaTrader 5 (Windows, terminale aperto e collegato al conto).

Uso da riga di comando:  python -m src.mt5_weekly --from 2026-01-01 [--login NUMERO --server NOME]
(la password, se serve, la chiede lo script e non viene salvata). Nell'app dei conti (python -m src.accounts_web) la scheda «Risultati» fa lo stesso per ogni conto salvato.
Raggruppamento: settimana ISO (lunedì-domenica) e mese, in base all'orario di CHIUSURA del trade, orario del server del broker.
Netto = profitto + commissioni + swap.
"""
import argparse
from pathlib import Path

import pandas as pd


def from_mt5(start: str, end: str | None, login: int | None, server: str | None) -> pd.DataFrame:
    import MetaTrader5 as mt5                                  # solo Windows
    import getpass
    if not mt5.initialize():
        raise SystemExit(f"MT5 non raggiungibile: apri il terminale e accedi al conto. {mt5.last_error()}")
    if login:
        if not mt5.login(login, password=getpass.getpass("Password MT5 (non viene salvata): "), server=server or ""):
            raise SystemExit(f"Accesso fallito: {mt5.last_error()}")
    t0, t1 = pd.Timestamp(start).to_pydatetime(), pd.Timestamp(end or pd.Timestamp.now()).to_pydatetime() + pd.Timedelta(days=1)
    deals = mt5.history_deals_get(t0, t1)
    mt5.shutdown()
    if not deals:
        raise SystemExit("Nessuna operazione nel periodo.")
    d = pd.DataFrame([x._asdict() for x in deals])
    d = d[d.entry.isin([1, 2, 3])]                             # solo chiusure (OUT, INOUT, OUT_BY); esclude depositi/prelievi (type>1)
    d = d[d.type.isin([0, 1])]
    d["time"] = pd.to_datetime(d.time, unit="s")
    return d.rename(columns={"symbol": "simbolo"})[["time", "simbolo", "profit", "commission", "swap"]]


def aggregate(d: pd.DataFrame, freq: str = "W") -> pd.DataFrame:
    """Profitto per periodo ('W' settimana ISO lun-dom, 'M' mese) in base all'orario di chiusura. Netto = profitto + commissioni + swap."""
    d = d.copy()
    d["netto"] = d.profit + d.commission + d.swap
    per = d.time.dt.to_period("W-SUN" if freq == "W" else "M")
    d["inizio"] = per.dt.start_time.dt.date
    g = d.groupby("inizio").agg(trade=("netto", "size"), vinti=("netto", lambda x: int((x > 0).sum())), persi=("netto", lambda x: int((x < 0).sum())),
                                profitto=("netto", lambda x: x[x > 0].sum()), perdita=("netto", lambda x: x[x < 0].sum()), netto=("netto", "sum"))
    g["cumulato"] = g.netto.cumsum()
    return g.round(2)


def weekly(d: pd.DataFrame) -> pd.DataFrame:
    return aggregate(d, "W")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2026-01-01")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--login", type=int, help="numero conto (la password la chiede lo script, non viene salvata)")
    ap.add_argument("--server")
    a = ap.parse_args()
    w = weekly(from_mt5(a.start, a.end, a.login, a.server))
    print(w.to_string())
    print(f"\nTotale: {int(w.trade.sum())} trade · netto {w.netto.sum():+.2f} · settimane in positivo {int((w.netto > 0).sum())}/{len(w)}")
    Path("data/export").mkdir(parents=True, exist_ok=True)
    w.to_csv("data/export/mt5_settimane.csv")
    print("Salvato in data/export/mt5_settimane.csv")
