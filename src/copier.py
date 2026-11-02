"""Copiatore di operazioni: riproduce sui conti DEMO di destinazione le operazioni che apri e chiudi sul conto SORGENTE (Vantage), senza Telegram.

Il conto sorgente (spunta «Conto sorgente» in Gestione Conti) viene SOLO LETTO: il software non invia mai ordini lì, anche se è un conto reale. Le destinazioni sono i conti attivi con
«Usa per i segnali» acceso; su un conto REALE non si apre né si chiude nulla (regola del progetto).
Regole:
 - si copiano solo le posizioni aperte DOPO l'avvio del copiatore (quelle già aperte vengono ignorate);
 - nuova posizione sul sorgente -> stessa direzione a mercato sulle destinazioni, con i LOTTI del conto di destinazione (campo «Lotti»); oro con qualunque nome (XAUUSD, GOLD...) -> oro di ogni broker;
 - posizione chiusa sul sorgente (a mano, a TP o a SL) -> chiusa su tutte le destinazioni; chiusura parziale -> chiusura parziale in proporzione;
 - sulle destinazioni NON si mettono TP e lo SL è solo di sicurezza (distanza dello SL sorgente x 1.5, se esiste): la chiusura vera segue il sorgente;
 - ogni evento è scritto in journal/ordini_mt5.csv (scheda Attività); battito in journal/mt5_copier.heartbeat.
Con un solo terminale MT5 ogni giro cambia conto (qualche secondo per conto): la copia non è istantanea. COPY_POLL_S (config.env) = pausa tra i giri, predefinita 3 s.
Uso: python -m src.copier        (oppure il pulsante «Avvia copia» in Gestione Conti)
"""
import csv
import json
import os
import time
from datetime import datetime, timezone

from src import mt5_accounts as ma

MAGIC_COPY = 530002
SAFETY = 1.5
MAX_COPIES = 5
STATE = ma.DATA_DIR / "copia_stato.json"
HEART = ma.DATA_DIR / "mt5_copier.heartbeat"
LOG = ma.DATA_DIR / "ordini_mt5.csv"


def log(msg: str, esito: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["quando_utc", "messaggio", "esito"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), msg, esito])
    print(f"{msg} -> {esito}", flush=True)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"seen": {}, "ignored": []}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st), encoding="utf-8")


def is_gold(sym: str) -> bool:
    u = sym.upper()
    return ("XAU" in u or "GOLD" in u) and not any(x in u for x in ("EUR", "GBP", "AUD", "JPY", "CHF", "XAG"))


def target_symbol(mt5, src_sym: str) -> str | None:
    """Nome dello strumento sul broker di destinazione: l'oro con qualunque nome; gli altri se hanno lo stesso nome."""
    if is_gold(src_sym):
        from src.price_compare import find_symbol
        return find_symbol(mt5, "XAUUSD")
    return src_sym if mt5.symbol_info(src_sym) else None


def targets() -> list[dict]:
    return [a for a in ma.list_accounts() if a["enabled"] and a["use_signals"] and not a["is_source"] and a.get("kind") != "real"]


def source() -> dict | None:
    return next((a for a in ma.list_accounts() if a["enabled"] and a["is_source"]), None)


def open_copy(acc: dict, src: dict) -> tuple[int, float]:
    """Apre sulla destinazione la copia della posizione sorgente. Restituisce (ticket, prezzo). ValueError se rifiutata."""
    with ma.session(acc) as mt5:
        if not ma.is_demo(mt5):
            raise ValueError("conto REALE: non si apre nulla")
        sym = target_symbol(mt5, src["symbol"])
        if not sym or not mt5.symbol_select(sym, True):
            raise ValueError(f"strumento {src['symbol']} non disponibile su questo conto")
        info = mt5.symbol_info(sym)
        if len([p for p in (mt5.positions_get() or []) if p.magic == MAGIC_COPY]) >= MAX_COPIES:
            raise ValueError(f"già {MAX_COPIES} copie aperte su questo conto")
        tick = mt5.symbol_info_tick(sym)
        buy = src["side"] == "buy"
        px = tick.ask if buy else tick.bid
        step = getattr(info, "volume_step", 0.01) or 0.01
        vol = max(getattr(info, "volume_min", step), round(acc["lots"] / step) * step)
        sl = 0.0
        if src.get("sl"):
            d = abs(src["open"] - src["sl"]) * SAFETY
            ref = tick.bid if buy else tick.ask
            sl = round(ref - d if buy else ref + d, info.digits)
        m = info.filling_mode
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": round(vol, 2), "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL, "price": px, "sl": sl, "tp": 0.0,
               "deviation": 20, "magic": MAGIC_COPY, "comment": f"cp:{src['ticket']}", "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": mt5.ORDER_FILLING_IOC if m & 2 else mt5.ORDER_FILLING_FOK if m & 1 else mt5.ORDER_FILLING_RETURN}
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            raise ValueError(f"ordine rifiutato dal broker: {getattr(res, 'retcode', None)} {getattr(res, 'comment', mt5.last_error())}")
        return int(res.order), float(res.price)


