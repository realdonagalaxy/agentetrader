"""Notifiche e segnali via Telegram Bot API.

Configurazione in config.env (mai su git): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

Uso da terminale:
  python -m src.telegram_bot --chat-id   # dopo aver scritto un messaggio al bot: stampa il tuo chat ID
  python -m src.telegram_bot --test      # invia un messaggio di prova
"""
import argparse
import os

import requests
from dotenv import load_dotenv

load_dotenv("config.env")
API = "https://api.telegram.org/bot{token}/{method}"


class TelegramBot:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")

    def _call(self, method: str, **payload) -> dict:
        r = requests.post(API.format(token=self.token, method=method), json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram: {data}")
        return data["result"]

    def send(self, text: str) -> None:
        if not self.chat_id:
            raise RuntimeError("TELEGRAM_CHAT_ID mancante: esegui `python -m src.telegram_bot --chat-id`")
        self._call("sendMessage", chat_id=self.chat_id, text=text, parse_mode="HTML")

    def send_signal(self, symbol: str, side: str, entry: float, sl: float, tp: float, note: str = "") -> None:
        risk = abs(entry - sl)
        rr = abs(tp - entry) / risk if risk else 0.0
        self.send(
            f"<b>{side.upper()} {symbol}</b>\n"
            f"Entry: {entry}\nSL: {sl}\nTP: {tp}\nR:R {rr:.2f}\n{note}"
        )

    def find_chat_ids(self) -> list[tuple[int, str]]:
        """Chat che hanno scritto al bot di recente (serve scrivere prima un messaggio al bot)."""
        seen = {}
        for u in self._call("getUpdates"):
            chat = (u.get("message") or u.get("channel_post") or {}).get("chat")
            if chat:
                seen[chat["id"]] = chat.get("first_name") or chat.get("title") or chat.get("username") or ""
        return list(seen.items())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat-id", action="store_true")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    bot = TelegramBot()
    if a.chat_id:
        found = bot.find_chat_ids()
        print("\n".join(f"chat_id = {i}   ({name})" for i, name in found) or
              "Nessun messaggio trovato: scrivi qualcosa al bot su Telegram e riprova.")
    if a.test:
        bot.send("✅ Trading agent collegato a Telegram")
        print("Messaggio inviato.")
