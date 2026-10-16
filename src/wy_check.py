"""Controllo completo SDP-Wyckoff su uno strumento: dati, confronto con il placebo, anno per anno, sensibilità ai costi.

Uso (dalla cartella del progetto, con data/<SIMBOLO>_BID_M5.csv.gz presente):
  python3 -m src.wy_check XAUUSD            # struttura M5
Produce solo testo: copia l'intero risultato in chat.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest_engine import simulate_trades
from src.data_loader import load_ohlc
from src.live_analysis import pip_size
from src.market_config import macro_at
from src.sdp_strategy import with_rr
from src.sdp_wyckoff import WyParams, generate


def main(sym: str, tf: int = 5, tol: float = 0.25) -> None:
    m5 = load_ohlc(f"data/{sym}_BID_M5.csv.gz")
    yrs = m5.groupby(m5.index.year).size()
    print(f"=== DATI {sym} ===")
    print(f"barre M5: {len(m5)} · {m5.index[0]} → {m5.index[-1]}")
    print(f"prezzo (close) min {m5.close.min():.4g} · max {m5.close.max():.4g} · ultimo {m5.close.iloc[-1]:.4g}")
    print("barre per anno:", {int(y): int(n) for y, n in yrs.items()})
    gaps = m5.index.to_series().diff().dropna()
    big = gaps[gaps > pd.Timedelta("4D")]
    print(f"buchi > 4 giorni: {len(big)}" + (f" (es. {big.index[0]})" if len(big) else ""))

    pk = Path(f"data/wy_signals_{sym}_M{tf}_tol{tol}.pkl")
    if pk.exists():
        sig = pd.read_pickle(pk)
    else:
        print("\ngenero i segnali (alcuni minuti)...", flush=True)
        sig = generate(m5, WyParams(struct_tf_min=tf, tol=tol))
        sig.to_pickle(pk)
    sig = sig[sig.kind == "signal"].copy() if "kind" in sig else sig.copy()
    crypto = sym.startswith(("BTC", "ETH"))
    sig["macro"] = [macro_at(t.to_pydatetime()) for t in sig.index]
    scope = sig if crypto else sig[sig.macro.notna()]
    print(f"\n=== CONFRONTO (struttura M{tf}, tol {tol} ATR, {'tutte le ore (crypto: finestre macro proprie da testare a parte)' if crypto else 'solo macro Londra+NY'}, TP 1:2) ===")
    variants = {"PLACEBO: qualsiasi CHoCH": pd.Series(True, index=scope.index),
                "solo Kill Zone (no Wyckoff)": scope.in_kz,
                "Wyckoff + volume (solo)": scope.wy_vol,
                "KZ + Wyckoff + volume": scope.in_kz & scope.wy_vol,
                "Wyckoff senza volume": scope.wy_div}
    res = {}
    for name, mask in variants.items():
        x = scope[mask].reset_index().groupby("sid").head(1).set_index("time").sort_index()
        if len(x) < 30:
            print(f"{name:30s} n={len(x)} (troppo pochi)")
            continue
        t = simulate_trades(m5, with_rr(x, 2.0), with_trend=False)
        t["risk_pips"] = (t.entry - t.sl).abs() / pip_size(sym)
        res[name] = t
        se = t.R.std() / np.sqrt(len(t))
        print(f"{name:30s} n={len(t):6d} expectancy={t.R.mean():+.3f}R (±{se:.3f}) win={(t.R > 0).mean():.3f}", flush=True)
    for name in ("Wyckoff + volume (solo)", "KZ + Wyckoff + volume"):
        if name not in res:
            continue
        t = res[name]
        yr = t.groupby(t.time.dt.year).R.agg(["count", "mean"])
        half = len(t) // 2
        print(f"\n--- {name} ---")
        print(f"anni positivi {int((yr['mean'] > 0).sum())}/{len(yr)} · prima metà {t.R.iloc[:half].mean():+.3f}R · seconda metà {t.R.iloc[half:].mean():+.3f}R")
        print("per anno:", {int(y): round(float(m), 2) for y, m in yr["mean"].items()})
        print(f"rischio mediano: {t.risk_pips.median():.1f} pip (1 pip = {pip_size(sym)})")
        for cost in (0.2, 0.5, 1.0):
            adj = t.R - cost / t.risk_pips
            print(f"  costo {cost} pip/trade → expectancy {adj.mean():+.3f}R (±{adj.std() / np.sqrt(len(adj)):.3f})")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 5)
