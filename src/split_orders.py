"""«Dividi» un ordine LIMIT in due (parzializzazione): una parte con TP1, l'altra con TP2, stesso prezzo e stesso SL.
MT5 non permette di cambiare i lotti di un ordine pendente: si piazzano i due nuovi ordini, poi si cancella l'originale (se qualcosa va storto si annulla tutto e l'ordine originale resta com'era).
Dopo TP1 (parte 1 chiusa in profitto) lo SL della parte 2 viene portato a pareggio da `watch_once`, chiamata a intervalli dal server di Gestione Conti.
Sui conti NON demo serve scrivere REALE come conferma. Le coppie create sono registrate in journal/split_ordini.json."""
import json
import math
import time
import uuid

from src import mt5_accounts as ma

MAGIC = 530002
FILE = ma.DATA_DIR / "split_ordini.json"
LIMITS = {2: True, 3: False}                                       # ORDER_TYPE_BUY_LIMIT / SELL_LIMIT -> è un buy?


def _load() -> list[dict]:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def _dec(step: float) -> int:
    s = f"{step:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def _split_lots(vol: float, pct: float, step: float, vmin: float) -> tuple[float, float]:
    """Lotti della parte 1 (pct %) e della parte 2 (il resto), multipli del passo del simbolo."""
    step = step or 0.01
    d = _dec(step)
    v1 = round(math.floor(vol * pct / 100 / step + 1e-9) * step, d)
    v2 = round(vol - v1, d)
    if v1 < vmin - 1e-12 or v2 < vmin - 1e-12:
        raise ValueError(f"{vol:g} lotti non si dividono così: serve almeno {vmin:g} lotti per parte (passo {step:g}). Cambia la percentuale o usa un ordine più grande.")
    return v1, v2


def _find(mt5, ticket: int):
    for o in (mt5.orders_get() or []):
        if int(o.ticket) == int(ticket):
            return o
    raise ValueError("L'ordine non c'è più su MT5 (eseguito, cancellato o modificato): aggiorna e riprova.")


def _plan(mt5, ticket: int, tp1: float, tp2: float, pct: float) -> dict:
    o = _find(mt5, ticket)
    t = int(o.type)
    if t not in LIMITS:
        raise ValueError("Si possono dividere solo gli ordini BUY LIMIT e SELL LIMIT.")
    buy = LIMITS[t]
    info = mt5.symbol_info(o.symbol)
    if info is None:
        raise ValueError(f"Simbolo {o.symbol} non disponibile sul conto.")
    if getattr(mt5.account_info(), "margin_mode", mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING) != mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:
        raise ValueError("Il conto è NETTING: due ordini sullo stesso simbolo si fondono in una sola posizione e il TP separato non è possibile. Serve un conto HEDGING.")
    price, sl = float(o.price_open), float(o.sl)
    if not sl:
        raise ValueError("L'ordine non ha lo SL: impostalo su MT5 prima di dividerlo.")
    if (buy and sl >= price) or (not buy and sl <= price):
        raise ValueError("Lo SL dell'ordine non è dalla parte giusta rispetto al prezzo.")
    if not (0 < pct < 100):
        raise ValueError("La percentuale a TP1 deve essere tra 0 e 100 (esclusi).")
    ok = (price < tp1 < tp2) if buy else (price > tp1 > tp2)
    if not ok:
        raise ValueError(("BUY: servono prezzo < TP1 < TP2" if buy else "SELL: servono prezzo > TP1 > TP2") + f" (prezzo {price:g}, TP1 {tp1:g}, TP2 {tp2:g}).")
    vol = float(getattr(o, "volume_current", None) or getattr(o, "volume_initial", None) or o.volume)
    v1, v2 = _split_lots(vol, pct, float(info.volume_step), float(info.volume_min))
    d = int(info.digits)
    bal = float(mt5.account_info().balance)
    per_lot = ma._loss_per_lot(mt5, info, buy, price, sl, o.symbol)
    risk = round(100 * per_lot * vol / bal, 2) if per_lot and bal > 0 else None
    return {"ticket": int(o.ticket), "symbol": o.symbol, "tipo": ma.ORDER_NAMES.get(t), "side": "buy" if buy else "sell", "price": price, "sl": sl,
            "volume": vol, "vol1": v1, "vol2": v2, "tp1": round(tp1, d), "tp2": round(tp2, d), "pct": pct, "risk_pct": risk,
            "rr1": round(abs(tp1 - price) / abs(price - sl), 2), "rr2": round(abs(tp2 - price) / abs(price - sl), 2), "_t": t, "_o": o}


