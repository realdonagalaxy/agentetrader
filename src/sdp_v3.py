"""SDP v3 — calibrata sui trade reali dell'utente (vedi knowledge/esempi_utente.md).

Long (lo short è lo specchio):
 1. lateralizzazione = minimi uguali (livello L); Leg 1 = salita fino a B; Kill Zone = estensione 1,272–1,618 della Leg 1 sotto L;
 2. finestre in GIORNI: fino a max_wait_bars dalla struttura alla rottura di L e leg2_bars di Leg 2;
 3. lo sforamento della Kill Zone è accettato fino a estensione 2,0 (abort_ext = 1,0 x Leg 1 sotto L);
 4. ingresso: CHoCH M5 (chiusura sopra l'ultimo pivot high prima dell'estremo) e poi RITORNO sul livello rotto (ordine limite al livello,
    valido retest_bars barre); SL = oltre l'ultimo test (ultimo minimo di swing della Leg 2); TP = fine Leg 1 (B);
 5. solo se R:R (entry → B) >= min_rr (1:3, regola del documento);
 6. gestione opzionale come da documento: a +3R chiudi il 50% e sposta lo SL a pareggio (modalità "managed").
Flag registrati per confronto: in_kz (estremo nella Kill Zone entro estensione 2,0), ob_touch, wy_div/wy_vol/wy_dec, vwap_ext.
Parametri PROVVISORI. Costi ignorati.
"""
from bisect import bisect_right
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest_engine import evaluate
from src.data_loader import load_ohlc, resample
from src.market_config import macro_at
from src.range_detector import atr, double_extremes, pivots
from src.sdp_strategy import _order_blocks
from src.sdp_wyckoff import WyParams, _wyckoff


@dataclass
class V3Params(WyParams):
    max_wait_bars: int = 2160     # barre M5 (7,5 giorni) dalla struttura alla rottura del livello
    leg2_bars: int = 1440         # barre M5 (5 giorni) massime di Leg 2
    choch_wait_bars: int = 96     # barre M5 dall'estremo al CHoCH
    retest_bars: int = 72         # barre M5 per il ritorno sul livello dopo il CHoCH
    abort_ext: float = 1.0        # estremo oltre (estensione 2,0) = zona fallita
    min_rr: float = 3.0
    max_cands: int = 3


def generate_v3(m5: pd.DataFrame, p: V3Params = V3Params(), stats: dict | None = None) -> pd.DataFrame:
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
    cs = m5["close"]
    macd_s = cs.ewm(span=p.macd_fast, adjust=False).mean() - cs.ewm(span=p.macd_slow, adjust=False).mean()
    hist = (macd_s - macd_s.ewm(span=p.macd_signal, adjust=False).mean()).to_numpy()
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
    out, seen_k0, seen_f, sid = [], set(), set(), 0
    for d in dbl.itertuples():
        bump("doppi")
        long = d.kind == "bottom"
        adv, fav, cl = (L, H, C) if long else (-H, -L, -C)
        piv = ph if long else pl            # pivot di riferimento del CHoCH
        advp = pl if long else ph           # pivot avversi (ultimo test)
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
            if sw_low < lvl - p.abort_ext * length or cl[j] > B:
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
            bump("CHoCH")
            ref = fav[piv[mm]]
            q = bisect_right(advp, j - p.n_swing) - 1
            pstart = advp[q] if (q >= 0 and advp[q] >= k0) else sw_idx
            sl_adv = adv[pstart:j + 1].min()
            f = next((k for k in range(j + 1, min(j + 1 + p.retest_bars, len(t5))) if adv[k] <= ref), None)
            if f is None:
                bump("senza ritorno")
                continue
            risk = ref - sl_adv
            if risk <= 0:
                continue
            rr = (B - ref) / risk
            if rr < p.min_rr:
                bump("R:R sotto minimo")
                continue
            if (f, long) in seen_f:
                continue
            seen_f.add((f, long))
            bump("trade")
            div, vol, dec, winfo = _wyckoff(h_, adv, W, b_idx, j, sw_idx, p.clim_tol_atr * A[i_s], p.lobe_min_frac)
            sgn = 1 if long else -1
            with np.errstate(divide="ignore", invalid="ignore"):
                z = (sgn * adv[sw_idx] - vwap[sw_idx]) / vsd[sw_idx]
            out.append({"time": pd.Timestamp(t5[f]), "sid": sid, "side": "buy" if long else "sell", "entry": sgn * ref,
                        "sl": sgn * sl_adv, "tp": sgn * B, "rr": rr, "choch_time": pd.Timestamp(t5[j]),
                        "level": d.level, "kz_lo": sgn * kz_lo, "kz_hi": sgn * kz_hi, "sw_price": sgn * sw_low,
                        "in_kz": bool(sw_low <= kz_hi + pad and sw_low >= lvl - p.abort_ext * length),
                        "ob_touch": bool(cand_hi is not None and np.isfinite(cand_hi) and sw_low <= cand_hi),
                        "wy_div": div, "wy_vol": vol, "wy_dec": dec,
                        "vwap_ext": float(-sgn * z) if np.isfinite(z) else np.nan, "vwap_bars": int(vbars[sw_idx])})
            ncand += 1
            if ncand >= p.max_cands:
                break
    return pd.DataFrame(out).set_index("time").sort_index() if out else pd.DataFrame()


