"""Apre su MetaTrader 5 (SOLO CONTO DEMO) l'operazione a mercato descritta in un messaggio Telegram che invii tu al bot.

Formato del messaggio (decisione utente 30/10/2026):
    BUY XAUUSD
    ➡️ Entry: 3972
    ❌ SL: 3957
    ✅ TP1: 3977
    ✅ TP2: 3982        (ignorato)
    ✅ TP3: 4012        (ignorato)
Entry (dal 04/11/2026): ordine BUY STOP / SELL STOP al prezzo del segnale, valido fino a fine giornata, senza correzione dello scarto tra broker (ENTRY_ORDER=market in config.env per tornare
a mercato). Entry già superata: a mercato solo se al TP1 mancano più di MARKET_MIN_PIPS (40) pips. Se il prezzo tocca il TP1 prima dello stop, l'ordine si annulla.
Regole (versione a mercato): lotto fisso LOTS (0.05); ordine A MERCATO (l'Entry del messaggio serve solo a controllare che il prezzo non si sia allontanato più di MAX_SLIP_PRICE);
SL e TP1 impostati sull'ordine; TP2/TP3 ignorati. Il simbolo XAUUSD viene tradotto in MT5_SYMBOL (es. GOLD).
Filtro sullo spread: non apre se lo spread supera MAX_SPREAD (1,00 $) o MAX_SPREAD_PCT (20%) della distanza del TP1.
Sicurezze: accetta messaggi solo dalla chat TELEGRAM_CHAT_ID; ignora i messaggi arrivati prima dell'avvio e quelli più vecchi di MAX_AGE_S;
rifiuta se il conto NON è demo (non c'è modo di forzare: il live richiede una modifica esplicita del codice, da concordare), se manca SL/TP1, se SL/TP sono dal lato sbagliato,
se ci sono già MAX_POSITIONS posizioni aperte con il magic number di questo programma, o se il prezzo è lontano dall'Entry. Quando una posizione aperta da qui si chiude a TP, risponde al messaggio del segnale, pulito: '✅ TP1 +N pips' o '❌ SL HIT -N pips' (oro: 1 pip = 0,10). Ogni esito viene risposto su Telegram e registrato in journal/ordini_mt5.csv.
Parametri MIEI da confermare: MAX_SLIP_PRICE=3.0, MAX_POSITIONS=3, MAX_AGE_S=120, deviazione 20 punti.
Uso: python -m src.mt5_orders            (ascolta Telegram e apre gli ordini)
     python -m src.mt5_orders --dry      (legge e valida ma non invia ordini)
"""
import argparse
from collections import deque
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):                           # su Windows l'output reindirizzato usa cp1252, che non conosce le emoji: senza questo il programma si ferma alla prima stampa
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

LOTS = 0.05
MAX_SLIP_PRICE = 3.0
MAX_POSITIONS = 6                 # posizioni aperte da questo programma per conto (ogni segnale con TP2 ne apre due)
ENTRY_ORDER = os.environ.get("ENTRY_ORDER", "market").lower()            # "market" (default: a mercato, Entry di Vantage convertita con lo scarto) oppure "stop" (BUY/SELL STOP all'Entry del segnale)
MIN_REMAINING_PIPS = float(os.environ.get("MIN_REMAINING_PIPS") or 45)  # a mercato si entra solo se, calcolata l'Entry su ActivTrades con lo scarto, al TP1 mancano PIÙ di questi pips
MARKET_MIN_PIPS = float(os.environ.get("MARKET_MIN_PIPS") or 40)       # Entry già superata: si entra a mercato solo se al TP1 mancano PIÙ di questi pips
PARTIAL_ENABLED = os.environ.get("PARTIAL_TP2") == "1"    # parzializzazione SPENTA (decisione 05/11/2026: tutto chiuso a TP1); per riaccenderla: PARTIAL_TP2=1 in config.env
PARTIAL_FRACTION = 0.6            # parte di lotti chiusa a TP1 (0,03 su 0,05); il resto va a pareggio e corre verso TP2
MAX_SPREAD = float(os.environ.get("MAX_SPREAD") or 1.00)            # $: oltre questo spread non si apre (rollover, notizie). Cambiabile in config.env
MAX_SPREAD_PCT = float(os.environ.get("MAX_SPREAD_PCT") or 0.20)    # frazione della distanza del TP1: lo spread non deve mangiarne più di così
MAX_AGE_S = 120
DEVIATION = 20
MAGIC = 530001
LOG = Path("journal/ordini_mt5.csv")
PENDING = Path("journal/ordini_aperti.json")
SCARTI = Path(os.environ.get("JOURNAL_DIR", "journal")) / "scarti.csv"      # uno scarto per ogni segnale eseguito: serve alla calibrazione canale/broker
SEGNALI = Path(os.environ.get("JOURNAL_DIR", "journal")) / "segnali.csv"             # un record per ogni segnale ricevuto (anche se scartato)
ESITI = Path(os.environ.get("JOURNAL_DIR", "journal")) / "segnali_esiti.csv"         # un record per segnale e per conto: aperto / rifiutato e perché, con prezzi e scarto del momento
CHIUSURE = Path(os.environ.get("JOURNAL_DIR", "journal")) / "segnali_chiusure.csv"   # un record per ogni posizione chiusa: motivo, prezzo, pips
INFO: dict = {}                                                                       # dettagli dell'ultima valutazione fatta da execute() (per il registro degli esiti)
HEARTBEAT = Path(os.environ.get("JOURNAL_DIR", "journal")) / "mt5_orders.heartbeat"       # battito: Gestione Conti lo legge per mostrare se l'ascolto è attivo
NUM = r"([0-9]+(?:[.,][0-9]+)?)"


def clean_text(text: str) -> str:
    """Normalizza il testo ricevuto: lettere a larghezza intera -> normali (ＢＵＹ -> BUY), tolti i caratteri invisibili che a volte si copiano insieme al testo."""
    import unicodedata
    t = unicodedata.normalize("NFKC", text)
    return "".join(c for c in t if c not in "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff")


