"""Assistente SDP v3: analizza il grafico e manda l'analisi su Telegram. La decisione di aprire il trade resta all'utente.

Ogni avviso viene registrato nel journal (foglio "Avvisi") e l'esito si calcola in automatico dai prezzi successivi.

Uso:
  # un'analisi a un istante (anche passato, per collaudo):
  python -m src.assistant --symbol XAUUSD --tf 5 --until "2025-12-15 10:00" [--send]
  # riproduzione di un periodo passato, passo di 60 minuti, journal separato di prova:
  python -m src.assistant --symbol XAUUSD --tf 15 --replay 2025-12-08 2025-12-12 --step 60 --journal journal/replay_journal.xlsx
Fonte dati dal vivo (cTrader Open API): da collegare quando l'applicazione sarà "Active" (vedi live_analysis.fetch_ctrader).
"""
import argparse
import html

import numpy as np
import pandas as pd

from src import alert_journal as aj
from src.chart import render_chart
from src.data_loader import load_ohlc, resample
from src.live_analysis import decimals, pip_size
from src.market_config import ENTRY_FROM, ENTRY_TO, MACRO_TZ, SEND_TRADE_PLAN, VWAP_RULE, in_entry_window, macro_at
from src.market_structure import multi_tf_trend
from src.range_detector import atr
from src.sdp_gold import GoldParams, generate_gold
from src.sdp_v3 import V3Params, generate_v3

DISCLAIMER = ("ℹ️ Backtest 2003–2025 su EURUSD, oro e Nasdaq: nessun vantaggio statistico dimostrato (≈0R, costi esclusi). "
              "Questo è un avviso di analisi: la decisione è tua e l'esito verrà registrato nel journal.")


DISCLAIMER_GOLD = ("ℹ️ Backtest oro 2003–2025 della sequenza BC/SC → UT → UTAD: nessun vantaggio statistico dimostrato (≈0R, costi esclusi). "
                   "Avviso di analisi: la decisione è tua e l'esito verrà registrato nel journal.")


def analyze(m5: pd.DataFrame, tf: int = 5, days: int = 25) -> dict:
    """Setup in formazione e ordini limite dall'ultimo istante disponibile."""
    m5 = m5.loc[m5.index[-1] - pd.Timedelta(days=days):]
    p = V3Params(struct_tf_min=tf)
    last = m5.index[-1]
    sig = generate_v3(m5, p, live=True)
    h1 = resample(m5, "1h")
    bias = multi_tf_trend(h1.iloc[-400:]) if len(h1) > 50 else {"H4": "?", "H1": "?", "bias": "?"}
    rows = []
    if len(sig):
        recent = last - pd.Timedelta(minutes=5 * p.retest_bars)
        keep = sig[(sig.state != "filled") | (pd.to_datetime(sig.choch_time.fillna(sig.index.to_series())) >= recent)].copy()
        keep["lv"] = keep.level.round(2)
        wf = keep[keep.state == "waiting_fill"]
        latest = wf.groupby(["side", "lv"]).choch_time.transform("max")                  # un solo ordine in attesa per struttura
        keep = keep.drop(index=wf.index[wf.choch_time != latest]) if len(wf) else keep
        for t, r in keep.iterrows():
            d = r.to_dict()
            d["time"] = t
            d["choch_time"] = d.get("choch_time") if pd.notna(d.get("choch_time")) else t
            rows.append(d)
    a15 = float(atr(resample(m5, "15min")).iloc[-1])
    return {"time": last, "bias": bias, "macro": macro_at(last.to_pydatetime()), "rows": rows, "tf": tf, "atr15": a15}


SEQ_PREFIXES = ("XAU", "XAG", "USATECH", "USA500", "USA30")        # oro, argento, indici americani: sequenza SC/ST/Spring + orario operativo


def is_gold(sym: str) -> bool:
    return sym.upper().startswith(SEQ_PREFIXES)


