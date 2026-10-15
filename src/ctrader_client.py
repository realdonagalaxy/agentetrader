"""Client cTrader Open API (Protobuf, via libreria `ctrader-open-api`).

Scheletro: autenticazione app + account e invio di un ordine. Estendere con
sottoscrizione spot/trendbar e callback. Default: ambiente demo.
"""
import os

from dotenv import load_dotenv
from ctrader_open_api import Auth, Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAApplicationAuthReq,
    ProtoOANewOrderReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAOrderType, ProtoOATradeSide
from twisted.internet import reactor

load_dotenv("config.env")


class CTraderClient:
    def __init__(self):
        self.client_id = os.environ["CTRADER_CLIENT_ID"]
        self.secret = os.environ["CTRADER_CLIENT_SECRET"]
        self.token = os.environ["CTRADER_ACCESS_TOKEN"]
        self.account_id = int(os.environ["CTRADER_ACCOUNT_ID"])
        self.env = os.environ.get("CTRADER_ENV", "demo")
        host = EndPoints.PROTOBUF_LIVE_HOST if self.env == "live" else EndPoints.PROTOBUF_DEMO_HOST
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self._on_connected)
        self.client.setMessageReceivedCallback(self._on_message)

    def _on_connected(self, client):
        req = ProtoOAApplicationAuthReq()
        req.clientId, req.clientSecret = self.client_id, self.secret
        client.send(req).addCallbacks(self._auth_account, self._on_error)

    def _auth_account(self, _):
        req = ProtoOAAccountAuthReq()
        req.ctidTraderAccountId, req.accessToken = self.account_id, self.token
        self.client.send(req).addErrback(self._on_error)

    def place_market_order(self, symbol_id: int, side: str, volume: int, sl=None, tp=None):
        if self.env == "live":
            raise PermissionError("Ordini live disabilitati: richiedono conferma esplicita (vedi CLAUDE.md).")
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self.account_id
        req.symbolId, req.volume = symbol_id, volume
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = ProtoOATradeSide.BUY if side.lower() == "buy" else ProtoOATradeSide.SELL
        if sl is not None:
            req.stopLoss = sl
        if tp is not None:
            req.takeProfit = tp
        return self.client.send(req)

    def _on_message(self, client, message):
        print(Protobuf.extract(message))

    def _on_error(self, failure):
        print("cTrader error:", failure)

    def run(self):
        self.client.startService()
        reactor.run()


if __name__ == "__main__":
    CTraderClient().run()
