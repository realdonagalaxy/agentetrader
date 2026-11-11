"""Backup e ripristino dei DATI di Gestione Conti per cambiare PC. Il codice è già su GitHub (git clone): qui c'è quello che su GitHub NON c'è.

  python -m src.backup_dati --esporta                 -> crea backup_gestione_conti_AAAAMMGG.zip (nella cartella del progetto)
  python -m src.backup_dati --importa file.zip        -> ripristina nel progetto del nuovo PC (non sovrascrive file più recenti senza --forza)

Dentro lo zip: elenco dei conti (journal/conti_mt5.db: login, server, lotti, TP, parzializzazione; SENZA password), impostazioni, registri dei segnali / esiti / trade manuali, chiusure,
posizioni da seguire, il tuo journal Excel (journal/trading_journal.xlsx). NON ci sono mai: config.env (token e chiavi), le password dei conti (stanno nel Gestore credenziali di Windows
e non si spostano: vanno riscritte in «Modifica»), la sessione Telegram (journal/telegram.session: si rifà sul nuovo PC con --elenca), i registri di funzionamento e i grafici in cache.
Con --con-config si aggiunge anche config.env: lo zip diventa SEGRETO (contiene il token del bot); cancellalo dopo l'uso.
"""
import argparse
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
J = Path(os.environ.get("JOURNAL_DIR", ROOT / "journal"))
ESCLUSI = {"mt5_orders.heartbeat", "mt5_orders.pid", "mt5_orders.log", "mt5_orders.version", "mt5.lock", "p.json", "richiesta_ultimo.flag", "richiesta_giorno.json", "segnale_manuale.json"}
ESCLUSI_PREFISSI = ("telegram.session", "~$")


def file_da_salvare() -> list[Path]:
    out = []
    for p in sorted(J.rglob("*")):
        if not p.is_file() or p.name in ESCLUSI or p.name.startswith(ESCLUSI_PREFISSI) or "grafici" in p.relative_to(J).parts:
            continue
        out.append(p)
    return out


def esporta(con_config: bool, dest: str | None) -> None:
    dest = Path(dest) if dest else ROOT / f"backup_gestione_conti_{datetime.now():%Y%m%d}.zip"
    files = file_da_salvare()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, "journal/" + p.relative_to(J).as_posix())
        if con_config and (ROOT / "config.env").exists():
            z.write(ROOT / "config.env", "config.env")
    print(f"Creato {dest} ({dest.stat().st_size / 1024:.0f} KB): {len(files)} file" + (" + config.env (ZIP SEGRETO)" if con_config else ""))
    print("Non incluse (vanno rifatte sul nuovo PC): password dei conti, sessione Telegram" + ("" if con_config else ", config.env"))


def importa(src: str, forza: bool) -> None:
    n = salt = 0
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                continue                                                                  # percorsi anomali: ignorati
            target = (J / name[len("journal/"):]) if name.startswith("journal/") else (ROOT / name)
            if name != "config.env" and not name.startswith("journal/"):
                continue
            if target.exists() and not forza:
                salt += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
            n += 1
    print(f"Ripristinati {n} file" + (f"; {salt} già presenti e lasciati com'erano (usa --forza per sovrascriverli)" if salt else ""))
    print("Ora: riscrivi le password dei conti in Gestione Conti → Modifica; rifai l'accesso a Telegram con  python -m src.telegram_reader --elenca")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esporta", action="store_true")
    ap.add_argument("--importa", metavar="ZIP")
    ap.add_argument("--con-config", action="store_true", help="include config.env (lo zip diventa segreto)")
    ap.add_argument("--forza", action="store_true", help="in importazione sovrascrive i file già presenti")
    ap.add_argument("--dest")
    a = ap.parse_args()
    if a.esporta:
        esporta(a.con_config, a.dest)
    elif a.importa:
        importa(a.importa, a.forza)
    else:
        ap.print_help()
        sys.exit(1)