def simulate_v3(m5: pd.DataFrame, sig: pd.DataFrame, managed: bool = False) -> pd.DataFrame:
    """Ordine limite riempito alla barra del segnale (valutata per intero, ipotesi prudente: SL prima del TP).
    managed: a +3R chiude il 50% e porta lo SL a pareggio; il resto va al TP o a pareggio."""
    Hh, Ll = m5["high"].to_numpy(), m5["low"].to_numpy()
    idx = m5.index
    rows = []
    for t, r in sig.iterrows():
        f = idx.get_loc(t)
        buy = r.side == "buy"
        e, sl, tp, rr = r.entry, r.sl, r.tp, r.rr
        risk = abs(e - sl)
        hi, lo = Hh[f:], Ll[f:]
        first = lambda m: int(m.argmax()) if m.any() else 10**9
        if buy:
            isl, itp, i3 = first(lo <= sl), first(hi >= tp), first(hi >= e + 3 * risk)
        else:
            isl, itp, i3 = first(hi >= sl), first(lo <= tp), first(lo <= e - 3 * risk)
        if not managed:
            if isl == itp == 10**9:
                continue
            R = -1.0 if isl <= itp else rr
        else:
            if i3 < isl:                         # +3R raggiunto prima dello SL
                rest_hi, rest_lo = hi[i3 + 1:], lo[i3 + 1:]
                if buy:
                    ibe, itp2 = first(rest_lo <= e), first(rest_hi >= tp)
                else:
                    ibe, itp2 = first(rest_hi >= e), first(rest_lo <= tp)
                if rr <= 3 + 1e-9 or itp2 < ibe:
                    R = 1.5 + 0.5 * rr
                elif ibe < 10**9:
                    R = 1.5
                else:
                    continue
            elif isl < 10**9:
                R = -1.0
            else:
                continue
        rows.append({"time": t, "side": r.side, "R": R, "rr": rr, "risk": risk})
    return pd.DataFrame(rows)


def _line(label, t):
    if len(t) < 30:
        return f"{label:34s} n={len(t)} (troppo pochi)"
    e = evaluate(t)
    a, i_, o_ = e["all"], e["in_sample"], e["out_of_sample"]
    se = t.R.std() / np.sqrt(len(t))
    return (f"{label:34s} n={a['n']:5.0f} win={a['win_rate']:.3f} exp={a['expectancy_R']:+.3f}R (±{se:.3f}) "
            f"PF={a['profit_factor']:.2f} | IS {i_['expectancy_R']:+.3f} OOS {o_['expectancy_R']:+.3f}")


def report(sig: pd.DataFrame, m5: pd.DataFrame, label: str, crypto: bool = False) -> None:
    sig = sig.copy()
    sig["macro"] = [macro_at(t.to_pydatetime()) for t in sig.index]
    variants = {"tutti i setup (riferimento)": pd.Series(True, index=sig.index),
                "Kill Zone": sig.in_kz, "KZ + OB": sig.in_kz & sig.ob_touch,
                "KZ + Wyckoff+volume": sig.in_kz & sig.wy_vol, "KZ + OB + Wy+vol": sig.in_kz & sig.ob_touch & sig.wy_vol}
    scopes = {"tutte le ore": pd.Series(True, index=sig.index)}
    if not crypto:
        scopes["macro Londra+NY"] = sig.macro.notna()
    for sname, smask in scopes.items():
        for mode in (False, True):
            print(f"\n--- {label} | {sname} | {'gestione BE+50% a 3R' if mode else 'TP unico a fine Leg 1'} ---", flush=True)
            for vname, vmask in variants.items():
                x = sig[smask & vmask].reset_index().groupby("sid").head(1).set_index("time").sort_index()
                print(_line(vname, simulate_v3(m5, x, managed=mode)) if len(x) else f"{vname:34s} n=0", flush=True)


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    tf = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    mode = sys.argv[3] if len(sys.argv) > 3 else "full"            # full | report | test
    m5 = load_ohlc(f"data/{sym}_BID_M5.csv.gz")
    if mode == "test":
        m5 = m5.loc["2018":"2019"]
    pk = f"data/v3_signals_{sym}_M{tf}.pkl"
    if mode == "report":
        sig = pd.read_pickle(pk)
    else:
        st: dict = {}
        sig = generate_v3(m5, V3Params(struct_tf_min=tf), st)
        if mode == "full":
            sig.to_pickle(pk)
        print(f"{sym} struttura M{tf} - Funnel:", st, flush=True)
    print(f"dati: {m5.index[0]} → {m5.index[-1]} · trade candidati: {len(sig)}")
    report(sig, m5, f"{sym} M{tf}", crypto=sym.startswith(("BTC", "ETH")))