def _public(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


def preview(acc: dict, ticket: int, tp1: float, tp2: float, pct: float) -> dict:
    """Cosa verrebbe fatto, senza toccare nulla. `needs_real`: il conto non è demo, la conferma richiede di scrivere REALE."""
    with ma.session(acc) as mt5:
        p = _plan(mt5, ticket, tp1, tp2, pct)
        return {**_public(p), "demo": ma.is_demo(mt5), "needs_real": not ma.is_demo(mt5), "login": acc["login"]}


def _req(mt5, o, p: dict, vol: float, tp: float, name: str, gid: str) -> dict:
    r = {"action": mt5.TRADE_ACTION_PENDING, "symbol": p["symbol"], "volume": vol, "type": int(o.type), "price": p["price"], "sl": p["sl"], "tp": tp,
         "magic": MAGIC, "comment": f"split-{gid}-{name}"[:31],
         "type_time": getattr(o, "type_time", mt5.ORDER_TIME_GTC), "type_filling": getattr(o, "type_filling", mt5.ORDER_FILLING_RETURN)}
    exp = int(getattr(o, "time_expiration", 0) or 0)
    if exp:
        r["expiration"] = exp
    return r


def _ok(mt5, res) -> bool:
    return res is not None and res.retcode in (mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_PLACED", 10008))


def execute(acc: dict, ticket: int, tp1: float, tp2: float, pct: float, expect: dict, confirm: str = "") -> dict:
    """Piazza le due parti e cancella l'ordine originale. `expect` (prezzo, sl, lotti visti nell'anteprima) evita di agire se l'ordine è cambiato nel frattempo."""
    with ma.session(acc) as mt5:
        demo = ma.is_demo(mt5)
        if not demo and str(confirm).strip() != "REALE":
            raise ValueError("Conto REALE: per confermare scrivi REALE.")
        p = _plan(mt5, ticket, tp1, tp2, pct)
        for k in ("price", "sl", "volume"):
            if abs(float(expect.get(k, "nan")) - p[k]) > 1e-9:
                raise ValueError("L'ordine è cambiato su MT5 dopo l'anteprima: riapri «Dividi» e ricontrolla.")
        o, gid = p["_o"], uuid.uuid4().hex[:8]
        placed, tickets = [], {}
        for vol, tp, name in ((p["vol1"], p["tp1"], "tp1"), (p["vol2"], p["tp2"], "tp2")):
            res = mt5.order_send(_req(mt5, o, p, vol, tp, name, gid))
            if not _ok(mt5, res):
                for t in placed:                                         # annulla: l'ordine originale non è stato toccato
                    mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": t})
                raise ValueError(f"Il broker ha rifiutato l'ordine {name.upper()} ({getattr(res, 'retcode', '?')} {getattr(res, 'comment', '')}). Nessuna modifica: l'ordine originale è rimasto.")
            placed.append(int(res.order))
            tickets[name] = int(res.order)
        res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(o.ticket)})
        if not _ok(mt5, res):
            for t in placed:
                mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": t})
            raise ValueError(f"Non sono riuscito a cancellare l'ordine originale ({getattr(res, 'retcode', '?')} {getattr(res, 'comment', '')}): ho annullato le due parti, tutto com'era.")
        items = _load()
        items.append({"gid": gid, "account": int(acc["id"]), "login": int(acc["login"]), "symbol": p["symbol"], "side": p["side"], "price": p["price"],
                      "tp1_order": tickets["tp1"], "tp2_order": tickets["tp2"], "state": "attivo", "created": int(time.time()), "note": ""})
        _save(items)
        return {**_public(p), "gid": gid, "demo": demo, "tickets": tickets}


def _closed_in_profit(mt5, position: int):
    """None = posizione non ancora chiusa (o mai aperta); True/False = chiusa in profitto o no."""
    deals = mt5.history_deals_get(position=int(position)) or ()
    outs = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
    if not outs:
        return None
    return sum(float(d.profit) for d in outs) > 0


def _position(mt5, ticket: int):
    for p in (mt5.positions_get() or []):
        if int(p.ticket) == int(ticket):
            return p
    return None


def _has_order(mt5, ticket: int) -> bool:
    return any(int(o.ticket) == int(ticket) for o in (mt5.orders_get() or []))


def _step(mt5, g: dict) -> None:
    """Un passaggio di controllo su una coppia: porta a pareggio la parte 2 quando la parte 1 ha chiuso in profitto."""
    t1, t2 = g["tp1_order"], g["tp2_order"]
    pos2 = _position(mt5, t2)
    if pos2 is None:
        if not _has_order(mt5, t2):
            g["state"], g["note"] = "chiusa", "parte TP2 non più aperta"
        return
    if _position(mt5, t1) is not None or _has_order(mt5, t1):
        return                                                           # la parte 1 è ancora aperta o in attesa
    res = _closed_in_profit(mt5, t1)
    if res is None:
        g["state"], g["note"] = "chiusa", "parte TP1 mai eseguita (ordine cancellato)"
        return
    if not res:
        g["state"], g["note"] = "chiusa", "parte TP1 chiusa in perdita: SL lasciato dov'è"
        return
    be = round(float(pos2.price_open), int(mt5.symbol_info(pos2.symbol).digits))
    if abs(float(pos2.sl) - be) < 1e-9:
        g["state"], g["note"] = "pareggio", "SL già a pareggio"
        return
    r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": pos2.symbol, "position": pos2.ticket, "sl": be, "tp": pos2.tp, "magic": MAGIC})
    if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
        g["state"], g["note"] = "pareggio", f"SL portato a {be:g} dopo TP1"
    else:
        g["note"] = f"pareggio non riuscito ({getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')}): riprovo"


def watch_once() -> int:
    """Controlla le coppie attive; restituisce quante ne ha elaborate. Mai eccezioni."""
    items = _load()
    active = [g for g in items if g.get("state") == "attivo"]
    if not active:
        return 0
    done = 0
    for aid in sorted({g["account"] for g in active}):
        try:
            acc = ma.get_account(aid)
            with ma.session(acc) as mt5:
                for g in (x for x in active if x["account"] == aid):
                    before = (g["state"], g["note"])
                    _step(mt5, g)
                    done += 1
                    if (g["state"], g["note"]) != before:
                        print(f"[split {g['gid']}] {g['symbol']} conto {g['login']}: {g['state']} · {g['note']}", flush=True)
        except Exception as e:
            print(f"[split] conto {aid}: {str(e)[:150]}", flush=True)
    try:
        cur = {g["gid"]: g for g in active}
        _save([cur.get(g["gid"], g) for g in _load()])                   # non sovrascrive coppie create nel frattempo
    except Exception:
        pass
    return done


def watch_loop(every: float = 30.0) -> None:
    while True:
        try:
            watch_once()
        except Exception as e:
            print("[split]", str(e)[:150], flush=True)
        time.sleep(every)
