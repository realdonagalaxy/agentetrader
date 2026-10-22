"""Journal dei trade come applicazione web LOCALE (solo sul tuo computer, indirizzo 127.0.0.1).

Avvio:  python3 -m src.journal_web            (il browser si apre da solo, di solito su http://127.0.0.1:8791; se la porta è occupata usa la successiva e la stampa)
Dati:   journal/journal.db (SQLite) e journal/images/ (screenshot). Nessun dato lascia il computer, tranne la lettura opzionale
        dello screenshot: se in config.env c'è ANTHROPIC_API_KEY, il pulsante "Leggi dallo screenshot" invia quell'immagine all'API di Anthropic.
Import: esporta il tab J-26 del foglio Google in CSV (File > Scarica > CSV) e caricalo dalla pagina ("Importa dal foglio").
Solo libreria standard di Python: nessuna installazione extra (python-dotenv, se presente, serve solo a leggere config.env).
Questa app NON invia ordini e non si collega a nessun broker.
"""
import argparse
import base64
import csv
import io
import json
import mimetypes
import os
import re
import sqlite3
import sys
import threading
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("JOURNAL_DIR", ROOT / "journal"))          # JOURNAL_DIR permette di tenere i dati altrove (utile anche per le prove)
DB_PATH = DATA_DIR / "journal.db"
IMG_DIR = DATA_DIR / "images"
WEB = Path(__file__).resolve().parent / "web"
MAX_BODY = 25 * 1024 * 1024

# colonne del foglio J-26 (posizione A..AI) -> campo del database
CONF_COLS = {4: "MACRO", 5: "FAVORE BIAS", 6: "REVERSAL ZONE", 7: "SWEEP LIQUIDITÀ", 8: "VWAP", 10: "SL STRUTTURALE", 11: "VOLUME TICK",
             12: "DIVERGENZA MACD", 13: "CHOCH M1 + MITIGAZIONE OB", 14: "MOVE-to-BE", 15: "Deep Mitigation 1", 16: "Deep Mitigation 2"}
FIELDS = ["asset", "date", "time", "side", "entry", "sl", "tp", "sl_pips", "rr_plan", "rr_final", "result", "r", "poi", "conf", "setup_ok", "entry_ok",
          "mgmt_ok", "emotions", "discipline", "context", "notes", "alert_id", "images", "links"]
SCHEMA = """CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, asset TEXT, date TEXT, time TEXT, side TEXT, entry REAL, sl REAL, tp REAL, sl_pips REAL,
  rr_plan TEXT, rr_final TEXT, result TEXT DEFAULT 'OPEN', r REAL, poi TEXT, conf TEXT DEFAULT '[]', setup_ok TEXT, entry_ok TEXT, mgmt_ok TEXT,
  emotions TEXT, discipline REAL, context TEXT, notes TEXT, alert_id TEXT, images TEXT DEFAULT '[]', links TEXT DEFAULT '[]', created_at TEXT)"""


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


def num(v):
    """Numero da testo con virgola o punto; None se vuoto/non valido."""
    if v is None:
        return None
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def iso_date(v: str) -> str | None:
    v = (v or "").strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
    if m:
        return f"{int(m[3]):04d}-{int(m[2]):02d}-{int(m[1]):02d}"
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
    return f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None


def result_kind(v: str) -> str:
    s = (v or "").lower()
    if "take" in s or s.strip() == "tp":
        return "TP"
    if "stop" in s or s.strip() == "sl":
        return "SL"
    if "break" in s or s.strip() in ("be", "pareggio"):
        return "BE"
    return "OPEN"


def rr_value(s) -> float | None:
    """'1:4' o '1:2.5' -> 4 / 2.5; numero semplice -> numero."""
    s = str(s or "").strip()
    m = re.fullmatch(r"1\s*:\s*([\d.,]+)", s)
    return num(m[1]) if m else num(s)


