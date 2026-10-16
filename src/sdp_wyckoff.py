"""SDP-Wyckoff — ingresso basato sugli eventi di Wyckoff dentro la Leg 2 (versione 2 della strategia).

Long (lo short è lo specchio: prezzi e istogramma cambiati di segno):
 1. lateralizzazione: massimi/minimi uguali (cluster entro tolleranza ATR), Leg 1 = uscita dal range (misurata dai minimi uguali);
 2. Leg 2: rompe il livello opposto. Dentro la Leg 2, sull'istogramma MACD (3,10,16), si cercano le gobbe negative (lobi):
    - CLIMAX (SC per i long, BC per gli short) = il lobo più profondo (gobba più grande) della Leg 2;
    - TEST/SPRING (UT/UTAD per gli short) = ultimo lobo, contenente il minimo corrente, con gobba PIÙ PICCOLA del climax,
      estremo di prezzo uguale o oltre il climax (tolleranza clim_tol_atr x ATR) e VOLUME inferiore al climax;
    - opzionale: le gobbe tra climax e test sono via via più piccole;
 3. ingresso: CHoCH M5 dopo il test. Flag registrati per ogni candidato: in Kill Zone Fibonacci (1.272–1.618), OB non mitigato toccato
    ("la zona che il colpo va a chiudere"), VWAP oltre la banda 2σ.
Le varianti (con/senza Kill Zone e OB) si confrontano a posteriori con report(). Parametri PROVVISORI.
"""
from bisect import bisect_right
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest_engine import evaluate, simulate_trades
from src.data_loader import load_ohlc, resample
from src.market_config import macro_at
from src.range_detector import atr, double_extremes, pivots
from src.sdp_strategy import SDPParams, _order_blocks, with_rr


@dataclass
class WyParams(SDPParams):
    max_cands: int = 3            # candidati CHoCH per struttura
    lobe_min_frac: float = 0.10   # lobi più piccoli di questa frazione del climax sono rumore
    abort_ext: float = 3.0        # Leg 2 oltre questa estensione della Leg 1: abbandono


def _lobes(h_seg: np.ndarray, off: int):
    neg = (h_seg < 0).astype(np.int8)
    d = np.diff(np.concatenate(([0], neg, [0])))
    return [(off + s, off + e) for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1)]


def _wyckoff(h_, adv, W, b_idx, j, sw_idx, tol_abs, min_frac):
    """(div, div+volume, div+volume+gobbe decrescenti, info) per il test che contiene sw_idx.
    info: {'sc_idx': barra del climax, 'sc_adv': estremo del climax (coordinate specchiate)} oppure {}."""
    lobes = _lobes(h_[b_idx:j + 1], b_idx)
    T = next((l for l in lobes if l[0] <= sw_idx <= l[1]), None)
    if T is None:
        return False, False, False, {}
    earlier = [l for l in lobes if l[1] < T[0]]
    if not earlier:
        return False, False, False, {}
    pk = lambda l: h_[l[0]:l[1] + 1].min()          # gobba = valore più negativo
    sc = min(earlier, key=pk)
    pk_sc, pk_t = pk(sc), pk(T)
    if pk_t <= pk_sc:                               # il test è la gobba più grande: sarebbe lui il climax
        return False, False, False, {}
    low_sc, low_t = adv[sc[0]:sc[1] + 1].min(), adv[T[0]:T[1] + 1].min()
    div = bool(low_t <= low_sc + tol_abs)
    vol = bool(div and W[T[0]:T[1] + 1].sum() < W[sc[0]:sc[1] + 1].sum())
    after = [l for l in lobes if sc[1] < l[0] and l[1] <= T[1]]
    peaks = [abs(pk(l)) for l in after if abs(pk(l)) >= min_frac * abs(pk_sc)]
    dec = bool(vol and peaks and all(peaks[i] <= peaks[i - 1] for i in range(1, len(peaks))))
    info = {"sc_idx": sc[0] + int(np.argmin(adv[sc[0]:sc[1] + 1])), "sc_adv": float(low_sc)}
    return div, vol, dec, info


