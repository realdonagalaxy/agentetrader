"""Confronto di strategie sugli STESSI segnali: rigioca ogni segnale sui prezzi M1 e calcola, con lo spread, cosa sarebbe successo con ciascuna variante di uscita e di filtro.

Segnali da:  --json  (esportazione della chat di Telegram Desktop: result.json)   oppure   --csv  (journal/segnali.csv scritto dal programma dei segnali).
Prezzi:      --m1 file  (pickle o CSV di barre M1 in UTC, es. quelli di export_m5 / Dukascopy)   oppure   --mt5  (barre M1 lette da MT5, solo Windows, terminale aperto).
Modello (lo stesso del programma dal vivo, src.mt5_orders):
 - ingresso a mercato all'apertura della prima barra M1 successiva al messaggio (+ --ritardo secondi); BUY all'ask (= bid + spread), SELL al bid; spread fisso --spread ($);
 - Entry, SL e TP di Vantage convertiti con lo scarto: --scarto fisso, altrimenti la mediana degli scarti misurati sui 30 segnali precedenti (almeno 10); senza scarto il filtro dei pips non si applica
   e i livelli sono a distanza dall'Entry sul prezzo di ingresso, come dal vivo;
 - SL e TP scattano sul prezzo di chiusura (BUY: bid, SELL: ask); nella stessa barra SL e TP -> si conta lo SL (ipotesi prudente); orizzonte --ore ore (poi chiusura al prezzo di mercato);
 - pips: oro 1 pip = 0,10 $.
Varianti: TP1 (la regola attuale), TP2, TP3, PARZ (60% a TP1, il resto a pareggio fino a TP2), e il filtro «pips mancanti al TP1 > X» per X = 0, 30, 40, 45, 60.
Per le varianti con TP2/TP3 si confrontano solo i segnali che li hanno. Le differenze sono sempre APPAIATE (stessi segnali) con errore standard; prima e seconda parte nel tempo (70/30) devono dare lo stesso segno.
Uso:  python -m src.analisi_segnali --json result.json --m1 data/XAUUSD_M1.pkl --spread 0.70 --scarto 8.0 [--fuso Europe/Rome]
"""
import argparse
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PIP = 0.10
FILTRI = (0, 30, 40, 45, 60)


# ---------- lettura dei segnali ----------
def flatten(text) -> str:
    """Il campo 'text' dell'esportazione Telegram è una stringa oppure un elenco di stringhe e frammenti formattati."""
    if isinstance(text, list):
        return "".join(x if isinstance(x, str) else str(x.get("text", "")) for x in text)
    return str(text or "")


def signals_from_json(path: str, fuso: str, simbolo: str = "XAUUSD") -> list[dict]:
    from src.mt5_orders import OWN_PREFIXES, clean_text, looks_like_signal, parse_signal
    data = json.load(open(path, encoding="utf-8"))
    out, last = [], {}
    for m in data.get("messages", []):
        if m.get("type") != "message":
            continue
        text = clean_text(flatten(m.get("text")))
        if not text or text.startswith(OWN_PREFIXES) or not looks_like_signal(text):
            continue
        try:
            sg = parse_signal(text)
        except ValueError:
            continue
        if m.get("date_unixtime"):
            t = pd.Timestamp(int(m["date_unixtime"]), unit="s")                      # già UTC
        else:
            t = pd.Timestamp(datetime.fromisoformat(m["date"]).replace(tzinfo=ZoneInfo(fuso)).astimezone(timezone.utc).replace(tzinfo=None))
        key = (sg["side"], sg["entry"], sg["sl"], sg["tp1"])
        if key in last and (t - last[key]).total_seconds() < 120:                    # lo stesso segnale ripubblicato
            continue
        last[key] = t
        if sg["symbol"] != simbolo:
            continue
        out.append({"time": t, **sg})
    return sorted(out, key=lambda r: r["time"])


def signals_from_csv(path: str) -> list[dict]:
    d = pd.read_csv(path)
    out = []
    for r in d.itertuples():
        if not r.direzione or pd.isna(r.entry):
            continue
        t = pd.Timestamp(r.ora_messaggio_utc if isinstance(r.ora_messaggio_utc, str) and r.ora_messaggio_utc else r.quando_utc).tz_localize(None)
        out.append({"time": t, "side": r.direzione, "symbol": r.simbolo, "entry": float(r.entry), "sl": float(r.sl), "tp1": float(r.tp1),
                    **({"tp2": float(r.tp2)} if not pd.isna(r.tp2) else {}), **({"tp3": float(r.tp3)} if not pd.isna(r.tp3) else {})})
    return sorted(out, key=lambda r: r["time"])