def compute_r(t: dict) -> float | None:
    """Stessa logica del foglio: TP = R:R finale (se c'è) altrimenti R:R pianificato; SL = -1; BE = 0; aperto = nessun risultato."""
    res = t.get("result")
    if res == "SL":
        return -1.0
    if res == "BE":
        return 0.0
    if res == "TP":
        return rr_value(t.get("rr_final")) or rr_value(t.get("rr_plan"))
    return None


def discipline(t: dict) -> float | None:
    answers = [t.get(k) for k in ("setup_ok", "entry_ok", "mgmt_ok") if t.get(k) in ("SI", "NO")]
    return round(100 * answers.count("SI") / len(answers)) if answers else None


def clean(d: dict) -> dict:
    """Normalizza un trade in arrivo dalla pagina (solo campi noti, tipi corretti)."""
    t = {k: d.get(k) for k in FIELDS}
    t["asset"] = str(t["asset"] or "").strip().upper()
    t["side"] = str(t["side"] or "").strip().upper()
    t["side"] = t["side"] if t["side"] in ("BUY", "SELL") else ""
    t["date"] = iso_date(t["date"]) or (t["date"] or "")
    t["time"] = str(t["time"] or "").strip()
    for k in ("entry", "sl", "tp", "sl_pips", "r", "discipline"):
        t[k] = num(t[k])
    t["result"] = result_kind(str(t["result"] or ""))
    for k in ("rr_plan", "rr_final", "poi", "emotions", "context", "notes", "alert_id"):
        t[k] = str(t[k] or "").strip()
    for k in ("rr_plan", "rr_final"):
        if re.fullmatch(r"[\d.,]+", t[k]):
            t[k] = "1:" + t[k].replace(",", ".")
    for k in ("setup_ok", "entry_ok", "mgmt_ok"):
        t[k] = t[k] if t[k] in ("SI", "NO") else ""
    for k in ("conf", "images", "links"):
        v = t[k] if isinstance(t[k], list) else []
        t[k] = json.dumps([str(x) for x in v], ensure_ascii=False)
    if t["sl_pips"] is None and t["entry"] and t["sl"]:
        pip = 0.1 if t["asset"].startswith(("XAU", "GOLD")) else 0.01 if "JPY" in t["asset"] else 0.0001
        t["sl_pips"] = round(abs(t["entry"] - t["sl"]) / pip, 1)
    if not t["rr_plan"] and t["entry"] and t["sl"] and t["tp"] and abs(t["entry"] - t["sl"]) > 0:
        t["rr_plan"] = f"1:{abs(t['tp'] - t['entry']) / abs(t['entry'] - t['sl']):.1f}"
    if t["r"] is None:
        t["r"] = compute_r(t)
    if t["discipline"] is None:
        t["discipline"] = discipline(t)
    return t


