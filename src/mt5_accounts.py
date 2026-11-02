"""Archivio dei conti MetaTrader 5 e operazioni su di essi (lettura, chiusura posizioni, esecuzione dei segnali).

Dati: journal/conti_mt5.db (SQLite, solo sul tuo computer). Le PASSWORD non finiscono nel database né in file del progetto: stanno nel Gestore credenziali
di Windows tramite la libreria `keyring` (pip install keyring). Senza password salvata il terminale deve essere già collegato a quel conto.
MT5 collega un terminale a UN conto alla volta: ogni operazione (session) prende un blocco valido anche tra processi diversi, si collega, VERIFICA che il login
sia quello giusto, opera e si scollega. Con più conti conviene un terminale MT5 separato per ciascuno (campo "Percorso terminale").
Trading solo su conti DEMO: su un conto reale il software legge e basta (regola del progetto: nessun ordine live senza conferma esplicita).
"""
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("JOURNAL_DIR", ROOT / "journal"))
DB_PATH = DATA_DIR / "conti_mt5.db"
SERVICE = "agentetrader-mt5"
MAX_LOTS = 1.0
MAGIC = 530001
SCHEMA = """CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, login INTEGER NOT NULL, server TEXT NOT NULL, terminal_path TEXT DEFAULT '',
  lots REAL DEFAULT 0.05, enabled INTEGER DEFAULT 1, use_signals INTEGER DEFAULT 1, note TEXT DEFAULT '', created_at TEXT)"""
_thread_lock = threading.RLock()


SETTINGS_PATH = DATA_DIR / "impostazioni.json"


def get_setting(key: str, default=None):
    """Impostazioni semplici dell'app (journal/impostazioni.json), condivise con il programma dei segnali."""
    import json
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8")).get(key, default)
    except (OSError, ValueError):
        return default


def set_setting(key: str, value) -> None:
    import json
    try:
        d = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d[key] = value
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(d), encoding="utf-8")


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    try:
        con.execute("ALTER TABLE accounts ADD COLUMN kind TEXT DEFAULT ''")      # 'demo' / 'real' / '' (non ancora letto)
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE accounts ADD COLUMN broker TEXT DEFAULT ''")    # nome del broker / prop firm come lo comunica MT5 (account_info.company)
    except sqlite3.OperationalError:
        pass
    return con


# ---------- password (Gestore credenziali di Windows) ----------
def _keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def get_password(acc: dict) -> str | None:
    if os.environ.get("MT5_SIMULATOR") == "1":
        return None
    kr = _keyring()
    try:
        return kr.get_password(SERVICE, f"{acc['login']}@{acc['server']}") if kr else None
    except Exception:
        return None


def set_password(login: int, server: str, password: str) -> None:
    if os.environ.get("MT5_SIMULATOR") == "1":
        return                                                        # il simulatore non usa il Gestore credenziali
    kr = _keyring()
    if kr is None:
        raise ValueError("Per salvare la password serve la libreria keyring: esegui  .venv\\Scripts\\pip install keyring  e riprova (oppure lascia vuota la password e tieni il terminale già collegato).")
    kr.set_password(SERVICE, f"{login}@{server}", password)


def del_password(login: int, server: str) -> None:
    kr = _keyring()
    try:
        if kr:
            kr.delete_password(SERVICE, f"{login}@{server}")
    except Exception:
        pass


# ---------- archivio ----------
def _pm(p: str):
    """Modulo dei percorsi adatto al testo: i percorsi con backslash (Windows) si trattano come Windows anche se il programma gira altrove (prove)."""
    import ntpath
    import posixpath
    return ntpath if "\\" in p or (len(p) > 1 and p[1] == ":") else posixpath


