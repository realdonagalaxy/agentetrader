"""Analisi SDP-Wyckoff del grafico → messaggio Telegram. La decisione di aprire il trade resta all'utente.

Fonti di dati:
  - file  : data/<SIMBOLO>_BID_M5.csv.gz (anche "riproduzione" del passato con --until, per collaudo)
  - ctrader: da collegare quando l'applicazione Open API sarà "Active" (vedi fetch_ctrader)

Uso:
  python -m src.live_analysis --symbol EURUSD --until "2025-03-12 08:35"          # stampa l'analisi
  python -m src.live_analysis --symbol EURUSD --until "2025-03-12 08:35" --send   # la invia a Telegram
"""
import argparse
import html
from datetime import datetime

import numpy as np
import pandas as pd

from src.data_loader import load_ohlc, resample
from src.market_config import MACRO_TZ, macro_at
from src.market_structure import multi_tf_trend
from src.sdp_wyckoff import WyParams, generate

DISCLAIMER = ("⚠️ Storico EURUSD 2003–2025 (senza costi): macro + Wyckoff ≈ +0,1R a trade, vantaggio piccolo e non ancora "
              "verificato su altri strumenti. Non è una raccomandazione: la decisione è tua.")


def decimals(sym: str) -> int:
    if "JPY" in sym or "XAU" in sym or "XAG" in sym:
        return 3 if "JPY" in sym else 2
    if "IDX" in sym or sym.startswith(("BTC", "ETH")):
        return 1
    return 5


def pip_size(sym: str) -> float:
    if "JPY" in sym:
        return 0.01
    if "XAU" in sym:
        return 0.1
    if "XAG" in sym:
        return 0.01
    if "IDX" in sym or sym.startswith(("BTC", "ETH")):
        return 1.0
    return 0.0001


def fetch_ctrader(sym: str, bars: int):
    raise NotImplementedError("Collegamento cTrader Open API: disponibile quando l'applicazione sul portale sarà 'Active'.")


def load_recent(sym: str, until: str | None = None, days: int = 25) -> pd.DataFrame:
    m5 = load_ohlc(f"data/{sym}_BID_M5.csv.gz")
    if until:
        m5 = m5.loc[:pd.Timestamp(until)]
    return m5.loc[m5.index[-1] - pd.Timedelta(days=days):]


def analyze(m5: pd.DataFrame, p: WyParams = WyParams(struct_tf_min=5), fresh_bars: int = 2) -> dict:
    last = m5.index[-1]
    sig = generate(m5, p)
    h1 = resample(m5, "1h")
    tr = multi_tf_trend(h1.iloc[-400:]) if len(h1) > 50 else {"H4": "?", "H1": "?", "bias": "?"}
    out = {"time": last, "bias": tr, "macro": macro_at(last.to_pydatetime()), "signals": [], "pending": []}
    if sig.empty:
        return out
    fresh = last - pd.Timedelta(minutes=5 * fresh_bars)
    s = sig[(sig.kind == "signal") & (sig.index >= fresh)]
    out["signals"] = s[s.in_kz & s.wy_vol].reset_index().to_dict("records")       # variante principale: KZ + Wyckoff + volume
    pend = sig[sig.kind == "pending"]
    out["pending"] = pend[pend.in_kz].reset_index().to_dict("records")
    return out


def _px(v: float, d: int) -> str:
    return f"{v:.{d}f}"


def _tick(b) -> str:
    return "✅" if b else "❌"