def row_out(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in ("conf", "images", "links"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except ValueError:
            d[k] = []
    return d


def save_trade(con, t: dict, tid: int | None = None) -> int:
    cols = FIELDS
    if tid is None:
        cur = con.execute(f"INSERT INTO trades ({','.join(cols)}, created_at) VALUES ({','.join('?' * len(cols))}, ?)",
                          [t[c] for c in cols] + [datetime.now().isoformat(timespec="seconds")])
        con.commit()
        return cur.lastrowid
    con.execute(f"UPDATE trades SET {','.join(c + '=?' for c in cols)} WHERE id=?", [t[c] for c in cols] + [tid])
    con.commit()
    return tid


def import_csv(text: str) -> dict:
    """Importa il CSV esportato dal tab J-26 (colonne A..AI come nel foglio). Salta le righe già presenti (stessa data, ora, asset, entry/SL/R)."""
    rows = list(csv.reader(io.StringIO(text)))
    start = next((i for i, r in enumerate(rows) if r and r[0].strip().upper() == "ASSET"), None)
    if start is None:
        raise ValueError("Non trovo la riga di intestazione (la colonna A deve chiamarsi ASSET): è il CSV del tab J-26?")
    con = db()
    seen = {(r["date"], r["time"], r["asset"], r["notes"]) for r in con.execute("SELECT date,time,asset,notes FROM trades")}
    added = skipped = bad = 0
    for r in rows[start + 1:]:
        r = r + [""] * (35 - len(r))
        if not r[0].strip():
            continue
        d = iso_date(r[1])
        if not d:
            bad += 1
            continue
        links = [x for x in (r[27], r[28], r[29]) if x.startswith("http")]
        t = clean({"asset": r[0], "date": d, "time": r[3].strip(), "side": r[31], "sl_pips": r[17], "rr_plan": r[18], "rr_final": r[19],
                   "result": r[25], "r": r[33], "poi": r[9], "conf": [n for c, n in CONF_COLS.items() if r[c].strip().upper() == "TRUE"],
                   "setup_ok": r[20].strip().upper(), "entry_ok": r[21].strip().upper(), "mgmt_ok": r[22].strip().upper(), "emotions": r[24],
                   "discipline": r[23], "context": r[34], "notes": r[30], "alert_id": r[32], "links": links})
        key = (t["date"], t["time"], t["asset"], t["notes"])
        if key in seen:
            skipped += 1
            continue
        save_trade(con, t)
        seen.add(key)
        added += 1
    con.close()
    return {"added": added, "skipped": skipped, "bad": bad}


def export_csv() -> str:
    con = db()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "asset", "data", "ora", "direzione", "entry", "sl", "tp", "sl_pips", "rr", "rr_finale", "esito", "R", "poi", "confluenze", "setup",
                "entry_ok", "managment", "disciplina", "contesto", "note", "id_avviso"])
    for r in con.execute("SELECT * FROM trades ORDER BY date, time, id"):
        d = row_out(r)
        w.writerow([d["id"], d["asset"], d["date"], d["time"], d["side"], d["entry"], d["sl"], d["tp"], d["sl_pips"], d["rr_plan"], d["rr_final"], d["result"],
                    d["r"], d["poi"], "; ".join(d["conf"]), d["setup_ok"], d["entry_ok"], d["mgmt_ok"], d["discipline"], d["context"], d["notes"], d["alert_id"]])
    con.close()
    return out.getvalue()


def save_image(data_url: str) -> str:
    m = re.fullmatch(r"data:(image/(png|jpeg|webp|gif));base64,(.+)", data_url or "", re.S)
    if not m:
        raise ValueError("immagine non valida")
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now():%Y%m%d_%H%M%S}_{os.urandom(3).hex()}.{'jpg' if m[2] == 'jpeg' else m[2]}"
    (IMG_DIR / name).write_bytes(base64.b64decode(m[3]))
    return name


def api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    env = ROOT / "config.env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'') or None
    return None


EXTRACT_PROMPT = ("Questo è lo screenshot di un trade su una piattaforma di trading. Rispondi SOLO con un oggetto JSON con le chiavi: asset (es. XAUUSD), "
                  "side (BUY o SELL), date (gg/mm/aaaa se visibile), time (HH:MM di apertura, ora italiana se indicata), entry, sl, tp (numeri), "
                  "result (Take Profit, Stop Loss, Break Even solo se il trade è chiuso e si vede, altrimenti null), notes (breve nota: timeframe, struttura). "
                  "Usa null per ogni valore che non vedi con certezza: non inventare nulla.")


def extract_from_image(data_url: str) -> dict:
    key = api_key()
    if not key:
        raise PermissionError("Manca ANTHROPIC_API_KEY in config.env: la lettura automatica dello screenshot è disattivata.")
    m = re.fullmatch(r"data:(image/(?:png|jpeg|webp|gif));base64,(.+)", data_url or "", re.S)
    if not m:
        raise ValueError("immagine non valida")
    body = json.dumps({"model": os.environ.get("JOURNAL_MODEL", "claude-sonnet-5-5"), "max_tokens": 600, "messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": m[1], "data": m[2]}}, {"type": "text", "text": EXTRACT_PROMPT}]}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        out = json.load(resp)
    text = "".join(b.get("text", "") for b in out.get("content", []))
    j = re.search(r"\{.*\}", text, re.S)
    return json.loads(j.group(0)) if j else {}


