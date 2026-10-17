"""Reazione ai livelli del Fixed Range Volume Profile di una gamba H1 + evidenza CHoCH M5.

Regole (utente, 17 ott 2026; i punti marcati ASSUNZIONE sono miei e vanno confermati):
 - struttura H1 da pivot a 2 barre per lato (HH/HL/LH/LL);
 - fase ribassista: l'ultimo swing low è un LL e l'ultimo swing high prima di esso è un LH -> gamba completata LH -> LL;
   fase rialzista: specchio (gamba HL -> HH);
 - profilo dei volumi (tick) a range fisso su quella gamba: POC, VAH, VAL (area di valore 70%);  ASSUNZIONE: livelli POC/VAH/VAL + controllo "50%" senza volumi
 - ritracciamento: il prezzo risale (ribassista) / scende (rialzista) verso la gamba e tocca un livello (ASSUNZIONE: tolleranza 0,25 ATR M15);
 - evidenza M5: CHoCH come in v3 (ASSUNZIONE), ingresso a mercato alla chiusura della candela del CHoCH, SL oltre l'estremo del ritracciamento dal tocco;
 - TP = fine della gamba (l'LL, o l'HH). ASSUNZIONE: R:R minimo 2,0; un solo trade per gamba e livello; setup valido fino a 5 giorni;
   annullato se il prezzo supera l'inizio della gamba (LH/HL) o fa un nuovo estremo oltre la fine della gamba prima dell'ingresso.
Costi ignorati. Nessun look-ahead: la gamba è nota solo 2 barre H1 dopo il suo ultimo pivot.
"""
from bisect import bisect_right
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest_engine import evaluate
from src.chart import volume_profile
from src.data_loader import load_ohlc, resample
from src.range_detector import atr, pivots


@dataclass
class FParams:
    n_h1: int = 2
    n_m5: int = 2
    tol_atr: float = 0.25         # tolleranza del tocco, x ATR14 M15
    choch_wait: int = 48          # barre M5 dal tocco al CHoCH
    valid_bars: int = 1440        # 5 giorni di barre M5
    min_rr: float = 2.0


LEVELS = ("POC", "VAH", "VAL", "MID")


