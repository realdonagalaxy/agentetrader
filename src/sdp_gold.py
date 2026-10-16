"""SDP-Oro v4 — sequenza Wyckoff dopo la rottura della lateralizzazione (regole dell'utente, 17 ott 2026).

Long (lo short è lo specchio; per i BUY "UT" = spring, "UTAD" = secondo spring):
 1. lateralizzazione (minimi/massimi uguali) + Leg 1 = prima induzione (come v3); Leg 2 = rottura del livello;
 2. MACD (8,21,5) sul grafico M5. Climax (SC/BC) = gobba dell'istogramma con PIÙ VOLUMI tra quelle formate in Leg 2
    (si aggiorna se una gobba successiva ha più volumi);
 3. UT = nuovo estremo oltre l'estremo del climax con una gobba di MENO volumi del climax + CHoCH M5
    (stessa definizione di v3: chiusura oltre l'ultimo pivot di riferimento, dopo l'ultimo test);
    ingresso A MERCATO alla chiusura della candela del CHoCH, SL oltre l'estremo dell'UT, TP1 = 2,5R;
 4. UTAD = seconda spinta oltre l'estremo dell'UT che rientra, con CHoCH M5: BUY/SELL STOP IMMEDIATO al massimo/minimo della
    candela del CHoCH (valido retest_bars barre), SL oltre l'estremo dell'UTAD, TP1 = 2,5R;
 5. gestione: a TP1 (2,5R) chiudi il 60% e SL a pareggio; il resto "scorre" fino alla fine della Leg 1.
ASSUNZIONI da confermare con l'utente: percentuale 60% a 2,5R, TP finale = fine Leg 1, stop pendente al massimo/minimo della candela CHoCH,
UTAD generato anche se l'UT non è andato a pareggio. Costi ignorati.
"""
from bisect import bisect_right
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest_engine import evaluate
from src.data_loader import load_ohlc
from src.range_detector import atr, double_extremes, pivots
from src.sdp_v3 import V3Params
from src.sdp_wyckoff import _lobes
from src.data_loader import resample


@dataclass
class GoldParams(V3Params):
    macd_fast: int = 8
    macd_slow: int = 21
    macd_signal: int = 5
    tp1_r: float = 2.5
    frac: float = 0.6             # quota chiusa a TP1


