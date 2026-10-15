"""Autorizzazione OAuth cTrader Open API: access token e account ID, scritti in config.env (mai stampati).

Prerequisiti in config.env: CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET, (opz.) CTRADER_REDIRECT_URI.
Il redirect URI deve essere uno di quelli registrati nell'app sul portale Open API (es. http://localhost).

  python -m src.ctrader_auth --url                 # 1) stampa il link da aprire nel browser e autorizzare
  python -m src.ctrader_auth --code CODICE         # 2) scambia il codice con il token (salvato in config.env)
  python -m src.ctrader_auth --accounts            # 3) elenca i conti; scegli il demo
  python -m src.ctrader_auth --set-account ID      # 4) salva CTRADER_ACCOUNT_ID e CTRADER_ENV
"""
import argparse
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests
from dotenv import load_dotenv

ENV = Path("config.env")
load_dotenv(ENV)
AUTH_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
TOKEN_URL = "https://openapi.ctrader.com/apps/token"
ACCOUNTS_URL = "https://api.spotware.com/connect/tradingaccounts"


def _set_env(key: str, value: str) -> None:
    text = ENV.read_text() if ENV.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.M)
    else:
        text += ("" if text.endswith("\n") or not text else "\n") + line + "\n"
    ENV.write_text(text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="store_true")
    ap.add_argument("--code", help="codice, oppure l'intero indirizzo a cui sei stato reindirizzato")
    ap.add_argument("--accounts", action="store_true")
    ap.add_argument("--set-account")
    a = ap.parse_args()
    cid, secret = os.environ.get("CTRADER_CLIENT_ID", ""), os.environ.get("CTRADER_CLIENT_SECRET", "")
    redirect = os.environ.get("CTRADER_REDIRECT_URI", "http://localhost")

    if a.url:
        print(f"{AUTH_URL}?client_id={cid}&redirect_uri={quote(redirect, safe='')}&scope=trading&product=web")
    if a.code:
        code = a.code
        if code.startswith("http"):
            code = parse_qs(urlparse(code).query).get("code", [""])[0]
        r = requests.get(TOKEN_URL, params={"grant_type": "authorization_code", "code": code,
                                            "redirect_uri": redirect, "client_id": cid, "client_secret": secret}, timeout=20)
        d = r.json()
        if not d.get("accessToken"):
            raise SystemExit(f"Errore: {d.get('errorCode') or d}")
        _set_env("CTRADER_ACCESS_TOKEN", d["accessToken"])
        if d.get("refreshToken"):
            _set_env("CTRADER_REFRESH_TOKEN", d["refreshToken"])
        print(f"Token salvato in config.env (scade tra {d.get('expiresIn', '?')} s).")
    if a.accounts:
        token = os.environ.get("CTRADER_ACCESS_TOKEN") or ""
        r = requests.get(ACCOUNTS_URL, params={"access_token": token}, timeout=20)
        r.raise_for_status()
        for acc in r.json():
            kind = "LIVE" if acc.get("live") else "DEMO"
            print(f"accountId={acc.get('accountId')}  numero={acc.get('accountNumber')}  {kind}  broker={acc.get('brokerTitle', '')}")
    if a.set_account:
        _set_env("CTRADER_ACCOUNT_ID", a.set_account)
        _set_env("CTRADER_ENV", "demo")
        print("CTRADER_ACCOUNT_ID salvato, CTRADER_ENV=demo.")


if __name__ == "__main__":
    main()
