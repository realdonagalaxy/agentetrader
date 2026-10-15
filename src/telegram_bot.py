"""Invio notifiche e segnali via Telegram Bot API."""
import os

import requests
from dotenv import load_dotenv

load_dotenv("config.env")


class TelegramBot:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = chat_id or os.environ["TELEGRAM_CHAT_ID"]
        self.url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send(self, text: str) -> None:
        r = requests.post(
            self.url,
            json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()

    def send_signal(self, symbol: str, side: str, entry: float, sl: float, tp: float, note: str = "") -> None:
        risk = abs(entry - sl)
        rr = abs(tp - entry) / risk if risk else 0.0
        self.send(
            f"<b>{side.upper()} {symbol}</b>\n"
            f"Entry: {entry}\nSL: {sl}\nTP: {tp}\nR:R {rr:.2f}\n{note}"
        )
