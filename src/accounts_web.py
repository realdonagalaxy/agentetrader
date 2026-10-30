"""Gestione e monitoraggio dei conti MetaTrader 5 come applicazione web LOCALE (127.0.0.1, solo questo computer).

Avvio:  python -m src.accounts_web        (si apre il browser, di solito su http://127.0.0.1:47951)
Funzioni: aggiungi / modifica / elimina conti; vedi saldo, equity, profitto aperto e posizioni di ciascun conto; chiudi singole posizioni o tutte (solo conti DEMO).
I conti abilitati con "Usa per i segnali" sono quelli su cui `python -m src.mt5_orders` apre le operazioni ricevute da Telegram (lotti per conto).
Su un conto REALE l'app legge soltanto: nessun ordine live senza una tua conferma esplicita (regola del progetto).
Prova senza MT5:  set MT5_SIMULATOR=1  (conti e prezzi finti, solo per vedere l'interfaccia).
"""
import argparse
import csv
import json
import os
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from src import mt5_accounts as ma

WEB = Path(__file__).resolve().parent / "web"
HDR = "accounts"                                                    # intestazione X-Requested-With richiesta alle scritture (impedisce invii da altri siti)


class Server(ThreadingHTTPServer):
    allow_reuse_address = False


def activity(n: int = 60) -> list[dict]:
    p = ma.DATA_DIR / "ordini_mt5.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-n:][::-1]


def results(df, currency: str | None, source: str) -> dict:
    """Riepilogo per settimana e per mese di un elenco di trade chiusi (time, profit, commission, swap)."""
    from src.mt5_weekly import aggregate
    if df.empty:
        return {"source": source, "currency": currency, "weeks": [], "months": [], "total": {"trade": 0, "netto": 0, "vinti": 0}}
    def rows(g):
        return [{"inizio": str(i), **{k: (int(v) if k in ("trade", "vinti", "persi") else float(v)) for k, v in r.items()}} for i, r in g.iterrows()]
    w, m = aggregate(df, "W"), aggregate(df, "M")
    return {"source": source, "currency": currency, "weeks": rows(w), "months": rows(m),
            "total": {"trade": int(w.trade.sum()), "vinti": int(w.vinti.sum()), "persi": int(w.persi.sum()), "netto": round(float(w.netto.sum()), 2),
                      "profitto": round(float(w.profitto.sum()), 2), "perdita": round(float(w.perdita.sum()), 2)}}


class Handler(BaseHTTPRequestHandler):
    server_version = "AccountsWeb/1.0"

    def log_message(self, fmt, *args):
        pass

    def _ok_host(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        return host in ("127.0.0.1", "localhost") and (not origin or urlparse(origin).hostname in ("127.0.0.1", "localhost"))

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def _data(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 100_000:
            raise ValueError("richiesta troppo grande")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self._ok_host():
            return self._send(403, b"host non consentito", "text/plain")
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, (WEB / "accounts.html").read_bytes(), "text/html; charset=utf-8")
        try:
            if path == "/api/accounts":
                return self._json({"accounts": ma.list_accounts(), "simulator": os.environ.get("MT5_SIMULATOR") == "1"})
            if path == "/api/activity":
                return self._json({"rows": activity()})
            if path == "/api/results":
                q = parse_qs(urlparse(self.path).query)
                start = (q.get("from") or [f"{datetime.now().year}-01-01"])[0]
                df, cur = ma.history(ma.get_account(int((q.get("account") or ["0"])[0])), start)
                return self._json(results(df, cur, "MT5"))
            m = re.fullmatch(r"/api/accounts/(\d+)/status", path)
            if m:
                return self._json(ma.snapshot(ma.get_account(int(m[1]))))
        except ValueError as e:
            return self._json({"error": str(e)}, 404)
        self._send(404, b"non trovato", "text/plain")

    def _write(self, method: str):
        if not self._ok_host() or self.headers.get("X-Requested-With") != HDR:
            return self._send(403, b"richiesta non consentita", "text/plain")
        path = urlparse(self.path).path
        try:
            if path == "/api/accounts" and method == "POST":
                return self._json({"id": ma.save_account(self._data())}, 201)
            if path == "/api/import-current" and method == "POST":
                return self._json(ma.import_connected(str(self._data().get("terminal_path") or "")), 201)
            if path == "/api/test" and method == "POST":
                return self._json(ma.test_connection(self._data()))
            m = re.fullmatch(r"/api/accounts/(\d+)", path)
            if m and method == "PUT":
                return self._json({"id": ma.save_account(self._data(), int(m[1]))})
            if m and method == "DELETE":
                ma.delete_account(int(m[1]))
                return self._json({"deleted": int(m[1])})
            m = re.fullmatch(r"/api/accounts/(\d+)/close", path)
            if m and method == "POST":
                d = self._data()
                tickets = [int(t) for t in d["tickets"]] if d.get("tickets") else None
                return self._json({"closed": ma.close_positions(ma.get_account(int(m[1])), tickets)})
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            return self._json({"error": str(e) or "dati non validi"}, 400)
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {str(e)[:250]}"}, 500)
        self._send(404, b"non trovato", "text/plain")

    do_POST = lambda self: self._write("POST")
    do_PUT = lambda self: self._write("PUT")
    do_DELETE = lambda self: self._write("DELETE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=47951)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv("config.env")
    except ImportError:
        pass
    srv = None
    for port in range(a.port, a.port + 30):
        try:
            srv = Server(("127.0.0.1", port), Handler)
            break
        except OSError:
            print(f"Porta {port} occupata, provo la successiva…")
    if srv is None:
        sys.exit("Nessuna porta libera: usa --port con un altro numero.")
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"Conti MT5 su {url}  (Ctrl+C per chiudere)\nArchivio: {ma.DB_PATH}", flush=True)
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nChiuso.")


if __name__ == "__main__":
    main()
