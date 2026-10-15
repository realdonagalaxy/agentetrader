"""Gestione del trading journal in Excel (openpyxl)."""
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook

JOURNAL_PATH = Path("journal/trading_journal.xlsx")
HEADERS = ["ID", "Aperto", "Chiuso", "Simbolo", "Lato", "Entry", "SL", "TP",
           "Exit", "R", "Esito", "Setup", "Errori", "Note"]


def init_journal(path: Path = JOURNAL_PATH) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Trades"
    ws.append(HEADERS)
    wb.create_sheet("Metriche")
    wb.save(path)


def add_trade(symbol: str, side: str, entry: float, sl: float, tp: float,
              setup: str = "", note: str = "", path: Path = JOURNAL_PATH) -> int:
    init_journal(path)
    wb = load_workbook(path)
    ws = wb["Trades"]
    trade_id = ws.max_row  # header = riga 1
    ws.append([trade_id, datetime.now().isoformat(timespec="seconds"), None,
               symbol, side, entry, sl, tp, None, None, "OPEN", setup, "", note])
    wb.save(path)
    return trade_id


def close_trade(trade_id: int, exit_price: float, errors: str = "",
                path: Path = JOURNAL_PATH) -> float:
    wb = load_workbook(path)
    ws = wb["Trades"]
    for row in ws.iter_rows(min_row=2):
        if row[0].value == trade_id:
            side, entry, sl = row[4].value, row[5].value, row[6].value
            risk = abs(entry - sl)
            pnl = (exit_price - entry) if side.lower() == "buy" else (entry - exit_price)
            r = pnl / risk if risk else 0.0
            row[2].value = datetime.now().isoformat(timespec="seconds")
            row[8].value, row[9].value = exit_price, round(r, 2)
            row[10].value = "WIN" if r > 0 else "LOSS" if r < 0 else "BE"
            row[12].value = errors
            wb.save(path)
            update_metrics(path)
            return r
    raise ValueError(f"Trade {trade_id} non trovato")


def update_metrics(path: Path = JOURNAL_PATH) -> dict:
    wb = load_workbook(path)
    rs = [r[9].value for r in wb["Trades"].iter_rows(min_row=2) if r[9].value is not None]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    m = {
        "Trade chiusi": len(rs),
        "Win rate": len(wins) / len(rs) if rs else 0,
        "Expectancy (R)": sum(rs) / len(rs) if rs else 0,
        "Profit factor": sum(wins) / abs(sum(losses)) if losses else None,
        "R totale": sum(rs),
    }
    ws = wb["Metriche"]
    ws.delete_rows(1, ws.max_row)
    for k, v in m.items():
        ws.append([k, v])
    wb.save(path)
    return m
