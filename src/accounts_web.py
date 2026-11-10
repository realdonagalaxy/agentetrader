"""Gestione Conti: gestione e monitoraggio dei conti MetaTrader 5 come applicazione web LOCALE (127.0.0.1, solo questo computer).

Avvio:  python -m src.accounts_web        (si apre il browser, di solito su http://127.0.0.1:8080)
Funzioni: aggiungi / modifica / elimina conti; vedi saldo, equity, profitto aperto e posizioni di ciascun conto; chiudi singole posizioni o tutte (solo conti DEMO).
I conti abilitati con "Usa per i segnali" sono quelli su cui `python -m src.mt5_orders` apre le operazioni ricevute da Telegram (lotti per conto).
Su un conto REALE l'app legge soltanto: nessun ordine live senza una tua conferma esplicita (regola del progetto).
Prova senza MT5:  set MT5_SIMULATOR=1  (conti e prezzi finti, solo per vedere l'interfaccia).
"""
import argparse
import hmac
import ipaddress
import secrets
import socket
import time
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


NET_MODE = False            # True: ascolta sulla rete (cellulare) e chiede il PIN a chi non è sul PC; si attiva con GC_RETE=1 e GC_PIN in config.env
PIN = ""
SESSIONS: dict[str, float] = {}      # token di sessione -> scadenza
FAILS: dict[str, tuple[int, float]] = {}     # indirizzo -> (tentativi errati, bloccato fino a)
LOGIN_HTML = """<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Gestione Conti</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0e1621;color:#e6ebf2;font:16px system-ui,-apple-system,Segoe UI,sans-serif;padding:16px}
form{background:#141e2b;border:1px solid #263548;border-radius:10px;padding:24px;width:min(340px,100%);display:grid;gap:14px}h1{font-size:18px;margin:0}
input{font:inherit;padding:12px;border-radius:6px;border:1px solid #263548;background:#0e1621;color:inherit;width:100%;box-sizing:border-box}
button{font:inherit;font-weight:600;padding:12px;border:0;border-radius:6px;background:#7aa3d6;color:#0b1420;cursor:pointer}#m{color:#e57f78;font-size:14px;min-height:18px}</style></head>
<body><form id="f"><h1>Gestione Conti</h1><input id="p" type="password" inputmode="numeric" autocomplete="current-password" placeholder="PIN" autofocus><button>Entra</button><div id="m"></div></form>
<script>document.getElementById("f").onsubmit=async e=>{e.preventDefault();const m=document.getElementById("m");m.textContent="";
const r=await fetch("/login",{method:"POST",headers:{"Content-Type":"application/json","X-Requested-With":"accounts"},body:JSON.stringify({pin:document.getElementById("p").value})});
if(r.ok)location.reload();else{const j=await r.json().catch(()=>({}));m.textContent=j.error||"PIN errato";}};</script></body></html>"""
PORTE = [8080] + list(range(47951, 47981))      # si prova prima la 8080; se è occupata, le successive