# ---------- prezzi ----------
def load_m1(path: str) -> pd.DataFrame:
    """Barre M1 in UTC da uno o più file: pickle, oppure CSV/CSV.GZ (anche con caratteri jolly, es. data/raw/XAUUSD_BID_M1_*.csv come li scrive dukascopy_fetch)."""
    import glob
    from src.data_loader import load_ohlc
    files = sorted(glob.glob(path)) or [path]
    parts = []
    for f in files:
        if f.endswith(".pkl"):
            m = pd.read_pickle(f)
            if m.index.tz is not None:
                m.index = m.index.tz_convert("UTC").tz_localize(None)
        else:
            m = load_ohlc(f)
        parts.append(m[["open", "high", "low", "close"]])
    m = pd.concat(parts)
    return m[~m.index.duplicated(keep="first")].sort_index()


def m1_from_mt5(start, end) -> pd.DataFrame:
    """Barre M1 dell'oro da MT5 (primo conto attivo dell'app), in UTC. Solo Windows. L'orario del server si toglie con MT5_UTC_OFFSET_HOURS (config.env)."""
    import os
    from datetime import timedelta
    from src import mt5_accounts as ma
    acc = next(a for a in ma.list_accounts() if a["enabled"])
    off = int(float(os.environ.get("MT5_UTC_OFFSET_HOURS") or 0) * 3600)
    with ma.session(acc) as mt5:
        from src.price_compare import find_symbol
        sym = find_symbol(mt5, "XAUUSD")
        rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, (start - timedelta(hours=3)).to_pydatetime().replace(tzinfo=timezone.utc), (end + timedelta(days=2)).to_pydatetime().replace(tzinfo=timezone.utc))
    if rates is None or len(rates) == 0:
        raise SystemExit("MT5 non ha barre M1 per il periodo: apri un grafico dell'oro e scorri indietro per scaricarle.")
    d = pd.DataFrame(rates)
    d.index = pd.to_datetime(d["time"] - off, unit="s")
    return d[["open", "high", "low", "close"]]


# ---------- simulazione ----------
def walk(side, hi, lo, close, i0, bid0, s, levels, horizon):
    """Percorre le barre da i0 e restituisce, per ogni livello richiesto in `levels` (dict nome->livello in prezzi BID), l'indice di barra in cui scatta, e l'indice dello SL.
    Restituisce (idx_sl, {nome: idx}). Indici None se non scatta entro l'orizzonte."""
    end = min(i0 + horizon, len(hi))
    h, l = hi[i0:end], lo[i0:end]
    def first(mask):
        return int(mask.argmax()) + i0 if mask.any() else None
    if side == "buy":
        sl = first(l <= levels["sl"])
        tps = {k: first(h >= v) for k, v in levels.items() if k != "sl"}
    else:
        sl = first(h >= levels["sl"])
        tps = {k: first(l <= v) for k, v in levels.items() if k != "sl"}
    return sl, tps, end - 1


def pnl(side, entry_px, level_bid, s):
    """Pips di un'uscita al livello (in prezzo bid): BUY esce al bid, SELL esce all'ask (= bid + s)."""
    return ((level_bid - entry_px) if side == "buy" else (entry_px - (level_bid + s))) / PIP


def mtm(side, close_bid, entry_px, s):
    return pnl(side, entry_px, close_bid, s)