def analyze_gold(m5: pd.DataFrame, tf: int = 15, days: int = 25, recent_min: int = 120) -> dict:
    """Sequenza BC/SC → UT → UTAD sull'oro: segnali degli ultimi `recent_min` minuti e climax in corso."""
    m5 = m5.loc[m5.index[-1] - pd.Timedelta(days=days):]
    last = m5.index[-1]
    sig = generate_gold(m5, GoldParams(struct_tf_min=tf), live=True)
    h1 = resample(m5, "1h")
    bias = multi_tf_trend(h1.iloc[-400:]) if len(h1) > 50 else {"H4": "?", "H1": "?", "bias": "?"}
    rows = []
    if len(sig):
        sig = sig.reset_index()
        t_col = sig.columns[0]
        fresh = sig[(sig.kind != "watch") & (pd.to_datetime(sig[t_col]) >= last - pd.Timedelta(minutes=recent_min))]
        watch = sig[sig.kind == "watch"]
        def stage_time(r):                         # istante dell'ultimo passo (ST oltre l'SC, o Spring oltre l'ST)
            for k in ("utad_time", "ut_time", "bc_time"):
                if k in r and pd.notna(r[k]):
                    return pd.Timestamp(r[k])
            return pd.NaT
        keep_w = np.array([(pd.notna(stage_time(r)) and stage_time(r) >= last - pd.Timedelta(minutes=recent_min)) for _, r in watch.iterrows()], dtype=bool)
        watch = watch.loc[keep_w] if len(watch) else watch
        for _, r in pd.concat([fresh, watch.sort_values(t_col).groupby(["side", "bc_time"]).tail(1)]).iterrows():
            d = r.to_dict()
            d["time"] = d.pop(t_col)
            if d["kind"] in ("UT", "UTAD") and not SEND_TRADE_PLAN:
                continue                                                  # niente piani Entry/SL/TP: solo conformazione
            if d["kind"] in ("UT", "UTAD") and VWAP_RULE and not bool(d.get("vwap_out" if VWAP_RULE == "choch" else "ext_out", True)):
                continue                                                  # CHoCH dentro le bande del VWAP: trade scartato
            if d["kind"] in ("UT", "UTAD") and not in_entry_window(pd.Timestamp(d["choch_time"]).to_pydatetime()):
                d.update(kind="early", state="watching")                 # fuori orario operativo: solo individuazione del setup
                for k in ("entry", "sl", "tp", "tp1", "rr"):
                    d[k] = float("nan")
            rows.append(d)
    a15 = float(atr(resample(m5, "15min")).iloc[-1])
    return {"time": last, "bias": bias, "macro": macro_at(last.to_pydatetime()), "rows": rows, "tf": tf, "atr15": a15}


