"""Diagnosi in una pagina: perché un segnale non si è aperto. Stampa un riepilogo SENZA segreti (token e chiavi mascherati) da incollare in chat.

Uso:  .venv\\Scripts\\python -m src.diagnosi
"""
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
J = Path(os.environ.get("JOURNAL_DIR", ROOT / "journal"))
CHIAVI = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_CANALE", "SENZA_BOT", "MT5_SYMBOL", "AVVIO_ASCOLTO", "SCARTO_ACTIVTRADES")


def mask(t: str) -> str:
    t = re.sub(r"bot\d+:[A-Za-z0-9_\-]+", "bot<TOKEN>", t)
    t = re.sub(r"\b\d{8,}:[A-Za-z0-9_\-]{20,}\b", "<TOKEN>", t)
    return t


def rows(name: str) -> list[dict]:
    try:
        with (J / name).open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def sez(t: str) -> None:
    print(f"\n=== {t} ===")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sez("VERSIONE E PROGRAMMA")
    try:
        ver = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=str(ROOT), timeout=5).stdout.strip()
    except Exception:
        ver = "?"
    print(f"codice: {ver} · Python {sys.version.split()[0]}")
    try:
        age = time.time() - float((J / "mt5_orders.heartbeat").read_text())
        run = (J / "mt5_orders.version").read_text().strip() if (J / "mt5_orders.version").exists() else "?"
        print(f"ascolto segnali: battito {age:.0f} s fa ({'ATTIVO' if age < 30 else 'FERMO'}), versione in esecuzione {run}" + ("  <-- DIVERSA dal codice: riavvia" if run != ver and age < 30 else ""))
    except (OSError, ValueError):
        print("ascolto segnali: MAI PARTITO (nessun battito)")
    sez("config.env (solo presenza, nessun valore tranne il nome del canale)")
    env = {}
    try:
        for line in (ROOT / "config.env").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.split("#")[0].strip()
    except OSError:
        print("config.env NON ESISTE")
    for k in CHIAVI:
        v = env.get(k, "")
        print(f"  {k}: " + ("assente/vuoto" if not v else (v if k in ("TELEGRAM_CANALE", "SENZA_BOT", "MT5_SYMBOL") else "presente")))
    print("  sessione Telegram:", "presente" if (J / "telegram.session").exists() else "ASSENTE (rifai: python -m src.telegram_reader --elenca)")
    sez("CANALE")
    try:
        c = json.loads((J / "canale_stato.json").read_text(encoding="utf-8"))
        print(f"  stato {c.get('state')} · {c.get('title', '')} · aggiornato {time.time() - float(c.get('ts', 0)):.0f} s fa · {mask(str(c.get('detail') or ''))}")
    except (OSError, ValueError):
        print("  nessuno stato registrato")
    sez("ULTIMI MESSAGGI DEL CANALE")
    for r in rows("canale_messaggi.csv")[-6:]:
        print(f"  {r.get('time_utc')} #{r.get('msg_id')} {mask((r.get('testo') or '')[:70])!r}")
    sez("ULTIMI SEGNALI RICONOSCIUTI")
    for r in rows("canale_segnali.csv")[-4:]:
        print(f"  {r.get('time_utc')} #{r.get('msg_id')} {r.get('side')} {r.get('symbol')} entry {r.get('entry')} sl {r.get('sl')} tp1 {r.get('tp1')} {('ERRORE: ' + r['errore']) if r.get('errore') else ''}")
    sez("ESITI DI APERTURA (per conto)")
    for r in rows("segnali_esiti.csv")[-8:]:
        print(f"  {r.get('quando_utc')} #{r.get('msg_id')} conto {r.get('conto')}: {r.get('esito')} · {mask((r.get('dettaglio') or '')[:150])}")
    sez("CONTI")
    try:
        sys.path.insert(0, str(ROOT))
        from src import mt5_accounts as ma
        for a in ma.list_accounts():
            print(f"  {a['login']} attivo={a['enabled']} segnali={a['use_signals']} TP{a.get('tp_target') or 1} parz={a.get('partial_pct') or 0}% password={'sì' if a.get('has_password') else 'NO'} tipo={a.get('kind') or '?'}")
    except Exception as e:
        print("  impossibile leggere i conti:", str(e)[:120])
    sez("REGISTRO (ultime 15 righe)")
    try:
        for line in (J / "mt5_orders.log").read_text(encoding="utf-8", errors="replace").splitlines()[-15:]:
            print("  " + mask(line[:220]))
    except OSError:
        print("  nessun registro")


if __name__ == "__main__":
    main()
