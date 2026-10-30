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
se ci sono già MAX_POSITIONS posizioni aperte con il magic number di questo programma, o se il prezzo è lontano dall'Entry. Quando una posizione aperta da qui si chiude a TP, risponde al messaggio del segnale con '✅ TP HIT' e i pips (oro: 1 pip = 0,10). Ogni esito viene risposto su Telegram e registrato in journal/ordini_mt5.csv.
Parametri MIEI da confermare: MAX_SLIP_PRICE=3.0, MAX_POSITIONS=3, MAX_AGE_S=120, deviazione 20 punti.
Uso: python -m src.mt5_orders            (ascolta Telegram e apre gli ordini)
     python -m src.mt5_orders --dry      (legge e valida ma non invia ordini)
"""
import argparse
import csv
import json
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
PENDING = Path("journal/ordini_aperti.json")
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


def execute(mt5, sig: dict, dry: bool = False, lots: float = LOTS) -> tuple[str, dict | None]:
    """Valida e (se non dry) invia l'ordine. Restituisce (testo di risposta, dati della posizione da seguire); solleva ValueError se rifiutato."""
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
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": lots, "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": px, "sl": round(sig["sl"], d), "tp": round(sig["tp1"], d), "deviation": DEVIATION, "magic": MAGIC,
           "comment": "tg-signal", "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling(mt5, info)}
    summary = f"{sig['side'].upper()} {sym} {lots} lotti a mercato ~{px} · SL {req['sl']} · TP1 {req['tp']}"
    if dry:
        return f"[PROVA, nessun ordine inviato] {summary}", None
    res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        raise ValueError(f"ordine rifiutato dal broker: {getattr(res, 'retcode', None)} {getattr(res, 'comment', mt5.last_error())}")
    return (f"✅ Aperto: {summary} · prezzo eseguito {res.price} · ticket {res.order}",
            {"position": int(res.order), "symbol": sym, "side": sig["side"], "open": float(res.price), "tp": req["tp"]})


def pips(sym: str, a: float, b: float) -> float:
    """Distanza in pips: oro 1 pip = 0,10 (come nei test), altri simboli 1 pip = 10 punti."""
    return abs(a - b) / (0.10 if sym.upper().startswith(("XAU", "GOLD")) else 10 * (mt5_point(sym)))


def mt5_point(sym: str) -> float:
    import MetaTrader5 as mt5
    return mt5.symbol_info(sym).point


def check_closed(mt5, pending: dict, bot, only=None, prefix: str = "") -> None:
    """Per ogni posizione seguita già chiusa: se è chiusa a TP risponde al messaggio del segnale con '✅ TP HIT' e i pips; poi la toglie dall'elenco."""
    for key, t in list(pending.items()):
        if only is not None and not only(t):
            continue
        deals = mt5.history_deals_get(position=t["position"]) or []
        out = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        if not out:
            continue
        d = out[-1]
        del pending[key]
        if d.reason == mt5.DEAL_REASON_TP:
            n = pips(t["symbol"], d.price, t["open"])
            msg = f"✅ TP HIT{prefix}\n{t['side'].upper()} {t['symbol']} · {n:.0f} pips · profitto {d.profit:+.2f}"
            say(bot, msg, t["msg_id"])
        log([datetime.now(timezone.utc).isoformat(timespec="seconds"), f"chiusura posizione {t['position']}", f"motivo {d.reason} prezzo {d.price} profitto {d.profit}"])
        save_pending(pending)


def save_pending(pending: dict) -> None:
    PENDING.parent.mkdir(exist_ok=True)
    PENDING.write_text(json.dumps(pending), encoding="utf-8")


def load_pending() -> dict:
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def say(bot, text: str, reply_to: int | None = None) -> None:
    """Risposta in testo semplice (i '<' dei messaggi di rifiuto rompono il formato HTML); un errore di invio non ferma il programma."""
    kw = {"reply_to_message_id": reply_to} if reply_to else {}
    try:
        bot._call("sendMessage", chat_id=bot.chat_id, text=text, **kw)
    except Exception as e:
        print("Invio Telegram fallito:", str(e)[:200], flush=True)


def log(row: list) -> None:
    LOG.parent.mkdir(exist_ok=True)
    new = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["quando_utc", "messaggio", "esito"])
        w.writerow(row)


def suggest() -> None:
    """Stampa un messaggio di prova coerente con il prezzo di adesso (BUY: SL -10, TP1 +3 dall'ask), da incollare subito nel canale."""
    from dotenv import load_dotenv
    load_dotenv("config.env")
    from src.mt5_feed import connect
    mt5 = connect()
    sym = broker_symbol("XAUUSD")
    mt5.symbol_select(sym, True)
    t = mt5.symbol_info_tick(sym)
    e = round(t.ask)
    print(f"Prezzo ora: bid {t.bid} · ask {t.ask}. Incolla subito (vale 2 minuti):\n")
    print(f"BUY XAUUSD\n\n➡️ Entry: {e}\n\n❌ SL: {e - 10}\n✅ TP1: {e + 3}\n✅ TP2: {e + 6}\n✅ TP3: {e + 9}")


