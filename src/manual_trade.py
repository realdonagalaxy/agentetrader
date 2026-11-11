"""Parte MANUALE di Gestione Conti: trading discrezionale. I dati del trade li scrive l'utente (modulo o testo incollato); il programma apre gli ordini e li gestisce con la STESSA logica
della parte automatica: TP scelto per conto, parzializzazione a TP1 con il resto a pareggio (BE), controllo dei risultati nella pagina.

Gestione del trade (decisa nel modulo, per ogni trade, uguale su tutti i conti scelti): TP1 = dove si parzializza, TP2 = dove si chiude il resto. Con «parzializza» attivo si aprono due posizioni
(quota % a TP1, il resto a TP2); quando TP1 viene toccato lo SL del resto va a pareggio (BE). Senza parzializzazione una posizione sola, chiusa al TP finale (TP2 se c'è, altrimenti TP1).
Differenze rispetto ai segnali del canale (parte automatica):
- i prezzi sono QUELLI DEL TUO CONTO: nessuna conversione dello scarto tra broker, nessun filtro dei 45 pips;
- ingresso a scelta per ogni trade: mercato, LIMIT o STOP al prezzo scritto;
- size dal RISCHIO in % del saldo (dalla distanza dello SL, conto per conto), non dai lotti fissi del conto;
- conti reali: solo se il conto è abilitato ai manuali, con conferma esplicita a ogni apertura e rischio massimo MANUAL_MAX_RISK_REAL (default 2%).

La richiesta la scrive la pagina in journal/manuali/<id>.json; la esegue il programma in ascolto (stesso che segue le posizioni e porta a BE): così c'è un solo proprietario dell'elenco delle posizioni.
"""
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

DIR = Path(os.environ.get("JOURNAL_DIR", "journal"))
REQ_DIR = DIR / "manuali"
MAN_CSV = DIR / "manuali.csv"
MAN_ESITI = DIR / "manuali_esiti.csv"
MAX_RISK = float(os.environ.get("MANUAL_MAX_RISK") or 5.0)              # % massimo del saldo rischiato in un trade (conti demo)
MAX_RISK_REAL = float(os.environ.get("MANUAL_MAX_RISK_REAL") or 2.0)    # % massimo sui conti REALI
MAX_LOTS = float(os.environ.get("MANUAL_MAX_LOTS") or 5.0)              # lotti massimi per trade
MAN_COLS = ["time_utc", "msg_id", "symbol", "side", "entry", "sl", "tp1", "tp2", "tp3", "tipo", "rischio", "parz", "nota", "errore", "testo"]
ESITI_COLS = ["quando_utc", "msg_id", "conto", "esito", "lotti", "bid", "ask", "spread", "scarto_usato", "fonte_scarto", "pips_al_tp1", "ticket", "prezzo_apertura", "dettaglio"]
TIPI = ("market", "limit", "stop")


def _num(v, name: str, required: bool = True):
    s = str(v if v is not None else "").strip().replace(",", ".")
    if not s:
        if required:
            raise ValueError(f"manca {name}")
        return None
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"{name} non è un numero: {v!r}")


def parse_request(d: dict) -> dict:
    """Valida i dati del trade. Livelli coerenti con la direzione: BUY SL < Entry < TP1 < TP2 < TP3, SELL al contrario (TP2/TP3 facoltativi)."""
    side = str(d.get("side") or "").strip().lower()
    if side not in ("buy", "sell"):
        raise ValueError("la direzione deve essere BUY o SELL")
    tipo = str(d.get("tipo") or "market").strip().lower()
    if tipo not in TIPI:
        raise ValueError("il tipo di ingresso deve essere mercato, limit o stop")
    r = {"symbol": str(d.get("symbol") or "XAUUSD").strip().upper(), "side": side, "tipo": tipo, "entry": _num(d.get("entry"), "Entry"), "sl": _num(d.get("sl"), "SL"),
         "tp1": _num(d.get("tp1"), "TP1"), "tp2": _num(d.get("tp2"), "TP2", False), "tp3": _num(d.get("tp3"), "TP3", False),
         "rischio": _num(d.get("rischio"), "il rischio %"), "nota": str(d.get("nota") or "")[:300]}
    pz = _num(d.get("parz"), "la quota da parzializzare", False) or 0.0
    if pz and not 10 <= pz <= 90:
        raise ValueError("la quota da chiudere a TP1 deve stare tra 10 e 90% (vuoto o 0 = nessuna parzializzazione)")
    r["parz"] = int(round(pz))
    if r["parz"] and r["tp2"] is None:
        raise ValueError("per parzializzare serve il TP2 (TP1 = dove chiudi la quota, TP2 = dove chiudi il resto)")
    if not r["symbol"].replace(".", "").replace("_", "").isalnum():
        raise ValueError("simbolo non valido")
    if not 0 < r["rischio"] <= MAX_RISK:
        raise ValueError(f"il rischio deve stare tra 0 e {MAX_RISK:g}% del saldo")
    levels = [r["sl"], r["entry"], r["tp1"]] + [x for x in (r["tp2"], r["tp3"]) if x is not None]
    if r["tp3"] is not None and r["tp2"] is None:
        raise ValueError("c'è TP3 ma manca TP2")
    asc = all(a < b for a, b in zip(levels, levels[1:]))
    desc = all(a > b for a, b in zip(levels, levels[1:]))
    if side == "buy" and not asc:
        raise ValueError("BUY: servono SL < Entry < TP1 < TP2 < TP3 (TP2 e TP3 se presenti)")
    if side == "sell" and not desc:
        raise ValueError("SELL: servono SL > Entry > TP1 > TP2 > TP3 (TP2 e TP3 se presenti)")
    return r


