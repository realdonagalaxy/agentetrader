"""Apre su MetaTrader 5 (SOLO CONTO DEMO) l'operazione a mercato descritta in un messaggio Telegram che invii tu al bot.

Formato del messaggio (decisione utente 30/10/2026):
    BUY XAUUSD
    ➡️ Entry: 3972
    ❌ SL: 3957
    ✅ TP1: 3977
    ✅ TP2: 3982        (ignorato)
    ✅ TP3: 4012        (ignorato)
Regole: lotto fisso LOTS (0.05); ordine A MERCATO (l'Entry del messaggio serve solo a controllare che il prezzo non si sia allontanato più di MAX_SLIP_PRICE);
SL e TP1 impostati sull'ordine; TP2/TP3 ignorati. Il simbolo XAUUSD viene tradotto in MT5_SYMBOL (es. GOLD).
Sicurezze: accetta messaggi solo dalla chat TELEGRAM_CHAT_ID; ignora i messaggi arrivati prima dell'avvio e quelli più vecchi di MAX_AGE_S;
rifiuta se il conto NON è demo (non c'è modo di forzare: il live richiede una modifica esplicita del codice, da concordare), se manca SL/TP1, se SL/TP sono dal lato sbagliato,
se ci sono già MAX_POSITIONS posizioni aperte con il magic number di questo programma, o se il prezzo è lontano dall'Entry. Ogni esito viene risposto su Telegram e registrato in journal/ordini_mt5.csv.
Parametri MIEI da confermare: MAX_SLIP_PRICE=3.0, MAX_POSITIONS=3, MAX_AGE_S=120, deviazione 20 punti.
Uso: python -m src.mt5_orders            (ascolta Telegram e apre gli ordini)
     python -m src.mt5_orders --dry      (legge e valida ma non invia ordini)
"""
import argparse
import csv
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

LOTS = 0.05
MAX_SLIP_PRICE = 3.0
MAX_POSITIONS = 3
MAX_AGE_S = 120
DEVIATION = 20
MAGIC = 530001
LOG = Path("journal/ordini_mt5.csv")
NUM = r"([0-9]+(?:[.,][0-9]+)?)"


def parse_signal(text: str) -> dict:
    """Estrae side, symbol, entry, sl, tp1. Solleva ValueError con il motivo se manca o è ambiguo qualcosa."""
    head = re.search(r"\b(BUY|SELL)\s+([A-Za-z0-9._]+)", text, re.I)
    if not head:
        raise ValueError("non trovo 'BUY/SELL SIMBOLO' nella prima riga")
    out = {"side": head.group(1).lower(), "symbol": head.group(2).upper()}
    for key, pat in (("entry", r"Entry"), ("sl", r"SL"), ("tp1", r"TP\s*1")):
        found = re.findall(pat + r"\s*[:=]?\s*" + NUM, text, re.I)
        if len(found) != 1:
            raise ValueError(f"{key.upper()} {'mancante' if not found else 'presente più volte'}")
        out[key] = float(found[0].replace(",", "."))
    return out


def check_levels(sig: dict, bid: float, ask: float) -> None:
    buy = sig["side"] == "buy"
    px = ask if buy else bid
    if buy and not sig["sl"] < px < sig["tp1"]:
        raise ValueError(f"BUY: servono SL < prezzo < TP1 (SL {sig['sl']}, prezzo {px}, TP1 {sig['tp1']})")
    if not buy and not sig["tp1"] < px < sig["sl"]:
        raise ValueError(f"SELL: servono TP1 < prezzo < SL (TP1 {sig['tp1']}, prezzo {px}, SL {sig['sl']})")
    if abs(px - sig["entry"]) > MAX_SLIP_PRICE:
        raise ValueError(f"il prezzo ({px}) dista più di {MAX_SLIP_PRICE:g} dall'Entry del messaggio ({sig['entry']}): non apro")


def broker_symbol(sym: str) -> str:
    return os.environ.get("MT5_SYMBOL", sym) if sym == "XAUUSD" else sym


