"""Journal degli avvisi dell'assistente (foglio "Avvisi" di journal/trading_journal.xlsx).

Ogni avviso inviato (setup in formazione o ordine limite) viene registrato; l'esito si calcola in automatico dai prezzi successivi
con le stesse regole del backtest v3 (riempimento al ritorno, SL, TP a fine Leg 1, gestione BE+50% a 3R).
La colonna "Decisione utente" resta vuota: la compili tu (Preso / Saltato) per confrontare le tue scelte con quelle del codice.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook

from src.sdp_v3 import V3Params, simulate_v3

PATH = Path("journal/trading_journal.xlsx")
SHEET = "Avvisi"
HEAD = ["ID", "Creato (UTC)", "Simbolo", "Lato", "Stato", "Livello", "KZ basso", "KZ alto", "Entry limite", "SL", "TP", "R:R",
        "Chiave", "Telegram", "Decisione utente", "Riempito (UTC)", "Esito", "R (TP unico)", "R (BE+50%)", "Chiuso (UTC)", "Note"]
COL = {h: i for i, h in enumerate(HEAD)}


def _open(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        wb = load_workbook(path)
    else:
        wb = Workbook()
        wb.active.title = "Trades"
    if SHEET not in wb.sheetnames:
        ws = wb.create_sheet(SHEET)
        ws.append(HEAD)
    return wb, wb[SHEET]


def alert_key(sym: str, rec: dict) -> str:
    if rec["state"] == "watching":
        return f"{sym}|{rec['side']}|{rec['level']:.2f}|watch|{rec.get('b_price', 0):.2f}"
    return f"{sym}|{rec['side']}|{rec['level']:.2f}|{pd.Timestamp(rec['choch_time']):%Y%m%d%H%M}"


def upsert(sym: str, rec: dict, path: Path = PATH) -> tuple[int, bool]:
    """Registra l'avviso se nuovo. Restituisce (id, nuovo)."""
    wb, ws = _open(path)
    key = alert_key(sym, rec)
    for row in ws.iter_rows(min_row=2):
        if row[COL["Chiave"]].value == key:
            return row[0].value, False
    new_id = ws.max_row  # header = riga 1
    ws.append([new_id, pd.Timestamp(rec["time"]).isoformat(), sym, rec["side"], rec["state"], round(float(rec["level"]), 5),
               round(float(rec["kz_lo"]), 5), round(float(rec["kz_hi"]), 5),
               None if pd.isna(rec.get("entry")) else round(float(rec["entry"]), 5),
               None if pd.isna(rec.get("sl")) else round(float(rec["sl"]), 5),
               None if pd.isna(rec.get("tp")) else round(float(rec["tp"]), 5),
               None if pd.isna(rec.get("rr")) else round(float(rec["rr"]), 2),
               key, None, None, None, None, None, None, None, None])
    wb.save(path)
    return new_id, True


def mark_sent(alert_id: int, path: Path = PATH) -> None:
    wb, ws = _open(path)
    for row in ws.iter_rows(min_row=2):
        if row[0].value == alert_id:
            row[COL["Telegram"]].value = "inviato"
    wb.save(path)


def resolve(m5: pd.DataFrame, row: dict, p: V3Params = V3Params()) -> dict | None:
    """Calcola riempimento ed esito di un ordine limite dai prezzi. None se non ancora determinabile."""
    t0 = pd.Timestamp(row["Creato (UTC)"])
    after = m5.loc[t0:]
    if len(after) < 2:
        return None
    buy = row["Lato"] == "buy"
    entry = float(row["Entry limite"])
    window = after.iloc[1:1 + p.retest_bars]
    touch = (window["low"] <= entry) if buy else (window["high"] >= entry)
    if not touch.any():
        if len(window) >= p.retest_bars:
            return {"Esito": "scaduto (non riempito)"}
        return None
    fill = touch.idxmax()
    sig = pd.DataFrame([{"side": row["Lato"], "entry": entry, "sl": float(row["SL"]), "tp": float(row["TP"]), "rr": float(row["R:R"])}],
                       index=pd.DatetimeIndex([fill]))
    plain, managed = simulate_v3(m5, sig, False), simulate_v3(m5, sig, True)
    out = {"Riempito (UTC)": pd.Timestamp(fill).isoformat()}
    if plain.empty and managed.empty:
        out["Esito"] = "aperto"
        return out
    rp = float(plain.R.iloc[0]) if len(plain) else None
    rm = float(managed.R.iloc[0]) if len(managed) else None
    out.update({"Esito": ("TP" if (rp or 0) > 0 else "SL") if rp is not None else "aperto",
                "R (TP unico)": rp, "R (BE+50%)": rm})
    return out


def update_outcomes(sym: str, m5: pd.DataFrame, path: Path = PATH) -> int:
    """Aggiorna gli esiti degli avvisi di `sym` ancora senza esito definitivo. Restituisce quanti ne ha aggiornati."""
    if not path.exists():
        return 0
    wb, ws = _open(path)
    n = 0
    for row in ws.iter_rows(min_row=2):
        r = {h: row[i].value for h, i in COL.items()}
        if r["Simbolo"] != sym or r["Stato"] == "watching" or r["Entry limite"] is None:
            continue
        if r["Esito"] not in (None, "aperto"):
            continue
        res = resolve(m5, r)
        if res:
            for k, v in res.items():
                row[COL[k]].value = v
            n += 1
    wb.save(path)
    return n


def summary(path: Path = PATH) -> pd.DataFrame:
    """Riepilogo: avvisi, riempiti, esito medio in R (codice) e confronto con le decisioni dell'utente."""
    wb, ws = _open(path)
    df = pd.DataFrame([[c.value for c in row] for row in ws.iter_rows(min_row=2)], columns=HEAD)
    return df
