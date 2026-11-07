"""Lettura SOLO LETTURA di un canale Telegram (anche privato) con il TUO account, tramite Telethon. Non invia messaggi, non entra in altri canali, non apre ordini.

Ogni messaggio va in journal/canale_messaggi.csv; quelli che sembrano un segnale e si leggono (src.mt5_orders.parse_signal) vanno anche in journal/canale_segnali.csv
(orario UTC, simbolo, direzione, entry, SL, TP1/2/3, testo). Così il canale si misura per settimane prima di usarlo con soldi veri.

Prima volta: crea l'app su https://my.telegram.org (API development tools) e metti in config.env TELEGRAM_API_ID e TELEGRAM_API_HASH. Al primo avvio Telegram manda un codice
nell'app: il file di sessione journal/telegram.session resta sul PC (è come una chiave del tuo account: mai su Git, mai condiviso).

Uso: python -m src.telegram_reader --elenca                      (elenca chat e canali con il loro id)
     python -m src.telegram_reader --canale "Nome o id" --storico 200   (scarica gli ultimi 200 messaggi)
     python -m src.telegram_reader --canale "Nome o id"                  (resta in ascolto dei nuovi messaggi)
"""
import argparse
import csv
import os
import sys
from datetime import timezone
from pathlib import Path

from src.mt5_orders import clean_text, looks_like_signal, parse_signal

JOURNAL = Path(os.environ.get("JOURNAL_DIR", "journal"))
MSG_CSV = JOURNAL / "canale_messaggi.csv"
SIG_CSV = JOURNAL / "canale_segnali.csv"
SESSION = str(JOURNAL / "telegram")                                  # Telethon aggiunge .session
MSG_COLS = ["time_utc", "msg_id", "testo"]
SIG_COLS = ["time_utc", "msg_id", "symbol", "side", "entry", "sl", "tp1", "tp2", "tp3", "inferred", "errore", "testo"]


