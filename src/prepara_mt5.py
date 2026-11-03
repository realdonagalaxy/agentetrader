"""Prepara il terminale MT5 al trading automatico: nel file di configurazione (config\\common.ini, sezione [Experts]) abilita «Consenti il trading algoritmico» e disattiva lo spegnimento
automatico quando cambia il conto o il profilo. Serve perché il programma cambia conto di continuo e MT5, per sicurezza, spegne il trading automatico a ogni cambio (errore 10027).
Va lanciato con MT5 CHIUSO (a terminale aperto MT5 riscrive il file alla chiusura e annulla la modifica). Prima di scrivere fa una copia di sicurezza: common.ini.bak_AAAAMMGG_HHMMSS.
Il percorso del terminale è MT5_PATH (config.env) oppure C:\\Program Files\\MetaTrader 5\\terminal64.exe. La cartella dati si riconosce da origin.txt, che contiene il percorso dell'installazione.
Uso: python -m src.prepara_mt5            (applica)        python -m src.prepara_mt5 --solo-vedi   (mostra lo stato senza modificare)
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
from datetime import datetime

WANT = {"Enabled": "1", "AllowLiveTrading": "1", "Account": "0", "Profile": "0"}     # Account/Profile = 1 significa «disabilita quando cambia»


def find_data_dir(terminal_exe: str) -> str | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    want = os.path.normcase(os.path.normpath(os.path.dirname(terminal_exe))).lower()
    for origin in glob.glob(os.path.join(appdata, "MetaQuotes", "Terminal", "*", "origin.txt")):
        try:
            raw = open(origin, "rb").read()
            txt = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "ignore")
        except OSError:
            continue
        if os.path.normcase(os.path.normpath(txt.strip())).lower() == want:
            return os.path.dirname(origin)
    return None


def read_ini(path: str) -> tuple[list[str], str, bool]:
    """Righe del file, codifica e se aveva il BOM. MT5 scrive i .ini in UTF-16 LE con BOM."""
    raw = open(path, "rb").read()
    if raw[:2] == b"\xff\xfe":
        enc = "utf-16"
    elif raw[:3] == b"\xef\xbb\xbf":
        enc = "utf-8-sig"
    else:
        enc = "utf-8"
    return raw.decode(enc).replace("\r\n", "\n").split("\n"), enc, True


def apply(lines: list[str]) -> tuple[list[str], dict]:
    """Imposta le chiavi desiderate nella sezione [Experts] (la crea se manca). Restituisce (righe nuove, {chiave: (prima, dopo)})."""
    changes, n = {}, len(lines)
    start = end = None
    for k, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            if s[1:-1].lower() == "experts":
                start = k
            elif start is not None and end is None:
                end = k
    if start is not None and end is None:
        end = n
    if start is None:                                              # sezione assente: la aggiungo in fondo
        trimmed = lines[:-1] if lines and lines[-1] == "" else lines
        return trimmed + ["[Experts]"] + [f"{k}={v}" for k, v in WANT.items()] + [""], {k: (None, v) for k, v in WANT.items()}
    seen, body = set(), []
    for ln in lines[start + 1:end]:
        if "=" in ln and not ln.strip().startswith(";"):
            key, val = ln.split("=", 1)
            key = key.strip()
            if key in WANT:
                seen.add(key)
                if val.strip() != WANT[key]:
                    changes[key] = (val.strip(), WANT[key])
                body.append(f"{key}={WANT[key]}")
                continue
        body.append(ln)
    blank = 0
    while body and body[-1] == "":                                 # righe vuote di coda della sezione: le rimetto dopo le chiavi aggiunte
        body.pop()
        blank += 1
    for k, v in WANT.items():
        if k not in seen:
            changes[k] = (None, v)
            body.append(f"{k}={v}")
    return lines[:start + 1] + body + [""] * max(blank, 1 if end < n else 0) + lines[end:], changes


def terminal_running() -> bool:
    if os.name != "nt":
        return False
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"], capture_output=True, text=True).stdout
    return "terminal64.exe" in out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-vedi", action="store_true")
    ap.add_argument("--terminale")
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv("config.env")
    except ImportError:
        pass
    exe = a.terminale or os.environ.get("MT5_PATH") or r"C:\Program Files\MetaTrader 5\terminal64.exe"
    data = find_data_dir(exe)
    if not data:
        sys.exit(f"Non trovo la cartella dati di {exe}. Apri il terminale almeno una volta, poi riprova (cerco in %APPDATA%\\MetaQuotes\\Terminal).")
    ini = os.path.join(data, "config", "common.ini")
    if not os.path.isfile(ini):
        sys.exit(f"File non trovato: {ini}. Apri e chiudi il terminale una volta e riprova.")
    lines, enc, bom = read_ini(ini)
    new, changes = apply(lines)
    print(f"Terminale: {exe}\nCartella dati: {data}")
    if not changes:
        print("Il file è già a posto: trading automatico consentito e nessuno spegnimento al cambio di conto.")
        return
    for k, (before, after) in changes.items():
        print(f"  {k}: {before if before is not None else '(assente)'} -> {after}")
    if a.solo_vedi:
        print("(solo lettura: nessuna modifica fatta)")
        return
    if terminal_running():
        sys.exit("MT5 è aperto: chiudilo del tutto (anche dall'icona vicino all'orologio) e rilancia questo comando, altrimenti MT5 annulla la modifica alla chiusura.")
    bak = f"{ini}.bak_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copy2(ini, bak)
    text = "\r\n".join(new)
    with open(ini, "wb") as f:
        f.write(text.encode("utf-16") if enc == "utf-16" else text.encode(enc))
    print(f"Fatto. Copia di sicurezza: {bak}\nOra riapri MT5: il pulsante «Algo Trading» deve essere verde.")


if __name__ == "__main__":
    main()