def format_signal(sym: str, a: dict, r: dict) -> str:
    d, pip = decimals(sym), pip_size(sym)
    buy = r["side"] == "buy"
    entry, sl = r["entry"], r["sl"]
    risk = abs(entry - sl)
    tp_end, tp2 = r["tp_end"], entry + (2 * risk if buy else -2 * risk)
    tp_ok = (tp_end > entry) if buy else (tp_end < entry)
    rr_end = abs(tp_end - entry) / risk if tp_ok and risk else float("nan")
    t_loc = a["time"].tz_localize("UTC").astimezone(MACRO_TZ) if a["time"].tzinfo is None else a["time"].astimezone(MACRO_TZ)
    want = "UP" if buy else "DOWN"
    bias = a["bias"]
    lines = [
        f"🔔 <b>{html.escape(sym)} — setup {'BUY' if buy else 'SELL'} (SDP-Wyckoff)</b>",
        f"🕒 {t_loc:%d/%m %H:%M} (Roma) · macro: {a['macro'] or 'fuori macro'}",
        f"📈 Bias H4 {bias['H4']} / H1 {bias['H1']} {_tick(bias['bias'] == want)}",
        "",
        f"<b>Struttura</b>: {'minimi' if buy else 'massimi'} uguali a {_px(r['level'], d)} · Leg 1 fino a {_px(r['b_price'], d)} "
        f"({r['leg1_pips'] * 1e-4 / pip:.0f} pip)",
        f"<b>Kill Zone</b> 1.272–1.618: {_px(min(r['kz_lo'], r['kz_hi']), d)} – {_px(max(r['kz_lo'], r['kz_hi']), d)} "
        f"· estremo shakeout {_px(r['sw_price'], d)} {_tick(r['in_kz'])}",
        f"<b>OB non mitigato toccato</b>: {_tick(r['ob_touch'])}",
        f"<b>Wyckoff</b>: climax {'SC' if buy else 'BC'} a {_px(r['sc_price'], d)} · gobba MACD minore {_tick(r['wy_div'])} · "
        f"volume minore {_tick(r['wy_vol'])} · gobbe decrescenti {_tick(r['wy_dec'])}",
        f"<b>VWAP</b>: estremo a {r['vwap_ext']:.1f}σ dal VWAP" + (" (oltre la banda 2σ ✅)" if r['vwap_ext'] >= 2 else ""),
        "",
        f"<b>Piano (a mercato dopo il CHoCH M5)</b>",
        f"Entry ≈ {_px(entry, d)}",
        f"SL {_px(sl, d)}  (rischio {risk / pip:.0f} pip)",
        f"TP fine Leg 1 {_px(tp_end, d)}" + (f"  (R:R {rr_end:.1f})" if tp_ok else "  (già superato)"),
        f"TP 1:2 {_px(tp2, d)}",
    ]
    if not (tp_ok and rr_end >= 3):
        lines.append("⚠️ R:R verso la fine Leg 1 sotto il minimo 1:3 del documento: setup che non rispetta la tua regola.")
    lines += [
        "",
        DISCLAIMER,
    ]
    return "\n".join(lines)


def format_pending(sym: str, a: dict, r: dict) -> str:
    d = decimals(sym)
    buy = r["side"] == "buy"
    missing = []
    if not r["ob_touch"]:
        missing.append("tocco di un OB non mitigato")
    if not r["wy_vol"]:
        missing.append("test Wyckoff (gobba MACD minore + volume minore)")
    missing.append("CHoCH M5")
    return "\n".join([
        f"👀 <b>{html.escape(sym)} — setup {'BUY' if buy else 'SELL'} in formazione</b>",
        f"Prezzo nei pressi della Kill Zone {_px(min(r['kz_lo'], r['kz_hi']), d)} – {_px(max(r['kz_lo'], r['kz_hi']), d)} "
        f"(estremo {_px(r['sw_price'], d)}) · livello rotto {_px(r['level'], d)}",
        f"Bias H4 {a['bias']['H4']} / H1 {a['bias']['H1']} · macro: {a['macro'] or 'fuori macro'}",
        "Da attendere: " + ", ".join(missing) + ".",
    ])


def messages(sym: str, a: dict) -> list[str]:
    return [format_signal(sym, a, r) for r in a["signals"]] + [format_pending(sym, a, r) for r in a["pending"]]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--until", help="riproduce il passato fino a questo istante (UTC), es. '2025-03-12 08:35'")
    ap.add_argument("--days", type=int, default=25)
    ap.add_argument("--send", action="store_true")
    a_ = ap.parse_args()
    m5 = load_recent(a_.symbol, a_.until, a_.days)
    res = analyze(m5)
    msgs = messages(a_.symbol, res)
    print(f"Analisi alle {res['time']} UTC: {len(res['signals'])} segnali, {len(res['pending'])} setup in formazione")
    for m in msgs:
        print("\n" + m)
    if a_.send:
        from src.telegram_bot import TelegramBot
        bot = TelegramBot()
        for m in msgs or [f"ℹ️ {a_.symbol}: nessun setup alle {res['time']:%H:%M} UTC. Bias H4 {res['bias']['H4']} / H1 {res['bias']['H1']}."]:
            bot.send(m)
        print("Inviato a Telegram.")
