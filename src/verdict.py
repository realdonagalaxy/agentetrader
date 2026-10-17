"""Verdetto automatico "c'è un vantaggio statistico?" per un gruppo di trade, confrontato con il placebo.

Criteri (fissati prima di guardare i numeri):
  1. almeno MIN_N trade;
  2. media almeno MIN_EDGE R sopra il placebo;
  3. distanza dal placebo di almeno Z_MIN errori standard (la differenza ha errore sqrt(se_gruppo² + se_placebo²));
  4. media positiva sia nel campione di sviluppo (primi 70% dei trade nel tempo) sia fuori campione (ultimo 30%).
Resta da fare a mano: conferma su un altro strumento. Con molte combinazioni guardate, la soglia giusta è più vicina a 3 errori.
"""
import numpy as np
import pandas as pd

MIN_N, MIN_EDGE, Z_MIN = 300, 0.10, 2.0


def verdict(t: pd.DataFrame, pl: pd.Series, min_n: int = MIN_N, min_edge: float = MIN_EDGE, z_min: float = Z_MIN) -> dict:
    """t: colonne time, R. pl: R dei trade placebo (stessa uscita). Restituisce le misure e l'esito."""
    t = t.dropna(subset=["R"]).sort_values("time")
    n = len(t)
    pl = pl.dropna()
    out = {"n": n, "mean": np.nan, "pl_mean": float(pl.mean()) if len(pl) else np.nan, "edge": np.nan, "z": np.nan, "is": np.nan, "oos": np.nan, "ok": False, "why": []}
    if n < 2 or len(pl) < 2:
        out["why"] = [f"n={n}"]
        return out
    se, pl_se = t.R.std() / np.sqrt(n), pl.std() / np.sqrt(len(pl))
    out["mean"] = float(t.R.mean())
    out["edge"] = out["mean"] - out["pl_mean"]
    out["z"] = out["edge"] / float(np.sqrt(se ** 2 + pl_se ** 2))
    cut = int(n * 0.7)
    out["is"], out["oos"] = float(t.R.iloc[:cut].mean()), float(t.R.iloc[cut:].mean())
    why = []
    if n < min_n:
        why.append(f"pochi trade ({n}<{min_n})")
    if out["edge"] < min_edge:
        why.append(f"vantaggio sul placebo {out['edge']:+.3f}R < {min_edge:+.2f}R")
    if out["z"] < z_min:
        why.append(f"{out['z']:.1f} errori sopra il placebo (<{z_min:.0f})")
    if not (out["is"] > 0 and out["oos"] > 0):
        why.append(f"segno diverso dentro/fuori campione ({out['is']:+.2f}/{out['oos']:+.2f})")
    out["ok"], out["why"] = not why, why
    return out


def print_verdicts(rows: list[tuple[str, dict]], title: str = "VERDETTO AUTOMATICO") -> None:
    print(f"\n=== {title} (uscita unica; vantaggio = media − placebo) ===")
    print(f"{'gruppo':44s} {'n':>5s} {'bilancio R':>10s} {'media':>7s} {'placebo':>8s} {'diff':>7s} {'z':>5s} {'IS':>6s} {'OOS':>6s}  esito")
    for name, v in rows:
        f = lambda x, w=7, p=3: f"{x:{w}.{p}f}" if np.isfinite(x) else " " * (w - 1) + "-"
        esito = "✅ vantaggio (da confermare su un altro strumento)" if v["ok"] else "❌ " + "; ".join(v["why"])
        print(f"{name:44s} {v['n']:5d} {f(v['mean'] * v['n'] if np.isfinite(v['mean']) else np.nan, 10, 1)} {f(v['mean'])} {f(v['pl_mean'], 8)} {f(v['edge'])} {f(v['z'], 5, 1)} {f(v['is'], 6, 2)} {f(v['oos'], 6, 2)}  {esito}")
