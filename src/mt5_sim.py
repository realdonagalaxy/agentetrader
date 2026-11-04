"""Simulatore minimale di MetaTrader 5 per provare l'interfaccia dei conti SENZA MT5 (Mac/Linux o prove). Attivo solo con MT5_SIMULATOR=1.
Prezzi inventati (non reali), conti demo fittizi: serve solo a verificare che il software funzioni. Non usarlo per decisioni di trading."""
import math
import time
from types import SimpleNamespace as N

ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_REAL = 0, 2
TRADE_ACTION_DEAL = 1
TRADE_ACTION_SLTP = 2
TRADE_ACTION_PENDING, TRADE_ACTION_REMOVE = 5, 8
ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP = 4, 5
ORDER_TIME_DAY = 1
TRADE_RETCODE_PLACED = 10008
ACCOUNT_MARGIN_MODE_RETAIL_NETTING, ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 0, 2
ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
TRADE_RETCODE_DONE = 10009
DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
DEAL_REASON_CLIENT, DEAL_REASON_SL, DEAL_REASON_TP = 0, 4, 5
TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15 = 1, 5, 15

_state = {"orders": {}, "login": None, "positions": {}, "deals": {}, "next": 5000000000, "real": {9990001}}
_BAL = {}


def terminal_info():
    return N(path=_state.get("path") or "C:\\Program Files\\MetaTrader 5")


def initialize(path=None, login=None, password=None, server=None, timeout=None, **kw):
    import ntpath
    import posixpath
    _state["path"] = (ntpath if "\\" in (path or "") else posixpath).dirname(path) if path else None
    _state["login"] = login or _state["login"] or 1001
    return True


def shutdown():
    return True


def last_error():
    return (1, "Success")


def account_info():
    lg = _state["login"]
    if lg is None:
        return None
    if lg not in _BAL:                                                   # primo accesso al conto: due posizioni di esempio
        _BAL[lg] = 10000.0 + (lg % 7) * 2500
        p0 = _px()
        for i, (ty, vol) in enumerate(((ORDER_TYPE_BUY, 0.05), (ORDER_TYPE_SELL, 0.10))):
            _state["next"] += 1
            _state["positions"][_state["next"]] = N(ticket=_state["next"], login=lg, symbol="GOLD", type=ty, volume=vol, price_open=round(p0 - (2 if ty == 0 else -2), 2), price_current=p0,
                                                    sl=round(p0 - 60, 2) if ty == 0 else round(p0 + 60, 2), tp=round(p0 + 90, 2) if ty == 0 else round(p0 - 90, 2), profit=0.0, swap=0.0,
                                                    time=int(time.time()) - 600, magic=0, comment="esempio")
    bal = _BAL[lg]
    _tick_positions()
    pos = [p for p in _state["positions"].values() if p.login == lg]
    pr = sum(p.profit for p in pos)
    return N(login=lg, name="Conto simulato", server="Simulatore", company="FundedNext Ltd" if lg in _state["real"] else "Broker Simulato Ltd", currency="EUR", leverage=500, balance=bal, equity=bal + pr, margin=100.0 * len(pos), margin_mode=ACCOUNT_MARGIN_MODE_RETAIL_NETTING if lg in _state.get("netting", set()) else ACCOUNT_MARGIN_MODE_RETAIL_HEDGING,
             margin_free=bal + pr - 100.0 * len(pos), profit=pr, trade_mode=ACCOUNT_TRADE_MODE_REAL if lg in _state["real"] else ACCOUNT_TRADE_MODE_DEMO)


def _px():
    t = time.time()
    return round(3990 + 6 * math.sin(t / 90) + 1.5 * math.sin(t / 7), 2)


def symbol_select(sym, on=True):
    return sym in ("GOLD", "XAUUSD")


def copy_rates_range(sym, tf, d0, d1):
    import random
    step = {1: 60, 5: 300, 15: 900}.get(tf, 60)
    t, out = int(d0.timestamp()) // step * step, []
    rnd, px = random.Random(t), 3990.0
    while t < d1.timestamp() and len(out) < 2000:
        o = px
        c = o + rnd.gauss(0, 0.8)
        out.append({"time": t, "open": o, "high": max(o, c) + abs(rnd.gauss(0, .3)), "low": min(o, c) - abs(rnd.gauss(0, .3)), "close": c})
        px, t = c, t + step
    return out


def symbols_get(*a, **kw):
    return (N(name="GOLD"), N(name="EURUSD"), N(name="XAUEUR"))