def looks_like_signal(text: str) -> bool:
    """Messaggio che sembra un segnale: ha BUY/SELL, oppure i tre livelli Entry, SL e TP1 con i loro numeri."""
    if re.search(r"\b(BUY|SELL)\b", text, re.I):
        return True
    return all(re.search(pat + r"\s*[:=]?\s*" + NUM, text, re.I) for pat in (r"Entry", r"SL", r"TP\s*1"))


def parse_signal(text: str) -> dict:
    """Estrae side, symbol, entry, sl, tp1. Se manca la riga «BUY/SELL SIMBOLO» la direzione si deduce dai livelli (SL sopra l'Entry e TP1 sotto = SELL; il contrario = BUY) e lo
    strumento è XAUUSD; in quel caso sig['inferred'] è True. Solleva ValueError con il motivo se manca o è ambiguo qualcosa."""
    head = re.search(r"\b(BUY|SELL)\s+([A-Za-z0-9._]+)", text, re.I)
    out = {"side": head.group(1).lower(), "symbol": head.group(2).upper(), "inferred": False} if head else {}
    for key, pat in (("entry", r"Entry"), ("sl", r"SL"), ("tp1", r"TP\s*1")):
        found = re.findall(pat + r"\s*[:=]?\s*" + NUM, text, re.I)
        if len(found) != 1:
            raise ValueError(f"{key.upper()} {'mancante' if not found else 'presente più volte'}")
        out[key] = float(found[0].replace(",", "."))
    tp3 = re.findall(r"TP\s*3\s*[:=]?\s*" + NUM, text, re.I)
    if len(tp3) == 1:
        out["tp3"] = float(tp3[0].replace(",", "."))
    tp2 = re.findall(r"TP\s*2\s*[:=]?\s*" + NUM, text, re.I)
    if len(tp2) == 1:
        out["tp2"] = float(tp2[0].replace(",", "."))
    if not head:
        if out["sl"] > out["entry"] > out["tp1"]:
            out.update(side="sell", symbol="XAUUSD", inferred=True)
        elif out["sl"] < out["entry"] < out["tp1"]:
            out.update(side="buy", symbol="XAUUSD", inferred=True)
        else:
            raise ValueError("manca la riga BUY/SELL e i livelli non permettono di dedurre la direzione (SL, Entry e TP1 non sono in ordine)")
    if "tp2" in out and not ((out["tp2"] > out["tp1"]) if out["side"] == "buy" else (out["tp2"] < out["tp1"])):
        raise ValueError(f"TP2 non coerente con la direzione {out['side'].upper()} (TP1 {out['tp1']}, TP2 {out['tp2']})")
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


def relative_levels() -> bool:
    """Default: SL e TP si applicano come DISTANZE dall'Entry del messaggio al prezzo del TUO broker (partendo dal bid per i BUY e dall'ask per i SELL, cioè dal prezzo che li fa scattare: lo spread non accorcia lo stop) (il canale quota un altro broker, es. Vantage: i prezzi assoluti differiscono).
    SIGNAL_LEVELS=absolute in config.env torna ai prezzi scritti nel messaggio."""
    return os.environ.get("SIGNAL_LEVELS", "relative").lower() != "absolute"


def check_message(sig: dict) -> None:
    """Coerenza interna del messaggio (nelle coordinate del canale): BUY SL < Entry < TP1, SELL TP1 < Entry < SL."""
    if sig["side"] == "buy" and not sig["sl"] < sig["entry"] < sig["tp1"]:
        raise ValueError(f"BUY: nel messaggio servono SL < Entry < TP1 (SL {sig['sl']}, Entry {sig['entry']}, TP1 {sig['tp1']})")
    if sig["side"] == "sell" and not sig["tp1"] < sig["entry"] < sig["sl"]:
        raise ValueError(f"SELL: nel messaggio servono TP1 < Entry < SL (TP1 {sig['tp1']}, Entry {sig['entry']}, SL {sig['sl']})")


def broker_symbol(sym: str) -> str:
    return os.environ.get("MT5_SYMBOL", sym) if sym == "XAUUSD" else sym


def filling(mt5, info) -> int:
    m = info.filling_mode
    return mt5.ORDER_FILLING_IOC if m & 2 else mt5.ORDER_FILLING_FOK if m & 1 else mt5.ORDER_FILLING_RETURN


