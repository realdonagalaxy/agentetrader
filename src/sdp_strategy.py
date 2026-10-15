"""SDP v0 — Struttura (doppio massimo/minimo M15) + shakeout (Spring/UTAD) + CHoCH M5, a favore del bias H4/H1.

NON è ancora la SDP completa: mancano Leg 1/Leg 2, Kill Zone Fibonacci 1.272–1.618, POI (OB/imbalance), VWAP,
MACD, macro orarie. Tutti i parametri sono PROVVISORI (vedi SDPParams) e vanno validati fuori campione.

Long (mirror per short):
 1. bias H4+H1 = UP (struttura HH/HL), calcolato solo su barre H1 già chiuse;
 2. doppio minimo M15 confermato (livello L);
 3. SHAKEOUT: una barra M5 scende sotto L e una chiusura M5 rientra sopra L entro `reclaim_bars`;
 4. CHoCH M5: chiusura sopra l'ultimo pivot high M5 formatosi prima del minimo dello shakeout -> ingresso a mercato;
 5. SL sotto il minimo della candela H1 che contiene il minimo dello shakeout (fino a quel momento); TP = rr * rischio.
"""
from bisect import bisect_right
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest_engine import evaluate, simulate_trades
from src.data_loader import load_ohlc, resample
from src.market_structure import multi_tf_trend
from src.range_detector import double_extremes, pivots


@dataclass
class SDPParams:
    n_swing: int = 2             # pivot a n barre per lato
    tol: float = 0.25            # tolleranza doppio massimo/minimo (frazione ATR14 M15)
    min_sep_min: int = 30        # distanza minima tra i due picchi (minuti)
    max_sep_min: int = 480       # distanza massima (8 ore = intraday)
    max_wait_bars: int = 144     # barre M5 (12h) entro cui cercare lo shakeout dopo la conferma
    reclaim_bars: int = 12       # barre M5 per rientrare nel livello dopo la rottura
    choch_wait_bars: int = 24    # barre M5 per il CHoCH dopo il rientro
    rr: float = 3.0              # TP = rr * rischio
    bias_h1_bars: int = 400      # finestra H1 per il bias
    require_bias: bool = True


def generate_signals(m5: pd.DataFrame, p: SDPParams = SDPParams()) -> pd.DataFrame:
    m15, h1 = resample(m5, "15min"), resample(m5, "1h")
    dbl = double_extremes(m15, p.n_swing, p.tol, max(2, p.min_sep_min // 15), p.max_sep_min // 15)
    t5 = m5.index.values
    H, L, C = m5["high"].to_numpy(), m5["low"].to_numpy(), m5["close"].to_numpy()
    ph, pl = pivots(m5, p.n_swing)
    ph, pl = list(ph), list(pl)
    bias_cache: dict = {}

    def bias_at(ts: np.datetime64) -> str:
        hour = ts.astype("datetime64[h]")
        if hour not in bias_cache:
            k = h1.index.values.searchsorted(hour)  # barre H1 con inizio < ora corrente = chiuse
            bias_cache[hour] = multi_tf_trend(h1.iloc[max(0, k - p.bias_h1_bars):k])["bias"] if k > 50 else "MISTO"
        return bias_cache[hour]

    out, seen = [], set()
    for d in dbl.itertuples():
        long = d.kind == "bottom"
        # serie "trasformate": per lo short si specchiano i prezzi (-prezzo) cosi' la logica e' unica
        adv, fav, cl = (L, H, C) if long else (-H, -L, -C)  # adv: estremo avverso (basso=più estremo)
        piv = ph if long else pl
        lvl = d.level if long else -d.level
        avail = np.datetime64(d.confirmed) + np.timedelta64(15, "m")
        start = int(np.searchsorted(t5, avail))
        end = min(start + p.max_wait_bars, len(t5) - 1)
        k0 = next((k for k in range(start, end) if adv[k] < lvl), None)
        if k0 is None:
            continue
        sw_low, sw_idx, reclaimed = adv[k0], k0, False
        last = min(k0 + p.reclaim_bars + p.choch_wait_bars, len(t5) - 1)
        for j in range(k0, last + 1):
            if adv[j] < sw_low:
                sw_low, sw_idx, reclaimed = adv[j], j, False
            if not reclaimed and cl[j] > lvl:
                reclaimed = True
            if not reclaimed:
                if j - k0 >= p.reclaim_bars:
                    break
                continue
            m = bisect_right(piv, sw_idx - p.n_swing) - 1
            if m < 0:
                break
            ref = fav[piv[m]]
            if cl[j] > ref and cl[j] > lvl and j > sw_idx:
                key = (t5[j], long)
                if key in seen:
                    break
                seen.add(key)
                h_start = int(np.searchsorted(t5, t5[sw_idx].astype("datetime64[h]")))
                extreme = adv[h_start:j + 1].min()
                risk = cl[j] - extreme
                if risk <= 0:
                    break
                b = bias_at(t5[j])
                if p.require_bias and b != ("UP" if long else "DOWN"):
                    break
                sgn = 1 if long else -1
                out.append({"time": pd.Timestamp(t5[j]), "side": "buy" if long else "sell",
                            "sl": sgn * extreme, "tp": sgn * (cl[j] + p.rr * risk),
                            "bias": b, "level": d.level, "risk_pips": risk * 1e4})
                break
    return pd.DataFrame(out).set_index("time").sort_index() if out else pd.DataFrame()


def run(m5: pd.DataFrame, p: SDPParams = SDPParams()) -> pd.DataFrame:
    sig = generate_signals(m5, p)
    return simulate_trades(m5, sig, with_trend=False) if len(sig) else pd.DataFrame()


if __name__ == "__main__":
    m5 = load_ohlc("data/EURUSD_BID_M5.csv.gz")
    for rr in (1.0, 2.0, 3.0):
        t = run(m5, SDPParams(rr=rr))
        e = evaluate(t)
        keys = ("n", "win_rate", "breakeven_win_rate", "expectancy_R", "profit_factor", "max_drawdown_R")
        for part in ("all", "in_sample", "out_of_sample"):
            print(f"rr={rr} {part:13s}", {k: round(float(e[part][k]), 3) for k in keys})
        print("  oos_warning:", e.get("oos_warning"))
