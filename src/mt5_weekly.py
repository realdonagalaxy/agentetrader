"""Profitti e perdite per settimana dallo storico di MetaTrader 5.

Due modi (le credenziali restano sul tuo computer, non vanno mai incollate in chat né salvate):
  1) Windows con MT5 aperto e già collegato al conto:  python -m src.mt5_weekly --from 2026-01-01
     (usa il pacchetto MetaTrader5, che esiste solo per Windows; senza --login usa il conto già connesso nel terminale)
  2) Qualsiasi sistema, da un file esportato da MT5 (scheda Cronologia > tasto destro > Report > CSV o XLSX... oppure un CSV con colonne tempo/profitto):
     python -m src.mt5_weekly --csv storico.csv
Raggruppamento: settimana ISO (lunedì-domenica) in base all'orario di CHIUSURA del trade, orario del server del broker.
Netto = profitto + commissioni + swap. Output: tabella a schermo e data/export/mt5_settimane.csv.
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


def from_csv(path: str) -> pd.DataFrame:
    sep = ";" if open(path, encoding="utf-8-sig").readline().count(";") > open(path, encoding="utf-8-sig").readline().count(",") else ","
    d = pd.read_csv(path, sep=sep, encoding="utf-8-sig", decimal="," if sep == ";" else ".")
    low = {c: c.lower().strip() for c in d.columns}
    def col(*names):
        for c, l in low.items():
            if any(n in l for n in names):
                return c
        return None
    tc = col("close time", "ora chiusura", "time", "tempo", "data")
    pc = col("profit", "profitto")
    if not tc or not pc:
        raise SystemExit(f"Non trovo le colonne tempo/profitto. Colonne presenti: {list(d.columns)}")
    out = pd.DataFrame({"time": pd.to_datetime(d[tc], dayfirst=True, errors="coerce"), "profit": pd.to_numeric(d[pc], errors="coerce")})
    for name, keys in (("commission", ("commission", "commissione")), ("swap", ("swap",))):
        c = col(*keys)
        out[name] = pd.to_numeric(d[c], errors="coerce").fillna(0.0) if c else 0.0
    out["simbolo"] = d[col("symbol", "simbolo")] if col("symbol", "simbolo") else ""
    return out.dropna(subset=["time", "profit"])


def weekly(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["netto"] = d.profit + d.commission + d.swap
    d["settimana"] = d.time.dt.to_period("W-SUN").dt.start_time.dt.date
    g = d.groupby("settimana").agg(trade=("netto", "size"), vinti=("netto", lambda x: int((x > 0).sum())), persi=("netto", lambda x: int((x < 0).sum())),
                                   profitto=("netto", lambda x: x[x > 0].sum()), perdita=("netto", lambda x: x[x < 0].sum()), netto=("netto", "sum"))
    g["cumulato"] = g.netto.cumsum()
    return g.round(2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--from", dest="start", default="2026-01-01")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--login", type=int, help="numero conto (la password la chiede lo script, non viene salvata)")
    ap.add_argument("--server")
    a = ap.parse_args()
    w = weekly(from_csv(a.csv) if a.csv else from_mt5(a.start, a.end, a.login, a.server))
    print(w.to_string())
    print(f"\nTotale: {int(w.trade.sum())} trade · netto {w.netto.sum():+.2f} · settimane in positivo {int((w.netto > 0).sum())}/{len(w)}")
    Path("data/export").mkdir(parents=True, exist_ok=True)
    w.to_csv("data/export/mt5_settimane.csv")
    print("Salvato in data/export/mt5_settimane.csv")