def norm_terminal(path: str) -> str:
    """Percorso del terminale: se indichi la cartella aggiungo terminale64.exe; su Windows verifico che il file esista."""
    p = path.strip().strip('"')
    if not p:
        return ""
    if p.lower().endswith(".exe") is False:
        p = _pm(p).join(p, "terminal64.exe")
    if os.name == "nt" and os.environ.get("MT5_SIMULATOR") != "1" and not os.path.isfile(p):
        raise ValueError(f"Il file del terminale non esiste: {p}. Indica il percorso completo di terminal64.exe (tasto destro sull'icona del terminale → Proprietà → Destinazione).")
    return p[:300]


def default_terminal() -> str:
    """Il terminale MT5 originale usato da TUTTI i conti: MT5_PATH in config.env, altrimenti C:\\Program Files\\MetaTrader 5\\terminal64.exe."""
    p = os.environ.get("MT5_PATH") or r"C:\Program Files\MetaTrader 5\terminal64.exe"
    if os.name == "nt" and os.environ.get("MT5_SIMULATOR") != "1" and not os.path.isfile(p):
        raise ValueError(f"Non trovo il terminale MT5: {p}. Se è installato altrove, scrivi in config.env la riga  MT5_PATH=percorso completo di terminal64.exe")
    return p


def clean(d: dict) -> dict:
    name, server = str(d.get("name") or "").strip(), str(d.get("server") or "").strip()
    try:
        login = int(str(d.get("login")).strip())
    except ValueError:
        raise ValueError("il numero di conto (login) deve essere un numero intero")
    if login <= 0:
        raise ValueError("il numero di conto (login) non è valido")
    name = name or str(login)                                        # il nome non si chiede più: se manca vale il numero di conto
    if not server:
        raise ValueError("il server del broker è obbligatorio (es. ActivTrades-Server)")
    try:
        lots = float(str(d.get("lots") or 0.05).replace(",", "."))
    except ValueError:
        raise ValueError("i lotti devono essere un numero")
    if not 0.01 <= lots <= MAX_LOTS:
        raise ValueError(f"i lotti devono stare tra 0,01 e {MAX_LOTS:g}")
    return {"name": name[:60], "login": login, "server": server[:80], "terminal_path": norm_terminal(str(d.get("terminal_path") or "")),
            "lots": round(lots, 2), "enabled": 1 if d.get("enabled", True) else 0, "use_signals": 1 if d.get("use_signals", True) else 0, "note": str(d.get("note") or "")[:300]}


