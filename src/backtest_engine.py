"""Engine di backtesting vettoriale su barre OHLC.

Una strategia è una funzione che riceve il DataFrame e restituisce una Series
di segnali: +1 long, -1 short, 0 flat (valutati alla chiusura, eseguiti alla barra successiva).
"""
from typing import Callable

import numpy as np
import pandas as pd


def load_data(path: str = "data/historical_ticks.csv", rule: str | None = "1h") -> pd.DataFrame:
    """CSV atteso: timestamp,bid[,ask][,volume] oppure timestamp,open,high,low,close[,volume]."""
    df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp").sort_index()
    if "close" not in df.columns:
        price = df["bid"]
        agg = {"volume": "sum"} if "volume" in df.columns else {}
        ohlc = price.resample(rule).ohlc()
        df = ohlc.join(df.resample(rule).agg(agg)) if agg else ohlc
    return df.dropna()


def run_backtest(df: pd.DataFrame, strategy: Callable[[pd.DataFrame], pd.Series],
                 cost: float = 0.0) -> dict:
    """cost = costo per cambio posizione (frazione del prezzo, es. spread+commissioni)."""
    signal = strategy(df).shift(1).fillna(0)  # evita look-ahead
    ret = df["close"].pct_change().fillna(0)
    turnover = signal.diff().abs().fillna(0)
    strat_ret = signal * ret - turnover * cost
    equity = (1 + strat_ret).cumprod()
    dd = equity / equity.cummax() - 1
    trades = strat_ret[turnover > 0]
    std = strat_ret.std()
    return {
        "return": equity.iloc[-1] - 1,
        "max_drawdown": dd.min(),
        "sharpe": np.sqrt(252 * 24) * strat_ret.mean() / std if std else 0.0,  # barre orarie
        "n_position_changes": int((turnover > 0).sum()),
        "hit_rate": float((strat_ret[signal != 0] > 0).mean()) if (signal != 0).any() else 0.0,
        "equity": equity,
    }


def sma_cross(fast: int = 20, slow: int = 50) -> Callable[[pd.DataFrame], pd.Series]:
    """Strategia d'esempio per testare il motore."""
    def _s(df: pd.DataFrame) -> pd.Series:
        return np.sign(df["close"].rolling(fast).mean() - df["close"].rolling(slow).mean()).fillna(0)
    return _s


if __name__ == "__main__":
    res = run_backtest(load_data(), sma_cross(), cost=0.0001)
    print({k: v for k, v in res.items() if k != "equity"})
