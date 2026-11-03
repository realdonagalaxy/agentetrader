"""Gestione Conti: gestione e monitoraggio dei conti MetaTrader 5 come applicazione web LOCALE (127.0.0.1, solo questo computer).

Avvio:  python -m src.accounts_web        (si apre il browser, di solito su http://127.0.0.1:47951)
Funzioni: aggiungi / modifica / elimina conti; vedi saldo, equity, profitto aperto e posizioni di ciascun conto; chiudi singole posizioni o tutte (solo conti DEMO).
I conti abilitati con "Usa per i segnali" sono quelli su cui `python -m src.mt5_orders` apre le operazioni ricevute da Telegram (lotti per conto).
Su un conto REALE l'app legge soltanto: nessun ordine live senza una tua conferma esplicita (regola del progetto).
Prova senza MT5:  set MT5_SIMULATOR=1  (conti e prezzi finti, solo per vedere l'interfaccia).
"""
import argparse
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


def telegram_status() -> dict:
    """Stato di Telegram: il token del bot risponde (getMe), la chat è configurata, il programma dei segnali è in ascolto (battito recente)."""
    import time
    from src.telegram_bot import TelegramBot
    out = {"enabled": bool(ma.get_setting("telegram_enabled", True)), "bot": None, "bot_error": None, "chat": bool(os.environ.get("TELEGRAM_CHAT_ID")), "listener_age": None}
    try:
        if not os.environ.get("TELEGRAM_BOT_TOKEN"):
            raise RuntimeError("TELEGRAM_BOT_TOKEN mancante in config.env")
        me = TelegramBot()._call("getMe")
        out["bot"] = "@" + (me.get("username") or me.get("first_name") or "bot")
    except Exception as e:
        out["bot_error"] = str(e)[:200]
    hb = ma.DATA_DIR / "mt5_orders.heartbeat"
    try:
        out["listener_age"] = round(time.time() - float(hb.read_text()))
    except (OSError, ValueError):
        pass
    return out


def _pid_file():
    return ma.DATA_DIR / "mt5_orders.pid"


def listener_running() -> bool:
    """Il programma dei segnali è in esecuzione se il suo battito è recente."""
    import time
    try:
        return time.time() - float((ma.DATA_DIR / "mt5_orders.heartbeat").read_text()) < 30
    except (OSError, ValueError):
        return False


def listener_start() -> int:
    """Avvia `python -m src.mt5_orders` in background (stesso Python di questa app). Output in journal/mt5_orders.log."""
    import subprocess
    import sys
    if listener_running():
        raise ValueError("L'ascolto dei segnali è già attivo.")
    log = open(ma.DATA_DIR / "mt5_orders.log", "a", encoding="utf-8")
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if os.name == "nt" else 0
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}          # il registro è UTF-8: niente errori con le emoji
    p = subprocess.Popen([sys.executable, "-u", "-m", "src.mt5_orders"], cwd=str(ma.ROOT), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags, env=env)
    _pid_file().write_text(str(p.pid))
    return p.pid


def listener_stop() -> None:
    import signal
    import subprocess
    try:
        pid = int(_pid_file().read_text())
    except (OSError, ValueError):
        raise ValueError("Non so quale programma fermare: se l'hai avviato tu dal Prompt, fermalo da lì con Ctrl+C.")
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        _pid_file().unlink()
        (ma.DATA_DIR / "mt5_orders.heartbeat").unlink()
    except OSError:
        pass


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
            if path == "/api/telegram":
                return self._json(telegram_status())
            if path == "/api/calendar":
                q = parse_qs(urlparse(self.path).query)
                month = (q.get("month") or [datetime.now().strftime("%Y-%m")])[0]
                if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
                    raise ValueError("mese non valido (formato AAAA-MM)")
                return self._json(ma.calendar_month(ma.get_account(int((q.get("account") or ["0"])[0])), month))
            m = re.fullmatch(r"/api/accounts/(\d+)/status", path)
            if m:
                return self._json(ma.snapshot(ma.get_account(int(m[1]))))
        except ValueError as e:
            return self._json({"error": str(e)}, 404)
        except Exception as e:                                      # mai lasciare la richiesta senza risposta
            return self._json({"error": f"{type(e).__name__}: {str(e)[:250]}"}, 500)
        self._send(404, b"non trovato", "text/plain")

    def _write(self, method: str):
        if not self._ok_host() or self.headers.get("X-Requested-With") != HDR:
            return self._send(403, b"richiesta non consentita", "text/plain")
        path = urlparse(self.path).path
        try:
            if path == "/api/accounts" and method == "POST":
                aid = ma.save_account(self._data())
                return self._json({"id": aid, "terminal_path": ma.get_account(aid)["terminal_path"]}, 201)
            if path == "/api/listener" and method == "POST":
                act = self._data().get("action")
                if act == "start":
                    return self._json({"started": listener_start()})
                if act == "stop":
                    listener_stop()
                    return self._json({"stopped": True})
                raise ValueError("azione non valida")
            if path == "/api/telegram/enabled" and method == "POST":
                ma.set_setting("telegram_enabled", bool(self._data().get("enabled")))
                return self._json({"enabled": bool(ma.get_setting("telegram_enabled", True))})
            if path == "/api/telegram/test" and method == "POST":
                if not ma.get_setting("telegram_enabled", True):
                    raise ValueError("Telegram è disattivato: accendi l'interruttore e riprova.")
                from src.telegram_bot import TelegramBot
                TelegramBot().send("✅ Gestione Conti: prova di collegamento a Telegram")
                return self._json({"sent": True})
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
            m = re.fullmatch(r"/api/accounts/(\d+)/enabled", path)
            if m and method == "POST":
                ma.set_enabled(int(m[1]), bool(self._data().get("enabled")))
                return self._json({"id": int(m[1])})
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
    print(f"Gestione Conti su {url}  (Ctrl+C per chiudere)\nArchivio: {ma.DB_PATH}", flush=True)
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nChiuso.")


if __name__ == "__main__":
    main()