def symbol_info(sym):
    return N(digits=2, filling_mode=3, point=0.01, trade_stops_level=0, expiration_mode=15) if sym in ("GOLD", "XAUUSD") else None


def symbol_info_tick(sym):
    p = _px()
    return N(bid=p, ask=round(p + 0.47, 2), time=int(time.time()))


def _tick_positions():
    p = _px()
    for tk, od in list(_state["orders"].items()):                    # ordini stop: scattano quando il prezzo raggiunge il livello
        ask = round(p + 0.47, 2)
        if (od.type == ORDER_TYPE_BUY_STOP and ask >= od.price_open) or (od.type == ORDER_TYPE_SELL_STOP and p <= od.price_open):
            _state["orders"].pop(tk)
            ty = ORDER_TYPE_BUY if od.type == ORDER_TYPE_BUY_STOP else ORDER_TYPE_SELL
            _state["positions"][tk] = N(ticket=tk, login=od.login, symbol=od.symbol, type=ty, volume=od.volume, price_open=od.price_open, price_current=p, sl=od.sl, tp=od.tp,
                                        profit=0.0, swap=0.0, time=int(time.time()), magic=od.magic, comment=od.comment)
            _state["deals"].setdefault(tk, []).append(N(entry=DEAL_ENTRY_IN, reason=DEAL_REASON_CLIENT, price=od.price_open, profit=0.0, position_id=tk, time=int(time.time()), type=ty))
    for k, pos in list(_state["positions"].items()):
        buy = pos.type == ORDER_TYPE_BUY
        cur = p if buy else round(p + 0.47, 2)
        pos.price_current = cur
        pos.profit = round(((cur - pos.price_open) if buy else (pos.price_open - cur)) * pos.volume * 100, 2)
        hit = None
        if pos.tp and ((cur >= pos.tp) if buy else (cur <= pos.tp)):
            hit = DEAL_REASON_TP
        elif pos.sl and ((cur <= pos.sl) if buy else (cur >= pos.sl)):
            hit = DEAL_REASON_SL
        if hit is not None:
            _close(pos, cur, hit)


def _close(pos, price, reason):
    _state["positions"].pop(pos.ticket, None)
    _BAL[pos.login] = _BAL.get(pos.login, 10000.0) + pos.profit
    lst = _state["deals"].setdefault(pos.ticket, [])
    if not any(x.entry == DEAL_ENTRY_IN for x in lst):
        lst.append(N(entry=DEAL_ENTRY_IN, reason=DEAL_REASON_CLIENT, price=pos.price_open, profit=0.0, position_id=pos.ticket, time=pos.time, type=pos.type))
    lst.append(N(entry=DEAL_ENTRY_OUT, reason=reason, price=price, profit=pos.profit, position_id=pos.ticket, time=int(time.time()), type=1 - pos.type))


def orders_get(ticket=None, **kw):
    _tick_positions()
    return tuple(o for o in _state["orders"].values() if o.login == _state["login"] and (ticket is None or o.ticket == ticket))


def positions_get(**kw):
    _tick_positions()
    return tuple(p for p in _state["positions"].values() if p.login == _state["login"])


_fake = {}


def _fake_trades(login):
    """Operazioni chiuse inventate (solo simulatore): apertura e chiusura con prezzi, verso e motivo (TP, SL o chiusura a mano)."""
    if login not in _fake:
        import random
        rnd, now, out = random.Random(login or 1), int(time.time()), []
        for i in range(90):
            tc = now - int(rnd.random() * 100 * 86400)
            ty, reason = rnd.randint(0, 1), rnd.choice((DEAL_REASON_TP, DEAL_REASON_TP, DEAL_REASON_SL, DEAL_REASON_CLIENT))
            p0 = round(3900 + rnd.random() * 100, 2)
            mv = {DEAL_REASON_TP: 5.0, DEAL_REASON_SL: -15.0}.get(reason, rnd.gauss(0, 4))
            p1 = round(p0 + (mv if ty == 0 else -mv), 2)
            pid = 7000000 + i
            out.append((pid, tc - 3000, tc, ty, p0, p1, round(mv * 5, 2), reason))
        _fake[login] = out
    return _fake[login]