def format_gold(sym: str, a: dict, r: dict) -> str:
    d, pip = decimals(sym), pip_size(sym)
    buy = r["side"] == "buy"
    side = "BUY" if buy else "SELL"
    t_loc = pd.Timestamp(a["time"]).tz_localize("UTC").astimezone(MACRO_TZ)
    ctx = f"🕒 {t_loc:%d/%m %H:%M} (Roma) · macro: {a['macro'] or 'fuori macro'} · Bias H4 {a['bias']['H4']} / H1 {a['bias']['H1']}"
    cl = "SC" if buy else "BC"
    ut, utad = ("ST", "Spring") if buy else ("UT", "UTAD")
    struct = (f"Struttura: {'minimi' if buy else 'massimi'} uguali a {_px(r['level'], d)} · Leg 1 fino a {_px(r['b_price'], d)} "
              f"({float(r['leg1_len']) / pip:.0f} pip) · {cl} a {_px(r['bc_price'], d)} (gobba più profonda del MACD 8,21,5)")
    if r["kind"] == "watch" and not (r.get("ut_time") is not None and pd.notna(r.get("ut_time"))):
        return f"🚨 SEGNALE DI {side} IN ARRIVO SU {html.escape(sym)} 🚨"           # climax SC/BC confermato
    if r["kind"] == "watch":
        sp = r.get("utad_time") is not None and pd.notna(r.get("utad_time"))
        if sp:
            ext = "minimo" if buy else "massimo"
            body = (f"{utad} a {_px(r['utad_price'], d)}: il {ext} ha superato l'{ut} ({_px(r['ut_price'], d)}).\n"
                    f"Attendo il CHoCH M5: poi arriva lo stop pendente con entry, SL e TP.")
        else:
            ext = "minimo" if buy else "massimo"
            body = (f"{ut} a {_px(r['ut_price'], d)}: il {ext} ha superato {'l' + chr(39) + cl if buy else 'il ' + cl} ({_px(r['bc_price'], d)}).\n"
                    f"Attendo il CHoCH M5: poi arriva l'ingresso a mercato con entry, SL e TP.")
        return "\n".join([f"<b>{side} {html.escape(sym)}</b> — {utad if sp else ut} oltre {ut if sp else cl}", "", body, ctx, struct, "", DISCLAIMER_GOLD])
    if r["kind"] == "setup":
        lat = "minimi" if buy else "massimi"
        return "\n".join([f"<b>{side} {html.escape(sym)}</b> — SETUP: lateralizzazione, Leg 1 e Leg 2", "",
                          f"{lat.capitalize()} uguali a {_px(r['level'], d)} (lateralizzazione) · Leg 1 fino a {_px(r['b_price'], d)} "
                          f"({float(r['leg1_len']) / pip:.0f} pip) · il prezzo ha rotto il livello: Leg 2 in corso.",
                          "Valuta il contesto.", ctx, "", "ℹ️ Segnale di struttura, non di ingresso: la valutazione è tua. Esito registrato nel journal."])
    if r["kind"] == "early":
        t_loc = pd.Timestamp(r["choch_time"]).tz_localize("UTC").astimezone(MACRO_TZ)
        return "\n".join([f"<b>{side} {html.escape(sym)}</b> — setup individuato alle {t_loc:%H:%M} (Roma)", "",
                          f"La sequenza {cl} → {ut}" + (f" → {utad}" if r.get("utad_time") is not None and pd.notna(r.get("utad_time")) else "")
                          + f" è completa con CHoCH M5, ma siamo fuori dall'orario operativo: i trade si aprono solo se il CHoCH M5 avviene tra le {ENTRY_FROM[0]}:{ENTRY_FROM[1]:02d} (apertura New York) e le {ENTRY_TO[0]}:{ENTRY_TO[1]:02d}.",
                          "Non apro il trade: attendo un nuovo CHoCH M5 nell'orario operativo.", ctx, struct, "", DISCLAIMER_GOLD])
    entry, sl, tp1, tp = float(r["entry"]), float(r["sl"]), float(r["tp1"]), float(r["tp"])
    risk = abs(entry - sl)
    if r["kind"] == "UT":
        how = f"{ut}: entry a mercato alla chiusura della candela del CHoCH M5."
        seq = f"{cl} → {ut} a {_px(r['ut_price'], d)} (minimo oltre il {cl}) con CHoCH M5"
        head = f"➡️ Entry (mercato): {_px(entry, d)}"
    else:
        dl = (pd.Timestamp(r["choch_time"]) + pd.Timedelta(minutes=5 * V3Params().retest_bars)).tz_localize("UTC").astimezone(MACRO_TZ)
        how = f"{utad}: {'BUY' if buy else 'SELL'} STOP immediato dopo il CHoCH M5, valido fino alle {dl:%H:%M} (Roma)."
        seq = f"{cl} → {ut} a {_px(r['ut_price'], d)} → {utad} a {_px(r['utad_price'], d)}, poi CHoCH M5"
        head = f"➡️ Entry ({'BUY' if buy else 'SELL'} STOP): {_px(entry, d)}"
    lines = [f"<b>{side} {html.escape(sym)}</b>", "", head, "", f"❌ SL: {_px(sl, d)}", f"✅ TP1: {_px(tp1, d)} (2,5R)", f"✅ TP2: {_px(tp, d)} (fine Leg 1)",
             "", how, f"Rischio {risk / pip:.0f} pip · R:R verso fine Leg 1: {float(r['rr']):.1f}. A TP1 chiudi il 60% e porta lo SL a pareggio; il resto scorre fino a fine Leg 1.",
             ctx, struct, f"Sequenza: {seq}"]
    if risk < 0.3 * a.get("atr15", 0):
        lines.append(f"⚠️ Rischio piccolo ({risk / pip:.0f} pip, meno di 0,3 ATR M15): spread e slippage possono pesare molto sul R:R.")
    return "\n".join(lines + ["", DISCLAIMER_GOLD])