def execute(mt5, sig: dict, dry: bool = False, lots: float = LOTS, tag: str = "") -> tuple[str, list]:
    """Valida e (se non dry) invia l'ordine. Restituisce (testo di risposta, elenco delle posizioni da seguire: una, oppure due se il segnale ha il TP2); solleva ValueError se rifiutato."""
    ti = mt5.terminal_info()
    if ti is not None and getattr(ti, "trade_allowed", True) is False:
        raise ValueError("Il trading automatico è spento in MT5 (pulsante «Algo Trading» rosso). Chiudi MT5 e lancia  .venv\\Scripts\\python -m src.prepara_mt5  per correggere l'impostazione che lo spegne al cambio di conto.")
    acc = mt5.account_info()
    if acc is None:
        raise ValueError("MT5 non risponde: controlla che il terminale sia aperto e collegato")
    if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        raise ValueError("il conto collegato NON è demo: non apro nulla")
    sym = broker_symbol(sig["symbol"])
    info = mt5.symbol_info(sym)
    if info is None or not mt5.symbol_select(sym, True):
        raise ValueError(f"simbolo {sym!r} non trovato su MT5")
    mine = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC] + [o for o in (mt5.orders_get() or []) if o.magic == MAGIC]
    if len(mine) >= MAX_POSITIONS:
        raise ValueError(f"già {len(mine)} posizioni o ordini aperti da questo programma (massimo {MAX_POSITIONS})")
    tick = mt5.symbol_info_tick(sym)
    INFO.clear()
    INFO.update(bid=tick.bid, ask=tick.ask, spread=round(tick.ask - tick.bid, 5))
    spread, tp_dist = tick.ask - tick.bid, abs(sig["tp1"] - sig["entry"])
    limit = min(MAX_SPREAD, MAX_SPREAD_PCT * tp_dist) if tp_dist > 0 else MAX_SPREAD
    if spread > limit + 1e-9:                                        # filtro sullo spread: con spread alto il costo mangia il TP
        raise ValueError(f"spread troppo alto: {spread:.2f} $ (limite {limit:.2f} $: massimo {MAX_SPREAD:.2f} $ e {MAX_SPREAD_PCT:.0%} del TP1 di {tp_dist:.2f} $). Non apro.")
    if ENTRY_ORDER == "stop" and relative_levels():
        return _execute_stop(mt5, sig, sym, info, tick, lots, dry, tag)
    buy = sig["side"] == "buy"
    px = tick.ask if buy else tick.bid
    d = info.digits
    note_off = ""
    if relative_levels():
        check_message(sig)
        sl_d, tp_d = abs(sig["entry"] - sig["sl"]), abs(sig["tp1"] - sig["entry"])
        ref = tick.bid if buy else tick.ask               # SL e TP scattano sul prezzo di CHIUSURA (BUY: bid, SELL: ask), come il grafico del canale: così lo spread non accorcia lo stop
        scarto = tick.bid - sig["entry"]                  # differenza di quotazione tra il tuo broker e il canale (entrambi sul bid)
        off, src = current_offset()
        pip = _pip(sym, info)
        if off is not None:                               # Entry, SL e TP di Vantage convertiti in prezzi di ActivTrades; si entra solo se al TP1 mancano abbastanza pips
            e_at, tp_at, sl_at = sig["entry"] + off, sig["tp1"] + off, sig["sl"] + off
            remaining = ((tp_at - tick.bid) if buy else (tick.bid - tp_at)) / pip
            INFO.update(offset=round(off, 3), src=src, remaining=round(remaining, 1))
            if remaining <= MIN_REMAINING_PIPS:
                raise ValueError(f"al TP1 mancano solo {remaining:.0f} pips (minimo {MIN_REMAINING_PIPS:.0f}): non apro. Entry di Vantage {sig['entry']} = {e_at:.2f} su ActivTrades "
                                 f"(scarto {off:+.2f}, {src}), TP1 {tp_at:.2f}, prezzo ora {tick.bid:.2f}.")
            if (buy and sl_at >= tick.bid) or (not buy and sl_at <= tick.bid):
                raise ValueError(f"il prezzo ({tick.bid:.2f}) ha già superato lo SL convertito ({sl_at:.2f}): non apro.")
            sl, tp = (sl_at, tp_at) if buy else (sl_at + (tick.ask - tick.bid), tp_at + (tick.ask - tick.bid))
            note_off = f" · Entry su ActivTrades {e_at:.2f} (scarto {off:+.2f}, {src}) · al TP1 mancano {remaining:.0f} pips"
        else:                                              # nessuno scarto disponibile: distanze dall'Entry sul prezzo di adesso, filtro dei pips non applicabile
            sl, tp = (ref - sl_d, ref + tp_d) if buy else (ref + sl_d, ref - tp_d)
            note_off = f" · filtro dei {MIN_REMAINING_PIPS:.0f} pips NON applicato: scarto non disponibile ({src})"
        try:
            log_scarto(tag, sig, tick, scarto)
        except OSError:
            pass
    else:
        check_levels(sig, tick.bid, tick.ask)
        sl, tp, scarto = sig["sl"], sig["tp1"], 0.0
    # parzializzazione: con TP2 nel segnale, conto in modalità hedging e lotti divisibili si aprono DUE posizioni (PARTIAL_FRACTION a TP1, il resto a TP2)
    step = getattr(info, "volume_step", 0.01) or 0.01
    vmin = getattr(info, "volume_min", step)
    v1 = round(round(lots * PARTIAL_FRACTION / step) * step, 2)
    v2 = round(lots - v1, 2)
    hedging = getattr(acc, "margin_mode", None) == getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2)
    split = PARTIAL_ENABLED and relative_levels() and sig.get("tp2") is not None and hedging and v1 >= vmin - 1e-9 and v2 >= vmin - 1e-9
    parts = [(v1, tp, "tp1")]
    if split:
        tp2_d = abs(sig["tp2"] - sig["entry"])
        off2 = current_offset()[0]
        tp2_lv = (sig["tp2"] + off2 + (0 if buy else tick.ask - tick.bid)) if off2 is not None else (ref + tp2_d if buy else ref - tp2_d)
        parts.append((v2, tp2_lv, "tp2"))
    else:
        parts = [(lots, tp, None)]
    reqs = [{"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": v, "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
             "price": px, "sl": round(sl, d), "tp": round(t, d), "deviation": DEVIATION, "magic": MAGIC,
             "comment": "tg-signal" + (f"-{name}" if name else ""), "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling(mt5, info)} for v, t, name in parts]
    base = f"{sig['side'].upper()} {sym} " + (f"{v1}+{v2} lotti" if split else f"{lots} lotti") + f" a mercato ~{px} · SL {reqs[0]['sl']} ({abs(px - reqs[0]['sl']):.2f} $) · TP1 {reqs[0]['tp']} ({abs(reqs[0]['tp'] - px):.2f} $)"
    summary = base
    if split:
        summary += f" · TP2 {reqs[1]['tp']} ({abs(reqs[1]['tp'] - px):.2f} $): a TP1 il resto va a pareggio"
    elif PARTIAL_ENABLED and sig.get("tp2") is not None:
        summary += " · TP2 ignorato: " + ("conto non in modalità hedging" if not hedging else "lotti non divisibili")
    if relative_levels():
        summary += note_off + f" · scarto misurato {scarto:+.2f} · spread {tick.ask - tick.bid:.2f}"
        hist = [v for _, v in read_scarti()[:-1]]                       # esclude quello appena registrato
        if len(hist) >= 5:
            import statistics as st
            m = st.median(hist)
            if abs(scarto - m) > 3.0:
                summary += f" · ⚠ scarto insolito (tipico {m:+.2f})"
    if dry:
        return f"[PROVA, nessun ordine inviato] {summary}", []
    trks, group, note = [], f"{time.time():.0f}-{tag}", ""
    for req, (_, _, name) in zip(reqs, parts):
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            why = f"{getattr(res, 'retcode', None)} {getattr(res, 'comment', mt5.last_error())}"
            if not trks:
                raise ValueError(f"ordine rifiutato dal broker: {why}")
            note = f" · ATTENZIONE: la seconda parte ({name}) non è stata aperta: {why}"
            break
        trks.append({"position": int(res.order), "symbol": sym, "side": sig["side"], "open": float(res.price), "tp": req["tp"], "sl": req["sl"], "part": name, "group": group})
    return (f"✅ Aperto: {summary} · prezzo eseguito {trks[0]['open']} · ticket {', '.join(str(t['position']) for t in trks)}{note}", trks)


def _pip(sym: str, info) -> float:
    return 0.10 if ("XAU" in sym.upper() or "GOLD" in sym.upper()) else ((info.point * 10) if info else 0.0001)


def _execute_stop(mt5, sig: dict, sym: str, info, tick, lots: float, dry: bool, tag: str) -> tuple[str, list]:
    """Entry con ordine BUY STOP / SELL STOP al prezzo del segnale (senza correzione dello scarto tra broker), valido fino a fine giornata. SL e TP1 a distanza dall'Entry, partendo
    dal prezzo che li fa scattare (BUY: bid = Entry - spread; SELL: ask = Entry + spread), come per gli ordini a mercato.
    Se l'Entry è già stata superata (lo stop non si può piazzare) si entra a mercato SOLO se al TP1 mancano più di MARKET_MIN_PIPS pips; altrimenti non si apre."""
    check_message(sig)
    buy = sig["side"] == "buy"
    d, entry = info.digits, sig["entry"]
    sl_d, tp_d = abs(entry - sig["sl"]), abs(sig["tp1"] - entry)
    sp = tick.ask - tick.bid
    ref = entry - sp if buy else entry + sp
    sl, tp = (ref - sl_d, ref + tp_d) if buy else (ref + sl_d, ref - tp_d)
    stops = (getattr(info, "trade_stops_level", 0) or 0) * (getattr(info, "point", 0.01) or 0.01)
    valid = (entry - tick.ask > stops) if buy else (tick.bid - entry > stops)         # BUY STOP sopra il prezzo, SELL STOP sotto
    pip = _pip(sym, info)
    kind = "stop" if valid else "market"
    if valid:
        exp_ok = getattr(info, "expiration_mode", 15) & 2
        req = {"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": lots, "type": mt5.ORDER_TYPE_BUY_STOP if buy else mt5.ORDER_TYPE_SELL_STOP,
               "price": round(entry, d), "sl": round(sl, d), "tp": round(tp, d), "deviation": DEVIATION, "magic": MAGIC, "comment": "tg-signal-stop",
               "type_time": mt5.ORDER_TIME_DAY if exp_ok else mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_RETURN}
        head = f"⏳ Ordine {'BUY' if buy else 'SELL'} STOP piazzato: {sym} {lots} lotti @ {req['price']} (valido fino a fine giornata)"
    else:
        remaining = ((sig["tp1"] - tick.ask) if buy else (tick.bid - sig["tp1"])) / pip
        if remaining <= MARKET_MIN_PIPS:
            raise ValueError(f"Entry {entry} già superata (prezzo {tick.ask if buy else tick.bid}) e al TP1 mancano solo {remaining:.0f} pips (minimo {MARKET_MIN_PIPS:.0f}): non apro.")
        px = tick.ask if buy else tick.bid
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": lots, "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL, "price": px, "sl": round(sl, d),
               "tp": round(tp, d), "deviation": DEVIATION, "magic": MAGIC, "comment": "tg-signal", "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling(mt5, info)}
        head = f"✅ Aperto a mercato (Entry già superata, al TP1 mancano {remaining:.0f} pips): {sig['side'].upper()} {sym} {lots} lotti ~{px}"
    summary = f"{head} · SL {req['sl']} ({abs(ref - req['sl']):.2f} $) · TP1 {req['tp']} ({abs(req['tp'] - ref):.2f} $) · spread {sp:.2f}"
    if dry:
        return f"[PROVA, nessun ordine inviato] {summary}", []
    res = mt5.order_send(req)
    ok = (mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_PLACED", 10008))
    if res is None or res.retcode not in ok:
        raise ValueError(f"ordine rifiutato dal broker: {getattr(res, 'retcode', None)} {getattr(res, 'comment', mt5.last_error())}")
    trk = {"position": int(res.order), "symbol": sym, "side": sig["side"], "open": float(entry if valid else res.price), "tp": req["tp"], "sl": req["sl"], "part": None,
           "group": f"{time.time():.0f}-{tag}", "pending": valid, "kind": kind}
    return f"{summary} · ticket {res.order}", [trk]


def follow_orders(mt5, pending: dict, bot, only=None) -> None:
    """Segue gli ordini stop in attesa: quando scattano diventano posizioni (avviso «Entrato»); se il prezzo tocca il TP1 prima dello stop l'ordine viene annullato; se scade o sparisce
    senza essere eseguito lo segnala. Presuppone che il ticket della posizione sia quello dell'ordine che l'ha aperta (conti hedging)."""
    for key, t in list(pending.items()):
        if not t.get("pending") or (only is not None and not only(t)):
            continue
        tk, buy = int(t["position"]), t["side"] == "buy"
        info = mt5.symbol_info(t["symbol"])
        fmt = lambda v: f"{v:.{getattr(info, 'digits', 2)}f}"
        pos = [p for p in (mt5.positions_get() or []) if int(p.ticket) == tk]
        if pos:
            t["pending"], t["open"] = False, float(pos[0].price_open)
            say(bot, f"📌 Entrato {t['side'].upper()} {t['symbol']} a {fmt(t['open'])}", t["msg_id"])
            save_pending(pending)
            continue
        if list(mt5.orders_get(ticket=tk) or ()):
            tick = mt5.symbol_info_tick(t["symbol"])
            if (tick.bid >= t["tp"]) if buy else (tick.ask <= t["tp"]):          # il movimento è partito senza lo stop: setup non più valido
                res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": tk})
                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    say(bot, f"🚫 Ordine annullato: il prezzo ha toccato il TP1 ({fmt(t['tp'])}) senza attivare lo stop", t["msg_id"])
                    del pending[key]
                    save_pending(pending)
            continue
        ins = [x for x in (mt5.history_deals_get(position=tk) or ()) if x.entry == mt5.DEAL_ENTRY_IN]
        if ins:                                                                 # scattato e già chiuso tra un controllo e l'altro: lo gestisce check_closed
            t["pending"], t["open"] = False, float(ins[0].price)
            save_pending(pending)
            continue
        say(bot, "⌛ Ordine stop non eseguito: scaduto o annullato", t["msg_id"])
        del pending[key]
        save_pending(pending)


def move_to_be(mt5, t: dict) -> bool:
    """Sposta lo SL della posizione al prezzo di apertura (pareggio). False se non si può (posizione chiusa, prezzo già tornato oltre il pareggio, rifiuto del broker)."""
    pos = [p for p in (mt5.positions_get() or []) if int(p.ticket) == int(t["position"])]
    if not pos:
        return False
    p = pos[0]
    info = mt5.symbol_info(t["symbol"])
    req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": p.ticket, "sl": round(t["open"], getattr(info, "digits", 2)), "tp": p.tp, "magic": MAGIC}
    res = mt5.order_send(req)
    return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE


def pips(sym: str, a: float, b: float) -> float:
    """Distanza in pips: oro 1 pip = 0,10 (come nei test), altri simboli 1 pip = 10 punti."""
    return abs(a - b) / (0.10 if sym.upper().startswith(("XAU", "GOLD")) else 10 * (mt5_point(sym)))


def mt5_point(sym: str) -> float:
    import MetaTrader5 as mt5
    return mt5.symbol_info(sym).point


def say_photo(bot, png: bytes, caption: str, reply_to: int | None = None) -> bool:
    """Invia l'immagine con didascalia (rispondendo al segnale). False se non è stato possibile: chi chiama ripiega sul solo testo. Con Telegram spento non invia nulla (True)."""
    if not telegram_on():
        return True
    try:
        SENT.append(clean_text(caption))
        bot.send_photo(png, caption, reply_to)
        return True
    except Exception as e:
        print("Invio immagine fallito:", str(e)[:200], flush=True)
        return False


def trade_screenshot(mt5, t: dict, deals, d, label: str) -> bytes | None:
    """Grafico dell'operazione chiusa (candele di ActivTrades con Entry, SL, TP e chiusura). None se mancano i dati. Orari: server del broker."""
    from src import mt5_accounts as ma
    ins = [x for x in deals if x.entry == mt5.DEAL_ENTRY_IN]
    t_in = ins[0].time if ins else d.time - 300
    return ma.render_history_chart(mt5, t["symbol"], t["side"], t["open"], t_in, d.price, d.time, t.get("sl"), t.get("tp") or None, label)


def announce(bot, mt5, t: dict, deals, d, text: str, label: str) -> None:
    """Risposta al segnale con lo screenshot dei livelli (Entry, SL, TP) e il testo come didascalia; se il grafico non è possibile, solo il testo."""
    png = None
    try:
        png = trade_screenshot(mt5, t, deals, d, label)
    except Exception as e:
        print("Screenshot non riuscito:", str(e)[:150], flush=True)
    if png and t.get("account"):                                       # copia per il calendario di Gestione Conti
        try:
            from src import mt5_accounts as ma
            ma.chart_path(ma.get_account(t["account"])["login"], int(t["position"]), int(d.ticket)).write_bytes(png)
        except Exception:
            pass
    if not (png and say_photo(bot, png, text, t["msg_id"])):
        say(bot, text, t["msg_id"])


def check_closed(mt5, pending: dict, bot, only=None, prefix: str = "") -> None:
    """Per ogni posizione seguita già chiusa: se è chiusa a TP risponde al messaggio del segnale, pulito: '✅ TP1 +N pips · prezzo P' o '❌ SL HIT -N pips · prezzo P'; poi la toglie dall'elenco."""
    for key, t in list(pending.items()):
        if (only is not None and not only(t)) or t.get("pending"):
            continue
        deals = mt5.history_deals_get(position=t["position"]) or []
        out = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        if not out:
            continue
        d = out[-1]
        del pending[key]
        n = pips(t["symbol"], d.price, t["open"])
        info = mt5.symbol_info(t["symbol"])
        price = f"{d.price:.{getattr(info, 'digits', 2)}f}"              # prezzo a cui la posizione si è chiusa
        sign = 1 if t["side"] == "buy" else -1
        sgn = n if (d.price - t["open"]) * sign >= 0 else -n               # pips con segno (guadagno o perdita reali)
        part, sib = t.get("part"), [(k2, t2) for k2, t2 in pending.items() if t2.get("group") and t2.get("group") == t.get("group") and k2 != key]
        if d.reason == mt5.DEAL_REASON_TP:
            lab = f"{'TP2' if part == 'tp2' else 'TP1'} {sgn:+.0f} pips · prezzo {price}"
            announce(bot, mt5, t, deals, d, f"✅ {lab}", lab)
            if part == "tp1":                                           # parte a TP1 incassata: lo stop del resto va a pareggio
                for k2, t2 in sib:
                    if t2.get("part") == "tp2":
                        try:
                            t2["be"] = move_to_be(mt5, t2)
                            print(f"SL a pareggio sulla posizione {t2['position']}: {'fatto' if t2['be'] else 'non possibile (prezzo già tornato sotto il pareggio?)'}", flush=True)
                        except Exception as e:
                            print("SL a pareggio non riuscito:", str(e)[:120], flush=True)
        elif d.reason == mt5.DEAL_REASON_SL:
            if part == "tp2" and t.get("be"):
                lab = f"BE {sgn:+.0f} pips · prezzo {price}"
                announce(bot, mt5, t, deals, d, f"🟰 {lab}", lab)
            elif not t.get("sl_reported"):
                lab = f"SL HIT {sgn:+.0f} pips · prezzo {price}"
                announce(bot, mt5, t, deals, d, f"❌ {lab}", lab)
            for k2, t2 in sib:                                           # un solo messaggio di SL per segnale
                t2["sl_reported"] = True
        log([datetime.now(timezone.utc).isoformat(timespec="seconds"), f"chiusura posizione {t['position']}", f"motivo {d.reason} prezzo {d.price} profitto {d.profit}"])
        log_chiusura(t, d, "tp" if d.reason == mt5.DEAL_REASON_TP else "sl" if d.reason == mt5.DEAL_REASON_SL else "altra", sgn)
        save_pending(pending)


def save_pending(pending: dict) -> None:
    PENDING.parent.mkdir(exist_ok=True)
    PENDING.write_text(json.dumps(pending), encoding="utf-8")


def load_pending() -> dict:
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


SENT: "deque[str]" = deque(maxlen=100)                         # testi inviati da questo programma: nel canale il bot rivede i propri post e non deve leggerli come segnali


OWN_PREFIXES = ("🟢 Pronto", "📡", "📥", "ℹ️", "⚠️", "⛔", "✅ Aperto", "✅ TP1 ", "❌ SL HIT", "⏳", "📌", "🚫", "⌛", "🟰 BE", "✅ TP2 ", "✅ Gestione Conti", "[")    # inizio dei messaggi scritti dal programma


def telegram_on() -> bool:
    """Interruttore «Telegram» di Gestione Conti: spento = il programma non legge i messaggi e non ne invia."""
    try:
        from src import mt5_accounts as ma
        return bool(ma.get_setting("telegram_enabled", True))
    except Exception:
        return True


def say(bot, text: str, reply_to: int | None = None) -> None:
    """Risposta in testo semplice (i '<' dei messaggi di rifiuto rompono il formato HTML); un errore di invio non ferma il programma. Con Telegram spento non invia nulla."""
    if not telegram_on():
        return
    kw = {"reply_to_message_id": reply_to} if reply_to else {}
    try:
        SENT.append(clean_text(text))
        bot._call("sendMessage", chat_id=bot.chat_id, text=text, **kw)
    except Exception as e:
        print("Invio Telegram fallito:", str(e)[:200], flush=True)


def _csv_append(path: Path, header: list, row: list) -> None:
    """Aggiunge una riga a un registro CSV (crea il file con l'intestazione). Un errore di scrittura non deve mai fermare il programma."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(header)
            w.writerow(row)
    except OSError:
        pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_segnale(msg_id, msg_time, sig: dict | None, text: str, errore: str = "") -> None:
    sig = sig or {}
    _csv_append(SEGNALI, ["quando_utc", "msg_id", "ora_messaggio_utc", "direzione", "simbolo", "entry", "sl", "tp1", "tp2", "tp3", "direzione_dedotta", "errore_lettura", "testo"],
                [now_iso(), msg_id, datetime.fromtimestamp(msg_time, tz=timezone.utc).isoformat(timespec="seconds") if msg_time else "", sig.get("side", ""), sig.get("symbol", ""),
                 sig.get("entry", ""), sig.get("sl", ""), sig.get("tp1", ""), sig.get("tp2", ""), sig.get("tp3", ""), int(bool(sig.get("inferred"))), errore, text.replace("\n", " | ")])


def log_esito(msg_id, conto, res: str, lots, trks: list) -> None:
    kind = "prova" if res.startswith("[PROVA") else "stop" if res.startswith("⏳") else "aperto" if res.startswith("✅ Aperto") else "rifiutato" if "Non apro" in res else "errore"
    _csv_append(ESITI, ["quando_utc", "msg_id", "conto", "esito", "lotti", "bid", "ask", "spread", "scarto_usato", "fonte_scarto", "pips_al_tp1", "ticket", "prezzo_apertura", "dettaglio"],
                [now_iso(), msg_id, conto, kind, lots, INFO.get("bid", ""), INFO.get("ask", ""), INFO.get("spread", ""), INFO.get("offset", ""), INFO.get("src", ""),
                 INFO.get("remaining", ""), ",".join(str(t["position"]) for t in trks), trks[0]["open"] if trks else "", res.replace("\n", " | ")[:400]])


def log_chiusura(t: dict, d, reason: str, pips_signed: float) -> None:
    _csv_append(CHIUSURE, ["quando_utc", "msg_id", "conto_id", "simbolo", "direzione", "parte", "esito", "prezzo_apertura", "prezzo_chiusura", "pips", "profitto", "ora_chiusura_server"],
                [now_iso(), t.get("msg_id", ""), t.get("account", ""), t["symbol"], t["side"], t.get("part") or "", reason, t["open"], d.price, round(pips_signed, 1), d.profit, int(d.time)])


def log_scarto(tag: str, sig: dict, tick, scarto: float) -> None:
    SCARTI.parent.mkdir(exist_ok=True)
    new = not SCARTI.exists()
    with SCARTI.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["quando_utc", "conto", "lato", "entry_canale", "bid", "ask", "spread", "scarto"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), tag, sig["side"], sig["entry"], tick.bid, tick.ask, round(tick.ask - tick.bid, 5), round(scarto, 3)])


def current_offset() -> tuple[float | None, str]:
    """Scarto tra il prezzo di ActivTrades e quello di Vantage (ActivTrades - Vantage), per convertire i livelli del segnale. Fonte: SCARTO_ACTIVTRADES in config.env, altrimenti la mediana
    degli scarti dei segnali già eseguiti (almeno 10). Nessuna fonte: (None, motivo)."""
    env = os.environ.get("SCARTO_ACTIVTRADES")
    if env not in (None, ""):
        try:
            return float(env.replace(",", ".")), "SCARTO_ACTIVTRADES"
        except ValueError:
            pass
    import statistics as st
    vals = [v for _, v in read_scarti()][-30:]
    if len(vals) >= 10:
        return st.median(vals), f"mediana di {len(vals)} segnali"
    return None, f"{len(vals)} segnali raccolti su 10 necessari"


def read_scarti() -> list[tuple[str, float]]:
    """(conto, scarto) dai segnali registrati: journal/scarti.csv più, se presenti, gli scarti scritti nei vecchi messaggi di journal/ordini_mt5.csv."""
    import re
    out, seen = [], set()
    if SCARTI.exists():
        with SCARTI.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    out.append((r["conto"], float(r["scarto"])))
                    seen.add(r["quando_utc"][:16])
                except (KeyError, ValueError):
                    pass
    if LOG.exists():
        with LOG.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                m = re.search(r"scarto (?:dal canale|del tuo broker dal canale) ([+-]?\d+\.\d+)", r.get("esito", ""))
                if m and r.get("quando_utc", "")[:16] not in seen:
                    out.append(("(storico)", float(m[1])))
    return out


def calibra() -> None:
    """Riepilogo degli scarti tra l'Entry del canale (Vantage) e il prezzo del tuo broker nel momento in cui il segnale viene eseguito."""
    import statistics as st
    rows = read_scarti()
    if not rows:
        print("Ancora nessuno scarto registrato: serve almeno un segnale eseguito. Dopo ogni segnale lo scarto viene salvato in journal/scarti.csv.")
        return
    allv = [v for _, v in rows]
    print(f"Scarti registrati: {len(allv)}\n")
    for tag in sorted({t for t, _ in rows}):
        v = [x for t, x in rows if t == tag]
        med = st.median(v)
        sd = st.pstdev(v) if len(v) > 1 else 0.0
        print(f"{tag or '(terminale singolo)':28s} n={len(v):3d}  mediana {med:+7.2f}  media {st.mean(v):+7.2f}  dev.st. {sd:5.2f}  min {min(v):+7.2f}  max {max(v):+7.2f}")
    med, sd = st.median(allv), (st.pstdev(allv) if len(allv) > 1 else 0.0)
    print(f"\nScarto tipico: {med:+.2f} $ (variabilità {sd:.2f} $). Ultimi 10: " + " ".join(f"{x:+.2f}" for x in allv[-10:]))
    if len(allv) < 10:
        print("Pochi dati (meno di 10 segnali): la stima non è affidabile, continua a raccogliere.")
    elif sd > 2.0:
        print("Lo scarto cambia molto da un segnale all'altro: non è una differenza fissa tra i broker (conta il ritardo tra messaggio ed esecuzione e i movimenti veloci). Ragionare per distanze, come fa il programma, è la scelta giusta.")
    else:
        print("Lo scarto è stabile: i due broker differiscono di un valore quasi costante. Per le distanze di SL e TP non serve correggerlo; serve solo a riconoscere segnali anomali.")
    print("Nota: lo scarto include anche il ritardo tra l'invio del messaggio e l'esecuzione, quindi sovrastima la differenza vera tra i broker.")


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
    # I conti già riconosciuti come REALI non vengono nemmeno contattati: collegarsi a loro cambierebbe il login del terminale e potrebbe lasciare fuori il demo.
    return [a for a in ma.list_accounts() if a["enabled"] and a["use_signals"] and a.get("kind") != "real"]


def check() -> None:
    """Diagnosi: per ogni conto dell'app dice se è usato per i segnali e se MT5 si collega davvero (login, tipo, simbolo)."""
    from dotenv import load_dotenv
    load_dotenv("config.env")
    from src import mt5_accounts as ma
    accs = ma.list_accounts()
    if not accs:
        print("Nessun conto nell'app: i segnali usano il terminale singolo (modalità precedente).")
    for a in accs:
        why = []
        if not a["enabled"]:
            why.append("DISATTIVATO (interruttore Attivo)")
        if not a["use_signals"]:
            why.append("«Usa per i segnali» è spento")
        if a.get("kind") == "real":
            why.append("è un conto REALE: non viene usato")
        print(f"\n[{a['name']}] login {a['login']} · {a['server']} · lotti {a['lots']} · password salvata: {'sì' if a['has_password'] else 'NO'} · terminale: {a['terminal_path'] or '(predefinito)'}")
        print("  Segnali:", "NON riceve (" + "; ".join(why) + ")" if why else "riceve i segnali")
        try:
            with ma.session(a) as m:
                sym = broker_symbol("XAUUSD")
                info = m.symbol_info(sym)
                print(f"  MT5: collegato · {'DEMO' if ma.is_demo(m) else 'REALE'} · simbolo {sym}: {'trovato' if info else 'NON TROVATO (controlla MT5_SYMBOL in config.env)'} · posizioni aperte {len(m.positions_get() or [])}")
        except Exception as e:
            print("  MT5: ERRORE:", str(e)[:250])


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
                follow_orders(m, pending, bot, only=lambda t, a=aid: t.get("account") == a)
                check_closed(m, pending, bot, only=lambda t, a=aid: t.get("account") == a, prefix=f" · {acc['name']}")
        except Exception as e:
            print(f"Controllo chiusure {acc['name']}:", str(e)[:200], flush=True)
    if legacy is not None and any(not t.get("account") for t in pending.values()):
        follow_orders(legacy, pending, bot, only=lambda t: not t.get("account"))
        check_closed(legacy, pending, bot, only=lambda t: not t.get("account"))


def main(dry: bool, channel: str = "") -> None:
    from dotenv import load_dotenv
    load_dotenv("config.env")
    from src import mt5_accounts as ma
    from src.telegram_bot import TelegramBot
    bot = TelegramBot()
    legacy = None
    allowed = str(bot.chat_id)
    try:
        last = bot._call("getUpdates", offset=-1)                 # scarta ciò che è arrivato prima dell'avvio
        offset = last[-1]["update_id"] + 1 if last else 0
    except Exception as e:                                        # un problema di rete all'avvio non deve fermare il programma
        print("Telegram non raggiungibile all'avvio, riprovo:", str(e)[:150], flush=True)
        offset = 0
    import queue
    feed: "queue.Queue" = queue.Queue()
    canale = (channel or os.environ.get("TELEGRAM_CANALE", "")).strip()
    if canale:                                                    # i segnali arrivano anche direttamente dal canale (account dell'utente, sola lettura)
        from src.telegram_reader import start_channel_feed
        start_channel_feed(canale, feed, notify=lambda t: say(bot, "📡 " + t))
    pending = load_pending()
    accs = active_accounts()
    where = f"{len(accs)} conti dall'app" if accs else f"terminale singolo, lotto {LOTS}"
    print(f"In ascolto su Telegram ({'PROVA' if dry else 'ordini su DEMO'}; {where}). Ctrl+C per fermare.", flush=True)
    say(bot, f"🟢 Pronto: invia il segnale ({'solo prova' if dry else 'apro su conti demo'}; {where}; solo TP1).")
    was_off = False
    while True:
        try:
            HEARTBEAT.parent.mkdir(exist_ok=True)
            HEARTBEAT.write_text(str(time.time()))
        except OSError:
            pass
        if not telegram_on():                                       # interruttore spento: né lettura né invio; le chiusure restano in attesa
            was_off = True
            time.sleep(2)
            continue
        if was_off:                                                 # riacceso: i messaggi arrivati mentre era spento si scartano (non si eseguono segnali vecchi)
            was_off = False
            try:
                last = bot._call("getUpdates", offset=-1)
                offset = last[-1]["update_id"] + 1 if last else offset
            except Exception:
                pass
            print("Telegram riacceso.", flush=True)
        try:
            if legacy is None and any(not t.get("account") for t in pending.values()):
                from src.mt5_feed import connect
                legacy = connect()
            follow_closures(pending, bot, legacy)
        except Exception as e:
            print("Controllo chiusure:", e, flush=True)
        try:
            ups = bot._call("getUpdates", offset=offset, timeout=2 if canale else 8)
        except Exception as e:
            print("Telegram:", type(e).__name__, str(e)[:200], flush=True)
            time.sleep(5)
            continue
        while not feed.empty():                                      # messaggi del canale: stesso percorso dei messaggi al bot (cid = chat attesa)
            ftext, fid, fdate = feed.get()
            ups.append({"update_id": None, "message": {"text": ftext, "chat": {"id": allowed}, "date": fdate, "message_id": None, "chan_id": fid}})
        for u in ups:
            if u["update_id"] is not None:
                offset = u["update_id"] + 1
            m = u.get("message") or u.get("channel_post") or u.get("edited_message") or u.get("edited_channel_post") or {}
            text = clean_text(m.get("text") or m.get("caption") or "")
            cid = str((m.get("chat") or {}).get("id"))
            if text in SENT or text.startswith(OWN_PREFIXES):         # un nostro stesso messaggio che ritorna dal canale
                continue
            if cid != allowed or not looks_like_signal(text):
                print(f"Ignorato: chat {cid} (attesa {allowed}), contiene BUY/SELL: {bool(re.search(r'BUY|SELL', text, re.I))}, tipo: {[k for k in u if k != 'update_id']}, "
                      f"campi: {[k for k in m if k not in ('chat', 'date', 'message_id', 'chan_id', 'sender_chat')]}, testo: {text[:80]!r}", flush=True)
                continue
            if time.time() - m.get("date", 0) > MAX_AGE_S:
                say(bot, "⚠️ Messaggio troppo vecchio (> 2 minuti): ignorato.")
                continue
            say(bot, "📥 Segnale ricevuto, lo applico sui conti…", m.get("message_id"))        # conferma immediata: se questa non arriva, il messaggio non è giunto al programma
            try:
                sig = parse_signal(text)
            except ValueError as e:
                lines = [f"⛔ Non apro: {e}"]
                log_segnale(m.get("message_id") or m.get("chan_id"), m.get("date"), None, text, str(e))
            else:
                log_segnale(m.get("message_id") or m.get("chan_id"), m.get("date"), sig, text)
                lines = [f"ℹ️ Manca la riga BUY/SELL: direzione dedotta dai livelli, {sig['side'].upper()} {sig['symbol']}."] if sig.get("inferred") else []
                targets = active_accounts() or [None]
                for acc in targets:
                    tag = f"[{acc['name']}] " if acc else ""
                    trks = []
                    INFO.clear()
                    try:
                        if acc:
                            with ma.session(acc) as mt:
                                res, trks = execute(mt, sig, dry, acc["lots"], acc["login"] and str(acc["login"]))
                        else:
                            if legacy is None:
                                from src.mt5_feed import connect
                                legacy = connect()
                            res, trks = execute(legacy, sig, dry)
                        for trk in trks:
                            if acc:
                                trk["account"] = acc["id"]
                            pending[f"{acc['id'] if acc else 0}:{trk['position']}"] = {**trk, "msg_id": m["message_id"]}
                        if trks:
                            save_pending(pending)
                    except ValueError as e:
                        res = f"⛔ Non apro: {e}"
                    except Exception as e:
                        res = f"⛔ Errore: {e}"
                    lines.append(tag + res)
                    log_esito(m.get("message_id") or m.get("chan_id"), acc["login"] if acc else "", res, acc["lots"] if acc else LOTS, trks)
                    log([datetime.now(timezone.utc).isoformat(timespec="seconds"), (tag + text).replace("\n", " | "), res])
            out = "\n".join(lines)
            print(out, flush=True)
            say(bot, out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="valida ma non invia ordini")
    ap.add_argument("--canale", default="", help="titolo/id del canale Telegram da leggere con il tuo account (vedi src/telegram_reader.py); in alternativa TELEGRAM_CANALE in config.env")
    ap.add_argument("--calibra", action="store_true", help="riepilogo degli scarti tra il prezzo del canale e quello del tuo broker")
    ap.add_argument("--check", action="store_true", help="diagnosi dei conti e del collegamento a MT5")
    ap.add_argument("--suggest", action="store_true", help="stampa un messaggio di prova coerente con il prezzo attuale")
    a = ap.parse_args()
    calibra() if a.calibra else check() if a.check else suggest() if a.suggest else main(a.dry, a.canale)