class Server(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if os.name == "nt":                                           # su Windows senza questo ci si potrebbe sovrapporre a un'altra app già in ascolto sulla stessa porta
            import socket
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


_LAST_REQ = 0.0


def _read_csv(name: str) -> list[dict]:
    import csv
    f = ma.DATA_DIR / name
    try:
        with f.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def day_range(date: str, tz_min: int):
    """Intervallo UTC (epoch) del giorno locale dell'utente: tz_min = JS getTimezoneOffset() (minuti, positivo a ovest di UTC)."""
    from datetime import datetime, timedelta, timezone
    d0 = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(minutes=tz_min)
    return d0, d0 + timedelta(days=1)


def _closures_from_mt5(needed: dict) -> dict:
    """Stato reale delle posizioni aperte dall'app, letto dalla cronologia di MT5: needed = {login: [ticket,...]} -> {(login, ticket): {"chiusura": "tp"|"sl"|"altra", "pips": float} oppure {} se ancora aperta}.
    Le posizioni già chiuse restano in una cache (journal/chiusure_cache.json) per non ricollegarsi a MT5 ogni volta. Un conto che non si collega viene saltato."""
    cache_f = ma.DATA_DIR / "chiusure_cache.json"
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    out, changed = {}, False
    by_login = {str(a["login"]): a for a in ma.list_accounts()}
    for lg, tickets in needed.items():
        todo = [t for t in tickets if f"{lg}:{t}" not in cache]
        for t in tickets:
            if f"{lg}:{t}" in cache:
                out[(lg, t)] = cache[f"{lg}:{t}"]
        if not todo or lg not in by_login:
            continue
        try:
            with ma.session(by_login[lg]) as m:
                for t in todo:
                    deals = m.history_deals_get(position=int(t)) or []
                    op = [d for d in deals if d.entry == m.DEAL_ENTRY_IN]
                    cl = [d for d in deals if d.entry == m.DEAL_ENTRY_OUT]
                    if not cl:
                        out[(lg, t)] = {}                                          # ancora aperta (o non trovata)
                        continue
                    d, o = cl[-1], (op[0] if op else None)
                    reason = "tp" if d.reason == m.DEAL_REASON_TP else "sl" if d.reason == m.DEAL_REASON_SL else "altra"
                    pip = 0.10 if str(d.symbol).upper().startswith(("XAU", "GOLD")) else 10 * ((m.symbol_info(d.symbol).point) if m.symbol_info(d.symbol) else 0.00001)
                    sign = 1 if (o is not None and o.type == 0) else -1      # DEAL_TYPE_BUY = 0
                    pips_ = round(sign * (d.price - o.price) / pip, 1) if o is not None else 0.0
                    res = {"chiusura": reason, "pips": pips_, "profitto": round(float(d.profit), 2)}
                    out[(lg, t)] = res
                    cache[f"{lg}:{t}"] = res
                    changed = True
        except Exception as e:                                                      # conto non collegato: le sue posizioni restano «non verificate»
            print("Cronologia MT5", lg, str(e)[:120], flush=True)
            for t in todo:
                out[(lg, t)] = {"errore": str(e)[:80]}
    if changed:
        try:
            cache_f.write_text(json.dumps(cache), encoding="utf-8")
        except OSError:
            pass
    return out


def signals_day(date: str, tz_min: int) -> dict:
    """Segnali del canale in un giorno (canale_segnali.csv) e cosa ha fatto l'app per ciascuno e per ogni conto: aperto / rifiutato (motivo) / chiuso a TP o SL (segnali_esiti.csv, segnali_chiusure.csv)."""
    from datetime import datetime, timezone
    d0, d1 = day_range(date, tz_min)
    accs = {str(a["login"]): a for a in ma.list_accounts() if a.get("use_signals")}
    by_id = {a["id"]: str(a["login"]) for a in ma.list_accounts()}
    sigs = {}
    for r in _read_csv("canale_segnali.csv"):                                  # un messaggio può comparire due volte (creato e poi modificato): vale l'ultima riga
        try:
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if d0 <= t < d1:
            sigs[r["msg_id"]] = {**r, "t": t.isoformat()}
    esiti, chius = {}, {}
    for r in _read_csv("segnali_esiti.csv"):
        if r.get("esito") != "prova":
            esiti.setdefault(r["msg_id"], {})[r["conto"]] = r                  # per ogni conto vale l'ultimo esito
    for r in _read_csv("segnali_chiusure.csv"):
        lg = by_id.get(int(r["conto_id"])) if str(r.get("conto_id", "")).isdigit() else None
        if lg:
            chius.setdefault(r["msg_id"], {}).setdefault(lg, []).append(r)
    needed = {}                                                                 # posizioni aperte dall'app per i segnali del giorno: se ne legge lo stato vero da MT5
    for mid in sigs:
        for lg, e in esiti.get(mid, {}).items():
            if e.get("esito") == "aperto" and e.get("ticket"):
                needed.setdefault(lg, []).append(str(e["ticket"]).split(",")[0].strip())
    real = _closures_from_mt5(needed) if needed else {}
    rows = []
    for mid, g in sorted(sigs.items(), key=lambda kv: kv[1]["t"]):
        per = {}
        for lg, a in accs.items():
            e = esiti.get(mid, {}).get(lg)
            c = {"target": a.get("tp_target") or 1}
            if e is None:
                c["stato"] = "nessuno"
            else:
                c["stato"] = e["esito"]
                c["dettaglio"] = (e.get("dettaglio") or "").split("Non apro:")[-1].strip()[:140]
                if e["esito"] == "aperto":
                    c["prezzo"] = e.get("prezzo_apertura")
                    rr = real.get((lg, str(e.get("ticket") or "").split(",")[0].strip())) or {}
                    cl = chius.get(mid, {}).get(lg) or []
                    if rr.get("chiusura"):                                          # cronologia di MT5: la fonte più affidabile
                        c["chiusura"], c["pips"] = rr["chiusura"], rr["pips"]
                    elif cl:
                        c["chiusura"] = cl[-1]["esito"]
                        c["pips"] = sum(float(x["pips"] or 0) for x in cl)
                    elif rr.get("errore"):
                        c["non_verificata"] = True
            per[lg] = c
        n_open = sum(1 for c in per.values() if c["stato"] in ("aperto", "stop"))
        rows.append({"id": mid, "t": g["t"], "side": g.get("side") or "", "symbol": g.get("symbol") or "", "entry": g.get("entry"), "sl": g.get("sl"),
                     "tp1": g.get("tp1"), "tp2": g.get("tp2"), "tp3": g.get("tp3"), "errore": g.get("errore") or "", "conti": per, "aperti": n_open})
    return {"date": date, "conti": [{"login": lg, "target": a.get("tp_target") or 1} for lg, a in accs.items()], "segnali": rows}


def telegram_status() -> dict:
    """Stato dell'ascolto dei segnali: il battito del programma (listener_age = secondi dall'ultimo controllo, None se mai partito)."""
    import time
    import json
    out = {"listener_age": None, "channel": {"state": "non_configurato"}}
    if os.environ.get("TELEGRAM_CANALE", "").strip():
        out["channel"] = {"state": "in_attesa", "name": os.environ["TELEGRAM_CANALE"].strip()}
        try:
            c = json.loads((ma.DATA_DIR / "canale_stato.json").read_text(encoding="utf-8"))
            out["channel"] = {"state": c.get("state") or "in_attesa", "name": c.get("title") or out["channel"]["name"], "detail": c.get("detail") or "",
                              "ts_age": round(time.time() - float(c.get("ts") or 0)), "last_msg_age": round(time.time() - float(c["last_msg"])) if c.get("last_msg") else None}
        except (OSError, ValueError):
            pass
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

    def _host_ok(self, h: str | None) -> bool:
        if not h:
            return False
        h = h.lower()
        if h in ("127.0.0.1", "localhost", "::1"):
            return True
        if not NET_MODE:
            return False
        try:
            return not ipaddress.ip_address(h).is_global                 # indirizzi di rete locale, anche quelli di Tailscale (100.x); mai un indirizzo pubblico
        except ValueError:
            me = socket.gethostname().lower()
            return h in (me, me + ".local")

    def _ok_host(self) -> bool:
        host = urlparse("//" + (self.headers.get("Host") or "")).hostname
        origin = self.headers.get("Origin")
        return self._host_ok(host) and (not origin or self._host_ok(urlparse(origin).hostname))

    def _authed(self) -> bool:
        if not NET_MODE or self.client_address[0] in ("127.0.0.1", "::1"):
            return True                                                    # dal PC non serve il PIN
        tok = ""
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "gc_session":
                tok = v
        exp = SESSIONS.get(tok)
        return bool(exp and exp > time.time())

    def _login(self):
        ip = self.client_address[0]
        n, until = FAILS.get(ip, (0, 0.0))
        if until > time.time():
            return self._json({"error": f"Troppi tentativi: riprova tra {int(until - time.time())} secondi."}, 429)
        try:
            pin = str(self._data().get("pin") or "")
        except (ValueError, json.JSONDecodeError):
            pin = ""
        if pin and hmac.compare_digest(pin.encode(), PIN.encode()):
            FAILS.pop(ip, None)
            tok = secrets.token_urlsafe(32)
            SESSIONS[tok] = time.time() + 30 * 86400
            return self._send(200, b'{"ok": true}', headers={"Set-Cookie": f"gc_session={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age={30 * 86400}"})
        n += 1
        FAILS[ip] = (n, time.time() + 120 if n >= 5 else 0.0)
        if n >= 5:
            FAILS[ip] = (0, time.time() + 120)
        return self._json({"error": "PIN errato"}, 401)

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8", headers: dict | None = None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
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
        if not self._authed():
            if path in ("/", "/index.html"):
                return self._send(200, LOGIN_HTML.encode(), "text/html; charset=utf-8")
            return self._json({"error": "accesso richiesto"}, 401)
        if path in ("/", "/index.html"):
            return self._send(200, (WEB / "accounts.html").read_bytes(), "text/html; charset=utf-8")
        try:
            if path == "/api/accounts":
                return self._json({"accounts": ma.list_accounts(), "simulator": os.environ.get("MT5_SIMULATOR") == "1"})
            if path == "/api/telegram":
                return self._json(telegram_status())
            if path == "/api/signals-day":
                q = parse_qs(urlparse(self.path).query)
                return self._json(signals_day((q.get("date") or [datetime.now().strftime("%Y-%m-%d")])[0], int((q.get("tz") or ["0"])[0])))
            if path == "/api/signals-sync-info":
                try:
                    return self._json(json.loads((ma.DATA_DIR / "giorno_info.json").read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    return self._json({})
            if path == "/api/last-signal":
                try:
                    return self._json(json.loads((ma.DATA_DIR / "ultimo_segnale_info.json").read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    return self._json({})
            if path == "/api/day":
                q = parse_qs(urlparse(self.path).query)
                day = (q.get("date") or [""])[0]
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                    raise ValueError("data non valida (formato AAAA-MM-GG)")
                return self._json(ma.day_trades(ma.get_account(int((q.get("account") or ["0"])[0])), day))
            if path == "/api/chart":
                q = parse_qs(urlparse(self.path).query)
                png = ma.trade_chart_png(ma.get_account(int((q.get("account") or ["0"])[0])), int((q.get("position") or ["0"])[0]), int((q.get("deal") or ["0"])[0]))
                return self._send(200, png, "image/png")
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
        if NET_MODE and path == "/login" and method == "POST":
            return self._login()
        if not self._authed():
            return self._json({"error": "accesso richiesto"}, 401)
        try:
            if path == "/api/accounts" and method == "POST":
                aid = ma.save_account(self._data())
                return self._json({"id": aid, "terminal_path": ma.get_account(aid)["terminal_path"]}, 201)
            if path == "/api/signals-sync" and method == "POST":                   # «Scarica dal canale»: il programma dei segnali registra tutti i segnali di quel giorno (senza eseguirli)
                d = self._data()
                d0, d1 = day_range(str(d.get("date")), int(d.get("tz") or 0))
                if not listener_running():
                    raise ValueError("L'ascolto dei segnali non è attivo: avvialo e riprova.")
                try:
                    (ma.DATA_DIR / "giorno_info.json").unlink()
                except OSError:
                    pass
                (ma.DATA_DIR / "richiesta_giorno.json").write_text(json.dumps({"start": d0.timestamp(), "end": d1.timestamp()}), encoding="utf-8")
                return self._json({"requested": True})
            if path == "/api/last-signal" and method == "POST":                    # «Apri l'ultimo segnale»: il programma dei segnali lo cerca nel canale e lo applica ai conti
                global _LAST_REQ
                if not listener_running():
                    raise ValueError("L'ascolto dei segnali non è attivo: avvialo e riprova.")
                if time.time() - _LAST_REQ < 20:
                    raise ValueError("Richiesta già inviata pochi secondi fa: aspetta l'esito prima di ripetere.")
                _LAST_REQ = time.time()
                try:
                    (ma.DATA_DIR / "ultimo_segnale_info.json").unlink()
                except OSError:
                    pass
                (ma.DATA_DIR / "richiesta_ultimo.flag").write_text(str(time.time()), encoding="utf-8")
                return self._json({"requested": True})
            if path == "/api/listener" and method == "POST":
                act = self._data().get("action")
                if act == "start":
                    return self._json({"started": listener_start()})
                if act == "stop":
                    listener_stop()
                    return self._json({"stopped": True})
                raise ValueError("azione non valida")
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
    ap.add_argument("--port", type=int, help="porta da provare per prima (predefinita 8080; se occupata si usano le successive)")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv("config.env")
    except ImportError:
        pass
    global NET_MODE, PIN
    NET_MODE, PIN = os.environ.get("GC_RETE") == "1", os.environ.get("GC_PIN", "")
    if NET_MODE and len(PIN) < 6:
        sys.exit("Accesso da rete attivo (GC_RETE=1) ma manca un PIN sicuro: scrivi in config.env una riga  GC_PIN=...  di almeno 6 caratteri.")
    host = "0.0.0.0" if NET_MODE else "127.0.0.1"
    srv = None
    for port in ([a.port] if a.port else []) + [x for x in PORTE if x != a.port]:
        try:
            srv = Server((host, port), Handler)
            break
        except OSError:
            print(f"Porta {port} occupata, provo la successiva…")
    if srv is None:
        sys.exit("Nessuna porta libera: usa --port con un altro numero.")
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}"
    print(f"Gestione Conti su {url}  (Ctrl+C per chiudere)\nArchivio: {ma.DB_PATH}", flush=True)
    if NET_MODE:
        ips = set()
        try:
            ips |= {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
                u.connect(("10.255.255.255", 1))
                ips.add(u.getsockname()[0])
        except OSError:
            pass
        print("Accesso da cellulare ATTIVO (serve il PIN). Dalla stessa rete Wi-Fi apri uno di questi indirizzi:")
        for ip in sorted(i for i in ips if not i.startswith("127.")):
            print(f"   http://{ip}:{port}")
    if os.environ.get("AVVIO_ASCOLTO", "1").strip().lower() not in ("0", "no", "off", "false"):    # insieme al server parte anche l'ascolto dei segnali (AVVIO_ASCOLTO=0 in config.env lo disattiva)
        try:
            print(f"Ascolto segnali avviato (pid {listener_start()}). Registro: {ma.DATA_DIR / 'mt5_orders.log'}", flush=True)
        except ValueError as e:
            print(str(e), flush=True)
        except Exception as e:
            print("Ascolto segnali non avviato:", str(e)[:200], flush=True)
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nChiuso.")


if __name__ == "__main__":
    main()
