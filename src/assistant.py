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

import pandas as pd

from src import alert_journal as aj
from src.chart import render_chart
from src.data_loader import load_ohlc, resample
from src.live_analysis import decimals, pip_size
from src.market_config import MACRO_TZ, macro_at
from src.market_structure import multi_tf_trend
from src.range_detector import atr
from src.sdp_v3 import V3Params, generate_v3

DISCLAIMER = ("ℹ️ Backtest 2003–2025 su EURUSD, oro e Nasdaq: nessun vantaggio statistico dimostrato (≈0R, costi esclusi). "
              "Questo è un avviso di analisi: la decisione è tua e l'esito verrà registrato nel journal.")


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


def split_message(msg: str) -> tuple[str, str]:
    """(didascalia per la foto, descrizione da mandare sotto): il blocco Entry/SL/TP resta con la foto."""
    parts = msg.split("\n\n")
    n = 3 if "➡️" in msg else 2
    return "\n\n".join(parts[:n]), "\n\n".join(parts[n:])


def run_once(sym: str, m5: pd.DataFrame, tf: int, journal=aj.PATH, bot=None, chart: bool = True, chart_dir=None) -> list[str]:
    a = analyze(m5, tf)
    sent = []
    for r in a["rows"]:
        r = {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in r.items()}
        for k in ("entry", "sl", "tp", "rr", "vwap_ext"):
            r.setdefault(k, float("nan"))
        aid, new = aj.upsert(sym, {**r, "entry": r["entry"] or float("nan"), "sl": r["sl"] or float("nan"),
                                   "tp": r["tp"] or float("nan"), "rr": r["rr"] or float("nan")}, journal)
        if new:
            rec = {k: (v if v is not None else float("nan")) for k, v in r.items()}
            msg = format_alert(sym, a, rec)
            sent.append(msg)
            png = None
            if chart:
                try:
                    tps = take_profits(float(rec["entry"]), float(rec["sl"]), float(rec["tp"]), rec["side"] == "buy") \
                        if pd.notna(rec["entry"]) else None
                    png = render_chart(sym, m5, tf, rec, tps)
                except Exception as e:                      # lo screenshot non deve mai bloccare l'avviso
                    print(f"(screenshot non disponibile: {e})")
            if chart_dir and png:
                from pathlib import Path
                Path(chart_dir).mkdir(parents=True, exist_ok=True)
                (Path(chart_dir) / f"{sym}_{aid}_{pd.Timestamp(a['time']):%Y%m%d_%H%M}.png").write_bytes(png)
            if bot:
                if png:
                    caption, rest = split_message(msg)
                    bot.send_photo(png, caption)
                    if rest:
                        bot.send(rest)
                else:
                    bot.send(msg)
                aj.mark_sent(aid, journal)
    aj.update_outcomes(sym, m5, journal)
    return sent


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
    ap.add_argument("--chart-dir", help="salva qui gli screenshot (utile per provare senza Telegram)")
    a = ap.parse_args()
    full = load_ohlc(f"data/{a.symbol}_BID_M5.csv.gz")
    bot = None
    if a.send:
        from src.telegram_bot import TelegramBot
        bot = TelegramBot()
    from pathlib import Path
    jp = Path(a.journal)
    if a.replay:
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
        print(df[["ID", "Creato (UTC)", "Lato", "Stato", "Entry limite", "SL", "TP", "R:R", "Esito", "R (TP unico)", "R (BE+50%)"]].to_string(index=False))
    else:
        m5 = full.loc[:pd.Timestamp(a.until)] if a.until else full
        for m in run_once(a.symbol, m5, a.tf, jp, bot, not a.no_chart, a.chart_dir):
            print("\n" + m)
