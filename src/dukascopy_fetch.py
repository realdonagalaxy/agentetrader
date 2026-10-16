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
SCALES = {"JPY": 1e3, "XAU": 1e3, "XAG": 1e3, "IDX": 1e3, "BTC": 10, "ETH": 10}  # default 1e5 (forex); BTC/ETH verificati; indici da verificare
CRYPTO = ("BTC", "ETH")                                                       # mercato 24/7: scaricare anche il sabato
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
    try:
        raw = lzma.decompress(content)
    except lzma.LZMAError:
        (cache_dir / "bi5" / sym / side / f"{day:%Y%m%d}.bi5").unlink(missing_ok=True)   # file corrotto: riscarica al prossimo giro
        return None
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
        days = [d0 + timedelta(n) for n in range((d1 - d0).days + 1)
                if sym.startswith(CRYPTO) or (d0 + timedelta(n)).weekday() != 5]
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
    ap.add_argument("--rounds", type=int, default=5, help="tentativi complessivi sugli anni falliti")
    a = ap.parse_args()
    start_d, end_d = date.fromisoformat(a.start), date.fromisoformat(a.end)
    for rnd in range(1, a.rounds + 1):
        if fetch_range(a.symbol, start_d, end_d, a.side, a.out):
            break
        if rnd < a.rounds:
            print(f"Giro {rnd}/{a.rounds}: alcuni anni mancano, riprovo tra 120 secondi...", flush=True)
            time.sleep(120)
    missing = [y for y in range(start_d.year, end_d.year + 1)
               if not (Path(a.out) / f"{a.symbol}_{a.side}_M1_{y}.csv").exists()]
    print("COMPLETO" if not missing else f"ANNI MANCANTI: {missing} (nessun dato disponibile oppure ancora bloccato: rilancia più tardi)")