def close_copy(acc: dict, ticket: int, fraction: float = 1.0) -> str:
    """Chiude (tutta o in parte) la copia. ValueError se non c'è più."""
    with ma.session(acc) as mt5:
        if not ma.is_demo(mt5):
            raise ValueError("conto REALE: non si chiude nulla")
        pos = [p for p in (mt5.positions_get() or []) if int(p.ticket) == int(ticket)]
        if not pos:
            raise ValueError("posizione non trovata (già chiusa)")
        p = pos[0]
        vol = None
        if fraction < 1.0:
            info = mt5.symbol_info(p.symbol)
            step = getattr(info, "volume_step", 0.01) or 0.01
            vol = round(round(p.volume * fraction / step) * step, 2)
            if vol < getattr(info, "volume_min", step) or vol >= p.volume:
                raise ValueError("chiusura parziale troppo piccola per il lotto minimo: ignorata")
        return ma._close(mt5, p, vol, "copia")


def step(st: dict, ready: dict) -> str | None:
    """Un giro: legge il sorgente, copia le nuove posizioni, chiude quelle chiuse, riduce quelle chiuse in parte. `ready` = {'ok': bool}: false al primo giro (si fa la base di partenza)."""
    src_acc = source()
    if src_acc is None:
        return "Nessun conto sorgente attivo (spunta «Conto sorgente» in Gestione Conti)."
    snap = ma.snapshot(src_acc)
    if not snap.get("connected"):
        return f"Sorgente non raggiungibile: {snap.get('error', '')[:150]}"
    cur = {str(p["ticket"]): p for p in snap["positions"]}
    seen, ignored = st["seen"], set(st["ignored"])
    if not ready["ok"]:                                              # base di partenza: ciò che è già aperto non si copia
        skip = [t for t in cur if t not in seen]
        ignored.update(skip)
        st["ignored"] = sorted(ignored)
        ready["ok"] = True
        save_state(st)
        if skip:
            log("copiatore avviato", f"{len(skip)} posizioni già aperte sul sorgente: ignorate")
    dest = targets()
    # nuove
    for t, p in cur.items():
        if t in ignored:
            continue
        if t not in seen:
            seen[t] = {"volume": p["volume"], "symbol": p["symbol"], "side": p["side"], "copies": {}}
            for a in dest:
                try:
                    tk, px = open_copy(a, {**p, "ticket": t})
                    seen[t]["copies"][str(a["id"])] = tk
                    log(f"copia {p['side'].upper()} {p['symbol']} #{t} su {a['login']}", f"aperta #{tk} a {px} ({a['lots']} lotti)")
                except Exception as e:
                    seen[t]["copies"][str(a["id"])] = None
                    log(f"copia {p['side'].upper()} {p['symbol']} #{t} su {a['login']}", f"NON aperta: {str(e)[:150]}")
            save_state(st)
        elif p["volume"] < seen[t]["volume"] - 1e-9:                 # chiusura parziale sul sorgente
            frac = (seen[t]["volume"] - p["volume"]) / seen[t]["volume"]
            for aid, tk in seen[t]["copies"].items():
                if tk:
                    try:
                        log(f"parziale #{t} su {aid}", close_copy(ma.get_account(int(aid)), tk, frac))
                    except Exception as e:
                        log(f"parziale #{t} su {aid}", f"non eseguita: {str(e)[:120]}")
            seen[t]["volume"] = p["volume"]
            save_state(st)
    # chiuse
    for t in [t for t in seen if t not in cur]:
        for aid, tk in seen[t]["copies"].items():
            if not tk:
                continue
            try:
                log(f"chiusura #{t} su {aid}", close_copy(ma.get_account(int(aid)), tk))
            except Exception as e:
                log(f"chiusura #{t} su {aid}", f"{str(e)[:120]}")
        del seen[t]
        save_state(st)
    return None


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv("config.env")
    except ImportError:
        pass
    pause = float(os.environ.get("COPY_POLL_S") or 3)
    st, ready, last_msg = load_state(), {"ok": False}, None
    print(f"Copiatore avviato (giro ogni {pause:g} s). Ctrl+C per fermare.", flush=True)
    while True:
        try:
            HEART.parent.mkdir(parents=True, exist_ok=True)
            HEART.write_text(str(time.time()))
        except OSError:
            pass
        try:
            msg = step(st, ready)
        except Exception as e:
            msg = f"Errore: {type(e).__name__}: {str(e)[:150]}"
        if msg and msg != last_msg:
            print(msg, flush=True)
        last_msg = msg
        time.sleep(pause)


if __name__ == "__main__":
    main()
