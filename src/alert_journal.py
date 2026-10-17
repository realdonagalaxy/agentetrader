"""Journal degli avvisi dell'assistente (foglio "Avvisi" di journal/trading_journal.xlsx).

Ogni avviso inviato (setup in formazione o ordine limite) viene registrato; l'esito si calcola in automatico dai prezzi successivi
con le stesse regole del backtest v3 (riempimento al ritorno, SL, TP a fine Leg 1; gestione dell'utente: 60% a +2R, resto a pareggio).
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
        "Chiave", "Telegram", "Decisione utente", "Riempito (UTC)", "Esito", "R (TP unico)", "R (gestione utente)", "Chiuso (UTC)", "Note", "Eventi", "Tipo"]
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
    ws = wb[SHEET]
    for i, h in enumerate(HEAD, start=1):          # aggiunge eventuali colonne nuove a un journal già esistente
        if ws.cell(row=1, column=i).value is None:
            ws.cell(row=1, column=i).value = h
    return wb, ws


def alert_key(sym: str, rec: dict) -> str:
    if rec.get("kind") in ("UT", "UTAD"):
        return f"{sym}|{rec['kind']}|{rec['side']}|{rec['level']:.2f}|{pd.Timestamp(rec['choch_time']):%Y%m%d%H%M}"
    if rec.get("kind") == "early":
        return f"{sym}|early|{rec['side']}|{rec['level']:.2f}|{pd.Timestamp(rec['choch_time']):%Y%m%d%H%M}"
    if rec.get("kind") == "watch":                      # un avviso per ogni passo: ST oltre l'SC, poi Spring oltre l'ST
        has = lambda k: rec.get(k) is not None and pd.notna(rec.get(k))
        if has("utad_time"):
            return f"{sym}|watch|{rec['side']}|{rec['level']:.2f}|Spring|{pd.Timestamp(rec['utad_time']):%Y%m%d%H%M}"
        if has("ut_time"):
            return f"{sym}|watch|{rec['side']}|{rec['level']:.2f}|ST|{pd.Timestamp(rec['ut_time']):%Y%m%d%H%M}"
        return f"{sym}|watch|{rec['side']}|{rec['level']:.2f}|SC"          # primo climax confermato della struttura: un solo avviso
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
               key, None, None, None, None, None, None, None, None, None, rec.get("kind")])
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
    if row.get("Tipo") in ("UT", "UTAD"):
        return _resolve_gold(m5, row, after, buy, entry, p)
    window = after.iloc[1:1 + p.retest_bars]
    touch = (window["low"] <= entry) if buy else (window["high"] >= entry)
    if not touch.any():
        if len(window) >= p.retest_bars:
            return {"Esito": "scaduto (non riempito)"}
        return None
    fill = touch.idxmax()
    sig = pd.DataFrame([{"side": row["Lato"], "entry": entry, "sl": float(row["SL"]), "tp": float(row["TP"]), "rr": float(row["R:R"])}],
                       index=pd.DatetimeIndex([fill]))
    plain, managed = simulate_v3(m5, sig, False), simulate_v3(m5, sig, True, partial_r=2.0, frac=0.6)
    out = {"Riempito (UTC)": pd.Timestamp(fill).isoformat()}
    if plain.empty and managed.empty:
        out["Esito"] = "aperto"
        return out
    rp = float(plain.R.iloc[0]) if len(plain) else None
    rm = float(managed.R.iloc[0]) if len(managed) else None
    out.update({"Esito": ("TP" if (rp or 0) > 0 else "SL") if rp is not None else "aperto",
                "R (TP unico)": rp, "R (gestione utente)": rm})
    return out


def gold_tps(r: dict) -> list[float]:
    risk = abs(float(r["Entry limite"]) - float(r["SL"]))
    return [float(r["Entry limite"]) + (1 if r["Lato"] == "buy" else -1) * 2.5 * risk, float(r["TP"])]


def _gold_fill(after: pd.DataFrame, r: dict, buy: bool, entry: float, p: V3Params):
    """UT: ingresso a mercato (prima barra dopo l'avviso). UTAD: stop pendente, annullato se prima tocca lo SL. Restituisce (fill, scaduto)."""
    if r["Tipo"] == "UT":
        return after.index[1], False
    win = after.iloc[1:1 + p.retest_bars]
    hit = (win["high"] >= entry) if buy else (win["low"] <= entry)
    dead = (win["low"] <= float(r["SL"])) if buy else (win["high"] >= float(r["SL"]))
    i_hit, i_dead = (int(hit.to_numpy().argmax()) if hit.any() else 10**9), (int(dead.to_numpy().argmax()) if dead.any() else 10**9)
    if i_hit < i_dead:
        return win.index[i_hit], False
    if i_dead < 10**9 or len(win) >= p.retest_bars:
        return None, True
    return None, False


def _resolve_gold(m5, row, after, buy, entry, p):
    from src.sdp_gold import simulate_gold
    fill, expired = _gold_fill(after, row, buy, entry, p)
    if expired:
        return {"Esito": "scaduto (non riempito)"}
    if fill is None:
        return None
    tp1, tp = gold_tps(row)
    sig = pd.DataFrame([{"kind": row["Tipo"], "side": row["Lato"], "entry": entry, "sl": float(row["SL"]), "tp1": tp1, "tp": float(row["TP"]),
                         "rr": float(row["R:R"]), "sid": 0, "start": fill}], index=pd.DatetimeIndex([fill]))
    res = simulate_gold(m5, sig)
    out = {"Riempito (UTC)": pd.Timestamp(fill).isoformat()}
    if res.empty or pd.isna(res.R_fine.iloc[0]) and pd.isna(res.R.iloc[0]) and pd.isna(res.R_tp1.iloc[0]):
        out["Esito"] = "aperto"
        return out
    g = res.iloc[0]
    out.update({"Esito": "SL" if g.R_tp1 == -1 else ("TP1+" if pd.notna(g.R) else "aperto"),
                "R (TP unico)": None if pd.isna(g.R_fine) else float(g.R_fine), "R (gestione utente)": None if pd.isna(g.R) else float(g.R)})
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


def events_for(m5: pd.DataFrame, r: dict, tps: list[float], p: V3Params = V3Params()) -> list[tuple[str, pd.Timestamp]]:
    """Eventi dell'ordine nell'ordine in cui accadono: filled, tp1..tpN, be (ritorno a pareggio dopo TP1), sl, expired.
    Ipotesi prudente sulla stessa barra: prima l'evento avverso."""
    t0 = pd.Timestamp(r["Creato (UTC)"])
    after = m5.loc[t0:]
    if len(after) < 2:
        return []
    buy = r["Lato"] == "buy"
    entry, sl = float(r["Entry limite"]), float(r["SL"])
    window = after.iloc[1:1 + p.retest_bars]
    if r.get("Tipo") in ("UT", "UTAD"):
        fill, expired = _gold_fill(after, r, buy, entry, p)
        if expired:
            return [("expired", window.index[-1])]
        if fill is None:
            return []
        ev = [("filled", fill)] if r["Tipo"] == "UTAD" else []
    else:
        touch = (window["low"] <= entry) if buy else (window["high"] >= entry)
        if not touch.any():
            return [("expired", window.index[-1])] if len(window) >= p.retest_bars else []
        fill = touch.idxmax()
        ev = [("filled", fill)]
    seg = m5.loc[fill:]
    lo, hi, idx = seg["low"].to_numpy(), seg["high"].to_numpy(), seg.index
    reached = 0
    for i in range(len(seg)):
        stop = entry if reached >= 1 else sl                    # dopo TP1 lo SL è a pareggio
        if (lo[i] <= stop) if buy else (hi[i] >= stop):
            ev.append(("be" if reached >= 1 else "sl", idx[i]))
            break
        k = reached
        while k < len(tps) and ((hi[i] >= tps[k]) if buy else (lo[i] <= tps[k])):
            k += 1
            ev.append((f"tp{k}", idx[i]))
        reached = k
        if reached == len(tps):
            break
    return ev


def process_events(sym: str, m5: pd.DataFrame, path: Path, tps_fn) -> list[tuple[int, str, pd.Timestamp, dict]]:
    """Restituisce gli eventi NUOVI (non ancora notificati) e li segna nel journal."""
    if not path.exists():
        return []
    wb, ws = _open(path)
    out = []
    for row in ws.iter_rows(min_row=2):
        r = {h: row[i].value for h, i in COL.items()}
        if r["Simbolo"] != sym or r["Stato"] == "watching" or r["Entry limite"] is None:
            continue
        tps = tps_fn(r)
        done = {x for x in (r["Eventi"] or "").split(",") if x}
        if done & {"sl", "be", "expired", f"tp{len(tps)}"}:
            continue
        new = [(n, t) for n, t in events_for(m5, r, tps) if n not in done]
        if new:
            row[COL["Eventi"]].value = ",".join(sorted(done | {n for n, _ in new}))
            out += [(r["ID"], n, t, r) for n, t in new]
    wb.save(path)
    return out
