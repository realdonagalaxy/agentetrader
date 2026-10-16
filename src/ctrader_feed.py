"""Prezzi in tempo reale da cTrader Open API (solo lettura) e ciclo di avvisi ogni 5 minuti.

NON TESTATO CON UN CONTO REALE: serve che l'applicazione sul portale Open API sia "Active" e che config.env abbia
CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET, CTRADER_ACCESS_TOKEN (+ CTRADER_REFRESH_TOKEN), CTRADER_ACCOUNT_ID (vedi src/ctrader_auth.py).
Il codice scarica solo le candele M5: nessun ordine.

Uso:
  python -m src.ctrader_feed --symbol XAUUSD --once --send
  python -m src.ctrader_feed --symbol XAUUSD --send            # ripete ogni 5 minuti (Ctrl+C per fermare)
"""
import argparse
import os
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv("config.env")
TOKEN_URL = "https://openapi.ctrader.com/apps/token"
PRICE_SCALE = 100000.0                      # i prezzi dei trendbar sono interi relativi, in 1/100000
CHUNK_DAYS = 3                              # richieste a blocchi: il server limita l'intervallo per richiesta
M5_MS = 300_000


def trendbars_to_df(trendbars) -> pd.DataFrame:
    """Lista di ProtoOATrendbar (o oggetti con gli stessi campi) -> DataFrame M5 in UTC (open, high, low, close, volume tick)."""
    rows = []
    for t in trendbars:
        low = t.low
        rows.append((t.utcTimestampInMinutes * 60, (low + t.deltaOpen) / PRICE_SCALE, (low + t.deltaHigh) / PRICE_SCALE,
                     low / PRICE_SCALE, (low + t.deltaClose) / PRICE_SCALE, float(t.volume)))
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df.pop("time"), unit="s")
    df.index.name = "time"
    return df[~df.index.duplicated()].sort_index()


def refresh_access_token() -> None:
    """Rinnova il token d'accesso con il refresh token (scrive il nuovo in config.env)."""
    from src.ctrader_auth import _set_env
    rt = os.environ.get("CTRADER_REFRESH_TOKEN")
    if not rt:
        return
    r = requests.get(TOKEN_URL, params={"grant_type": "refresh_token", "refresh_token": rt,
                                        "client_id": os.environ["CTRADER_CLIENT_ID"], "client_secret": os.environ["CTRADER_CLIENT_SECRET"]}, timeout=20)
    d = r.json()
    if d.get("accessToken"):
        os.environ["CTRADER_ACCESS_TOKEN"] = d["accessToken"]
        _set_env("CTRADER_ACCESS_TOKEN", d["accessToken"])
        if d.get("refreshToken"):
            os.environ["CTRADER_REFRESH_TOKEN"] = d["refreshToken"]
            _set_env("CTRADER_REFRESH_TOKEN", d["refreshToken"])
    else:
        print(f"(rinnovo token non riuscito: {d.get('errorCode') or d})")


class CTraderFeed:
    """Connessione cTrader Open API: autenticazione, ricerca simbolo, download candele M5 e ciclo periodico."""

    def __init__(self, symbol: str, days: int = 25):
        from ctrader_open_api import Client, EndPoints, TcpProtocol
        self.symbol, self.days = symbol, days
        self.account_id = int(os.environ["CTRADER_ACCOUNT_ID"])
        live = os.environ.get("CTRADER_ENV", "demo") == "live"
        host = EndPoints.PROTOBUF_LIVE_HOST if live else EndPoints.PROTOBUF_DEMO_HOST
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.symbol_id = None

    def _send(self, req):
        from ctrader_open_api import Protobuf
        d = self.client.send(req)
        d.addCallback(Protobuf.extract)
        return d

    def connect(self):
        """Deferred: collega, autentica app e conto, trova il symbolId."""
        from twisted.internet import defer
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (ProtoOAAccountAuthReq, ProtoOAApplicationAuthReq, ProtoOASymbolsListReq)

        @defer.inlineCallbacks
        def go(_client):
            app = ProtoOAApplicationAuthReq()
            app.clientId, app.clientSecret = os.environ["CTRADER_CLIENT_ID"], os.environ["CTRADER_CLIENT_SECRET"]
            yield self._send(app)
            acc = ProtoOAAccountAuthReq()
            acc.ctidTraderAccountId, acc.accessToken = self.account_id, os.environ["CTRADER_ACCESS_TOKEN"]
            yield self._send(acc)
            sl = ProtoOASymbolsListReq()
            sl.ctidTraderAccountId = self.account_id
            res = yield self._send(sl)
            names = {s.symbolName.upper(): s.symbolId for s in res.symbol}
            want = os.environ.get("CTRADER_SYMBOL", self.symbol).upper()
            if want not in names:
                close = [n for n in names if self.symbol.upper()[:3] in n][:8]
                raise RuntimeError(f"Simbolo {want!r} non trovato su cTrader. Simili: {close}. Imposta CTRADER_SYMBOL in config.env.")
            self.symbol_id = names[want]

        d = defer.Deferred()
        self.client.setConnectedCallback(lambda c: go(c).chainDeferred(d))
        self.client.setDisconnectedCallback(lambda c, reason: print("cTrader: connessione chiusa", reason))
        self.client.startService()
        return d

    def fetch_m5(self):
        """Deferred con il DataFrame delle ultime candele M5 chiuse (a blocchi di CHUNK_DAYS giorni)."""
        from twisted.internet import defer
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq
        from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod

        @defer.inlineCallbacks
        def go():
            end = int(time.time() * 1000)
            start = end - self.days * 86_400_000
            bars = []
            t0 = start
            while t0 < end:
                t1 = min(t0 + CHUNK_DAYS * 86_400_000, end)
                req = ProtoOAGetTrendbarsReq()
                req.ctidTraderAccountId, req.symbolId, req.period = self.account_id, self.symbol_id, ProtoOATrendbarPeriod.M5
                req.fromTimestamp, req.toTimestamp = t0, t1
                res = yield self._send(req)
                bars.extend(res.trendbar)
                t0 = t1
            df = trendbars_to_df(bars)
            now5 = pd.Timestamp.utcnow().tz_localize(None).floor("5min")
            return df[df.index < now5]                    # solo candele chiuse
        return go()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--journal")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--chart-dir")
    a = ap.parse_args()
    from twisted.internet import reactor, threads
    from src import alert_journal as aj
    from src.assistant import run_once

    refresh_access_token()
    bot = None
    if a.send:
        from src.telegram_bot import TelegramBot
        bot = TelegramBot()
    journal = Path(a.journal or aj.PATH)
    feed = CTraderFeed(a.symbol)

    def analyze(m5):
        for m in run_once(a.symbol, m5, 5, journal, bot, True, a.chart_dir):
            print(f"\n[{pd.Timestamp.utcnow():%Y-%m-%d %H:%M} UTC]\n{m}", flush=True)

    def tick():
        d = feed.fetch_m5()
        d.addCallback(lambda m5: threads.deferToThread(analyze, m5))
        d.addErrback(lambda f: print(f"errore: {f.getErrorMessage()}", flush=True))
        return d

    def loop():
        def after(_):
            if a.once:
                reactor.stop()
                return
            wait = 300 - time.time() % 300 + 8
            reactor.callLater(wait, lambda: tick().addBoth(after))
        tick().addBoth(after)

    d = feed.connect()
    d.addCallbacks(lambda _: loop(), lambda f: (print(f"Collegamento non riuscito: {f.getErrorMessage()}"), reactor.stop()))
    reactor.run()


if __name__ == "__main__":
    main()
