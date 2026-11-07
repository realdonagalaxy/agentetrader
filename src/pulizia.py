"""Pulizia dei dati di test di Gestione Conti prima di una nuova prova. Per default MOSTRA soltanto cosa cancellerebbe; con --conferma cancella.

Cancella (se presenti): registri dei segnali, degli esiti e delle chiusure, journal/ordini_mt5.csv, l'elenco delle posizioni seguite (ordini_aperti.json), i grafici salvati e i file del lettore del canale.
NON tocca mai: i conti e le loro password, le impostazioni, journal/trading_journal.xlsx, i dati di prezzo in data/ e le posizioni su MT5.
Opzioni: --anche-scarti azzera anche journal/scarti.csv (le misure dello scarto di prezzo: servono alla conversione con ActivTrades, di norma conviene tenerle);
         --anche-conti elimina anche tutti i conti dell'app (database conti_mt5.db) e le loro password (poi si riaggiungono; su MT5 non cambia nulla);
         --anche-telegram cancella i messaggi recenti dal tuo canale/chat Telegram (quelli del bot e, nelle chat private, i tuoi): Telegram permette ai bot di cancellare solo messaggi di meno di 48 ore, i più vecchi vanno tolti a mano.
Uso: python -m src.pulizia [--anche-scarti] [--anche-conti] [--anche-telegram] [--conferma]
"""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

J = Path(os.environ.get("JOURNAL_DIR", "journal"))
BASE = ["segnali.csv", "segnali_esiti.csv", "segnali_chiusure.csv", "ordini_mt5.csv", "ordini_aperti.json", "canale_messaggi.csv", "canale_segnali.csv", "grafici"]


def listener_attivo() -> bool:
    hb = J / "mt5_orders.heartbeat"
    try:
        return time.time() - float(hb.read_text()) < 30
    except (OSError, ValueError):
        return False


def pulisci_telegram(max_msgs: int = 1000) -> None:
    """Manda un messaggio-segnaposto per conoscere l'ultimo id e cancella a ritroso a blocchi di 100 (cancellare id inesistenti o troppo vecchi non fa danni)."""
    from dotenv import load_dotenv
    load_dotenv("config.env")
    from src.telegram_bot import TelegramBot
    bot = TelegramBot()
    last = bot._call("sendMessage", chat_id=bot.chat_id, text="🧹 Pulizia in corso…")["message_id"]
    ids = list(range(last, max(0, last - max_msgs), -1))
    n = 0
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        try:
            if bot._call("deleteMessages", chat_id=bot.chat_id, message_ids=chunk):
                n += len(chunk)
        except Exception as e:
            print("Telegram:", str(e)[:150])
    print(f"Telegram: richiesta la cancellazione di {n} id (esistono davvero solo quelli di meno di 48 ore).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anche-scarti", action="store_true")
    ap.add_argument("--anche-conti", action="store_true")
    ap.add_argument("--anche-telegram", action="store_true")
    ap.add_argument("--conferma", action="store_true", help="cancella davvero (senza, solo anteprima)")
    a = ap.parse_args()
    names = BASE + (["scarti.csv"] if a.anche_scarti else [])
    targets = [J / n for n in names if (J / n).exists()]
    print("Verrà cancellato:" if a.conferma else "ANTEPRIMA (non cancello nulla). Verrebbe cancellato:")
    for t in targets:
        kind = "cartella" if t.is_dir() else f"{t.stat().st_size / 1024:.0f} KB"
        print(f"  - {t} ({kind})")
    if not targets:
        print("  (niente da cancellare tra i file di test)")
    if a.anche_conti:
        print("  - tutti i conti dell'app e le loro password (portachiavi di Windows)")
    if a.anche_telegram:
        print("  - messaggi recenti (ultime 48 ore) del tuo canale/chat Telegram")
    if not a.anche_scarti:
        print("Resta: journal/scarti.csv (misure dello scarto), conti, impostazioni, trading_journal.xlsx.")
    if not a.conferma:
        print("\nPer cancellare davvero: aggiungi --conferma (con l'ascolto dei segnali fermo e nessuna posizione aperta da seguire).")
        return
    if listener_attivo():
        sys.exit("L'ascolto dei segnali è in esecuzione: fermalo (chiudi la finestra «Ascolto segnali» o spegni l'ascolto in Gestione Conti) e riprova.")
    for t in targets:
        shutil.rmtree(t) if t.is_dir() else t.unlink()
    if a.anche_conti:
        from src import mt5_accounts as ma
        accs = ma.list_accounts()
        for x in accs:
            ma.delete_account(x["id"])
        print(f"Conti cancellati: {len(accs)}.")
    if a.anche_telegram:
        pulisci_telegram()
    print("Pulizia fatta.")


if __name__ == "__main__":
    main()