def out(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["enabled"], d["use_signals"] = bool(d["enabled"]), bool(d["use_signals"])
    d["has_password"] = bool(get_password(d))
    return d


def list_accounts() -> list[dict]:
    con = db()
    rows = [out(r) for r in con.execute("SELECT * FROM accounts ORDER BY id")]
    con.close()
    return rows


def get_account(aid: int) -> dict:
    con = db()
    r = con.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
    con.close()
    if r is None:
        raise ValueError("conto non trovato")
    return out(r)


def save_account(d: dict, aid: int | None = None) -> int:
    """Registra o aggiorna un conto SOLO dopo che MT5 si è collegato davvero con questi dati (login, password, server). Se l'accesso fallisce non viene scritto nulla:
    né il record, né la password nel Gestore credenziali. Una modifica che non tocca login, server o password (lotti, nota, interruttori) non richiede l'accesso."""
    c, pw = clean(d), str(d.get("password") or "")
    con = db()
    old = None
    if aid is not None:
        old = con.execute("SELECT login, server, terminal_path FROM accounts WHERE id=?", (aid,)).fetchone()
        if old is None:
            con.close()
            raise ValueError("conto non trovato")
    dup = con.execute("SELECT id FROM accounts WHERE login=? AND server=? AND id IS NOT ?", (c["login"], c["server"], aid)).fetchone()
    con.close()
    if dup:
        raise ValueError("esiste già un conto con questo login e questo server")
    changed = old is None or bool(pw) or (old["login"], old["server"]) != (c["login"], c["server"])
    first = None
    if changed:
        if not pw:
            raise ValueError("Scrivi la password: il conto viene registrato solo dopo che MT5 si è collegato con questi dati." if old is None
                             else "Hai cambiato login o server: riscrivi anche la password, per verificare il collegamento.")
        if old is None and not c["terminal_path"]:
            c["terminal_path"] = default_terminal()                    # tutti i conti usano lo stesso MT5 originale
        first = _test_with_password(c, pw)
        if not first.get("connected"):
            raise ValueError(first.get("error") or "MT5 non si è collegato al conto: non è stato registrato nulla.")
    # da qui MT5 si è collegato: ora (e solo ora) si scrive
    if pw:
        set_password(c["login"], c["server"], pw)
    con = db()
    if old is None:
        cur = con.execute("INSERT INTO accounts (name,login,server,terminal_path,lots,enabled,use_signals,note,created_at) VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
                          (c["name"], c["login"], c["server"], c["terminal_path"], c["lots"], c["enabled"], c["use_signals"], c["note"]))
        aid = cur.lastrowid
    else:
        if (old["login"], old["server"]) != (c["login"], c["server"]):
            del_password(old["login"], old["server"])                  # la vecchia password non vale più
        con.execute("UPDATE accounts SET name=?,login=?,server=?,terminal_path=?,lots=?,enabled=?,use_signals=?,note=? WHERE id=?",
                    (c["name"], c["login"], c["server"], c["terminal_path"], c["lots"], c["enabled"], c["use_signals"], c["note"], aid))
    if first:                                                          # tipo e società li conosciamo già dal primo collegamento
        con.execute("UPDATE accounts SET kind=?, broker=COALESCE(NULLIF(?, ''), broker) WHERE id=?",
                    ("demo" if first.get("demo") else "real", first.get("company", ""), aid))
    con.commit()
    con.close()
    return aid


def set_enabled(aid: int, enabled: bool) -> None:
    """Abilita o disabilita un conto: un conto disabilitato non viene monitorato e non riceve i segnali."""
    get_account(aid)
    con = db()
    con.execute("UPDATE accounts SET enabled=? WHERE id=?", (1 if enabled else 0, aid))
    con.commit()
    con.close()


def delete_account(aid: int) -> None:
    a = get_account(aid)
    con = db()
    con.execute("DELETE FROM accounts WHERE id=?", (aid,))
    con.commit()
    con.close()
    del_password(a["login"], a["server"])


# ---------- connessione a MT5 ----------
def explain(mt5, prefix: str = "MT5 non si collega") -> str:
    """Messaggio d'errore di MT5 con la spiegazione dei casi più comuni."""
    err = mt5.last_error()
    code = err[0] if isinstance(err, tuple) and err else None
    hint = {-6: "Accesso rifiutato dal broker: login, password o NOME DEL SERVER non corrispondono. Controlla il server (identico a quello della finestra di accesso di MT5, maiuscole e spazi compresi), "
                "la password (dopo averla cambiata va risalvata in «Modifica») e che il conto sia ancora attivo.",
            -10003: "Il terminale MT5 indicato non si avvia: controlla il percorso di terminal64.exe.",
            -10005: "MT5 non risponde in tempo. Se il terminale è appena stato creato, aprilo una volta a mano dal collegamento sul Desktop (MT5 NumeroConto), chiudi eventuali finestre di accesso o di apertura conto e aspetta che sia pronto; poi chiudilo e riprova. "
                    "Controlla anche che non sia aperto «come amministratore» (programma e terminale devono avere gli stessi permessi).",
            -10004: "Nessun collegamento con il terminale: aprilo e attendi che sia pronto.",
            -2: "Parametri non validi: controlla login, password e server."}.get(code, "")
    return f"{prefix}: {err}. {hint}".strip()


def _mt5():
    if os.environ.get("MT5_SIMULATOR") == "1":
        from src import mt5_sim
        return mt5_sim
    try:
        import MetaTrader5 as mt5
    except ImportError as e:
        raise RuntimeError("Pacchetto MetaTrader5 non disponibile: funziona solo su Windows con MT5 installato.") from e
    return mt5


@contextmanager
def _file_lock(timeout: float = 40.0):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = open(DATA_DIR / "mt5.lock", "a+")
    t0 = time.time()
    while True:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() - t0 > timeout:
                f.close()
                raise RuntimeError("MT5 è occupato da un altro programma del progetto: riprova tra qualche secondo.")
            time.sleep(0.2)
    try:
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()


def _same_dir(a: str, b: str) -> bool:
    n = lambda x: _pm(x).normcase(_pm(x).normpath(x)).rstrip("\\/").lower()
    return n(a) == n(b)


def _check_terminal(mt5, acc: dict) -> None:
    """Se per il conto è indicato un terminale, verifica che sia proprio quello a cui MT5 si è collegato (altrimenti si rischia di leggere o operare sul conto sbagliato)."""
    want = acc.get("terminal_path")
    if not want:
        return
    ti = mt5.terminal_info()
    got = getattr(ti, "path", "") if ti else ""
    if got and not _same_dir(_pm(want).dirname(want), got):
        raise RuntimeError(f"Si è aperto il terminale «{got}» invece di «{_pm(want).dirname(want)}». Chiudi tutti i terminali MT5, apri solo quello giusto e riprova.")


@contextmanager
def session(acc: dict):
    """Collega MT5 al conto indicato, verifica il login e restituisce il modulo mt5; alla fine scollega. Un'operazione alla volta."""
    with _thread_lock, _file_lock():
        mt5 = _mt5()
        kw = {}
        if acc.get("terminal_path"):
            kw["path"] = acc["terminal_path"]
        pw = get_password(acc)
        if pw or os.environ.get("MT5_SIMULATOR") == "1":
            kw.update(login=int(acc["login"]), password=pw or "", server=acc["server"])
        mt5.shutdown()                                              # parte sempre da uno stato pulito: nessun collegamento rimasto da un altro conto
        kw["timeout"] = int(os.environ.get("MT5_TIMEOUT_MS") or 60000)   # un terminale appena copiato impiega di più al primo avvio
        ok = mt5.initialize(**kw)
        if not ok and mt5.last_error()[0] == -10005:                # IPC timeout: il terminale ora è avviato, un secondo tentativo di norma riesce
            mt5.shutdown()
            ok = mt5.initialize(**kw)
        if not ok:
            raise RuntimeError(explain(mt5))
        try:
            _check_terminal(mt5, acc)
            info = mt5.account_info()
            if info is None or int(info.login) != int(acc["login"]):
                got = getattr(info, "login", None)
                raise RuntimeError(f"Il terminale è collegato al conto {got}, non al {acc['login']}: salva la password del conto (o indica il suo terminale) e riprova.")
            yield mt5
        finally:
            mt5.shutdown()


def is_demo(mt5) -> bool:
    return mt5.account_info().trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO


def _pos(p) -> dict:
    return {"ticket": int(p.ticket), "symbol": p.symbol, "side": "buy" if p.type == 0 else "sell", "volume": p.volume, "open": p.price_open, "price": p.price_current,
            "sl": p.sl, "tp": p.tp, "profit": round(p.profit + getattr(p, "swap", 0.0), 2), "time": int(p.time), "magic": p.magic, "comment": p.comment}


def snapshot(acc: dict) -> dict:
    """Saldo, equity e posizioni aperte del conto. Mai eccezioni: in caso di errore {'connected': False, 'error': ...}."""
    try:
        with session(acc) as mt5:
            i = mt5.account_info()
            _remember_kind(acc["id"], is_demo(mt5), getattr(i, "company", "")) if acc.get("id") else None
            return {"connected": True, "demo": is_demo(mt5), "currency": i.currency, "balance": i.balance, "equity": i.equity, "margin": i.margin,
                    "free_margin": i.margin_free, "profit": i.profit, "leverage": i.leverage, "broker_name": i.name, "company": (getattr(i, "company", "") or "").strip(),
                    "positions": [_pos(p) for p in (mt5.positions_get() or [])], "at": int(time.time())}
    except Exception as e:
        return {"connected": False, "error": str(e)[:300]}


def _remember_kind(aid: int, demo: bool, company: str = "") -> None:
    con = db()
    con.execute("UPDATE accounts SET kind=?, broker=COALESCE(NULLIF(?, ''), broker) WHERE id=?", ("demo" if demo else "real", (company or "").strip(), aid))
    con.commit()
    con.close()


def test_connection(d: dict) -> dict:
    c = clean(d)
    acc = {**c, "password": None}
    pw = str(d.get("password") or "")
    if pw:
        return _test_with_password(c, pw)
    return snapshot(acc)


def _test_with_password(c: dict, pw: str) -> dict:
    """Prova senza salvare: collega con la password indicata."""
    try:
        with _thread_lock, _file_lock():
            mt5 = _mt5()
            kw = {"login": c["login"], "password": pw, "server": c["server"], "timeout": int(os.environ.get("MT5_TIMEOUT_MS") or 60000)}
            if c["terminal_path"]:
                kw["path"] = c["terminal_path"]
            ok = mt5.initialize(**kw)
            if not ok and mt5.last_error()[0] == -10005:
                mt5.shutdown()
                ok = mt5.initialize(**kw)
            if not ok:
                return {"connected": False, "error": explain(mt5)}
            try:
                _check_terminal(mt5, c)
                i = mt5.account_info()
                if i is None or int(i.login) != c["login"]:
                    return {"connected": False, "error": f"Collegato al conto {getattr(i, 'login', None)} invece di {c['login']}"}
                return {"connected": True, "demo": is_demo(mt5), "currency": i.currency, "balance": i.balance, "equity": i.equity, "positions": [],
                        "company": (getattr(i, "company", "") or "").strip()}
            finally:
                mt5.shutdown()
    except Exception as e:
        return {"connected": False, "error": str(e)[:300]}


def _close(mt5, p) -> str:
    tick = mt5.symbol_info_tick(p.symbol)
    buy = p.type == mt5.ORDER_TYPE_BUY
    info = mt5.symbol_info(p.symbol)
    m = info.filling_mode if info else 3
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume, "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
           "position": p.ticket, "price": tick.bid if buy else tick.ask, "deviation": 20, "magic": MAGIC, "comment": "chiusura manuale", "type_time": mt5.ORDER_TIME_GTC,
           "type_filling": mt5.ORDER_FILLING_IOC if m & 2 else mt5.ORDER_FILLING_FOK if m & 1 else mt5.ORDER_FILLING_RETURN}
    res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        raise ValueError(f"chiusura rifiutata dal broker: {getattr(res, 'retcode', None)} {getattr(res, 'comment', mt5.last_error())}")
    return f"chiusa {p.symbol} #{p.ticket} a {res.price}"


