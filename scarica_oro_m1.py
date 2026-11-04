"""Scarica le barre M1 dell'oro (XAUUSD, prezzo BID) da Dukascopy in un unico file CSV, usando SOLO la libreria standard di Python (niente pandas, numpy o requests).
Serve quando Windows blocca i file di pandas: il risultato è un CSV (time, open, high, low, close, volume, orario UTC) che poi si carica come qualunque altro dato.

Uso:   python scarica_oro_m1.py 2026-08-20 2026-11-03 [--out data/raw] [--simbolo XAUUSD] [--lato BID]
Scrive: <out>/XAUUSD_BID_M1_<inizio>_<fine>.csv   (i file giornalieri scaricati restano in <out>/bi5 come cache: se si ferma, rilanciando si riprende da dove era arrivato)
Il giorno in corso non è disponibile su Dukascopy: l'ultima data utile è ieri. Il sabato non si scarica (mercato chiuso).
"""
import argparse
import csv
import lzma
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/{side}_candles_min_1.bi5"       # il mese nell'indirizzo parte da 0 (gennaio = 00)
REC = struct.Struct(">IIIIIf")                                                                            # secondi dall'inizio del giorno, open, close, low, high, volume
SCALE = 1e3                                                                                               # prezzi dell'oro: intero / 1000


def parse_bi5(content: bytes, day: date) -> list[tuple]:
    """Barre M1 di un giorno da un file .bi5 (compresso LZMA). Lista vuota se il file è vuoto (festivo)."""
    if not content:
        return []
    raw = lzma.decompress(content)
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    out = []
    for off in range(0, len(raw) - REC.size + 1, REC.size):
        sec, o, c, l, h, v = REC.unpack_from(raw, off)
        out.append((base + timedelta(seconds=sec), o / SCALE, h / SCALE, l / SCALE, c / SCALE, v))
    return out


def download(url: str, cache: Path) -> bytes | None:
    """Bytes del giorno (b'' = nessun dato). None = fallito. Usa la cache su disco e rispetta i limiti del sito."""
    if cache.exists():
        return cache.read_bytes()
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = b""
            elif e.code == 429:
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            else:
                time.sleep(2 * (attempt + 1))
                continue
        except Exception:
            time.sleep(2 * (attempt + 1))
            continue
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
        return data
    return None


def fetch_day(sym: str, day: date, side: str, out: Path):
    cache = out / "bi5" / sym / side / f"{day:%Y%m%d}.bi5"
    content = download(URL.format(sym=sym, y=day.year, m=day.month - 1, d=day.day, side=side), cache)
    if content is None:
        return None
    try:
        return parse_bi5(content, day)
    except lzma.LZMAError:
        cache.unlink(missing_ok=True)                                  # file corrotto: si riscarica al prossimo giro
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("start")
    ap.add_argument("end")
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--simbolo", default="XAUUSD")
    ap.add_argument("--lato", default="BID")
    a = ap.parse_args()
    d0, d1 = date.fromisoformat(a.start), date.fromisoformat(a.end)
    if d1 >= date.today():
        d1 = date.today() - timedelta(days=1)
        print(f"Il giorno in corso non è disponibile: mi fermo a {d1}.")
    out = Path(a.out)
    days = [d0 + timedelta(n) for n in range((d1 - d0).days + 1) if (d0 + timedelta(n)).weekday() != 5]
    print(f"Scarico {len(days)} giorni di {a.simbolo} {a.lato} da {d0} a {d1}…", flush=True)
    done = [0]
    def job(day):
        r = fetch_day(a.simbolo, day, a.lato, out)
        done[0] += 1
        if done[0] % 10 == 0 or done[0] == len(days):
            print(f"  {done[0]}/{len(days)}", flush=True)
        return r
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(job, days))
    failed = [d for d, r in zip(days, res) if r is None]
    if failed:
        sys.exit(f"{len(failed)} giorni non scaricati (primo: {failed[0]}). Il file NON è stato scritto: rilancia lo stesso comando, riprende dalla cache.")
    path = out / f"{a.simbolo}_{a.lato}_M1_{d0:%Y%m%d}_{d1:%Y%m%d}.csv"
    n = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for chunk in res:
            for t, o, h, l, c, v in chunk:
                w.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), f"{o:.3f}", f"{h:.3f}", f"{l:.3f}", f"{c:.3f}", f"{v:.5f}"])
                n += 1
    print(f"Fatto: {n} barre M1 in {path}")


if __name__ == "__main__":
    main()
