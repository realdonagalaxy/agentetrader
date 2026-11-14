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
    try:
        con.execute("ALTER TABLE accounts ADD COLUMN tp_target INTEGER DEFAULT 1")   # quale TP del segnale usa il conto: 1, 2 o 3
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE accounts ADD COLUMN partial_pct INTEGER DEFAULT 0")   # % dei lotti chiusa a TP1 (con il resto a pareggio); 0 = nessuna parzializzazione
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE accounts ADD COLUMN manual_ok INTEGER")          # usa il conto per i trade manuali: NULL = predefinito (sì se demo, no se reale)
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
            "lots": round(lots, 2), "enabled": 1 if d.get("enabled", True) else 0, "use_signals": 1 if d.get("use_signals", True) else 0, "note": str(d.get("note") or "")[:300],
            "tp_target": int(d.get("tp_target") or 1) if str(d.get("tp_target") or 1) in ("1", "2", "3") else 1,
            "partial_pct": _pct(d.get("partial_pct")), "manual_ok": None if d.get("manual_ok") is None else (1 if d.get("manual_ok") else 0)}


def _pct(v) -> int:
    """Percentuale di lotti da chiudere a TP1: 0 (spento) oppure da 10 a 90."""
    try:
        n = int(float(str(v or 0).replace(",", ".")))
    except ValueError:
        raise ValueError("la percentuale da parzializzare deve essere un numero")
    if n and not 10 <= n <= 90:
        raise ValueError("la percentuale da parzializzare deve stare tra 10 e 90 (0 = nessuna parzializzazione)")
    return n


