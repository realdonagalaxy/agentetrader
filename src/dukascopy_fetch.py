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


def _download(url: str, cache: Path, session: requests.Session) -> bytes | None:
    """Bytes del .bi5 (b'' = nessun dato, es. festivo). None = fallito. Cache su disco; rispetta i 429."""
    if cache.exists():
        return cache.read_bytes()
    for attempt in range(8):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404:
                data = b""
            elif r.status_code == 429:
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            else:
                r.raise_for_status()
                data = r.content
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
            return data
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def fetch_day(sym: str, day: date, side: str, session: requests.Session, cache_dir: Path):
    """Lista di barre M1 del giorno, oppure None se il download è fallito."""
    url = URL.format(sym=sym, y=day.year, m=day.month - 1, d=day.day, side=side)
    cache = cache_dir / "bi5" / sym / side / f"{day:%Y%m%d}.bi5"
    content = _download(url, cache, session)
    if content is None:
        return None
    if not content:
        return []
    raw = lzma.decompress(content)
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    sc = scale_for(sym)
    out = []
    for off in range(0, len(raw), REC.size):
        sec, o, c, l, h, v = REC.unpack_from(raw, off)
        out.append((base + timedelta(seconds=sec), o / sc, h / sc, l / sc, c / sc, v))
    return out


def fetch_range(sym: str, start: date, end: date, side: str = "BID", out: str = "data/raw", threads: int = 3) -> bool:
    """Un CSV per anno. Un anno con giorni falliti NON viene scritto (rilanciare per riprendere dalla cache)."""
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = True
    for year in range(start.year, end.year + 1):
        path = out_dir / f"{sym}_{side}_M1_{year}.csv"
        if path.exists():
            continue
        d0, d1 = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
        days = [d0 + timedelta(n) for n in range((d1 - d0).days + 1) if (d0 + timedelta(n)).weekday() != 5]
        with requests.Session() as s, ThreadPoolExecutor(threads) as ex:
            res = list(ex.map(lambda d: fetch_day(sym, d, side, s, out_dir), days))
        failed = [d for d, r in zip(days, res) if r is None]
        if failed:
            ok = False
            print(f"{year}: {len(failed)} giorni falliti (es. {failed[0]}) - anno NON scritto, rilancia", file=sys.stderr, flush=True)
            continue
        df = pd.DataFrame([r for chunk in res for r in chunk], columns=["time", "open", "high", "low", "close", "volume"])
        df.to_csv(path, index=False)
        print(f"{year}: {len(df)} barre M1 -> {path}", flush=True)
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("start")
    ap.add_argument("end")
    ap.add_argument("--side", default="BID")
    ap.add_argument("--out", default="data/raw")
    a = ap.parse_args()
    fetch_range(a.symbol, date.fromisoformat(a.start), date.fromisoformat(a.end), a.side, a.out)
