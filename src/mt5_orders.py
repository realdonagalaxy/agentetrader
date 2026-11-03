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
Filtro sullo spread: non apre se lo spread supera MAX_SPREAD (1,00 $) o MAX_SPREAD_PCT (20%) della distanza del TP1.
Sicurezze: accetta messaggi solo dalla chat TELEGRAM_CHAT_ID; ignora i messaggi arrivati prima dell'avvio e quelli più vecchi di MAX_AGE_S;
rifiuta se il conto NON è demo (non c'è modo di forzare: il live richiede una modifica esplicita del codice, da concordare), se manca SL/TP1, se SL/TP sono dal lato sbagliato,
se ci sono già MAX_POSITIONS posizioni aperte con il magic number di questo programma, o se il prezzo è lontano dall'Entry. Quando una posizione aperta da qui si chiude a TP, risponde al messaggio del segnale, pulito: '✅ TP1 +N pips' o '❌ SL HIT -N pips' (oro: 1 pip = 0,10). Ogni esito viene risposto su Telegram e registrato in journal/ordini_mt5.csv.
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
MAX_SPREAD = float(os.environ.get("MAX_SPREAD") or 1.00)            # $: oltre questo spread non si apre (rollover, notizie). Cambiabile in config.env
MAX_SPREAD_PCT = float(os.environ.get("MAX_SPREAD_PCT") or 0.20)    # frazione della distanza del TP1: lo spread non deve mangiarne più di così
MAX_AGE_S = 120
DEVIATION = 20
MAGIC = 530001
LOG = Path("journal/ordini_mt5.csv")
PENDING = Path("journal/ordini_aperti.json")
SCARTI = Path(os.environ.get("JOURNAL_DIR", "journal")) / "scarti.csv"      # uno scarto per ogni segnale eseguito: serve alla calibrazione canale/broker
HEARTBEAT = Path(os.environ.get("JOURNAL_DIR", "journal")) / "mt5_orders.heartbeat"       # battito: Gestione Conti lo legge per mostrare se l'ascolto è attivo
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


def execute(mt5, sig: dict, dry: bool = False, lots: float = LOTS, tag: str = "") -> tuple[str, dict | None]:
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
    spread, tp_dist = tick.ask - tick.bid, abs(sig["tp1"] - sig["entry"])
    limit = min(MAX_SPREAD, MAX_SPREAD_PCT * tp_dist) if tp_dist > 0 else MAX_SPREAD
    if spread > limit + 1e-9:                                        # filtro sullo spread: con spread alto il costo mangia il TP
        raise ValueError(f"spread troppo alto: {spread:.2f} $ (limite {limit:.2f} $: massimo {MAX_SPREAD:.2f} $ e {MAX_SPREAD_PCT:.0%} del TP1 di {tp_dist:.2f} $). Non apro.")
    buy = sig["side"] == "buy"
    px = tick.ask if buy else tick.bid
    d = info.digits
    if relative_levels():
        check_message(sig)
        sl_d, tp_d = abs(sig["entry"] - sig["sl"]), abs(sig["tp1"] - sig["entry"])
        ref = tick.bid if buy else tick.ask               # SL e TP scattano sul prezzo di CHIUSURA (BUY: bid, SELL: ask), come il grafico del canale: così lo spread non accorcia lo stop
        sl, tp = (ref - sl_d, ref + tp_d) if buy else (ref + sl_d, ref - tp_d)
        scarto = tick.bid - sig["entry"]                  # differenza di quotazione tra il tuo broker e il canale (entrambi sul bid)
        try:
            log_scarto(tag, sig, tick, scarto)
        except OSError:
            pass
    else:
        check_levels(sig, tick.bid, tick.ask)
        sl, tp, scarto = sig["sl"], sig["tp1"], 0.0
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": lots, "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": px, "sl": round(sl, d), "tp": round(tp, d), "deviation": DEVIATION, "magic": MAGIC,
           "comment": "tg-signal", "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling(mt5, info)}
    summary = f"{sig['side'].upper()} {sym} {lots} lotti a mercato ~{px} · SL {req['sl']} ({abs(px - req['sl']):.2f} $) · TP1 {req['tp']} ({abs(req['tp'] - px):.2f} $)"
    if relative_levels():
        summary += f" · scarto dal canale {scarto:+.2f} · spread {tick.ask - tick.bid:.2f}"
        hist = [v for _, v in read_scarti()[:-1]]                       # esclude quello appena registrato
        if len(hist) >= 5:
            import statistics as st
            m = st.median(hist)
            if abs(scarto - m) > 3.0:
                summary += f" · ⚠ scarto insolito (tipico {m:+.2f})"
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
    """Per ogni posizione seguita già chiusa: se è chiusa a TP risponde al messaggio del segnale, pulito: '✅ TP1 +N pips' o '❌ SL HIT -N pips'; poi la toglie dall'elenco."""
    for key, t in list(pending.items()):
        if only is not None and not only(t):
            continue
        deals = mt5.history_deals_get(position=t["position"]) or []
        out = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        if not out:
            continue
        d = out[-1]
        del pending[key]
        n = pips(t["symbol"], d.price, t["open"])
        if d.reason == mt5.DEAL_REASON_TP:
            say(bot, f"✅ TP1 +{n:.0f} pips", t["msg_id"])
        elif d.reason == mt5.DEAL_REASON_SL:
            say(bot, f"❌ SL HIT -{n:.0f} pips", t["msg_id"])
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
        bot._call("sendMessage", chat_id=bot.chat_id, text=text, **kw)
    except Exception as e:
        print("Invio Telegram fallito:", str(e)[:200], flush=True)


def log_scarto(tag: str, sig: dict, tick, scarto: float) -> None:
    SCARTI.parent.mkdir(exist_ok=True)
    new = not SCARTI.exists()
    with SCARTI.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["quando_utc", "conto", "lato", "entry_canale", "bid", "ask", "spread", "scarto"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), tag, sig["side"], sig["entry"], tick.bid, tick.ask, round(tick.ask - tick.bid, 5), round(scarto, 3)])


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
    try:
        last = bot._call("getUpdates", offset=-1)                 # scarta ciò che è arrivato prima dell'avvio
        offset = last[-1]["update_id"] + 1 if last else 0
    except Exception as e:                                        # un problema di rete all'avvio non deve fermare il programma
        print("Telegram non raggiungibile all'avvio, riprovo:", str(e)[:150], flush=True)
        offset = 0
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
                                res, trk = execute(mt, sig, dry, acc["lots"], acc["login"] and str(acc["login"]))
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
    ap.add_argument("--calibra", action="store_true", help="riepilogo degli scarti tra il prezzo del canale e quello del tuo broker")
    ap.add_argument("--check", action="store_true", help="diagnosi dei conti e del collegamento a MT5")
    ap.add_argument("--suggest", action="store_true", help="stampa un messaggio di prova coerente con il prezzo attuale")
    a = ap.parse_args()
    calibra() if a.calibra else check() if a.check else suggest() if a.suggest else main(a.dry)