def generate_gold(m5: pd.DataFrame, p: GoldParams = GoldParams(), stats: dict | None = None, live: bool = False) -> pd.DataFrame:
    tf = p.struct_tf_min
    ms = m5 if tf == 5 else resample(m5, f"{tf}min")
    A = atr(ms).to_numpy()
    dbl = double_extremes(ms, p.n_swing, p.tol, max(2, p.min_sep_min // tf), p.max_sep_min // tf)
    t5, ts = m5.index.values, ms.index.values
    H, L, C = (m5[c].to_numpy() for c in ("high", "low", "close"))
    W = m5["volume"].to_numpy() if "volume" in m5 else np.ones(len(m5))
    ph, pl = (list(x) for x in pivots(m5, p.n_swing))
    cs = m5["close"]
    macd_s = cs.ewm(span=p.macd_fast, adjust=False).mean() - cs.ewm(span=p.macd_slow, adjust=False).mean()
    hist = (macd_s - macd_s.ewm(span=p.macd_signal, adjust=False).mean()).to_numpy()
    st = stats if stats is not None else {}
    bump = lambda k: st.__setitem__(k, st.get(k, 0) + 1)
    out, seen_k0, sid = [], set(), 0
    N = len(t5)
    for d in dbl.itertuples():
        bump("doppi")
        long = d.kind == "bottom"
        sgn = 1 if long else -1
        adv, fav, cl = (L, H, C) if long else (-H, -L, -C)
        piv = ph if long else pl
        advp = pl if long else ph
        lvl = d.level if long else -d.level
        h_ = hist if long else -hist
        start = int(np.searchsorted(t5, np.datetime64(d.confirmed) + np.timedelta64(tf, "m")))
        end = min(start + p.max_wait_bars, N - 1)
        k0 = next((k for k in range(start, end) if adv[k] < lvl), None)
        if k0 is None or (k0, long) in seen_k0:
            continue
        seen_k0.add((k0, long))
        p2 = int(np.searchsorted(t5, np.datetime64(d.t2)))
        p1 = int(np.searchsorted(t5, np.datetime64(d.t1)))
        H0 = fav[p1:p2 + 1].max()
        runmax, b_idx = -np.inf, None
        for k in range(p2 + 1, k0 + 1):
            if b_idx is None:
                if fav[k] > H0:
                    runmax, b_idx = fav[k], k
                continue
            if fav[k] > runmax:
                runmax, b_idx = fav[k], k
            elif adv[k] < runmax - p.leg1_ret * (runmax - lvl):
                break
        if b_idx is None:
            continue
        B = runmax
        length = B - lvl
        i_s = min(int(np.searchsorted(ts, np.datetime64(d.confirmed))), len(A) - 1)
        if not (length >= p.min_leg_atr * A[i_s]):
            continue
        bump("Leg 1 valida")
        sid += 1
        last = min(k0 + p.leg2_bars, N - 1)
        over = next((k for k in range(k0, last + 1) if cl[k] > B), None)    # Leg 2 annullata se il prezzo torna oltre B
        if over is not None:
            last = over - 1
        base = {"sid": sid, "side": "buy" if long else "sell", "level": d.level, "b_price": sgn * B, "leg1_len": length,
                "lat_t1": pd.Timestamp(t5[p1]), "lat_t2": pd.Timestamp(t5[p2]), "lat_hi": sgn * H0, "b_time": pd.Timestamp(t5[b_idx]),
                "kz_lo": sgn * (lvl - (p.fib_hi - 1) * length), "kz_hi": sgn * (lvl - (p.fib_lo - 1) * length)}
        lobes = [(max(s, k0), e) for s, e in _lobes(h_[k0:last + 1], k0) if e >= k0]
        lobes = [(s, e) for s, e in lobes if adv[s:e + 1].min() < lvl]
        used: set[int] = set()

        def scan(s, e, ref_low, vol_ref):
            """Primo CHoCH M5 dopo un estremo oltre ref_low nella gobba (s,e). Restituisce (j, sw_idx, sw_low, vol) o None."""
            sw_low, sw_idx = np.inf, None
            for j in range(s, min(e + p.choch_wait_bars, last) + 1):
                if adv[j] < sw_low:
                    sw_low, sw_idx = adv[j], j
                if sw_low >= ref_low or j <= sw_idx:
                    continue
                q = bisect_right(advp, j - p.n_swing) - 1
                if q < 0 or advp[q] < sw_idx:
                    continue
                pt = advp[q]
                if pt in used or j - pt > p.choch_wait_bars:
                    continue
                mm = bisect_right(piv, pt - 1) - 1
                if mm < 0:
                    continue
                ref = fav[piv[mm]]
                if not (cl[j] > ref and cl[j] > adv[pt]):
                    continue
                used.add(pt)
                return j, sw_idx, float(adv[sw_idx:j + 1].min()), float(W[s:min(j, e) + 1].sum()), pt
            return None

        clim, stage, ut = None, 0, None            # clim = (s, e, low, volume)
        bc = lambda c: (pd.Timestamp(t5[c[0] + int(np.argmin(adv[c[0]:c[1] + 1]))]), sgn * c[2])
        for s, e in lobes:
            lowT, volT = float(adv[s:e + 1].min()), float(W[s:e + 1].sum())
            if lowT < lvl - p.abort_ext * length:
                break
            if clim is None:
                clim = (s, e, lowT, volT)
                continue
            if stage == 0:
                if s <= clim[1]:
                    continue
                if lowT < clim[2]:
                    r = scan(s, e, clim[2], clim[3])
                    if r and r[3] < clim[3]:
                        j, swi, swl, _, pt = r
                        risk = cl[j] - swl
                        rr = (B - cl[j]) / risk if risk > 0 else 0
                        if rr >= p.tp1_r:
                            bump("UT")
                            tb = bc(clim)
                            out.append({**base, "time": pd.Timestamp(t5[j]), "kind": "UT", "state": "filled", "start": pd.Timestamp(t5[j + 1]) if j + 1 < N else pd.Timestamp(t5[j]),
                                        "entry": sgn * cl[j], "sl": sgn * swl, "tp1": sgn * (cl[j] + p.tp1_r * risk), "tp": sgn * B, "rr": rr,
                                        "choch_time": pd.Timestamp(t5[j]), "bc_time": tb[0], "bc_price": tb[1],
                                        "ut_time": pd.Timestamp(t5[swi]), "ut_price": sgn * swl})
                        else:
                            bump("UT con R:R sotto 2,5")
                        stage, ut = 1, (s, e, swl, swi, j)
                        continue
                    if r:                                 # CHoCH ma più volumi del climax: è lei il nuovo climax
                        clim = (s, e, lowT, volT)
                        continue
                if volT > clim[3]:
                    clim = (s, e, lowT, volT)
            else:
                if s <= ut[4] or lowT >= ut[2]:
                    continue
                r = scan(s, e, ut[2], None)
                if not r:
                    continue
                j, swi, swl, _, pt = r
                stop = fav[j]
                risk = stop - swl
                rr = (B - stop) / risk if risk > 0 else 0
                if rr < p.tp1_r:
                    bump("UTAD con R:R sotto 2,5")
                    break
                f, state = None, "filled"
                for k in range(j + 1, min(j + 1 + p.retest_bars, N)):
                    if adv[k] <= swl:
                        break
                    if fav[k] >= stop:
                        f = k
                        break
                if f is None:
                    if live and j + p.retest_bars >= N - 1 and (j == N - 1 or adv[j + 1:].min() > swl if j < N - 1 else True):
                        f, state = j, "waiting_fill"
                    else:
                        bump("UTAD non riempito")
                        break
                bump("UTAD")
                tb = bc(clim)
                out.append({**base, "time": pd.Timestamp(t5[j]), "kind": "UTAD", "state": state, "start": pd.Timestamp(t5[f]),
                            "entry": sgn * stop, "sl": sgn * swl, "tp1": sgn * (stop + p.tp1_r * risk), "tp": sgn * B, "rr": rr,
                            "choch_time": pd.Timestamp(t5[j]), "bc_time": tb[0], "bc_price": tb[1],
                            "ut_time": pd.Timestamp(t5[ut[3]]), "ut_price": sgn * ut[2],
                            "utad_time": pd.Timestamp(t5[swi]), "utad_price": sgn * swl})
                break
        if live and clim is not None and last == N - 1 and not any(o["sid"] == sid and o["kind"] == "UTAD" for o in out):
            tb = bc(clim)
            w = {**base, "time": pd.Timestamp(t5[last]), "kind": "watch", "state": "watching", "bc_time": tb[0], "bc_price": tb[1]}
            if ut is not None:
                w.update({"ut_time": pd.Timestamp(t5[ut[3]]), "ut_price": sgn * ut[2]})
            out.append(w)
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out).sort_values("time", kind="stable")
    return df.drop_duplicates(["time", "kind", "side"]).set_index("time")    # strutture sovrapposte con lo stesso segnale


def simulate_gold(m5: pd.DataFrame, sig: pd.DataFrame, p: GoldParams = GoldParams()) -> pd.DataFrame:
    """R per segnale in 3 modalità: tp1 (tutto a 2,5R), fine (tutto a fine Leg 1), gestita (60% a 2,5R, SL a BE, resto a fine Leg 1).
    Stessa barra: prima lo SL (ipotesi prudente). Operazioni ancora aperte escluse."""
    Hh, Ll = m5["high"].to_numpy(), m5["low"].to_numpy()
    idx = m5.index
    first = lambda m: int(m.argmax()) if m.any() else 10**9
    rows = []
    for t, r in sig[sig.kind.isin(["UT", "UTAD"])].iterrows():
        f = idx.get_loc(r.start)
        buy = r.side == "buy"
        e, sl, tp1, tp = r.entry, r.sl, r.tp1, r.tp
        risk = abs(e - sl)
        hi, lo = Hh[f:], Ll[f:]
        if buy:
            isl, i1, itp = first(lo <= sl), first(hi >= tp1), first(hi >= tp)
        else:
            isl, i1, itp = first(hi >= sl), first(lo <= tp1), first(lo <= tp)
        row = {"time": t, "kind": r.kind, "side": r.side, "risk": risk, "rr": r.rr, "sid": r.sid}
        row["R_tp1"] = (-1.0 if isl <= i1 else p.tp1_r) if min(isl, i1) < 10**9 else np.nan
        row["R_fine"] = (-1.0 if isl <= itp else r.rr) if min(isl, itp) < 10**9 else np.nan
        if isl <= i1 and isl < 10**9:
            row["R"] = -1.0
        elif i1 < isl:
            rh, rl = hi[i1 + 1:], lo[i1 + 1:]
            ibe, itp2 = (first(rl <= e), first(rh >= tp)) if buy else (first(rh >= e), first(rl <= tp))
            if itp <= i1 or itp2 < ibe:
                row["R"] = p.frac * p.tp1_r + (1 - p.frac) * r.rr
            elif ibe < 10**9:
                row["R"] = p.frac * p.tp1_r
            else:
                row["R"] = np.nan
        else:
            row["R"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _line(label, t, col):
    t = t.dropna(subset=[col]).assign(R=lambda x: x[col])
    if len(t) < 30:
        return f"{label:30s} n={len(t)} (troppo pochi" + (f"; media {t.R.mean():+.2f}R)" if len(t) else ")")
    e = evaluate(t)
    a, i_, o_ = e["all"], e["in_sample"], e["out_of_sample"]
    se = t.R.std() / np.sqrt(len(t))
    return (f"{label:30s} n={a['n']:5.0f} win={a['win_rate']:.3f} exp={a['expectancy_R']:+.3f}R (±{se:.3f}) "
            f"PF={a['profit_factor']:.2f} | IS {i_['expectancy_R']:+.3f} OOS {o_['expectancy_R']:+.3f}")


def report(res: pd.DataFrame, label: str) -> None:
    for kind, g in [("UT", res[res.kind == "UT"]), ("UTAD", res[res.kind == "UTAD"]), ("UT + UTAD", res)]:
        print(f"\n--- {label} | {kind} ---")
        for col, name in [("R_tp1", "tutto a TP1 (2,5R)"), ("R_fine", "tutto a fine Leg 1"), ("R", "gestita 60% a 2,5R + BE")]:
            print(_line(name, g.sort_values("time"), col) if len(g) else f"{name} n=0")


def placebo(m5: pd.DataFrame, sig: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Stessi lato, rischio e R:R dei segnali ma su barre casuali (±1–30 giorni): misura quanto vale il solo schema SL/TP 2,5R."""
    rng = np.random.default_rng(seed)
    cl, n = m5["close"].to_numpy(), len(m5)
    rows = []
    for t, r in sig[sig.kind.isin(["UT", "UTAD"])].iterrows():
        i = m5.index.get_loc(r.start) + int(rng.choice([-1, 1]) * rng.integers(288, 288 * 30))
        if not 0 <= i < n - 1:
            continue
        e, risk, sg = cl[i], abs(r.entry - r.sl), (1 if r.side == "buy" else -1)
        rows.append({"time": m5.index[i], "kind": r.kind, "side": r.side, "entry": e, "sl": e - sg * risk, "tp1": e + sg * 2.5 * risk,
                     "tp": e + sg * r.rr * risk, "rr": r.rr, "sid": r.sid, "start": m5.index[i + 1]})
    return pd.DataFrame(rows).set_index("time")


def filters(sig: pd.DataFrame, p: GoldParams = GoldParams()) -> pd.DataFrame:
    """Aggiunge i flag: in_kz (estremo di UT/UTAD nella Kill Zone, sforamento fino a estensione 2,0) e macro (Londra / New York)."""
    from src.market_config import macro_at
    s = sig[sig.kind.isin(["UT", "UTAD"])].copy()
    sg = np.where(s.side == "buy", 1, -1)
    ext = np.where(s.kind == "UTAD", s.utad_price, s.ut_price)
    lvl = np.where(s.side == "buy", s.level, -s.level)
    a, kz_hi = sg * ext, sg * np.where(s.side == "buy", s.kz_hi, s.kz_hi)
    s["in_kz"] = (a <= np.maximum(sg * s.kz_hi, sg * s.kz_lo)) & (a >= lvl - p.abort_ext * s.leg1_len)
    s["macro"] = [macro_at(t.to_pydatetime()) for t in s.index]
    return s


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    tf = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    mode = sys.argv[3] if len(sys.argv) > 3 else "full"            # full | test
    m5 = load_ohlc(f"data/{sym}_BID_M5.csv.gz")
    if mode == "test":
        m5 = m5.loc["2018":"2019"]
    st: dict = {}
    sig = generate_gold(m5, GoldParams(struct_tf_min=tf), st)
    print(f"{sym} struttura M{tf} - Funnel:", st, flush=True)
    print(f"dati: {m5.index[0]} → {m5.index[-1]} · segnali: {len(sig)}")
    if len(sig):
        sig.to_pickle(f"data/gold_signals_{sym}_M{tf}.pkl")
        report(simulate_gold(m5, sig), f"{sym} M{tf}")
        fs = filters(sig)
        res = simulate_gold(m5, fs)
        key = lambda df: list(zip(df.index, df.kind, df.side))
        fm = {k: (a, b) for k, a, b in zip(key(fs), fs.in_kz, fs.macro)}
        res["in_kz"] = [fm[(t, k, s_)][0] for t, k, s_ in zip(res.time, res.kind, res.side)]
        res["macro"] = [fm[(t, k, s_)][1] for t, k, s_ in zip(res.time, res.kind, res.side)]
        for name, m in [("Kill Zone", res.in_kz), ("Londra+NY", res.macro.notna()), ("solo Londra", res.macro == "Londra"),
                        ("solo New York", res.macro == "New York"), ("KZ + Londra/NY", res.in_kz & res.macro.notna())]:
            print(f"\n--- {sym} M{tf} | filtro: {name} ---")
            for col, nm in [("R_tp1", "tutto a TP1 (2,5R)"), ("R", "gestita 60% a 2,5R + BE")]:
                print(_line(nm, res[m].sort_values("time"), col))
        pl = pd.concat([simulate_gold(m5, placebo(m5, sig, sd)) for sd in range(5)])
        print(f"\n--- {sym} M{tf} | PLACEBO (barre casuali, 5 ripetizioni) ---")
        for col, nm in [("R_tp1", "tutto a TP1 (2,5R)"), ("R", "gestita 60% a 2,5R + BE")]:
            print(_line(nm, pl.sort_values("time"), col))