def _loss_per_lot(mt5, info, buy: bool, price: float, sl: float, sym: str) -> float:
    """Perdita in valuta del conto per 1 lotto se il prezzo va da «price» allo SL."""
    try:
        pr = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL, sym, 1.0, price, sl)
        if pr:
            return abs(float(pr))
    except Exception:
        pass
    tv, ts = getattr(info, "trade_tick_value", None), getattr(info, "trade_tick_size", None)
    if tv and ts:
        return abs(price - sl) / ts * tv
    raise ValueError(f"non riesco a calcolare il valore del rischio per {sym}: controlla il simbolo")


def execute_manual(mt5, req: dict, acc: dict, dry: bool = False, confirm_real: bool = False) -> tuple[str, list]:
    """Apre il trade manuale sul conto collegato. Ritorna (testo, posizioni da seguire); solleva ValueError con il motivo se non apre."""
    from src import mt5_orders as mo
    ti = mt5.terminal_info()
    if ti is not None and getattr(ti, "trade_allowed", True) is False:
        raise ValueError("Il trading automatico è spento in MT5 (pulsante «Algo Trading» rosso).")
    ai = mt5.account_info()
    if ai is None:
        raise ValueError("MT5 non risponde: controlla che il terminale sia aperto e collegato")
    real = ai.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO
    if real:
        if not acc.get("manual_ok"):
            raise ValueError("conto REALE non abilitato ai trade manuali (spunta «Usa per i trade manuali» in Modifica)")
        if not dry and not confirm_real:
            raise ValueError("conto REALE: manca la conferma esplicita")
        if req["rischio"] > MAX_RISK_REAL:
            raise ValueError(f"conto REALE: rischio massimo {MAX_RISK_REAL:g}% (richiesto {req['rischio']:g}%)")
    sym = mo.broker_symbol(req["symbol"])
    info = mt5.symbol_info(sym)
    if info is None or not mt5.symbol_select(sym, True):
        raise ValueError(f"simbolo {sym!r} non trovato su MT5")
    tick = mt5.symbol_info_tick(sym)
    buy, d, tipo = req["side"] == "buy", info.digits, req["tipo"]
    stops = (getattr(info, "trade_stops_level", 0) or 0) * (getattr(info, "point", 0.01) or 0.01)
    # --- obiettivo e parzializzazione: dal trade (TP1 = parziale, TP2 = chiusura del resto), uguali su ogni conto
    partial = req["parz"] / 100 if req.get("parz") else 0.0
    target = 2 if req.get("tp2") is not None else 1
    chosen = req["tp2"] if target == 2 else req["tp1"]
    # --- prezzo di riferimento e controlli sul tipo di ingresso
    px_mkt = tick.ask if buy else tick.bid
    if tipo == "market":
        ref = px_mkt
        if (buy and not (req["sl"] < tick.bid and chosen > tick.ask)) or (not buy and not (req["sl"] > tick.ask and chosen < tick.bid)):
            raise ValueError(f"a mercato i livelli non sono coerenti con il prezzo di adesso ({tick.bid:.{d}f}/{tick.ask:.{d}f}): SL {req['sl']}, TP{target} {chosen}")
    else:
        ref = req["entry"]
        ok = {("buy", "limit"): req["entry"] < tick.ask - stops, ("buy", "stop"): req["entry"] > tick.ask + stops,
              ("sell", "limit"): req["entry"] > tick.bid + stops, ("sell", "stop"): req["entry"] < tick.bid - stops}[(req["side"], tipo)]
        if not ok:
            raise ValueError(f"{req['side'].upper()} {tipo.upper()} a {req['entry']}: con il prezzo di adesso ({tick.bid:.{d}f}/{tick.ask:.{d}f}) l'ordine non si può piazzare (limit: sotto il prezzo per BUY, sopra per SELL; stop: il contrario)")
    # --- size dal rischio
    balance = float(getattr(ai, "balance", 0) or 0)
    if balance <= 0:
        raise ValueError("saldo del conto non disponibile")
    risk_amount = balance * req["rischio"] / 100
    per_lot = _loss_per_lot(mt5, info, buy, ref, req["sl"], sym)
    step = getattr(info, "volume_step", 0.01) or 0.01
    vmin, vmax = getattr(info, "volume_min", step) or step, getattr(info, "volume_max", MAX_LOTS) or MAX_LOTS
    lots = int(risk_amount / per_lot / step + 1e-9) * step                     # arrotonda per difetto: mai più del rischio scelto
    lots = round(min(lots, vmax, MAX_LOTS), 2)
    if lots < vmin - 1e-9:
        raise ValueError(f"rischio troppo basso per questo SL: {req['rischio']:g}% di {balance:.2f} = {risk_amount:.2f} {ai.currency} darebbe meno del lotto minimo {vmin:g} "
                         f"(1 lotto perde {per_lot:.2f} {ai.currency} fino allo SL)")
    # --- parzializzazione: due ordini se hedging e lotti divisibili, altrimenti uno solo al TP scelto
    hedging = getattr(ai, "margin_mode", None) == getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2)
    why, split, v1, v2 = "", False, 0.0, 0.0
    if partial:
        v1 = round(int(lots * partial / step + 0.5 + 1e-9) * step, 2)
        v2 = round(lots - v1, 2)
        if not hedging:
            why = "conto non in modalità hedging"
        elif v1 < vmin - 1e-9 or v2 < vmin - 1e-9:
            why = f"lotti non divisibili ({lots:g} con passo {step:g})"
        else:
            split = True
    parts = [(v1, req["tp1"], "tp1"), (v2, chosen, "tp2")] if split else [(lots, chosen, None)]
    order_type = {("buy", "market"): mt5.ORDER_TYPE_BUY, ("sell", "market"): mt5.ORDER_TYPE_SELL}.get((req["side"], tipo))
    if order_type is None:
        order_type = getattr(mt5, f"ORDER_TYPE_{req['side'].upper()}_{tipo.upper()}")
    reqs = []
    for v, tp, name in parts:
        r = {"symbol": sym, "volume": v, "type": order_type, "sl": round(req["sl"], d), "tp": round(tp, d), "deviation": mo.DEVIATION, "magic": mo.MAGIC,
             "comment": "manuale" + (f"-{name}" if name else ""), "type_time": mt5.ORDER_TIME_GTC}
        if tipo == "market":
            r.update(action=mt5.TRADE_ACTION_DEAL, price=px_mkt, type_filling=mo.filling(mt5, info))
        else:
            r.update(action=mt5.TRADE_ACTION_PENDING, price=round(req["entry"], d), type_filling=mt5.ORDER_FILLING_RETURN)
        reqs.append(r)
    lab = {"market": "a mercato", "limit": "LIMIT", "stop": "STOP"}[tipo]
    px_txt = f"~{px_mkt:.{d}f}" if tipo == "market" else f"@ {req['entry']:.{d}f}"
    desc = (f"{req['side'].upper()} {sym} {lots:g} lotti ({req['rischio']:g}% = {risk_amount:.2f} {ai.currency}) {lab} {px_txt} · SL {reqs[0]['sl']} "
            f"({abs(ref - reqs[0]['sl']):.2f})")
    if split:
        desc += f" · TP1 {reqs[0]['tp']} con {v1:g} lotti, poi TP2 {reqs[1]['tp']} con {v2:g}: a TP1 il resto va a pareggio (BE)"
    else:
        desc += f" · TP{target} {reqs[0]['tp']} ({abs(ref - reqs[0]['tp']):.2f})"
        if partial:
            desc += f" · parzializzazione NON applicata: {why}"
    if real:
        desc = "[CONTO REALE] " + desc
    if dry:
        return f"[ANTEPRIMA, nessun ordine inviato] {desc}", []
    trks, group, note = [], f"M{time.time():.0f}-{acc.get('login', '')}", ""
    ok_codes = (mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_PLACED", 10008))
    for r, (_, _, name) in zip(reqs, parts):
        res = mt5.order_send(r)
        if res is None or res.retcode not in ok_codes:
            why2 = f"{getattr(res, 'retcode', None)} {getattr(res, 'comment', mt5.last_error())}"
            if not trks:
                raise ValueError(f"ordine rifiutato dal broker: {why2}")
            note = f" · ATTENZIONE: la seconda parte non è stata aperta: {why2}"
            break
        trk = {"position": int(res.order), "symbol": sym, "side": req["side"], "open": float(res.price) if tipo == "market" else float(req["entry"]), "tp": r["tp"], "sl": r["sl"],
               "part": name, "group": group, "target": 1 if name == "tp1" else target}
        if tipo != "market":
            trk.update(pending=True, kind=tipo, keep=True)                                # ordine in attesa: segue follow_orders; non si annulla se il prezzo tocca il TP
        trks.append(trk)
    head = "✅ Aperto" if tipo == "market" else f"⏳ Ordine {tipo.upper()} piazzato"
    return f"{head} manuale: {desc}{note} · ticket {', '.join(str(t['position']) for t in trks)}", trks


# ---------------- registri e coda di richieste ----------------
def _append(path: Path, cols: list, row: dict) -> None:
    DIR.mkdir(exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def log_manual(mid: str, req: dict) -> None:
    _append(MAN_CSV, MAN_COLS, {"time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "msg_id": mid, "symbol": req["symbol"], "side": req["side"], "entry": req["entry"],
                                "sl": req["sl"], "tp1": req["tp1"], "tp2": req["tp2"] or "", "tp3": req["tp3"] or "", "tipo": req["tipo"], "rischio": req["rischio"], "parz": req.get("parz") or "", "nota": req["nota"]})


def log_esito(mid: str, conto, kind: str, lots, trks: list, text: str) -> None:
    _append(MAN_ESITI, ESITI_COLS, {"quando_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "msg_id": mid, "conto": conto, "esito": kind, "lotti": lots,
                                    "ticket": ",".join(str(t["position"]) for t in trks), "prezzo_apertura": trks[0]["open"] if trks else "", "dettaglio": text.replace("\n", " | ")[:400]})


def write_request(req: dict, account_ids: list, confirm_real: bool) -> str:
    """Scrive la richiesta per il programma in ascolto; ritorna l'id."""
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    mid = f"M{int(time.time() * 1000)}"
    tmp = REQ_DIR / f"{mid}.tmp"
    tmp.write_text(json.dumps({"id": mid, "req": req, "accounts": account_ids, "confirm_real": bool(confirm_real)}), encoding="utf-8")
    tmp.rename(REQ_DIR / f"{mid}.json")
    return mid


def process_requests(pending: dict, bot, say, save_pending) -> int:
    """Esegue le richieste in coda (chiamata dal ciclo del programma in ascolto). Ritorna quante ne ha elaborate."""
    from src import mt5_accounts as ma
    n = 0
    if not REQ_DIR.exists():
        return 0
    for f in sorted(REQ_DIR.glob("M*.json")):
        if f.name.endswith(".done.json") or f.name.endswith(".result.json"):
            continue
        try:
            job = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        mid, req, results = job["id"], job["req"], []
        try:
            f.unlink()
        except OSError:
            continue
        n += 1
        log_manual(mid, req)
        for aid in job["accounts"]:
            try:
                acc = ma.get_account(int(aid))
            except Exception:
                results.append({"conto": aid, "ok": False, "testo": "conto non trovato"})
                continue
            try:
                with ma.session(acc) as mt:
                    text, trks = execute_manual(mt, req, acc, False, job.get("confirm_real", False))
                for t in trks:
                    t["account"] = acc["id"]
                    pending[f"{acc['id']}:{t['position']}"] = {**t, "msg_id": None, "sig_id": mid}
                if trks:
                    save_pending(pending)
                log_esito(mid, acc["login"], "aperto" if trks and not trks[0].get("pending") else "stop", acc["lots"], trks, text)
                results.append({"conto": acc["login"], "ok": True, "testo": text})
            except Exception as e:
                msg = str(e)
                log_esito(mid, acc["login"], "rifiutato", acc["lots"], [], f"⛔ Non apro: {msg}")
                results.append({"conto": acc["login"], "ok": False, "testo": msg})
            say(bot, f"[{acc['login']}] " + (results[-1]["testo"] if results[-1]["ok"] else "⛔ Non apro: " + results[-1]["testo"]))
        (REQ_DIR / f"{mid}.result.json").write_text(json.dumps({"id": mid, "ts": time.time(), "risultati": results}, ensure_ascii=False), encoding="utf-8")
    return n
