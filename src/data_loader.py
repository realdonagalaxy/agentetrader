"""Caricamento candele OHLCV da CSV (export piattaforma o dukascopy_downloader)."""
import pandas as pd

_TIME_COLS = ("etc/utc", "date", "timestamp", "time", "datetime", "gmt time")


def load_ohlc(path: str, drop_flat: bool = True) -> pd.DataFrame:
    """Restituisce DataFrame open/high/low/close/volume con indice datetime UTC naive, ordinato e senza duplicati.
    drop_flat: elimina le candele di riempimento (O=H=L=C e volume 0, mercato chiuso: domenica sera / weekend)."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next((c for c in df.columns if c in _TIME_COLS), df.columns[0])
    idx = pd.to_datetime(df.pop(tcol), utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
    df.index = pd.DatetimeIndex(idx, name="time")
    missing = {"open", "high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"{path}: colonne mancanti {sorted(missing)}")
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df = df[[c for c in ("open", "high", "low", "close", "volume") if c in df.columns]].dropna(subset=["close"])
    if drop_flat and "volume" in df:
        flat = (df["volume"] == 0) & (df["open"] == df["high"]) & (df["high"] == df["low"]) & (df["low"] == df["close"])
        df = df[~flat]
    return df


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df:
        agg["volume"] = "sum"
    return df.resample(rule).agg(agg).dropna(subset=["close"])