def out(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["enabled"], d["use_signals"] = bool(d["enabled"]), bool(d["use_signals"])
    d["manual_ok"] = bool(d["manual_ok"]) if d.get("manual_ok") is not None else (d.get("kind") == "demo")       # predefinito: sì per i demo, no per i reali
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
        cur = con.execute("INSERT INTO accounts (name,login,server,terminal_path,lots,enabled,use_signals,note,tp_target,partial_pct,manual_ok,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                          (c["name"], c["login"], c["server"], c["terminal_path"], c["lots"], c["enabled"], c["use_signals"], c["note"], c["tp_target"], c["partial_pct"], c["manual_ok"]))
        aid = cur.lastrowid
    else:
        if (old["login"], old["server"]) != (c["login"], c["server"]):
            del_password(old["login"], old["server"])                  # la vecchia password non vale più
        con.execute("UPDATE accounts SET name=?,login=?,server=?,terminal_path=?,lots=?,enabled=?,use_signals=?,note=?,tp_target=?,partial_pct=?,manual_ok=? WHERE id=?",
                    (c["name"], c["login"], c["server"], c["terminal_path"], c["lots"], c["enabled"], c["use_signals"], c["note"], c["tp_target"], c["partial_pct"], c["manual_ok"], aid))
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
    if "--tp" in sys.argv:                                              # imposta il TP usato da ogni conto: --tp 6285383=1 6285381=2 6285380=3
        pairs = [x for x in sys.argv[sys.argv.index("--tp") + 1:] if "=" in x]
        if not pairs:
            sys.exit("Uso: python -m src.mt5_accounts --tp LOGIN=1|2|3 [LOGIN=1|2|3 ...]")
        by_login = {str(a["login"]): a for a in list_accounts()}
        for pr in pairs:
            lg, tp = pr.split("=", 1)
            if lg not in by_login or tp not in ("1", "2", "3"):
                sys.exit(f"Non valido: {pr} (conti presenti: {', '.join(by_login) or 'nessuno'}; TP deve essere 1, 2 o 3)")
        con = db()
        for pr in pairs:
            lg, tp = pr.split("=", 1)
            con.execute("UPDATE accounts SET tp_target=? WHERE id=?", (int(tp), by_login[lg]["id"]))
            print(f"Conto {lg}: TP{tp}")
        con.commit()
        con.close()
    elif "--delete-all" in sys.argv:
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


def _closed_trades(mt5, t0, t1) -> list[dict]:
    """Operazioni chiuse con data di chiusura in [t0, t1) (datetime naive, orario del server): una riga per ogni deal di chiusura con apertura, chiusura, motivo (tp/sl/altra),
    pips (oro 1 pip = 0,10, altri strumenti 10 punti) e netto. Una chiusura parziale è una riga a parte."""
    from datetime import timedelta, timezone
    from datetime import datetime
    deals = mt5.history_deals_get(t0 - timedelta(days=1), t1 + timedelta(days=1))
    if deals is None:
        raise RuntimeError(f"MT5 non restituisce la cronologia: {mt5.last_error()}. In MT5 apri la scheda Cronologia (Ctrl+T) e scegli «Tutta la cronologia», poi riprova.")
    out, opens, psize = [], {}, {}
    for d in deals:
        if d.entry not in (1, 2, 3) or d.type not in (0, 1):
            continue
        when = datetime.fromtimestamp(d.time, tz=timezone.utc).replace(tzinfo=None)
        if not t0 <= when < t1:
            continue
        if d.position_id not in opens:
            ins = [x for x in (mt5.history_deals_get(position=d.position_id) or ()) if x.entry == 0]
            opens[d.position_id] = ins[0] if ins else None
        o = opens[d.position_id]
        if o is None:                                              # apertura non trovata nella cronologia: non si può calcolare
            continue
        if d.symbol not in psize:
            if "XAU" in d.symbol.upper() or "GOLD" in d.symbol.upper():
                psize[d.symbol] = 0.10
            else:
                info = mt5.symbol_info(d.symbol)
                psize[d.symbol] = (info.point * 10) if info else 0.0001
        out.append({"day": when.strftime("%Y-%m-%d"), "position": int(d.position_id), "deal": int(d.ticket), "symbol": d.symbol, "side": "buy" if o.type == 0 else "sell",
                    "volume": getattr(d, "volume", None), "open_time": int(o.time), "open_price": o.price, "close_time": int(d.time), "close_price": d.price,
                    "reason": "tp" if d.reason == mt5.DEAL_REASON_TP else "sl" if d.reason == mt5.DEAL_REASON_SL else "altra",
                    "pips": round(((d.price - o.price) if o.type == 0 else (o.price - d.price)) / psize[d.symbol], 1),
                    "net": round(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0), 2)})
    return sorted(out, key=lambda r: r["close_time"])


def _balance_flows(mt5, t0) -> list[tuple]:
    """Tutti i movimenti del conto da t0 a oggi: (quando, importo netto, è_operazione). Netto = profitto + commissione + swap (+ fee); is_trade=False per depositi, prelievi, crediti."""
    from datetime import datetime, timedelta, timezone
    deals = mt5.history_deals_get(t0 - timedelta(days=1), datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2)) or ()
    out = []
    for d in deals:
        when = datetime.fromtimestamp(d.time, tz=timezone.utc).replace(tzinfo=None)
        out.append((when, float(d.profit) + float(getattr(d, "commission", 0.0)) + float(getattr(d, "swap", 0.0)) + float(getattr(d, "fee", 0.0)), d.type in (0, 1)))
    return out


def _day_pct(flows, bal_now: float, d0, d1=None):
    """Percentuale guadagnata o persa in [d0, d1) (default: un giorno) rispetto al SALDO a inizio periodo. Il saldo di inizio si ricostruisce dal saldo di adesso togliendo tutti i movimenti
    da d0 in poi (depositi e prelievi compresi). Conta solo il realizzato: operazioni chiuse nel periodo, con commissioni e swap. None se il saldo iniziale non è positivo."""
    from datetime import timedelta
    d1 = d1 or d0 + timedelta(days=1)
    start = bal_now - sum(v for w, v, _ in flows if w >= d0)
    pnl = sum(v for w, v, trade in flows if trade and d0 <= w < d1)
    return round(100 * pnl / start, 2) if start > 0 else None


