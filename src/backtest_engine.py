"""Engine di backtesting vettoriale su barre OHLC.

Una strategia è una funzione che riceve il DataFrame e restituisce una Series
di segnali: +1 long, -1 short, 0 flat (valutati alla chiusura, eseguiti alla barra successiva).
"""
from typing import Callable

import numpy as np
import pandas as pd

from src.market_config import SESSIONS_UTC, session_label
from src.market_structure import is_countertrend, multi_tf_trend


def load_data(path: str = "data/historical_ticks.csv", rule: str | None = "1h") -> pd.DataFrame:
    """CSV atteso: timestamp,bid[,ask][,volume] oppure timestamp,open,high,low,close[,volume]."""
    df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp").sort_index()
    if "close" not in df.columns:
        price = df["bid"]
        agg = {"volume": "sum"} if "volume" in df.columns else {}
        ohlc = price.resample(rule).ohlc()
        df = ohlc.join(df.resample(rule).agg(agg)) if agg else ohlc
    return df.dropna()


def run_backtest(df: pd.DataFrame, strategy: Callable[[pd.DataFrame], pd.Series]) -> dict:
    """Backtest vettoriale su rendimenti. Costi ignorati (per ora)."""
    signal = strategy(df).shift(1).fillna(0)  # evita look-ahead
    ret = df["close"].pct_change().fillna(0)
    turnover = signal.diff().abs().fillna(0)
    strat_ret = signal * ret
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


# ---------- Backtest orientato a Rischio/Rendimento (in multipli di R, costi ignorati) ----------

def simulate_trades(df: pd.DataFrame, signals: pd.DataFrame,
                    sessions: tuple[str, ...] = tuple(SESSIONS_UTC), with_trend: bool = True) -> pd.DataFrame:
    """Simula trade con SL/TP fissi.

    df: OHLC con indice datetime (UTC).
    signals: indice = barra di segnale; colonne `side` ('buy'/'sell'), `sl`, `tp` (+ eventuali colonne extra, riportate).
    Ingresso alla chiusura della barra di segnale; SL/TP valutati dalla barra successiva.
    Se SL e TP sono toccati nella stessa barra si assume SL (ipotesi prudente).
    Trade non risolti a fine dati vengono scartati. Solo segnali nelle `sessions` indicate.
    with_trend=True calcola il trend H4/H1 per ogni trade (lento; richiede df H1).
    """
    hi, lo, cl = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    extra = [c for c in signals.columns if c not in ("side", "sl", "tp")]
    rows = []
    for t, sig in signals.sort_index().iterrows():
        if t not in df.index:
            continue
        label = session_label(t.to_pydatetime())
        if not any(x in label.split("+") for x in sessions):
            continue
        i = df.index.get_loc(t)
        entry, sl, tp, side = cl[i], sig["sl"], sig["tp"], sig["side"].lower()
        risk = abs(entry - sl)
        if risk == 0 or (side == "buy") != (sl < entry):
            continue
        if side == "buy":
            hit_sl, hit_tp = lo[i + 1:] <= sl, hi[i + 1:] >= tp
        else:
            hit_sl, hit_tp = hi[i + 1:] >= sl, lo[i + 1:] <= tp
        isl = hit_sl.argmax() if hit_sl.any() else None
        itp = hit_tp.argmax() if hit_tp.any() else None
        if isl is None and itp is None:
            continue
        r = -1.0 if (itp is None or (isl is not None and isl <= itp)) else abs(tp - entry) / risk
        row = {"time": t, "side": side, "entry": entry, "sl": sl, "tp": tp, "R": r,
               "planned_RR": abs(tp - entry) / risk, "session": label}
        row.update({k: sig[k] for k in extra})
        if with_trend:
            tr = multi_tf_trend(df.iloc[: i + 1])
            row.update(trend_h4=tr["H4"], trend_h1=tr["H1"], countertrend=is_countertrend(side, tr["bias"]))
        rows.append(row)
    return pd.DataFrame(rows)


def rr_metrics(trades: pd.DataFrame) -> dict:
    """Metriche di rischio/rendimento sui multipli di R."""
    if trades.empty:
        return {"n": 0}
    r = trades["R"]
    wins, losses = r[r > 0], r[r < 0]
    eq = r.cumsum()
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = abs(losses.mean()) if len(losses) else 1.0
    return {
        "n": len(r),
        "win_rate": len(wins) / len(r),
        "avg_win_R": avg_win,
        "avg_loss_R": avg_loss,
        "payoff_ratio": avg_win / avg_loss if avg_loss else np.nan,
        "breakeven_win_rate": 1 / (1 + avg_win / avg_loss) if avg_win else np.nan,
        "expectancy_R": r.mean(),
        "profit_factor": wins.sum() / abs(losses.sum()) if len(losses) else np.inf,
        "total_R": r.sum(),
        "max_drawdown_R": (eq - eq.cummax()).min(),
        "longest_losing_streak": int((r < 0).astype(int).groupby((r >= 0).cumsum()).sum().max()),
    }


def evaluate(trades: pd.DataFrame, oos_frac: float = 0.3) -> dict:
    """Metriche totali, In-Sample vs Out-of-Sample (ultima quota cronologica) e spaccati per sessione/trend."""
    trades = trades.sort_values("time").reset_index(drop=True)
    cut = int(len(trades) * (1 - oos_frac))
    out = {"all": rr_metrics(trades), "in_sample": rr_metrics(trades.iloc[:cut]),
           "out_of_sample": rr_metrics(trades.iloc[cut:])}
    if len(trades) and out["in_sample"].get("n", 0) and out["out_of_sample"].get("n", 0):
        out["oos_warning"] = out["out_of_sample"]["expectancy_R"] < 0.5 * out["in_sample"]["expectancy_R"]
    for col in ("session", "countertrend"):
        if col in trades:
            out[f"by_{col}"] = {str(k): rr_metrics(g) for k, g in trades.groupby(col)}
    return out


if __name__ == "__main__":
    res = run_backtest(load_data(), sma_cross())
    print({k: v for k, v in res.items() if k != "equity"})