def generate(m5: pd.DataFrame, p: FParams = FParams(), stats: dict | None = None) -> pd.DataFrame:
    st = stats if stats is not None else {}
    bump = lambda k: st.__setitem__(k, st.get(k, 0) + 1)
    h1 = resample(m5, "1h")
    ph1, pl1 = pivots(h1, p.n_h1)
    swings = sorted([(int(i), "H", float(h1["high"].iloc[i])) for i in ph1] + [(int(i), "L", float(h1["low"].iloc[i])) for i in pl1])
    alt: list = []
    for i, k, v in swings:                                   # alternanza H/L: tra due dello stesso tipo resta il più estremo
        if alt and alt[-1][1] == k:
            if (k == "H" and v > alt[-1][2]) or (k == "L" and v < alt[-1][2]):
                alt[-1] = (i, k, v)
            continue
        alt.append((i, k, v))

    t5 = m5.index.values
    N = len(m5)
    Hh, Ll, Cc = (m5[c].to_numpy() for c in ("high", "low", "close"))
    a15 = atr(resample(m5, "15min")).reindex(m5.index, method="ffill").to_numpy()
    ph5, pl5 = (list(x) for x in pivots(m5, p.n_m5))
    hour = pd.Timedelta(hours=1)
    out, sid = [], 0
    for k in range(3, len(alt)):
        a3, a2, a1, a0 = alt[k - 3], alt[k - 2], alt[k - 1], alt[k]
        if a0[1] == "L" and a0[2] < a2[2] and a1[2] < a3[2]:
            sgn = -1                                          # ribassista: LH -> LL, ingresso SELL
        elif a0[1] == "H" and a0[2] > a2[2] and a1[2] > a3[2]:
            sgn = 1                                           # rialzista: HL -> HH, ingresso BUY
        else:
            continue
        bump("gambe")
        t_leg0, t_leg1 = h1.index[a1[0]], h1.index[a0[0]] + hour
        if a0[0] + p.n_h1 >= len(h1):
            continue
        c0 = int(np.searchsorted(t5, (h1.index[a0[0] + p.n_h1] + hour).to_datetime64()))
        if c0 >= N - 2 or np.isnan(a15[c0]):
            continue
        vp = volume_profile(m5, t_leg0, t_leg1)
        if not vp:
            continue
        _, _, _, poc, val, vah = vp
        lo_leg, hi_leg = min(a0[2], a1[2]), max(a0[2], a1[2])
        prices = {"POC": poc, "VAH": vah, "VAL": val, "MID": (lo_leg + hi_leg) / 2}
        # coordinate "da long": per i SELL i prezzi sono cambiati di segno
        adv, fav, cl = (Ll, Hh, Cc) if sgn == 1 else (-Hh, -Ll, -Cc)
        piv, advp = (ph5, pl5) if sgn == 1 else (pl5, ph5)
        start_adv = a1[2] if sgn == 1 else -a1[2]            # inizio della gamba (HL o LH): se il prezzo lo supera, il setup è finito
        tp_l = a0[2] if sgn == 1 else -a0[2]                  # fine della gamba (HH o LL)
        end = min(c0 + p.valid_bars, N - 1)
        seg_adv, seg_fav = adv[c0:end + 1], fav[c0:end + 1]
        bad = (seg_adv < start_adv) | (seg_fav > tp_l)
        jend = c0 + (int(bad.argmax()) if bad.any() else len(seg_adv))
        tol = p.tol_atr * a15[c0]
        sid += 1
        for name, price in prices.items():
            lv = sgn * price
            if not (start_adv < lv < tp_l):
                continue
            rng = np.arange(c0 + 1, jend)
            cross = rng[(adv[rng] <= lv + tol) & (adv[rng - 1] > lv + tol)]
            if not len(cross):
                continue
            tj = int(cross[0])
            bump(f"tocco {name}")
            sw_low, sw_idx = np.inf, None
            for j in range(tj, min(tj + p.choch_wait, jend - 1) + 1):
                if adv[j] < sw_low:
                    sw_low, sw_idx = adv[j], j
                if j <= sw_idx:
                    continue
                q = bisect_right(advp, j - p.n_m5) - 1
                if q < 0 or advp[q] < sw_idx:
                    continue
                pt = advp[q]
                mm = bisect_right(piv, pt - 1) - 1
                if mm < 0:
                    continue
                ref = fav[piv[mm]]
                if not (cl[j] > ref and cl[j] > adv[pt]):
                    continue
                risk = cl[j] - sw_low
                if risk <= 0 or tp_l <= cl[j]:
                    break
                rr = (tp_l - cl[j]) / risk
                if rr < p.min_rr:
                    bump(f"R:R sotto minimo {name}")
                    break
                bump(f"trade {name}")
                out.append({"time": pd.Timestamp(t5[j]), "sid": sid, "level": name, "side": "buy" if sgn == 1 else "sell",
                            "entry": sgn * cl[j], "sl": sgn * sw_low, "tp": sgn * tp_l, "rr": rr, "leg_t0": t_leg0, "leg_t1": t_leg1})
                break
    return pd.DataFrame(out).sort_values("time").reset_index(drop=True) if out else pd.DataFrame()