def _append(path: Path, cols: list, row: dict) -> None:
    JOURNAL.mkdir(exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def write_status(**kw) -> None:
    """Stato del collegamento al canale, letto da Gestione Conti (journal/canale_stato.json). Si aggiornano solo i campi passati."""
    import json
    import time
    f = JOURNAL / "canale_stato.json"
    try:
        cur = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = {}
    cur.update(kw, ts=time.time())
    try:
        JOURNAL.mkdir(exist_ok=True)
        f.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def seen_ids() -> set:
    if not MSG_CSV.exists():
        return set()
    with MSG_CSV.open(encoding="utf-8") as f:
        return {r["msg_id"] for r in csv.DictReader(f)}


def process(text: str, when, msg_id, seen: set | None = None) -> str:
    """Salva un messaggio e, se è un segnale, anche il segnale. Ritorna 'dup', 'msg' (messaggio normale), 'segnale' o 'illeggibile'."""
    if seen is not None:
        if str(msg_id) in seen:
            return "dup"
        seen.add(str(msg_id))
    text = clean_text(text or "")
    if not text.strip():
        return "msg"
    t = when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if when.tzinfo else when.strftime("%Y-%m-%d %H:%M:%S")
    _append(MSG_CSV, MSG_COLS, {"time_utc": t, "msg_id": msg_id, "testo": text})
    if not looks_like_signal(text):
        return "msg"
    row = {"time_utc": t, "msg_id": msg_id, "testo": text}
    try:
        sig = parse_signal(text)
        row.update({k: sig.get(k, "") for k in ("symbol", "side", "entry", "sl", "tp1", "tp2", "tp3", "inferred")})
        out = "segnale"
    except ValueError as e:
        row["errore"] = str(e)
        out = "illeggibile"
    _append(SIG_CSV, SIG_COLS, row)
    return out


def _client():
    from dotenv import load_dotenv
    load_dotenv("config.env")
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID", "").strip(), os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not api_id.isdigit() or not api_hash:
        sys.exit("Mancano TELEGRAM_API_ID e TELEGRAM_API_HASH in config.env (si creano su https://my.telegram.org -> API development tools).")
    try:
        from telethon import TelegramClient
    except ImportError:
        sys.exit("Manca telethon: pip install telethon")
    JOURNAL.mkdir(exist_ok=True)
    return TelegramClient(SESSION, int(api_id), api_hash)


def _norm(t: str) -> str:
    """Confronto tollerante: maiuscole, accenti (È/É/E), lettere speciali dei font e spazi multipli non contano."""
    import unicodedata
    t = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", t))
    t = "".join(" " if unicodedata.category(c) in ("Pd", "Pc") else c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


async def _find(client, name: str):
    """Canale per id numerico, @username o titolo (maiuscole ignorate, basta una parte del titolo se è unica)."""
    if name.lstrip("-").isdigit():
        try:
            return await client.get_entity(int(name))
        except ValueError:
            sys.exit(f"Nessuna chat con id {name} nel tuo account. Esegui --elenca e copia l'id reale (il numero nell'esempio della guida è inventato).")
    if name.startswith("@"):
        return await client.get_entity(name)
    norm = _norm(name)
    matches = [d for d in await client.get_dialogs() if norm in _norm(d.name or "")]
    exact = [d for d in matches if _norm(d.name or "") == norm]
    matches = exact or matches
    if len(matches) != 1:
        sys.exit(f"Canale «{name}»: {'nessuno trovato' if not matches else 'più di uno: ' + ', '.join(d.name for d in matches)}. Usa --elenca e passa l'id.")
    return matches[0].entity


def start_channel_feed(name: str, q, notify=None) -> None:
    """Per il listener degli ordini: ascolta il canale in un thread e mette in coda (testo, id, timestamp) di ogni nuovo messaggio. Richiede la sessione già creata con --elenca. Sola lettura."""
    import asyncio
    import threading

    def tell(msg: str) -> None:
        print(msg, flush=True)
        write_status(detail=msg)
        if notify:
            try:
                notify(msg)
            except Exception:
                pass

    def work():
        import time
        from telethon import events
        asyncio.set_event_loop(asyncio.new_event_loop())
        client = _client()
        seen = seen_ids()
        state = {"told": False}

        async def run():
            await client.connect()
            if not await client.is_user_authorized():
                write_status(state="errore")
                tell("Canale Telegram: sessione non autorizzata. Esegui prima: python -m src.telegram_reader --elenca")
                return False
            ent = await _find(client, name)
            title = getattr(ent, "title", None) or name
            write_status(state="collegato", title=title, detail="")

            @client.on(events.NewMessage(chats=ent))
            async def handler(ev):
                text = ev.message.message or ""
                process(text, ev.message.date, ev.message.id, seen)
                q.put((text, ev.message.id, ev.message.date.timestamp()))
                write_status(last_msg=ev.message.date.timestamp(), last_signal=bool(looks_like_signal(clean_text(text))) or None)

            async def pulse():                                                # ogni 15 s: connessione viva? (serve a Gestione Conti per mostrare lo stato vero)
                while True:
                    write_status(state="collegato" if client.is_connected() else "riconnessione", title=title)
                    await asyncio.sleep(15)

            pulse_task = asyncio.ensure_future(pulse())

            if not state["told"]:                                             # il messaggio di collegamento una volta sola, anche dopo una riconnessione
                tell(f"Canale «{getattr(ent, 'title', name)}» collegato (sola lettura).")
                state["told"] = True
            else:
                print("Canale ricollegato.", flush=True)
            try:
                await client.run_until_disconnected()
            finally:
                pulse_task.cancel()
            return True

        wait = 10
        while True:                                                           # sempre in ascolto: se la connessione cade si riprova
            try:
                if asyncio.get_event_loop().run_until_complete(run()) is False:
                    return
                wait = 10
            except BaseException as e:                                        # SystemExit di _find incluso: il listener continua con il solo canale del bot
                write_status(state="errore" if not state["told"] else "riconnessione")
                if not state["told"] or wait == 10:
                    tell(f"Canale Telegram non collegato: {type(e).__name__} {str(e)[:200]}. Riprovo.")
                if isinstance(e, SystemExit) and not state["told"]:
                    return                                                    # canale non trovato: inutile riprovare
                wait = min(wait * 2, 300)
            time.sleep(wait)

    threading.Thread(target=work, daemon=True, name="canale-telegram").start()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--elenca", action="store_true", help="elenca chat e canali con id")
    ap.add_argument("--canale", help="titolo, @username o id del canale")
    ap.add_argument("--ultimo", action="store_true", help="mostra l'ultimo messaggio del canale e lo manda al tuo bot Telegram (chat TELEGRAM_CHAT_ID)")
    ap.add_argument("--storico", type=int, default=0, help="scarica gli ultimi N messaggi invece di ascoltare")
    a = ap.parse_args()
    if not a.elenca and not a.canale:
        ap.error("serve --elenca oppure --canale")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from telethon import events
    client = _client()

    async def run():
        await client.start()                                              # primo avvio: chiede telefono e codice
        if a.elenca:
            for d in await client.get_dialogs():
                kind = "canale" if d.is_channel and not d.is_group else "gruppo" if d.is_group else "chat"
                print(f"{d.id:>16}  {kind:7s} {d.name}")
            return
        ent = await _find(client, a.canale)
        title = getattr(ent, "title", None) or a.canale
        seen = seen_ids()
        if a.ultimo:
            msgs = [m async for m in client.iter_messages(ent, limit=1)]
            if not msgs:
                print("Il canale non ha messaggi.")
                return
            m = msgs[0]
            when = m.date.astimezone().strftime("%d/%m/%Y %H:%M")
            body = clean_text(m.message or "") or "(messaggio senza testo: immagine o altro)"
            text = f"📨 Ultimo messaggio di «{title}» ({when}):\n\n{body}"
            print(text)
            from dotenv import load_dotenv
            load_dotenv("config.env")
            from src.telegram_bot import TelegramBot
            bot = TelegramBot()
            bot._call("sendMessage", chat_id=bot.chat_id, text=text)
            print("Inviato al tuo bot Telegram.")
            return
        if a.storico:
            counts = {}
            async for m in client.iter_messages(ent, limit=a.storico):
                r = process(m.message or "", m.date, m.id, seen)
                counts[r] = counts.get(r, 0) + 1
            print(f"{title}: letti {a.storico} messaggi -> {counts}. File: {MSG_CSV}, {SIG_CSV}")
            return

        @client.on(events.NewMessage(chats=ent))
        async def handler(ev):
            r = process(ev.message.message or "", ev.message.date, ev.message.id, seen)
            if r in ("segnale", "illeggibile"):
                print(f"[{ev.message.date:%H:%M:%S}] {r}: {(ev.message.message or '')[:80]!r}", flush=True)

        print(f"In ascolto su «{title}» (sola lettura). Ctrl+C per fermare.", flush=True)
        await client.run_until_disconnected()

    with client:
        client.loop.run_until_complete(run())


if __name__ == "__main__":
    main()