def simulate_signal(sg, m1, arr, off, s, delay_s, horizon, tie="sl"):
    """Esito di tutte le varianti per un segnale. None se non ci sono prezzi. `arr` = (indice, open, high, low, close) come array."""
    idx, op, hi, lo, cl = arr
    t0 = sg["time"] + pd.Timedelta(seconds=delay_s)
    i0 = int(idx.searchsorted(np.datetime64(t0.ceil("min"))))
    if i0 >= len(idx) - 2 or (idx[i0] - np.datetime64(t0)) > np.timedelta64(15, "m"):
        return None                                                  # nessun prezzo vicino al messaggio (buco nei dati o fuori periodo)
    buy = sg["side"] == "buy"
    bid0 = float(op[i0])
    entry_px = bid0 + s if buy else bid0
    measured = bid0 - sg["entry"]
    e_off = off if off is not None else measured                       # senza scarto: livelli a distanza dall'Entry sul prezzo di adesso (come dal vivo)
    lv = {"sl": sg["sl"] + e_off, "tp1": sg["tp1"] + e_off}
    for k in ("tp2", "tp3"):
        if k in sg:
            lv[k] = sg[k] + e_off
    remaining = ((lv["tp1"] - bid0) if buy else (bid0 - lv["tp1"])) / PIP
    if (buy and lv["sl"] >= bid0) or (not buy and lv["sl"] <= bid0):
        return None                                                  # prezzo già oltre lo SL: dal vivo non si apre
    sl_i, tp_i, last = walk(sg["side"], hi, lo, cl, i0, bid0, s, lv, horizon)
    res = {"time": sg["time"], "side": sg["side"], "entry": sg["entry"], "measured": measured, "remaining": remaining if off is not None else np.nan, "has_tp2": "tp2" in sg, "has_tp3": "tp3" in sg}
    def exit_single(k):
        t = tp_i.get(k)
        if t is not None and (sl_i is None or t < sl_i or (tie == "tp" and t == sl_i)):          # stessa barra: per prudenza SL (tie="sl"), oppure TP (tie="tp") per misurare quanto conta
            return pnl(sg["side"], entry_px, lv[k], s), "tp"
        if sl_i is not None:
            return pnl(sg["side"], entry_px, lv["sl"], s), "sl"
        return mtm(sg["side"], float(cl[last]), entry_px, s), "tempo"
    res["TP1"], res["TP1_esito"] = exit_single("tp1")
    if "tp2" in lv:
        res["TP2"], _ = exit_single("tp2")
    if "tp3" in lv:
        res["TP3"], _ = exit_single("tp3")
    if "tp2" in lv:                                                  # parzializzazione: 60% a TP1, il resto a pareggio fino a TP2
        a, kind = exit_single("tp1")
        if kind == "tp":
            t1 = tp_i["tp1"]
            be = entry_px if buy else entry_px - s                    # livello BID che equivale al pareggio
            h, l = hi[t1 + 1:last + 1], lo[t1 + 1:last + 1]
            if buy:
                b_hit = int((l <= be).argmax()) if (l <= be).any() else None
                t_hit = int((h >= lv["tp2"]).argmax()) if (h >= lv["tp2"]).any() else None
            else:
                b_hit = int((h >= be).argmax()) if (h >= be).any() else None
                t_hit = int((l <= lv["tp2"]).argmax()) if (l <= lv["tp2"]).any() else None
            if t_hit is not None and (b_hit is None or t_hit < b_hit):
                b = pnl(sg["side"], entry_px, lv["tp2"], s)
            elif b_hit is not None:
                b = 0.0
            else:
                b = mtm(sg["side"], float(cl[last]), entry_px, s)
            res["PARZ"] = 0.6 * a + 0.4 * b
        else:
            res["PARZ"] = a
    return res


