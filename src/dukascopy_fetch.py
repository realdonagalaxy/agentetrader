"""Scarica candele M1 BID/ASK da datafeed.dukascopy.com (file giornalieri .bi5) e le salva per anno.

Uso: python -m src.dukascopy_fetch EURUSD 2003-05-01 2025-12-31 [--side BID|ASK] [--out data/raw]
Record da 24 byte (big-endian): sec dall'inizio del giorno UTC, open, close, low, high (int, prezzo*scala), volume float.
"""
import argparse
import lzma
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/{side}_candles_min_1.bi5"
SCALES = {"JPY": 1e3, "XAU": 1e3, "XAG": 1e3}  # default 1e5 (indici/altri simboli: da verificare per simbolo)
REC = struct.Struct(">IIIIIf")


def scale_for(sym: str) -> float:
    return next((v for k, v in SCALES.items() if k in sym), 1e5)


def fetch_day(sym: str, day: date, side: str, session: requests.Session) -> list[tuple]:
    url = URL.format(sym=sym, y=day.year, m=day.month - 1, d=day.day, side=side)
    for attempt in range(5):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404 or not r.content:
                return []
            r.raise_for_status()
            raw = lzma.decompress(r.content)
            base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            sc = scale_for(sym)
            out = []
            for off in range(0, len(raw), REC.size):
                s, o, c, l, h, v = REC.unpack_from(raw, off)
                out.append((base + timedelta(seconds=s), o / sc, h / sc, l / sc, c / sc, v))
            return out
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    print(f"FALLITO {day}", file=sys.stderr)
    return []


def fetch_range(sym: str, start: date, end: date, side: str = "BID", out: str = "data/raw", threads: int = 16) -> None:
    Path(out).mkdir(parents=True, exist_ok=True)
    for year in range(start.year, end.year + 1):
        path = Path(out) / f"{sym}_{side}_M1_{year}.csv"
        if path.exists():
            continue
        d0, d1 = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
        days = [d0 + timedelta(n) for n in range((d1 - d0).days + 1) if (d0 + timedelta(n)).weekday() != 5]
        with requests.Session() as s, ThreadPoolExecutor(threads) as ex:
            rows = [r for chunk in ex.map(lambda d: fetch_day(sym, d, side, s), days) for r in chunk]
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        df.to_csv(path, index=False)
        print(f"{year}: {len(df)} barre M1 -> {path}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("start")
    ap.add_argument("end")
    ap.add_argument("--side", default="BID")
    ap.add_argument("--out", default="data/raw")
    a = ap.parse_args()
    fetch_range(a.symbol, date.fromisoformat(a.start), date.fromisoformat(a.end), a.side, a.out)