def close_positions(acc: dict, tickets: list[int] | None = None) -> list[str]:
    """Chiude le posizioni indicate (o tutte). Solo conti demo."""
    with session(acc) as mt5:
        if not is_demo(mt5):
            raise ValueError("conto REALE: il software non chiude né apre posizioni su conti reali (solo lettura)")
        pos = [p for p in (mt5.positions_get() or []) if tickets is None or int(p.ticket) in tickets]
        if not pos:
            raise ValueError("nessuna posizione da chiudere (forse è già chiusa)")
        return [_close(mt5, p) for p in pos]


def import_connected(terminal_path: str = "") -> dict:
    """Legge il conto a cui il terminale MT5 (già aperto e collegato) è connesso e lo aggiunge all'archivio, senza password.
    Conto demo: usato per i segnali con 0,05 lotti. Conto reale: aggiunto in sola lettura, NON usato per i segnali."""
    with _thread_lock, _file_lock():
        mt5 = _mt5()
        kw = {"path": terminal_path} if terminal_path else {}
        if os.environ.get("MT5_SIMULATOR") == "1":
            kw["login"] = 51234567
        if not mt5.initialize(**kw):
            raise ValueError(f"MT5 non si collega: {mt5.last_error()}. Apri il terminale e accedi al conto.")
        try:
            i = mt5.account_info()
            if i is None:
                raise ValueError("Il terminale non è collegato a nessun conto.")
            demo = i.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
            login, server = int(i.login), str(i.server)
            name = f"{(getattr(i, 'company', '') or server).split(',')[0][:30]} {'demo' if demo else 'reale'} {login}"
        finally:
            mt5.shutdown()
    con = db()
    dup = con.execute("SELECT id FROM accounts WHERE login=? AND server=?", (login, server)).fetchone()
    con.close()
    if dup:
        raise ValueError(f"Il conto {login} ({server}) è già nell'elenco.")
    aid = save_account({"name": name, "login": login, "server": server, "terminal_path": terminal_path, "lots": 0.05, "enabled": True, "use_signals": demo,
                        "note": "importato dal terminale MT5"})
    _remember_kind(aid, demo, getattr(i, "company", ""))
    return {"id": aid, "name": name, "login": login, "server": server, "demo": demo}