def _px(v, d):
    return f"{float(v):.{d}f}"


def _tick(b):
    return "✅" if bool(b) else "❌"


def take_profits(entry: float, sl: float, tp_end: float, buy: bool) -> list[float]:
    """TP1 = +2R (qui chiudi il 60% del profitto), TP3 = fine Leg 1, TP2 = a metà tra i due."""
    risk = abs(entry - sl)
    tp1 = entry + (1 if buy else -1) * 2 * risk
    if abs(tp_end - entry) <= 2.2 * risk:                     # fine Leg 1 praticamente a 2R: un solo obiettivo
        return [tp_end]
    return [tp1, (tp1 + tp_end) / 2, tp_end]


def format_alert(sym: str, a: dict, r: dict) -> str:
    d, pip = decimals(sym), pip_size(sym)
    buy = r["side"] == "buy"
    side = "BUY" if buy else "SELL"
    t_loc = pd.Timestamp(a["time"]).tz_localize("UTC").astimezone(MACRO_TZ)
    ctx = f"🕒 {t_loc:%d/%m %H:%M} (Roma) · macro: {a['macro'] or 'fuori macro'} · Bias H4 {a['bias']['H4']} / H1 {a['bias']['H1']}"
    kz = f"{_px(min(r['kz_lo'], r['kz_hi']), d)} – {_px(max(r['kz_lo'], r['kz_hi']), d)}"
    struct = (f"Struttura: {'minimi' if buy else 'massimi'} uguali a {_px(r['level'], d)} · Leg 1 fino a {_px(r['b_price'], d)} "
              f"({float(r['leg1_len']) / pip:.0f} pip) · Kill Zone 1.272–1.618: {kz} · estremo {_px(r['sw_price'], d)}")
    if r["state"] == "watching":
        return "\n".join([f"<b>{side} {html.escape(sym)}</b> — in formazione", "",
                          f"Il prezzo è nella Kill Zone ({kz}). Attendere CHoCH M5 e ritorno sul livello rotto: allora arriva l'ordine con entry, SL e TP.",
                          ctx, struct, f"OB non mitigato toccato: {_tick(r.get('ob_touch'))} (M{a['tf']})", "", DISCLAIMER])
    entry, sl, tp_end = float(r["entry"]), float(r["sl"]), float(r["tp"])
    risk = abs(entry - sl)
    tps = take_profits(entry, sl, tp_end, buy)
    deadline = (pd.Timestamp(r["choch_time"]) + pd.Timedelta(minutes=5 * V3Params().retest_bars)).tz_localize("UTC").astimezone(MACRO_TZ)
    status = "già riempito" if r["state"] == "filled" else f"in attesa del ritorno, valido fino alle {deadline:%H:%M} (Roma)"
    conf = f"OB {_tick(r.get('ob_touch'))} · Wyckoff gobba minore {_tick(r.get('wy_div'))} / volume minore {_tick(r.get('wy_vol'))}"
    if pd.notna(r.get("vwap_ext")):
        conf += f" · VWAP {float(r['vwap_ext']):.1f}σ"
    lines = [f"<b>{side} {html.escape(sym)}</b>", "", f"➡️ Entry: {_px(entry, d)}", "", f"❌ SL: {_px(sl, d)}"]
    lines += [f"✅ TP{i + 1}: {_px(t, d)}" for i, t in enumerate(tps)]
    lines += ["", f"Ordine limite {status}.",
              f"Rischio {risk / pip:.0f} pip · R:R verso fine Leg 1: {float(r['rr']):.1f}. "
              + ("A TP1 (+2R) chiudi il 60% del profitto; TP finale = fine Leg 1." if len(tps) > 1
                 else "Obiettivo = fine Leg 1."),
              ctx, struct, f"Conferme: {conf} (M{a['tf']})"]
    if risk < 0.3 * a.get("atr15", 0):
        lines.append(f"⚠️ Rischio piccolo ({risk / pip:.0f} pip, meno di 0,3 ATR M15): spread e slippage possono pesare molto sul R:R.")
    return "\n".join(lines + ["", DISCLAIMER])