# ---------- statistica ----------
def se(x):
    x = np.asarray(x, float)
    return float(x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else float("nan")


def line(name, x, base=None):
    x = np.asarray(x, float)
    n = len(x)
    cut = int(n * 0.7)
    s = f"{name:34s} n={n:4d} media {x.mean():+7.2f} pips (±{se(x):5.2f})  totale {x.sum():+8.1f}"
    if n >= 10:
        s += f"  | 1ª parte {x[:cut].mean():+6.2f}  2ª parte {x[cut:].mean():+6.2f}"
    if base is not None and n == len(base) and n > 2:
        d = x - np.asarray(base, float)
        z = d.mean() / se(d) if se(d) > 0 else 0.0
        s += f"  | diff. vs TP1 {d.mean():+6.2f} (±{se(d):5.2f}, z {z:+.1f})"
    return s


def report(rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    n = len(df)
    print(f"\nSegnali rigiocati: {n}  ({df.time.min():%Y-%m-%d} -> {df.time.max():%Y-%m-%d})")
    if n < 30:
        print("ATTENZIONE: meno di 30 segnali: qualunque confronto qui sotto è solo indicativo.")
    print(f"TP1 raggiunto: {np.mean(df.TP1_esito == 'tp'):.1%} · SL: {np.mean(df.TP1_esito == 'sl'):.1%} · tempo scaduto: {np.mean(df.TP1_esito == 'tempo'):.1%}\n")
    print("=== Uscita (stessi segnali, pips netti con spread) ===")
    print(line("TP1 su tutti i segnali (attuale)", df.TP1))
    for k, txt in (("TP2", "TP2"), ("TP3", "TP3"), ("PARZ", "PARZ 60/40 (TP1 + BE/TP2)")):
        sub = df[df[k].notna()] if k in df else df.iloc[0:0]
        if len(sub) >= 2:
            print(line(f"{txt} (solo seg. con TP2)", sub[k], None))
            print(line("   stessi segnali con TP1", sub.TP1, None))
            d = sub[k].values - sub.TP1.values
            z = d.mean() / se(d) if se(d) > 0 else 0.0
            print(f"   differenza appaiata {txt} - TP1: {d.mean():+.2f} pips (±{se(d):.2f}, z {z:+.1f})  {'-> dentro il rumore' if abs(z) < 2 else '-> da verificare su più segnali'}")
    fil = df[df.remaining.notna()]
    print("\n=== Filtro «pips mancanti al TP1 > X» (solo con scarto disponibile) ===")
    if len(fil) < 5:
        print("Scarto non disponibile (usa --scarto) o troppi pochi segnali.")
    for x in FILTRI if len(fil) >= 5 else ():
        keep, drop = fil[fil.remaining > x], fil[fil.remaining <= x]
        print(f"X={x:3d}: entrati {len(keep):4d} media {keep.TP1.mean() if len(keep) else float('nan'):+6.2f} | scartati {len(drop):4d} media {drop.TP1.mean() if len(drop) else float('nan'):+6.2f}"
              + (f"  (se gli scartati avessero media > 0, il filtro butta via trade buoni)" if len(drop) >= 5 and drop.TP1.mean() > 0 and x == 45 else ""))
    print("\n=== Per direzione (TP1) ===")
    for sd in ("buy", "sell"):
        sub = df[df.side == sd]
        if len(sub) >= 2:
            print(line(f"{sd.upper()}", sub.TP1))
    print("\nNota: sono simulazioni su barre M1 (SL prima di TP nella stessa barra, spread fisso): il risultato reale può differire. Servono centinaia di segnali per conclusioni solide.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="result.json esportato da Telegram Desktop")
    ap.add_argument("--csv", help="journal/segnali.csv")
    ap.add_argument("--m1", help="barre M1 (pickle o CSV, UTC)")
    ap.add_argument("--mt5", action="store_true", help="legge le barre M1 da MT5 (Windows)")
    ap.add_argument("--fuso", default="Europe/Rome", help="fuso orario dei messaggi se l'esportazione non ha date_unixtime")
    ap.add_argument("--spread", type=float, default=0.70, help="spread fisso in $ (ActivTrades ~0,70)")
    ap.add_argument("--scarto", type=float, help="scarto fisso ActivTrades - Vantage in $ (senza: mediana mobile dei 30 segnali precedenti, almeno 10)")
    ap.add_argument("--ritardo", type=float, default=5, help="secondi tra il messaggio e l'esecuzione")
    ap.add_argument("--ore", type=float, default=24, help="durata massima del trade in ore")
    ap.add_argument("--simbolo", default="XAUUSD")
    ap.add_argument("--pari", choices=("sl", "tp"), default="sl", help="se nella stessa barra M1 toccano sia SL sia TP: conta lo SL (prudente) o il TP")
    a = ap.parse_args()
    sigs = signals_from_json(a.json, a.fuso, a.simbolo) if a.json else signals_from_csv(a.csv) if a.csv else None
    if sigs is None:
        raise SystemExit("Indica --json o --csv.")
    print(f"Segnali letti: {len(sigs)}")
    if not sigs:
        raise SystemExit("Nessun segnale riconosciuto: controlla il file (servono righe Entry, SL, TP1).")
    m1 = m1_from_mt5(sigs[0]["time"], sigs[-1]["time"]) if a.mt5 else load_m1(a.m1)
    arr = (m1.index.values, m1.open.values, m1.high.values, m1.low.values, m1.close.values)
    rows, hist, skipped = [], [], 0
    for sg in sigs:
        use = a.scarto if a.scarto is not None else (float(np.median(hist[-30:])) if len(hist) >= 10 else None)
        r = simulate_signal(sg, m1, arr, use, a.spread, a.ritardo, int(a.ore * 60), a.pari)
        if r is None:
            skipped += 1
            continue
        hist.append(r["measured"])
        rows.append(r)
    print(f"Fuori dal periodo dei prezzi o non apribili: {skipped}")
    if not rows:
        raise SystemExit("Nessun segnale rigiocabile.")
    report(rows)


if __name__ == "__main__":
    main()