class Handler(BaseHTTPRequestHandler):
    server_version = "JournalWeb/1.0"

    def log_message(self, fmt, *args):          # niente log verbosi (e mai chiavi nei log)
        pass

    def _ok_host(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        return host in ("127.0.0.1", "localhost") and (not origin or urlparse(origin).hostname in ("127.0.0.1", "localhost"))

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8", extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("richiesta troppo grande")
        return self.rfile.read(n)

    def do_GET(self):
        if not self._ok_host():
            return self._send(403, b"host non consentito", "text/plain")
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, (WEB / "journal.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/trades":
            con = db()
            rows = [row_out(r) for r in con.execute("SELECT * FROM trades ORDER BY date DESC, time DESC, id DESC")]
            con.close()
            return self._json({"trades": rows, "extract": bool(api_key())})
        if path == "/api/export":
            return self._send(200, export_csv().encode(), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="journal_trade.csv"'})
        m = re.fullmatch(r"/img/([\w.\-]+)", path)
        if m and (IMG_DIR / m[1]).is_file():
            return self._send(200, (IMG_DIR / m[1]).read_bytes(), mimetypes.guess_type(m[1])[0] or "application/octet-stream")
        self._send(404, b"non trovato", "text/plain")

    def _write(self, method: str):
        if not self._ok_host():
            return self._send(403, b"host non consentito", "text/plain")
        path = urlparse(self.path).path
        try:
            if path == "/api/trades" and method == "POST":
                con = db()
                tid = save_trade(con, clean(json.loads(self._body())))
                con.close()
                return self._json({"id": tid}, 201)
            m = re.fullmatch(r"/api/trades/(\d+)", path)
            if m and method == "PUT":
                con = db()
                save_trade(con, clean(json.loads(self._body())), int(m[1]))
                con.close()
                return self._json({"id": int(m[1])})
            if m and method == "DELETE":
                con = db()
                con.execute("DELETE FROM trades WHERE id=?", (int(m[1]),))
                con.commit()
                con.close()
                return self._json({"deleted": int(m[1])})
            if path == "/api/image" and method == "POST":
                return self._json({"name": save_image(json.loads(self._body()).get("data"))})
            if path == "/api/extract" and method == "POST":
                return self._json(extract_from_image(json.loads(self._body()).get("data")))
            if path == "/api/import" and method == "POST":
                return self._json(import_csv(self._body().decode("utf-8-sig")))
        except PermissionError as e:
            return self._json({"error": str(e)}, 400)
        except (ValueError, json.JSONDecodeError) as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:                                  # errore di rete verso l'API, ecc.: messaggio leggibile, mai la chiave
            return self._json({"error": f"{type(e).__name__}: {str(e)[:200]}"}, 500)
        self._send(404, b"non trovato", "text/plain")

    do_POST = lambda self: self._write("POST")
    do_PUT = lambda self: self._write("PUT")
    do_DELETE = lambda self: self._write("DELETE")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8791, help="porta di partenza (se occupata prova le successive)")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    srv = None
    for port in range(a.port, a.port + 30):                         # porta occupata da un'altra app: provo la successiva
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)    # solo questo computer
            break
        except OSError:
            print(f"Porta {port} occupata, provo la successiva…")
    if srv is None:
        sys.exit(f"Nessuna porta libera tra {a.port} e {a.port + 29}: usa --port con un altro numero.")
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"Journal in esecuzione su {url}  (Ctrl+C per chiudere)\nDati: {DB_PATH}")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nChiuso.")


if __name__ == "__main__":
    main()