def calendar_month(acc: dict, month: str) -> dict:
    """Operazioni CHIUSE del conto nel mese (YYYY-MM), raggruppate per giorno di chiusura (orario del server del broker):
    numero di TP, di SL, di altre chiusure (a mano, copia...), somma dei PIPS e profitto netto. TP/SL = motivo di chiusura registrato da MT5."""
    from datetime import datetime
    y, m = (int(x) for x in month.split("-"))
    t0, t1 = datetime(y, m, 1), datetime(y + (m == 12), m % 12 + 1, 1)
    with session(acc) as mt5:
        ai = mt5.account_info()
        cur, bal_now = ai.currency, float(ai.balance)
        trades = _closed_trades(mt5, t0, t1)
        flows = _balance_flows(mt5, t0)
    days = {}
    for r in trades:
        c = days.setdefault(r["day"], {"tp": 0, "sl": 0, "altre": 0, "pips": 0.0, "trade": 0, "netto": 0.0})
        c["tp" if r["reason"] == "tp" else "sl" if r["reason"] == "sl" else "altre"] += 1
        c["pips"] += r["pips"]
        c["trade"] += 1
        c["netto"] += r["net"]
    for key, c in days.items():
        c["pips"], c["netto"] = round(c["pips"], 1), round(c["netto"], 2)
        c["pct"] = _day_pct(flows, bal_now, datetime.strptime(key, "%Y-%m-%d"))
    tot = {k: round(sum(c[k] for c in days.values()), 2) for k in ("tp", "sl", "altre", "pips", "trade", "netto")}
    tot["pct"] = _day_pct(flows, bal_now, t0, t1)
    return {"month": month, "currency": cur, "days": days, "total": tot}


ORDER_NAMES = {2: "BUY LIMIT", 3: "SELL LIMIT", 4: "BUY STOP", 5: "SELL STOP", 6: "BUY STOP LIMIT", 7: "SELL STOP LIMIT"}


def trade_list(acc: dict, month: str) -> dict:
    """Elenco dei trade letti da MT5 (sola lettura): posizioni aperte ora, ordini pendenti e operazioni chiuse nel mese (YYYY-MM), qualunque sia il modo in cui sono state aperte.
    Per ogni operazione chiusa: SL e TP iniziali (dall'ordine di apertura), pips, R (chiusura - apertura divisa per la distanza dello SL iniziale) e netto di commissioni e swap."""
    from datetime import datetime
    y, m = (int(x) for x in month.split("-"))
    t0, t1 = datetime(y, m, 1), datetime(y + (m == 12), m % 12 + 1, 1)
    with session(acc) as mt5:
        cur = mt5.account_info().currency
        closed = _closed_trades(mt5, t0, t1)
        for r in closed:
            orders = sorted(mt5.history_orders_get(position=r["position"]) or (), key=lambda o: getattr(o, "time_setup", 0))
            first = orders[0] if orders else None
            sl = float(first.sl) if first is not None and getattr(first, "sl", 0) else None
            tp = float(first.tp) if first is not None and getattr(first, "tp", 0) else None
            sign = 1 if r["side"] == "buy" else -1
            r["sl"], r["tp"] = sl, tp
            r["r"] = round(sign * (r["close_price"] - r["open_price"]) / abs(r["open_price"] - sl), 2) if sl and abs(r["open_price"] - sl) > 0 else None
        opens = []
        for p in (mt5.positions_get() or []):
            d = _pos(p)
            d["r"] = round((1 if d["side"] == "buy" else -1) * (d["price"] - d["open"]) / abs(d["open"] - d["sl"]), 2) if d["sl"] and abs(d["open"] - d["sl"]) > 0 else None
            opens.append(d)
        pend = [{"ticket": int(o.ticket), "symbol": o.symbol, "tipo": ORDER_NAMES.get(int(o.type), f"tipo {o.type}"), "volume": getattr(o, "volume_current", None) or getattr(o, "volume", None),
                 "price": o.price_open, "sl": o.sl or None, "tp": o.tp or None, "time": int(getattr(o, "time_setup", 0)), "comment": getattr(o, "comment", "")} for o in (mt5.orders_get() or [])]
    return {"month": month, "currency": cur, "open": opens, "pending": pend, "closed": sorted(closed, key=lambda r: -r["close_time"])}