def generate(m5: pd.DataFrame, p: WyParams = WyParams(), stats: dict | None = None) -> pd.DataFrame:
    tf = p.struct_tf_min
    ms = m5 if tf == 5 else resample(m5, f"{tf}min")
    A = atr(ms).to_numpy()
    dbl = double_extremes(ms, p.n_swing, p.tol, max(2, p.min_sep_min // tf), p.max_sep_min // tf)
    t5, ts = m5.index.values, ms.index.values
    H, L, C = (m5[c].to_numpy() for c in ("high", "low", "close"))
    W = m5["volume"].to_numpy() if "volume" in m5 else np.ones(len(m5))
    o_, h_s, l_s, c_s = (ms[c].to_numpy() for c in ("open", "high", "low", "close"))
    ph, pl = (list(x) for x in pivots(m5, p.n_swing))
    obs = {True: _order_blocks(o_, h_s, l_s, c_s, A, p), False: _order_blocks(-o_, -l_s, -h_s, -c_s, A, p)}
    # istogramma MACD (3,10,16)
    cs = m5["close"]
    macd_s = cs.ewm(span=p.macd_fast, adjust=False).mean() - cs.ewm(span=p.macd_slow, adjust=False).mean()
    hist = (macd_s - macd_s.ewm(span=p.macd_signal, adjust=False).mean()).to_numpy()
    # VWAP giornaliero (reset 00:00 UTC)
    tp_ = (H + L + C) / 3
    day = m5.index.normalize()
    cw = pd.Series(W, index=m5.index).groupby(day).cumsum().to_numpy()
    cpv = pd.Series(W * tp_, index=m5.index).groupby(day).cumsum().to_numpy()
    cpv2 = pd.Series(W * tp_ * tp_, index=m5.index).groupby(day).cumsum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = cpv / cw
        vsd = np.sqrt(np.maximum(cpv2 / cw - vwap ** 2, 0))
    vbars = pd.Series(1, index=m5.index).groupby(day).cumsum().to_numpy()

    st = stats if stats is not None else {}
    bump = lambda k: st.__setitem__(k, st.get(k, 0) + 1)
    out, seen_k0, sid = [], set(), 0
    for d in dbl.itertuples():
        bump("doppi")
        long = d.kind == "bottom"
        adv, fav, cl = (L, H, C) if long else (-H, -L, -C)
        piv = ph if long else pl
        lvl = d.level if long else -d.level
        h_ = hist if long else -hist
        start = int(np.searchsorted(t5, np.datetime64(d.confirmed) + np.timedelta64(tf, "m")))
        end = min(start + p.max_wait_bars, len(t5) - 1)
        k0 = next((k for k in range(start, end) if adv[k] < lvl), None)
        if k0 is None or (k0, long) in seen_k0:
            continue
        seen_k0.add((k0, long))
        p2 = int(np.searchsorted(t5, np.datetime64(d.t2)))
        b_idx = p2 + int(np.argmax(fav[p2:k0 + 1]))
        B = fav[b_idx]
        length = B - lvl
        i_s = min(int(np.searchsorted(ts, np.datetime64(d.confirmed))), len(A) - 1)
        if not (length >= p.min_leg_atr * A[i_s]):
            continue
        bump("Leg 1 valida")
        sid += 1
        kz_hi, kz_lo = lvl - (p.fib_lo - 1) * length, lvl - (p.fib_hi - 1) * length
        pad = p.kz_pad * length
        o_pos, o_lo, o_hi, o_mit = obs[long]
        form_limit = int(np.searchsorted(ts, t5[k0].astype("datetime64[m]") - np.timedelta64(tf, "m"), "right")) - 1
        sw_low, sw_idx = adv[k0], k0
        cand_hi, used, ncand = None, set(), 0
        last = min(k0 + p.leg2_bars, len(t5) - 1)
        for j in range(k0, last + 1):
            if adv[j] < sw_low:
                sw_low, sw_idx = adv[j], j
            if sw_low < lvl - p.abort_ext * length:
                break
            if cand_hi is None and adv[j] <= kz_hi + pad:
                tpos = int(np.searchsorted(ts, t5[j] - np.timedelta64(tf - 5, "m"), "right")) - 1
                sl_ = slice(int(np.searchsorted(o_pos, tpos - p.ob_lookback_min // tf)),
                            int(np.searchsorted(o_pos, form_limit, "right")))
                m = (o_mit[sl_] > tpos) & (o_hi[sl_] >= kz_lo - pad) & (o_lo[sl_] <= kz_hi + pad)
                cand_hi = o_hi[sl_][m].max() if m.any() else -np.inf
            if j <= sw_idx or j - sw_idx > p.choch_wait_bars or sw_idx in used:
                continue
            mm = bisect_right(piv, sw_idx - p.n_swing) - 1
            if mm < 0 or not (cl[j] > fav[piv[mm]] and cl[j] > sw_low):
                continue
            used.add(sw_idx)
            extreme = adv[int(np.searchsorted(t5, t5[sw_idx].astype("datetime64[h]"))):j + 1].min()
            risk = cl[j] - extreme
            if risk <= 0:
                continue
            div, vol, dec, winfo = _wyckoff(h_, adv, W, b_idx, j, sw_idx, p.clim_tol_atr * A[i_s], p.lobe_min_frac)
            sgn = 1 if long else -1
            with np.errstate(divide="ignore", invalid="ignore"):
                z = (sgn * adv[sw_idx] - vwap[sw_idx]) / vsd[sw_idx]
            out.append({"time": pd.Timestamp(t5[j]), "sid": sid, "side": "buy" if long else "sell", "entry": sgn * cl[j],
                        "risk": risk, "sl": sgn * extreme, "tp": sgn * (cl[j] + p.rr * risk),
                        "tp_end": sgn * B, "tp_origin": sgn * lvl, "level": d.level, "leg1_pips": length * 1e4,
                        "in_kz": bool(kz_lo - pad <= sw_low <= kz_hi + pad),
                        "ob_touch": bool(cand_hi is not None and np.isfinite(cand_hi) and sw_low <= cand_hi),
                        "wy_div": div, "wy_vol": vol, "wy_dec": dec,
                        "kind": "signal", "kz_lo": sgn * kz_lo, "kz_hi": sgn * kz_hi, "b_price": sgn * B, "sw_price": sgn * sw_low,
                        "sw_time": pd.Timestamp(t5[sw_idx]),
                        "sc_price": sgn * winfo["sc_adv"] if winfo else np.nan,
                        "sc_time": pd.Timestamp(t5[winfo["sc_idx"]]) if winfo else pd.NaT,
                        "ob_hi": (sgn * cand_hi) if (cand_hi is not None and np.isfinite(cand_hi)) else np.nan,
                        "vwap_ext": float(-sgn * z) if np.isfinite(z) else np.nan, "vwap_bars": int(vbars[sw_idx])})
            bump("candidati CHoCH")
            ncand += 1
            if ncand >= p.max_cands:
                break
        else:
            # struttura ancora aperta all'ultima barra disponibile: setup "in formazione" (usato dall'analisi dal vivo)
            if last == len(t5) - 1 and sw_low >= lvl - p.abort_ext * length:
                jj = last
                div, vol, dec, winfo = _wyckoff(h_, adv, W, b_idx, jj, sw_idx, p.clim_tol_atr * A[i_s], p.lobe_min_frac)
                sgn = 1 if long else -1
                out.append({"time": pd.Timestamp(t5[jj]), "sid": sid, "kind": "pending", "side": "buy" if long else "sell",
                            "level": d.level, "leg1_pips": length * 1e4, "b_price": sgn * B,
                            "kz_lo": sgn * kz_lo, "kz_hi": sgn * kz_hi, "sw_price": sgn * sw_low, "sw_time": pd.Timestamp(t5[sw_idx]),
                            "in_kz": bool(kz_lo - pad <= sw_low <= kz_hi + pad),
                            "ob_touch": bool(cand_hi is not None and np.isfinite(cand_hi) and sw_low <= cand_hi),
                            "ob_hi": (sgn * cand_hi) if (cand_hi is not None and np.isfinite(cand_hi)) else np.nan,
                            "wy_div": div, "wy_vol": vol, "wy_dec": dec,
                            "sc_price": sgn * winfo["sc_adv"] if winfo else np.nan,
                            "sc_time": pd.Timestamp(t5[winfo["sc_idx"]]) if winfo else pd.NaT})
    return pd.DataFrame(out).set_index("time").sort_index() if out else pd.DataFrame()


def report(sig: pd.DataFrame, m5: pd.DataFrame, label: str) -> None:
    """Varianti fissate in anticipo. Per ogni struttura si prende il primo candidato che soddisfa la variante."""
    sig = sig[sig.get("kind", "signal") == "signal"].copy() if "kind" in sig else sig.copy()
    sig["macro"] = [macro_at(t.to_pydatetime()) for t in sig.index]
    ok = sig.vwap_bars >= 24
    variants = {
        "KZ+OB (riferimento)": sig.in_kz & sig.ob_touch,
        "KZ+OB+Wyckoff": sig.in_kz & sig.ob_touch & sig.wy_div,
        "KZ+OB+Wy+volume": sig.in_kz & sig.ob_touch & sig.wy_vol,
        "KZ+OB+Wy+vol+decr": sig.in_kz & sig.ob_touch & sig.wy_dec,
        "KZ+Wy+volume (no OB)": sig.in_kz & sig.wy_vol,
        "Wy+volume (solo)": sig.wy_vol,
        "Wy+vol+VWAP2": sig.wy_vol & ok & (sig.vwap_ext >= 2),
    }
    for scope, smask in (("tutte le ore", pd.Series(True, index=sig.index)), ("macro", sig.macro.notna())):
        for vname, vmask in variants.items():
            x0 = sig[smask & vmask].reset_index().groupby("sid").head(1).set_index("time").sort_index()
            for tname in ("rr 2", "fine Leg 1"):
                if tname == "rr 2":
                    x = with_rr(x0, 2.0)
                else:
                    x = x0.assign(tp=x0["tp_end"])
                    x = x[((x.side == "buy") & (x.tp > x.entry)) | ((x.side == "sell") & (x.tp < x.entry))]
                if len(x) < 30:
                    print(f"{label} | {scope:12s} | {vname:21s} | {tname:10s} | n={len(x)} (troppo pochi)", flush=True)
                    continue
                t = simulate_trades(m5, x, with_trend=False)
                e = evaluate(t)
                a_, i_, o_ = e["all"], e["in_sample"], e["out_of_sample"]
                se = t.R.std() / np.sqrt(len(t))
                print(f"{label} | {scope:12s} | {vname:21s} | {tname:10s} | n={a_['n']:5.0f} win={a_['win_rate']:.3f} "
                      f"pareggio={a_['breakeven_win_rate']:.3f} exp={a_['expectancy_R']:+.3f}R (±{se:.3f}) "
                      f"| IS {i_['expectancy_R']:+.3f} OOS {o_['expectancy_R']:+.3f}", flush=True)


if __name__ == "__main__":
    import sys
    tf = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    tol = float(sys.argv[2]) if len(sys.argv) > 2 else 0.25
    sample = sys.argv[3] if len(sys.argv) > 3 else "full"        # "full" | "report" | "test"
    sym = sys.argv[4] if len(sys.argv) > 4 else "EURUSD"
    m5 = load_ohlc(f"data/{sym}_BID_M5.csv.gz")
    name = f"data/wy_signals_M{tf}_tol{tol}.pkl" if sym == "EURUSD" else f"data/wy_signals_{sym}_M{tf}_tol{tol}.pkl"
    if sample == "test":
        m5 = m5.loc["2018":"2019"]
    if sample == "report":
        sig = pd.read_pickle(name)
    else:
        st: dict = {}
        sig = generate(m5, WyParams(struct_tf_min=tf, tol=tol), st)
        if sample == "full":
            sig.to_pickle(name)
        print(f"STRUTTURA M{tf} tol {tol} - Funnel:", st, flush=True)
        print("Candidati con flag:", {c: int(sig[c].sum()) for c in ("in_kz", "ob_touch", "wy_div", "wy_vol", "wy_dec")}, "su", len(sig), flush=True)
    report(sig, m5, f"{sym} M{tf} tol{tol}")