def format_event(sym: str, name: str, r: dict, tps: list[float]) -> str:
    d = decimals(sym)
    buy = r["Lato"] == "buy"
    head = f"<b>{'BUY' if buy else 'SELL'} {html.escape(sym)}</b>"
    entry = _px(r["Entry limite"], d)
    n = len(tps)
    if name == "filled":
        return f"{head}\n\n✅ Ordine riempito a {entry}.\nSL {_px(r['SL'], d)} · TP1 {_px(tps[0], d)}" + (f" · TP{n} {_px(tps[-1], d)}" if n > 1 else "")
    if name == "tp1" and n > 1:
        return (f"{head}\n\n🎯 TP1 raggiunto ({_px(tps[0], d)})\n\n"
                f"👉 Chiudi il 60% della posizione\n👉 Porta lo SL a pareggio (BE): {entry}")
    if name == f"tp{n}":
        return f"{head}\n\n🏁 {'TP finale' if n == 1 else f'TP{n}'} raggiunto ({_px(tps[-1], d)}): trade chiuso a target."
    if name.startswith("tp"):
        return f"{head}\n\n🎯 {name.upper()} raggiunto ({_px(tps[int(name[2:]) - 1], d)}). Il resto resta aperto con SL a pareggio ({entry})."
    if name == "be":
        return f"{head}\n\n↩️ Prezzo tornato a pareggio ({entry}) dopo TP1: il resto si chiude a BE. Il 60% era già incassato."
    if name == "sl":
        return f"{head}\n\n🛑 SL colpito ({_px(r['SL'], d)}): -1R."
    return f"{head}\n\n⌛ Ordine scaduto o annullato senza riempimento: setup annullato."


def split_message(msg: str) -> tuple[str, str]:
    """(didascalia per la foto, descrizione da mandare sotto): il blocco Entry/SL/TP resta con la foto."""
    parts = msg.split("\n\n")
    n = 3 if "➡️" in msg else 2
    return "\n\n".join(parts[:n]), "\n\n".join(parts[n:])


def run_once(sym: str, m5: pd.DataFrame, tf: int, journal=aj.PATH, bot=None, chart: bool = True, chart_dir=None) -> list[str]:
    gold = is_gold(sym)
    a = analyze_gold(m5, 5) if gold else analyze(m5, tf)          # oro: tutto a M5 (struttura, MACD, CHoCH, grafico)
    sent = []
    for r in a["rows"]:
        r = {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in r.items()}
        for k in ("entry", "sl", "tp", "rr", "vwap_ext", "sw_price"):
            r.setdefault(k, float("nan"))
        aid, new = aj.upsert(sym, {**r, "entry": r["entry"] or float("nan"), "sl": r["sl"] or float("nan"),
                                   "tp": r["tp"] or float("nan"), "rr": r["rr"] or float("nan")}, journal)
        if new:
            rec = {k: (v if v is not None else float("nan")) for k, v in r.items()}
            msg = format_gold(sym, a, rec) if gold else format_alert(sym, a, rec)
            sent.append(msg)
            png = None
            if chart and not msg.startswith("🚨"):                  # l'avviso del climax è solo testo
                try:
                    tps = None if gold else (take_profits(float(rec["entry"]), float(rec["sl"]), float(rec["tp"]), rec["side"] == "buy")
                                             if pd.notna(rec["entry"]) else None)
                    png = render_chart(sym, m5, tf, rec, tps)
                except Exception as e:                      # lo screenshot non deve mai bloccare l'avviso
                    print(f"(screenshot non disponibile: {e})")
            if chart_dir and png:
                from pathlib import Path
                Path(chart_dir).mkdir(parents=True, exist_ok=True)
                (Path(chart_dir) / f"{sym}_{aid}_{pd.Timestamp(a['time']):%Y%m%d_%H%M}.png").write_bytes(png)
            if bot:
                if png:
                    caption, _ = split_message(msg)              # solo foto + Entry/SL/TP: niente descrizione sotto
                    bot.send_photo(png, caption)
                else:
                    bot.send(msg)
                aj.mark_sent(aid, journal)
    aj.update_outcomes(sym, m5, journal)
    tps_of = lambda r: aj.gold_tps(r) if r.get("Tipo") in ("UT", "UTAD") else take_profits(float(r["Entry limite"]), float(r["SL"]), float(r["TP"]), r["Lato"] == "buy")
    for aid, name, t, row in aj.process_events(sym, m5, journal, tps_of):          # aggiornamenti: riempimento, TP1/BE, TP, SL...
        msg = format_event(sym, name, row, tps_of(row))
        sent.append(f"[aggiornamento · {pd.Timestamp(t)} UTC · avviso {aid}]\n{msg}")
        if bot:
            bot.send(msg)
    return sent


