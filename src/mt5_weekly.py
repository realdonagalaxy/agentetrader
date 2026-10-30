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
import re
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


def from_csv(path: str, text: str | None = None) -> pd.DataFrame:
    import io
    text = text if text is not None else read_text(Path(path).read_bytes())
    first = text.splitlines()[0] if text.strip() else ""
    sep = "\t" if first.count("\t") > max(first.count(";"), first.count(",")) else ";" if first.count(";") > first.count(",") else ","
    d = pd.read_csv(io.StringIO(text), sep=sep, decimal="," if sep == ";" else ".", thousands=" " if sep != "," else None)
    low = {c: c.lower().strip() for c in d.columns}
    def col(*names):
        for c, l in low.items():
            if any(n in l for n in names):
                return c
        return None
    tc = col("close time", "ora chiusura", "time", "tempo", "data")
    pc = col("profit", "profitto")
    if not tc or not pc:
        raise ValueError(f"Non trovo le colonne tempo/profitto. Colonne presenti: {list(d.columns)}")
    out = pd.DataFrame({"time": d[tc].map(to_time), "profit": d[pc].map(to_num)})
    for name, keys in (("commission", ("commission", "commissione")), ("swap", ("swap",))):
        c = col(*keys)
        out[name] = d[c].map(to_num).fillna(0.0) if c else 0.0
    out["simbolo"] = d[col("symbol", "simbolo")] if col("symbol", "simbolo") else ""
    return out.dropna(subset=["time", "profit"])


def to_time(v):
    """Data/ora da testo o cella Excel: accetta 2026.10.30 15:45 (formato MT5), 2026-10-30 15:45:10 e 30/10/2026 15:45."""
    import datetime as dt
    if isinstance(v, (dt.datetime, pd.Timestamp)):
        return pd.Timestamp(v)
    t = str(v).strip()
    if not t or t.lower() == "nan":
        return pd.NaT
    m = re.match(r"^(\d{4})[.\-/](\d{2})[.\-/](\d{2})(.*)$", t)
    if m:
        t = f"{m[1]}-{m[2]}-{m[3]}{m[4]}"
        return pd.to_datetime(t, errors="coerce")
    return pd.to_datetime(t, dayfirst=True, errors="coerce")


def to_num(v):
    """Numero da testo con spazi come separatore di migliaia e virgola o punto decimale (es. '1 234,50'); NaN se non valido."""
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace("\xa0", "").replace(" ", "")
    if not t:
        return float("nan")
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return float("nan")


def from_xlsx(raw: bytes) -> tuple[pd.DataFrame, str | None]:
    """Report MT5 in Excel. Legge la tabella delle POSIZIONI CHIUSE (colonne Posizione, due colonne Ora = apertura e chiusura, Commissione, Swap, Profitto) oppure quella dei DEAL
    (Operazione, Direzione, Commissione, Swap, Profitto: contano i deal di uscita). Restituisce (trade, valuta). Il 'Report sul Conto Trading', che mostra solo saldo e posizioni
    aperte, non contiene operazioni chiuse: in quel caso errore con la spiegazione."""
    import io
    import openpyxl
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    cur, rows_out = None, []
    open_only = False
    for ws in wb:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        for r in rows:
            txt = " ".join(str(c) for c in r if c is not None)
            m = re.search(r"\((\w{3}),", txt)
            if m and cur is None and re.match(r"^\s*(Conto|Account)", txt, re.I):
                cur = m[1]
        for i, r in enumerate(rows):
            names = [str(c).strip().lower() if c is not None else "" for c in r]
            if "profitto" not in names and "profit" not in names:
                continue
            if "prezzo di mercato" in names or "market price" in names:
                open_only = True                                   # tabella delle posizioni aperte: nessuna chiusura
                continue
            pi = names.index("profitto") if "profitto" in names else names.index("profit")
            si = names.index("swap") if "swap" in names else None
            ci = next((k for k, n in enumerate(names) if n.startswith(("commissione", "commission"))), None)
            sym = next((k for k, n in enumerate(names) if n in ("simbolo", "symbol")), None)
            times = [k for k, n in enumerate(names) if n in ("ora", "time", "orario")]
            direz = next((k for k, n in enumerate(names) if n in ("direzione", "direction")), None)
            if not times:
                continue
            tcol = times[-1]                                       # posizioni: l'ultima colonna Ora è la chiusura; deal: l'unica
            for r2 in rows[i + 1:]:
                if all(c is None for c in r2):
                    break
                if direz is not None and str(r2[direz]).strip().lower() not in ("out", "in/out", "out by"):
                    continue
                t = to_time(r2[tcol])
                pr = to_num(r2[pi])
                if pd.isna(t) or pd.isna(pr):
                    continue
                rows_out.append({"time": t, "simbolo": r2[sym] if sym is not None else "", "profit": pr,
                                 "commission": (to_num(r2[ci]) if ci is not None else 0.0) or 0.0, "swap": (to_num(r2[si]) if si is not None else 0.0) or 0.0})
    if not rows_out:
        if open_only:
            raise ValueError("Questo file è il «Report sul Conto Trading» di MT5: mostra saldo e posizioni APERTE, non le operazioni chiuse. "
                             "In MT5 apri la scheda «Cronologia» (Ctrl+T), imposta il periodo, tasto destro → Report → «Report Excel (xlsx)» o «CSV» e carica quello.")
        raise ValueError("Non trovo operazioni chiuse nel file: servono le colonne Ora, Profitto (e Swap/Commissione). Esporta il Report dalla scheda Cronologia di MT5.")
    return pd.DataFrame(rows_out), cur


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


def read_text(raw: bytes) -> str:
    """Esportazioni MT5 spesso in UTF-16 o Windows-1252: prova le codifiche comuni."""
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("latin-1")


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