def filling(mt5, info) -> int:
    m = info.filling_mode
    return mt5.ORDER_FILLING_IOC if m & 2 else mt5.ORDER_FILLING_FOK if m & 1 else mt5.ORDER_FILLING_RETURN


def execute(mt5, sig: dict, dry: bool = False) -> str:
    """Valida e (se non dry) invia l'ordine. Restituisce il testo di risposta; solleva ValueError se rifiutato."""
    acc = mt5.account_info()
    if acc is None:
        raise ValueError("MT5 non risponde: controlla che il terminale sia aperto e collegato")
    if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        raise ValueError("il conto collegato NON è demo: non apro nulla")
    sym = broker_symbol(sig["symbol"])
    info = mt5.symbol_info(sym)
    if info is None or not mt5.symbol_select(sym, True):
        raise ValueError(f"simbolo {sym!r} non trovato su MT5")
    mine = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
    if len(mine) >= MAX_POSITIONS:
        raise ValueError(f"già {len(mine)} posizioni aperte da questo programma (massimo {MAX_POSITIONS})")
    tick = mt5.symbol_info_tick(sym)
    check_levels(sig, tick.bid, tick.ask)
    buy = sig["side"] == "buy"
    px = tick.ask if buy else tick.bid
    d = info.digits
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": LOTS, "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": px, "sl": round(sig["sl"], d), "tp": round(sig["tp1"], d), "deviation": DEVIATION, "magic": MAGIC,
           "comment": "tg-signal", "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling(mt5, info)}
    summary = f"{sig['side'].upper()} {sym} {LOTS} lotti a mercato ~{px} · SL {req['sl']} · TP1 {req['tp']}"
    if dry:
        return f"[PROVA, nessun ordine inviato] {summary}"
    res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        raise ValueError(f"ordine rifiutato dal broker: {getattr(res, 'retcode', None)} {getattr(res, 'comment', mt5.last_error())}")
    return f"✅ Aperto: {summary} · prezzo eseguito {res.price} · ticket {res.order}"


def log(row: list) -> None:
    LOG.parent.mkdir(exist_ok=True)
    new = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["quando_utc", "messaggio", "esito"])
        w.writerow(row)


def main(dry: bool) -> None:
    from dotenv import load_dotenv
    load_dotenv("config.env")
    from src.mt5_feed import connect
    from src.telegram_bot import TelegramBot
    bot, mt5 = TelegramBot(), connect()
    allowed = str(bot.chat_id)
    last = bot._call("getUpdates", offset=-1)                     # scarta ciò che è arrivato prima dell'avvio
    offset = last[-1]["update_id"] + 1 if last else 0
    print(f"In ascolto su Telegram ({'PROVA' if dry else 'ordini su DEMO'}, lotto {LOTS}). Ctrl+C per fermare.", flush=True)
    bot.send(f"🟢 Pronto: invia il segnale ({'solo prova' if dry else 'apro su conto demo'}, {LOTS} lotti, solo TP1).")
    while True:
        try:
            ups = bot._call("getUpdates", offset=offset, timeout=25)
        except Exception as e:
            print("Telegram:", e, flush=True)
            time.sleep(5)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            text = m.get("text") or ""
            if str((m.get("chat") or {}).get("id")) != allowed or not re.search(r"\b(BUY|SELL)\b", text, re.I):
                continue
            if time.time() - m.get("date", 0) > MAX_AGE_S:
                bot.send("⚠️ Messaggio troppo vecchio (> 2 minuti): ignorato.")
                continue
            try:
                out = execute(mt5, parse_signal(text), dry)
            except ValueError as e:
                out = f"⛔ Non apro: {e}"
            except Exception as e:
                out = f"⛔ Errore: {e}"
            print(out, flush=True)
            log([datetime.now(timezone.utc).isoformat(timespec="seconds"), text.replace("\n", " | "), out])
            bot.send(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="valida ma non invia ordini")
    main(ap.parse_args().dry)