def _deals_of(t):
    pid, to, tc, ty, p0, p1, pl, reason = t
    return [N(ticket=pid * 2, position_id=pid, time=to, type=ty, entry=DEAL_ENTRY_IN, reason=DEAL_REASON_CLIENT, price=p0, profit=0.0, commission=-0.35, swap=0.0, fee=0.0, symbol="GOLD"),
            N(ticket=pid * 2 + 1, position_id=pid, time=tc, type=1 - ty, entry=DEAL_ENTRY_OUT, reason=reason, price=p1, profit=pl, commission=-0.35, swap=0.0, fee=0.0, symbol="GOLD")]


def history_orders_get(*a, position=None, **kw):
    for t in _fake_trades(_state["login"]):
        if t[0] == position:
            pid, to, tc, ty, p0, p1, pl, reason = t
            return (N(position_id=pid, time_setup=to, price_open=p0, sl=round(p0 - 15 if ty == 0 else p0 + 15, 2), tp=round(p0 + 5 if ty == 0 else p0 - 5, 2)),)
    return ()


def history_deals_get(*a, position=None, **kw):
    if a:                                                              # intervallo di date
        t0 = a[0].timestamp() if hasattr(a[0], "timestamp") else a[0]
        t1 = a[1].timestamp() if hasattr(a[1], "timestamp") else a[1]
        for t in _fake_trades(_state["login"]):
            for d in _deals_of(t):
                d._asdict = (lambda y=d: {k: v for k, v in vars(y).items() if k != "_asdict"})
        return tuple(d for t in _fake_trades(_state["login"]) for d in _deals_of(t) if t0 <= d.time < t1)
    for t in _fake_trades(_state["login"]):
        if t[0] == position:
            return tuple(_deals_of(t))
    return tuple(_state["deals"].get(position, ()))


def order_send(req):
    _tick_positions()
    if req.get("action") == TRADE_ACTION_PENDING:
        _state["next"] += 1
        _state["orders"][_state["next"]] = N(ticket=_state["next"], login=_state["login"], symbol=req["symbol"], type=req["type"], price_open=req["price"], sl=req["sl"], tp=req["tp"],
                                             volume=req["volume"], magic=req.get("magic", 0), comment=req.get("comment", ""))
        return N(retcode=TRADE_RETCODE_PLACED, comment="Placed", price=0, order=_state["next"])
    if req.get("action") == TRADE_ACTION_REMOVE:
        if _state["orders"].pop(req["order"], None) is None:
            return N(retcode=10013, comment="Invalid request", price=0, order=0)
        return N(retcode=TRADE_RETCODE_DONE, comment="Done", price=0, order=req["order"])
    if req.get("action") == TRADE_ACTION_SLTP:                         # modifica di SL/TP
        pos = _state["positions"].get(req["position"])
        if pos is None:
            return N(retcode=10013, comment="Invalid request", price=0, order=0)
        buy = pos.type == ORDER_TYPE_BUY
        cur = symbol_info_tick(pos.symbol).bid if buy else symbol_info_tick(pos.symbol).ask
        if req.get("sl") and ((req["sl"] >= cur) if buy else (req["sl"] <= cur)):
            return N(retcode=10016, comment="Invalid stops", price=0, order=0)
        pos.sl, pos.tp = req.get("sl", pos.sl), req.get("tp", pos.tp)
        return N(retcode=TRADE_RETCODE_DONE, comment="Done", price=0, order=pos.ticket)
    tick = symbol_info_tick(req["symbol"])
    if "position" in req:                                            # chiusura
        pos = _state["positions"].get(req["position"])
        if pos is None:
            return N(retcode=10013, comment="Invalid request", price=0, order=0)
        price = tick.bid if pos.type == ORDER_TYPE_BUY else tick.ask
        pos.price_current = price
        pos.profit = round(((price - pos.price_open) if pos.type == ORDER_TYPE_BUY else (pos.price_open - price)) * pos.volume * 100, 2)
        _close(pos, price, DEAL_REASON_CLIENT)
        return N(retcode=TRADE_RETCODE_DONE, comment="Done", price=price, order=pos.ticket)
    _state["next"] += 1
    buy = req["type"] == ORDER_TYPE_BUY
    price = tick.ask if buy else tick.bid
    _state["positions"][_state["next"]] = N(ticket=_state["next"], login=_state["login"], symbol=req["symbol"], type=req["type"], volume=req["volume"], price_open=price,
                                            price_current=price, sl=req["sl"], tp=req["tp"], profit=0.0, swap=0.0, time=int(time.time()), magic=req.get("magic", 0), comment=req.get("comment", ""))
    return N(retcode=TRADE_RETCODE_DONE, comment="Done", price=price, order=_state["next"])
