"""Confronto delle quotazioni dell'oro tra i conti MT5 dell'app (sola lettura: nessun ordine).

Per ogni conto attivo legge bid e ask a turno, ripetendo il giro N volte (i conti si leggono uno dopo l'altro, quindi un solo campione è troppo rumoroso), e mostra la MEDIANA:
bid, ask, spread e differenza dal primo conto (riferimento). La differenza del PREZZO MEDIO ((bid+ask)/2) è lo scarto di quotazione tra i broker; la differenza dello spread è il costo diverso.
Risponde a: "i prezzi coincidono o serve applicare lo spread?" Se lo scarto medio è piccolo rispetto al rumore (colonna 'dev.st.') i broker quotano alla pari.
Uso: python -m src.price_compare [--rounds 8] [--pause 1.0] [--symbol XAUUSD]    (il nome dello strumento sul broker si ricava da solo: XAUUSD, GOLD, XAUUSD.a ...)
Registra ogni campione in journal/confronto_prezzi.csv.
"""
import argparse
import csv
import statistics as st
import time
from datetime import datetime, timezone

from src import mt5_accounts as ma


def find_symbol(mt5, want: str) -> str | None:
    """Nome dello strumento sul broker: esatto, altrimenti il primo che contiene XAU o GOLD (non su altre valute) e USD."""
    syms = [s.name for s in (mt5.symbols_get() or [])]
    if want in syms:
        return want
    cand = [n for n in syms if ("XAU" in n.upper() or "GOLD" in n.upper()) and not any(x in n.upper() for x in ("EUR", "GBP", "AUD", "JPY", "CHF", "XAG"))]
    cand.sort(key=lambda n: (len(n), n))
    return cand[0] if cand else None


def sample(acc: dict, want: str, cache: dict) -> dict:
    with ma.session(acc) as mt5:
        sym = cache.get(acc["id"]) or find_symbol(mt5, want)
        if not sym:
            raise RuntimeError(f"nessuno strumento '{want}'/oro trovato su questo conto")
        cache[acc["id"]] = sym
        mt5.symbol_select(sym, True)
        t = mt5.symbol_info_tick(sym)
        if t is None:
            raise RuntimeError(f"nessun prezzo per {sym}: mercato chiuso?")
        return {"symbol": sym, "bid": t.bid, "ask": t.ask, "server_time": int(t.time)}


def main(rounds: int, pause: float, want: str) -> None:
    accs = [a for a in ma.list_accounts() if a["enabled"]]
    if len(accs) < 2:
        raise SystemExit("Servono almeno due conti attivi nell'app per il confronto (attiva l'interruttore «Attivo»).")
    cache, data = {}, {a["id"]: [] for a in accs}
    log = ma.DATA_DIR / "confronto_prezzi.csv"
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["quando_utc", "conto", "simbolo", "bid", "ask", "spread", "ora_server_tick"])
        for r in range(rounds):
            for a in accs:
                try:
                    s = sample(a, want, cache)
                except Exception as e:
                    print(f"{a['name']}: {str(e)[:150]}")
                    data[a["id"]] = None
                    continue
                if data[a["id"]] is not None:
                    data[a["id"]].append(s)
                    w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), a["name"], s["symbol"], s["bid"], s["ask"], round(s["ask"] - s["bid"], 5), s["server_time"]])
            print(f"giro {r + 1}/{rounds}", end="\r", flush=True)
            time.sleep(pause)
    ok = [a for a in accs if data[a["id"]]]
    if len(ok) < 2:
        raise SystemExit("\nNon sono riuscito a leggere almeno due conti: controlla che i terminali siano aperti (o le password salvate).")
    med = lambda a, k: st.median(x[k] for x in data[a["id"]])
    mid = lambda a: [(x["bid"] + x["ask"]) / 2 for x in data[a["id"]]]
    ref = ok[0]
    print(f"\n{'conto':32s} {'simbolo':10s} {'bid':>9s} {'ask':>9s} {'spread':>7s} {'Δ prezzo medio':>15s} {'dev.st.':>8s}")
    for a in ok:
        d = [m - r for m, r in zip(mid(a), mid(ref))]
        sp = med(a, "ask") - med(a, "bid")
        print(f"{a['name'][:32]:32s} {data[a['id']][0]['symbol']:10s} {med(a, 'bid'):9.2f} {med(a, 'ask'):9.2f} {sp:7.2f} {st.median(d):+15.2f} {(st.pstdev(d) if len(d) > 1 else 0):8.2f}")
    print(f"\nRiferimento: {ref['name']}. Δ prezzo medio = (bid+ask)/2 del conto meno quello del riferimento (mediana dei {rounds} giri); dev.st. = rumore dovuto al ritardo tra le letture.")
    print("Se Δ è vicino a 0 (entro la dev.st.) i broker quotano alla pari e basta lo spread; se è di diversi dollari serve l'adeguamento per distanze (già attivo nei segnali).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--symbol", default="XAUUSD")
    a = ap.parse_args()
    main(a.rounds, a.pause, a.symbol)
