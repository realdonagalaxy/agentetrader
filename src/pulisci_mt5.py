"""Toglie da un terminale MT5 l'accesso salvato (es. il demo preimpostato dal broker) così non si ricollega da solo.

  python -m src.pulisci_mt5                       -> mostra cosa farebbe su TUTTI i terminali dei conti di Gestione Conti (non scrive nulla)
  python -m src.pulisci_mt5 --applica             -> lo fa davvero (copia .bak di ogni file toccato). Chiudi prima MT5 e Gestione Conti.
  python -m src.pulisci_mt5 --terminale "C:\\Program Files\\MetaTrader 5\\terminal64.exe" [--applica]   -> solo quel terminale

Non tocca la lista dei server del broker (servers.dat). Gestione Conti accede ai conti con login e password salvati nell'app, quindi non dipende da questi accessi.
"""
import argparse
import sys

from src import mt5_accounts as ma


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--terminale")
    ap.add_argument("--applica", action="store_true")
    a = ap.parse_args()
    paths = [a.terminale] if a.terminale else sorted({x["terminal_path"] for x in ma.list_accounts() if x.get("terminal_path")} | {ma.default_terminal()})
    tot = 0
    for p in paths:
        try:
            acts = ma.clean_terminal_credentials(p, apply=a.applica)
        except Exception as e:
            print(f"{p}: errore {e}")
            continue
        print(f"\n{p}")
        for x in acts or ["(niente da togliere)"]:
            print("  " + ("" if a.applica or not acts else "[prova] ") + x)
        tot += len(acts)
    if tot and not a.applica:
        print("\nNon ho scritto nulla. Chiudi MT5 e Gestione Conti, poi rilancia con --applica.")
    elif tot:
        print("\nFatto. Di ogni file modificato c'è una copia .bak nella stessa cartella.")


if __name__ == "__main__":
    sys.exit(main())
