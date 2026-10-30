"""Simulatore minimale di MetaTrader 5 per provare l'interfaccia dei conti SENZA MT5 (Mac/Linux o prove). Attivo solo con MT5_SIMULATOR=1.
Prezzi inventati (non reali), conti demo fittizi: serve solo a verificare che il software funzioni. Non usarlo per decisioni di trading."""
import math
import time
from types import SimpleNamespace as N

ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_REAL = 0, 2
TRADE_ACTION_DEAL = 1
ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
TRADE_RETCODE_DONE = 10009
DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
DEAL_REASON_CLIENT, DEAL_REASON_SL, DEAL_REASON_TP = 0, 4, 5
TIMEFRAME_M5 = 5

_state = {"login": None, "positions": {}, "deals": {}, "next": 5000000000, "real": {9990001}}
_BAL = {}


def initialize(path=None, login=None, password=None, server=None, **kw):
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
    return N(login=lg, name="Conto simulato", server="Simulatore", currency="EUR", leverage=500, balance=bal, equity=bal + pr, margin=100.0 * len(pos),
             margin_free=bal + pr - 100.0 * len(pos), profit=pr, trade_mode=ACCOUNT_TRADE_MODE_REAL if lg in _state["real"] else ACCOUNT_TRADE_MODE_DEMO)


def _px():
    t = time.time()
    return round(3990 + 6 * math.sin(t / 90) + 1.5 * math.sin(t / 7), 2)


def symbol_select(sym, on=True):
    return sym in ("GOLD", "XAUUSD")


def symbol_info(sym):
    return N(digits=2, filling_mode=3, point=0.01) if sym in ("GOLD", "XAUUSD") else None


def symbol_info_tick(sym):
    p = _px()
    return N(bid=p, ask=round(p + 0.47, 2), time=int(time.time()))


def _tick_positions():
    p = _px()
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
    _state["deals"].setdefault(pos.ticket, []).append(N(entry=DEAL_ENTRY_OUT, reason=reason, price=price, profit=pos.profit, position_id=pos.ticket))


def positions_get(**kw):
    _tick_positions()
    return tuple(p for p in _state["positions"].values() if p.login == _state["login"])


def history_deals_get(*a, position=None, **kw):
    if a:                                                              # intervallo di date: trade di esempio generati
        import random
        rnd = random.Random(_state["login"] or 1)
        out, now = [], int(time.time())
        for i in range(70):
            tc = now - int(rnd.random() * 120 * 86400)
            pl = round(rnd.gauss(4, 28), 2)
            pid = 7000000 + i
            out.append(N(ticket=pid * 2, position_id=pid, time=tc - 3000, type=rnd.randint(0, 1), entry=DEAL_ENTRY_IN, profit=0.0, commission=-0.35, swap=0.0, fee=0.0, symbol="GOLD", _asdict=lambda: {}))
            out.append(N(ticket=pid * 2 + 1, position_id=pid, time=tc, type=rnd.randint(0, 1), entry=DEAL_ENTRY_OUT, profit=pl, commission=-0.35, swap=round(-rnd.random(), 2), fee=0.0, symbol="GOLD", _asdict=lambda: {}))
        for x in out:
            x._asdict = (lambda y=x: {k: v for k, v in vars(y).items() if k != "_asdict"})
        return tuple(x for x in out if x.time >= a[0].timestamp())
    return tuple(_state["deals"].get(position, ()))


def order_send(req):
    _tick_positions()
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