def demo(sym: str, full: pd.DataFrame, journal, bot=None, chart_dir=None, days: int = 90) -> list[str]:
    """Prende l'ultimo segnale UT/UTAD (oro) degli ultimi `days` giorni dei dati e lo invia come se fosse appena arrivato.
    Serve a vedere l'aspetto di foto e messaggio su Telegram. Il journal indicato viene ricreato."""
    from pathlib import Path
    sig = generate_gold(full.loc[full.index[-1] - pd.Timedelta(days=days):], GoldParams(struct_tf_min=5))
    sig = sig[sig.kind.isin(["UT", "UTAD"])] if len(sig) else sig
    if not len(sig):
        return []
    t = sig.index[-1]
    Path(journal).unlink(missing_ok=True)
    return run_once(sym, full.loc[:t + pd.Timedelta(minutes=10)], 5, Path(journal), bot, True, chart_dir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--tf", type=int, default=5)
    ap.add_argument("--until")
    ap.add_argument("--replay", nargs=2, metavar=("INIZIO", "FINE"))
    ap.add_argument("--step", type=int, default=60)
    ap.add_argument("--journal", default=str(aj.PATH))
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--no-chart", action="store_true")
    ap.add_argument("--demo", action="store_true", help="oro: invia l'ultimo segnale trovato nei dati per vedere foto e messaggio")
    ap.add_argument("--chart-dir", help="salva qui gli screenshot (utile per provare senza Telegram)")
    a = ap.parse_args()
    full = load_ohlc(f"data/{a.symbol}_BID_M5.csv.gz")
    bot = None
    if a.send:
        from src.telegram_bot import TelegramBot
        bot = TelegramBot()
    from pathlib import Path
    jp = Path(a.journal)
    if a.demo:
        msgs = demo(a.symbol, full, jp, bot, a.chart_dir)
        print("\n\n".join(msgs) if msgs else "Nessun segnale UT/UTAD trovato negli ultimi 90 giorni dei dati.")
    elif a.replay:
        t, end = pd.Timestamp(a.replay[0]), pd.Timestamp(a.replay[1])
        n = 0
        while t <= end:
            msgs = run_once(a.symbol, full.loc[:t], a.tf, jp, bot, not a.no_chart, a.chart_dir)
            for m in msgs:
                n += 1
                print(f"\n[{t}]\n{m}")
            t += pd.Timedelta(minutes=a.step)
        aj.update_outcomes(a.symbol, full.loc[:end + pd.Timedelta(days=3)], jp)      # esiti con i prezzi successivi
        df = aj.summary(jp)
        print(f"\n=== {n} avvisi inviati/registrati ===")
        print(df[["ID", "Creato (UTC)", "Lato", "Stato", "Entry limite", "SL", "TP", "R:R", "Esito", "R (TP unico)", "R (gestione utente)"]].to_string(index=False))
    else:
        m5 = full.loc[:pd.Timestamp(a.until)] if a.until else full
        for m in run_once(a.symbol, m5, a.tf, jp, bot, not a.no_chart, a.chart_dir):
            print("\n" + m)