def active_accounts() -> list[dict]:
    """Conti dell'archivio (src.mt5_accounts) abilitati e usati per i segnali; riletti a ogni giro, quindi le modifiche dall'app si applicano subito."""
    from src import mt5_accounts as ma
    return [a for a in ma.list_accounts() if a["enabled"] and a["use_signals"]]


def follow_closures(pending: dict, bot, legacy) -> None:
    """Controlla le chiusure a TP: per ogni conto con posizioni seguite si collega a quel conto; le posizioni senza conto (modalità a terminale singolo) usano `legacy`."""
    from src import mt5_accounts as ma
    for aid in {t["account"] for t in pending.values() if t.get("account")}:
        try:
            acc = ma.get_account(aid)
        except ValueError:                                           # conto cancellato dall'app: smetto di seguire le sue posizioni
            for k in [k for k, t in pending.items() if t.get("account") == aid]:
                del pending[k]
            save_pending(pending)
            continue
        try:
            with ma.session(acc) as m:
                check_closed(m, pending, bot, only=lambda t, a=aid: t.get("account") == a, prefix=f" · {acc['name']}")
        except Exception as e:
            print(f"Controllo chiusure {acc['name']}:", str(e)[:200], flush=True)
    if legacy is not None and any(not t.get("account") for t in pending.values()):
        check_closed(legacy, pending, bot, only=lambda t: not t.get("account"))


def main(dry: bool) -> None:
    from dotenv import load_dotenv
    load_dotenv("config.env")
    from src import mt5_accounts as ma
    from src.telegram_bot import TelegramBot
    bot = TelegramBot()
    legacy = None
    allowed = str(bot.chat_id)
    last = bot._call("getUpdates", offset=-1)                     # scarta ciò che è arrivato prima dell'avvio
    offset = last[-1]["update_id"] + 1 if last else 0
    pending = load_pending()
    accs = active_accounts()
    where = f"{len(accs)} conti dall'app" if accs else f"terminale singolo, lotto {LOTS}"
    print(f"In ascolto su Telegram ({'PROVA' if dry else 'ordini su DEMO'}; {where}). Ctrl+C per fermare.", flush=True)
    say(bot, f"🟢 Pronto: invia il segnale ({'solo prova' if dry else 'apro su conti demo'}; {where}; solo TP1).")
    while True:
        try:
            if legacy is None and any(not t.get("account") for t in pending.values()):
                from src.mt5_feed import connect
                legacy = connect()
            follow_closures(pending, bot, legacy)
        except Exception as e:
            print("Controllo chiusure:", e, flush=True)
        try:
            ups = bot._call("getUpdates", offset=offset, timeout=8)
        except Exception as e:
            print("Telegram:", type(e).__name__, str(e)[:200], flush=True)
            time.sleep(5)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            m = u.get("message") or u.get("channel_post") or u.get("edited_message") or u.get("edited_channel_post") or {}
            text = m.get("text") or m.get("caption") or ""
            cid = str((m.get("chat") or {}).get("id"))
            if cid != allowed or not re.search(r"\b(BUY|SELL)\b", text, re.I):
                print(f"Ignorato: chat {cid} (attesa {allowed}), contiene BUY/SELL: {bool(re.search(r'BUY|SELL', text, re.I))}, tipo: {[k for k in u if k != 'update_id']}", flush=True)
                continue
            if time.time() - m.get("date", 0) > MAX_AGE_S:
                say(bot, "⚠️ Messaggio troppo vecchio (> 2 minuti): ignorato.")
                continue
            try:
                sig = parse_signal(text)
            except ValueError as e:
                lines = [f"⛔ Non apro: {e}"]
            else:
                lines = []
                targets = active_accounts() or [None]
                for acc in targets:
                    tag = f"[{acc['name']}] " if acc else ""
                    try:
                        if acc:
                            with ma.session(acc) as mt:
                                res, trk = execute(mt, sig, dry, acc["lots"])
                        else:
                            if legacy is None:
                                from src.mt5_feed import connect
                                legacy = connect()
                            res, trk = execute(legacy, sig, dry)
                        if trk:
                            if acc:
                                trk["account"] = acc["id"]
                            pending[f"{acc['id'] if acc else 0}:{trk['position']}"] = {**trk, "msg_id": m["message_id"]}
                            save_pending(pending)
                    except ValueError as e:
                        res = f"⛔ Non apro: {e}"
                    except Exception as e:
                        res = f"⛔ Errore: {e}"
                    lines.append(tag + res)
                    log([datetime.now(timezone.utc).isoformat(timespec="seconds"), (tag + text).replace("\n", " | "), res])
            out = "\n".join(lines)
            print(out, flush=True)
            say(bot, out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="valida ma non invia ordini")
    ap.add_argument("--suggest", action="store_true", help="stampa un messaggio di prova coerente con il prezzo attuale")
    a = ap.parse_args()
    suggest() if a.suggest else main(a.dry)