def simulate(m5: pd.DataFrame, sig: pd.DataFrame, horizon: int = 8640) -> pd.DataFrame:
    """R per trade (SL -1R, TP +rr R; stessa barra: prima lo SL). Trade non risolti entro `horizon` barre scartati."""
    Hh, Ll = m5["high"].to_numpy(), m5["low"].to_numpy()
    idx = m5.index
    rows = []
    for r in sig.itertuples():
        i = idx.get_loc(r.time)
        hi, lo = Hh[i + 1:i + 1 + horizon], Ll[i + 1:i + 1 + horizon]
        if r.side == "buy":
            hs, ht = lo <= r.sl, hi >= r.tp
        else:
            hs, ht = hi >= r.sl, lo <= r.tp
        isl, itp = (int(hs.argmax()) if hs.any() else None), (int(ht.argmax()) if ht.any() else None)
        if isl is None and itp is None:
            continue
        R = -1.0 if (itp is None or (isl is not None and isl <= itp)) else r.rr
        rows.append({"time": r.time, "side": r.side, "R": R, "rr": r.rr, "level": r.level, "sid": r.sid})
    return pd.DataFrame(rows)


def placebo(m5: pd.DataFrame, sig: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Stessi lato, rischio e R:R su barre casuali (±1–30 giorni)."""
    rng = np.random.default_rng(seed)
    cl, n = m5["close"].to_numpy(), len(m5)
    rows = []
    for r in sig.itertuples():
        i = m5.index.get_loc(r.time) + int(rng.choice([-1, 1]) * rng.integers(288, 288 * 30))
        if not 0 <= i < n - 1:
            continue
        e, risk, sg = cl[i], abs(r.entry - r.sl), (1 if r.side == "buy" else -1)
        rows.append({"time": m5.index[i], "side": r.side, "entry": e, "sl": e - sg * risk, "tp": e + sg * r.rr * risk, "rr": r.rr, "level": r.level, "sid": r.sid})
    return pd.DataFrame(rows)


def _line(label, t):
    if len(t) < 30:
        return f"{label:32s} n={len(t)} (troppo pochi" + (f"; media {t.R.mean():+.2f}R)" if len(t) else ")")
    e = evaluate(t)
    a, i_, o_ = e["all"], e["in_sample"], e["out_of_sample"]
    se = t.R.std() / np.sqrt(len(t))
    return (f"{label:32s} n={a['n']:5.0f} win={a['win_rate']:.3f} (pareggio {a['breakeven_win_rate']:.3f}) exp={a['expectancy_R']:+.3f}R (±{se:.3f}) "
            f"PF={a['profit_factor']:.2f} | IS {i_['expectancy_R']:+.3f} OOS {o_['expectancy_R']:+.3f}")


def report(res: pd.DataFrame, m5: pd.DataFrame, sig: pd.DataFrame, label: str) -> None:
    first = res[res.level != "MID"].sort_values("time").groupby("sid").head(1)
    variants = {"profilo (primo tra POC/VAH/VAL)": first, "solo POC": res[res.level == "POC"], "solo VAH": res[res.level == "VAH"],
                "solo VAL": res[res.level == "VAL"], "CONTROLLO: 50% della gamba": res[res.level == "MID"], "tutti i livelli": res}
    print(f"\n--- {label} ---")
    for name, t in variants.items():
        print(_line(name, t.sort_values("time")))
    pl = pd.concat([simulate(m5, placebo(m5, sig, s)) for s in range(5)])
    print(_line("PLACEBO (barre casuali, 5 rip.)", pl.sort_values("time")))
    from src.verdict import print_verdicts, verdict
    print_verdicts([(n_, verdict(t_[["time", "R"]], pl["R"])) for n_, t_ in variants.items()], f"{label}")


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    mode = sys.argv[2] if len(sys.argv) > 2 else "full"          # full | test
    min_rr = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    m5 = load_ohlc(f"data/{sym}_BID_M5.csv.gz")
    if mode == "test":
        m5 = m5.loc["2018":"2019"]
    st: dict = {}
    sig = generate(m5, FParams(min_rr=min_rr), st)
    print(f"{sym} - Funnel:", st, flush=True)
    print(f"dati: {m5.index[0]} → {m5.index[-1]} · trade candidati: {len(sig)} (R:R minimo {min_rr})")
    if len(sig):
        sig.to_pickle(f"data/frvp_signals_{sym}.pkl")
        report(simulate(m5, sig), m5, sig, f"{sym} FRVP H1 + CHoCH M5")