def day_trades(acc: dict, day: str) -> dict:
    """Le operazioni chiuse in un giorno (YYYY-MM-DD), una per riga, per il dettaglio del calendario."""
    from datetime import datetime, timedelta
    t0 = datetime.strptime(day, "%Y-%m-%d")
    with session(acc) as mt5:
        cur = mt5.account_info().currency
        trades = _closed_trades(mt5, t0, t0 + timedelta(days=1))
    return {"date": day, "currency": cur, "trades": trades}


def chart_path(login, position: int, deal: int):
    d = DATA_DIR / "grafici"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{login}_{position}_{deal}.png"


def render_history_chart(mt5, symbol: str, side: str, open_price: float, open_time: int, close_price: float, close_time: int, sl, tp, label: str) -> bytes | None:
    """Grafico di un'operazione chiusa (candele del periodo con Entry, SL, TP e chiusura). None se MT5 non ha le candele. Tempi: orario del server (epoch)."""
    from datetime import datetime, timezone
    from src import trade_chart
    minutes = (close_time - open_time) / 60
    tf, secs = (mt5.TIMEFRAME_M1, 60) if minutes <= 180 else (mt5.TIMEFRAME_M5, 300) if minutes <= 900 else (mt5.TIMEFRAME_M15, 900)
    d0 = datetime.fromtimestamp(open_time - 30 * secs, tz=timezone.utc)
    d1 = datetime.fromtimestamp(close_time + 15 * secs, tz=timezone.utc)
    rates = mt5.copy_rates_range(symbol, tf, d0, d1)
    if rates is None or len(rates) < 5:
        return None
    candles = [(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])) for r in rates]
    info = mt5.symbol_info(symbol)
    return trade_chart.render(candles, open_price, sl or None, tp or None, close_price, side, symbol, label, getattr(info, "digits", 2), open_time, close_time)


def trade_chart_png(acc: dict, position: int, deal: int) -> bytes:
    """Grafico di un'operazione già chiusa, preso dalla cronologia di MT5 (livelli di SL e TP = quelli dell'ordine di apertura). Salvato in journal/grafici: le volte dopo è immediato."""
    f = chart_path(acc["login"], position, deal)
    if f.exists():
        return f.read_bytes()
    with session(acc) as mt5:
        deals = list(mt5.history_deals_get(position=position) or ())
        ins = [x for x in deals if x.entry == 0]
        outs = [x for x in deals if int(x.ticket) == int(deal)]
        if not ins or not outs:
            raise ValueError("operazione non trovata nella cronologia di MT5")
        o, d = ins[0], outs[0]
        orders = list(mt5.history_orders_get(position=position) or ())
        sl = next((x.sl for x in orders if getattr(x, "sl", 0)), None)
        tp = next((x.tp for x in orders if getattr(x, "tp", 0)), None)
        side = "buy" if o.type == 0 else "sell"
        info = mt5.symbol_info(d.symbol)
        pip = 0.10 if ("XAU" in d.symbol.upper() or "GOLD" in d.symbol.upper()) else ((info.point * 10) if info else 0.0001)
        pips = ((d.price - o.price) if side == "buy" else (o.price - d.price)) / pip
        what = "TP" if d.reason == mt5.DEAL_REASON_TP else "SL" if d.reason == mt5.DEAL_REASON_SL else "Chiusura"
        label = f"{what} {pips:+.0f} pips · prezzo {d.price:.{getattr(info, 'digits', 2)}f}"
        png = render_history_chart(mt5, d.symbol, side, o.price, int(o.time), d.price, int(d.time), sl, tp, label)
    if png is None:
        raise ValueError("MT5 non ha le candele di quel periodo: apri un grafico del simbolo in MT5 e scorri indietro, poi riprova")
    f.write_bytes(png)
    return png