if __name__ == "__main__":
    import sys
    if "--delete-all" in sys.argv:
        accs = list_accounts()
        if not accs:
            sys.exit("Nessun conto da cancellare.")
        print("Verranno cancellati dall'archivio (e le loro password dal Gestore credenziali):")
        for a in accs:
            print(f"  - {a['name']} ({a['login']}, {a['server']})")
        print("Le posizioni aperte su MT5 e le cartelle dei terminali in C:\\MT5 NON vengono toccate.")
        if input("Scrivi SI per confermare: ").strip().upper() != "SI":
            sys.exit("Annullato.")
        for a in accs:
            delete_account(a["id"])
        print(f"Cancellati {len(accs)} conti.")
    elif "--import-current" in sys.argv:
        try:
            print("Aggiunto:", import_connected())
        except ValueError as e:
            sys.exit(str(e))


def history(acc: dict, start: str):
    """Trade CHIUSI del conto dal giorno `start` (YYYY-MM-DD): una riga per posizione con profitto, commissioni e swap sommati su tutti i suoi deal.
    L'orario è quello del server del broker (come la settimana/mese mostrati da MT5). Restituisce (DataFrame, valuta)."""
    import pandas as pd
    from datetime import datetime, timedelta
    t0 = datetime.strptime(start, "%Y-%m-%d")
    t1 = datetime.now() + timedelta(days=2)
    with session(acc) as mt5:
        cur = mt5.account_info().currency
        deals = mt5.history_deals_get(t0, t1)
        if deals is None:
            raise RuntimeError(f"MT5 non restituisce la cronologia: {mt5.last_error()}. In MT5 apri la scheda Cronologia (Ctrl+T) e scegli «Tutta la cronologia», poi riprova.")
        if not deals:
            return pd.DataFrame(columns=["time", "simbolo", "profit", "commission", "swap"]), cur
        d = pd.DataFrame([x._asdict() for x in deals])
        d = d[d["type"].isin([0, 1])]                                      # solo operazioni di mercato (esclude depositi, prelievi, bonus)
        d["fee"] = d["fee"] if "fee" in d else 0.0
        d["commission"] = d["commission"] + d["fee"]
        out = d[d["entry"].isin([1, 2, 3])]                                # deal di chiusura: danno l'orario
        agg = d.groupby("position_id").agg(profit=("profit", "sum"), commission=("commission", "sum"), swap=("swap", "sum"), simbolo=("symbol", "first"))
        t = out.groupby("position_id")["time"].max()
        r = agg.loc[t.index].assign(time=pd.to_datetime(t, unit="s"))
        return r.reset_index(drop=True)[["time", "simbolo", "profit", "commission", "swap"]], cur
