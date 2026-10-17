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
    mode: str = "macd"            # "macd" = gobbe dell'istogramma (la più grande = climax); "tick" = swing con volumi tick (niente MACD)
    tick_win: int = 6             # modalità tick: volume sommato su ±tick_win barre attorno al minimo/massimo di swing


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
        base = {"sid": sid, "mode": p.mode, "side": "buy" if long else "sell", "level": d.level, "b_price": sgn * B, "leg1_len": length,
                "lat_t1": pd.Timestamp(t5[p1]), "lat_t2": pd.Timestamp(t5[p2]), "lat_hi": sgn * H0, "b_time": pd.Timestamp(t5[b_idx]),
                "kz_lo": sgn * (lvl - (p.fib_hi - 1) * length), "kz_hi": sgn * (lvl - (p.fib_lo - 1) * length)}
        lobes = [(max(s, k0), e) for s, e in _lobes(h_[k0:last + 1], k0) if e >= k0]
        if p.mode == "tick":                       # "gobba" = swing avverso (pivot) con la sua finestra di volume tick
            lobes = [(max(q - p.tick_win, k0), min(q + p.tick_win, last)) for q in advp if k0 <= q <= last - p.n_swing]
        lobes = [(s, e) for s, e in lobes if adv[s:e + 1].min() < lvl]
        used: set[int] = set()

        def mt(s, e):
            """Dimensione della gobba: profondità del picco dell'istogramma (macd) oppure somma dei volumi tick (tick)."""
            return float(W[s:e + 1].sum()) if p.mode == "tick" else float(-h_[s:e + 1].min())

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
                return j, sw_idx, float(adv[sw_idx:j + 1].min()), mt(s, min(j, e)), pt
            return None

        if p.mode == "macd":
            # Sequenza (etichette = swing/pivot successivi, "tutto spostato a sinistra" come da utente):
            #  SC = candela del picco dell'istogramma (gobba più profonda della Leg 2); ST = primo swing low sotto il minimo della candela SC;
            #  Spring = primo swing low sotto l'ST; ulteriori test dello Spring non sono etichettati.
            #  Ingressi: CHoCH M5 dopo l'ST (prima dello Spring) -> mercato, SL sotto il minimo più basso fino al CHoCH;
            #            CHoCH M5 dopo lo Spring (inclusi i suoi test) -> stop pendente, SL sotto il minimo più basso fino al CHoCH.
            dep = -h_
            c_idx, c_dep, stage, st_lab, sp_lab, sw_low, sw_idx, ut, done = None, 0.0, 0, None, None, np.inf, None, None, False

            def first_pivot_below(after, level, j):
                x = bisect_right(advp, after)
                while x < len(advp) and advp[x] <= j - p.n_swing:
                    if adv[advp[x]] < level:
                        return advp[x]
                    x += 1
                return None

            for j in range(k0, last + 1):
                if adv[j] < lvl and dep[j] > c_dep:
                    c_idx, c_dep, stage, st_lab, sp_lab, sw_low, sw_idx, ut = j, dep[j], 0, None, None, np.inf, None, None
                    continue
                if c_idx is None:
                    continue
                if st_lab is None:
                    st_lab = first_pivot_below(c_idx, adv[c_idx], j)
                if st_lab is not None and sp_lab is None:
                    sp_lab = first_pivot_below(st_lab, adv[st_lab], j)
                if sp_lab is not None and stage != 1:                      # Spring formato: si passa alla fase 1
                    stage, sw_low, sw_idx = 1, adv[sp_lab], sp_lab
                ref_low = adv[c_idx] if stage == 0 else (adv[st_lab] if st_lab is not None else adv[c_idx])
                if stage == 0 and adv[j] < ref_low and adv[j] < sw_low:
                    sw_low, sw_idx = adv[j], j
                elif stage == 1 and adv[j] < sw_low:
                    sw_low, sw_idx = adv[j], j
                if stage == 2 or sw_idx is None or j <= sw_idx or (stage == 0 and st_lab is None):
                    continue
                if sw_low < lvl - p.abort_ext * length:
                    break
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
                swl = float(adv[sw_idx:j + 1].min())
                tb = (pd.Timestamp(t5[c_idx]), sgn * float(adv[c_idx]))
                if stage == 0:
                    risk = cl[j] - swl
                    rr = (B - cl[j]) / risk if risk > 0 else 0
                    if rr >= p.tp1_r:
                        bump("UT")
                        out.append({**base, "time": pd.Timestamp(t5[j]), "kind": "UT", "state": "filled", "start": pd.Timestamp(t5[min(j + 1, N - 1)]),
                                    "entry": sgn * cl[j], "sl": sgn * swl, "tp1": sgn * (cl[j] + p.tp1_r * risk), "tp": sgn * B, "rr": rr,
                                    "choch_time": pd.Timestamp(t5[j]), "bc_time": tb[0], "bc_price": tb[1],
                                    "ut_time": pd.Timestamp(t5[st_lab]), "ut_price": sgn * float(adv[st_lab])})
                    else:
                        bump("UT con R:R sotto 2,5")
                    ut = (st_lab, float(adv[st_lab]), j)
                    stage, sw_low, sw_idx, sp_lab = 2, np.inf, None, None   # dopo il CHoCH dell'ST si attende lo Spring
                    continue
                stop = fav[j]
                risk = stop - swl
                rr = (B - stop) / risk if risk > 0 else 0
                if rr < p.tp1_r:
                    bump("UTAD con R:R sotto 2,5")
                    continue                                     # un ulteriore test dello Spring può dare un nuovo CHoCH
                f, state = None, "filled"
                for k in range(j + 1, min(j + 1 + p.retest_bars, N)):
                    if adv[k] <= swl:
                        break
                    if fav[k] >= stop:
                        f = k
                        break
                if f is None:
                    if live and j + p.retest_bars >= N - 1 and (j == N - 1 or adv[j + 1:].min() > swl):
                        f, state = j, "waiting_fill"
                    else:
                        bump("UTAD non riempito")
                        continue
                bump("UTAD")
                out.append({**base, "time": pd.Timestamp(t5[j]), "kind": "UTAD", "state": state, "start": pd.Timestamp(t5[f]),
                            "entry": sgn * stop, "sl": sgn * swl, "tp1": sgn * (stop + p.tp1_r * risk), "tp": sgn * B, "rr": rr,
                            "choch_time": pd.Timestamp(t5[j]), "bc_time": tb[0], "bc_price": tb[1],
                            "ut_time": pd.Timestamp(t5[st_lab]), "ut_price": sgn * float(adv[st_lab]),
                            "utad_time": pd.Timestamp(t5[sp_lab]), "utad_price": sgn * float(adv[sp_lab])})
                done = True
                break
            if live and c_idx is not None and last == N - 1 and last - c_idx >= 2 and not done:     # climax confermato: almeno 2 barre dopo il picco
                w = {**base, "time": pd.Timestamp(t5[last]), "kind": "watch", "state": "watching",
                     "bc_time": pd.Timestamp(t5[c_idx]), "bc_price": sgn * float(adv[c_idx])}
                if st_lab is not None:
                    w.update({"ut_time": pd.Timestamp(t5[st_lab]), "ut_price": sgn * float(adv[st_lab])})
                if sp_lab is not None:
                    w.update({"utad_time": pd.Timestamp(t5[sp_lab]), "utad_price": sgn * float(adv[sp_lab])})
                out.append(w)
            continue
        clim, stage, ut = None, 0, None            # clim = (s, e, low, volume)
        def bc(c):
            """Candela del climax: con il MACD è la barra del picco della gobba (in linea col pallino sull'istogramma);
            con i volumi tick il minimo/massimo di swing."""
            i = c[0] + int(np.argmin(h_[c[0]:c[1] + 1] if p.mode == "macd" else adv[c[0]:c[1] + 1]))
            return pd.Timestamp(t5[i]), sgn * float(adv[i] if p.mode == "macd" else c[2])
        for s, e in lobes:
            lowT, volT = float(adv[s:e + 1].min()), mt(s, e)
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
    df = df.drop_duplicates(["time", "kind", "side", "level"]).set_index("time")      # strutture sovrapposte con lo stesso segnale
    return add_vwap(m5, add_sweep(m5, df))


def add_sweep(m5: pd.DataFrame, df: pd.DataFrame, days: int = 5, n_h1: int = 2) -> pd.DataFrame:
    """Colonne `sweep_h1` / `sweep_by`: ST/UT o Spring/UTAD che per primi superano un pivot H1 (a 2 barre per lato) degli ultimi `days` giorni.
    Un pivot H1 conta solo se il BC/SC (e il prezzo prima) non lo aveva già superato: è il punto ST/UT o Spring/UTAD a prendere quella liquidità.
    Sell: massimi H1 superati verso l'alto; Buy: minimi H1 superati verso il basso. Il pivot è noto solo n_h1 barre H1 dopo (nessun look-ahead)."""
    if df.empty:
        return df
    h1 = resample(m5, "1h")
    ph, pl = pivots(h1, n_h1)
    hour = pd.Timedelta(hours=1)
    t5 = m5.index.values
    H, L = m5["high"].to_numpy(), m5["low"].to_numpy()
    hi = [(h1.index[i], h1.index[min(i + n_h1, len(h1) - 1)] + hour, float(h1["high"].iloc[i])) for i in ph]
    lo = [(h1.index[i], h1.index[min(i + n_h1, len(h1) - 1)] + hour, float(h1["low"].iloc[i])) for i in pl]
    flags, by = [], []
    for t, r in df.iterrows():
        sell = r["side"] == "sell"
        pts = []
        if pd.notna(r.get("ut_time")):
            pts.append(("UT" if sell else "ST", pd.Timestamp(r["ut_time"]), float(r["ut_price"])))
        if pd.notna(r.get("utad_time")):
            pts.append(("UTAD" if sell else "Spring", pd.Timestamp(r["utad_time"]), float(r["utad_price"])))
        ok, who = False, ""
        i_bc = int(np.searchsorted(t5, np.datetime64(r["bc_time"]))) if pd.notna(r.get("bc_time")) else None
        for name, tp_, pr in pts:
            for t_p, t_conf, P in (hi if sell else lo):
                if not (tp_ - pd.Timedelta(days=days) <= t_p < tp_ and t_conf <= tp_ and i_bc is not None):
                    continue
                if (pr > P) if sell else (pr < P):
                    i0 = int(np.searchsorted(t5, np.datetime64(t_conf)))
                    seen = (H[i0:i_bc + 1].max() > P) if sell else (L[i0:i_bc + 1].min() < P) if i_bc >= i0 else False
                    if not seen:
                        ok, who = True, name
                        break
            if ok:
                break
        flags.append(ok)
        by.append(who)
    out = df.copy()
    out["sweep_h1"], out["sweep_by"] = flags, by
    return out


def add_vwap(m5: pd.DataFrame, df: pd.DataFrame, k: float = 2.0) -> pd.DataFrame:
    """Colonne `vwap_z` / `vwap_out`: la chiusura della candela del CHoCH M5 è oltre la banda ±k·σ del VWAP giornaliero (reset 00:00 UTC,
    pesato per i volumi tick, σ = deviazione standard pesata del prezzo tipico)? Sell: sopra la banda alta; Buy: sotto la banda bassa.
    `ext_z` / `ext_out`: lo stesso per l'estremo di UT/UTAD (ST/Spring). Dentro le bande = trade da scartare."""
    if df.empty:
        return df
    W = m5["volume"].to_numpy(dtype=float) if "volume" in m5 else np.ones(len(m5))
    H, L, C = (m5[c].to_numpy() for c in ("high", "low", "close"))
    tp_ = (H + L + C) / 3
    day = m5.index.normalize()
    cw = pd.Series(W, index=m5.index).groupby(day).cumsum().to_numpy()
    cpv = pd.Series(W * tp_, index=m5.index).groupby(day).cumsum().to_numpy()
    cpv2 = pd.Series(W * tp_ * tp_, index=m5.index).groupby(day).cumsum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = cpv / cw
        vsd = np.sqrt(np.maximum(cpv2 / cw - vwap ** 2, 0))
    t5 = m5.index.values
    zc, ze = [], []
    for t, r in df.iterrows():
        sg = 1 if r["side"] == "sell" else -1
        zs = []
        i = int(np.searchsorted(t5, np.datetime64(r.get("choch_time", t))))
        with np.errstate(divide="ignore", invalid="ignore"):
            zs.append(sg * (C[min(i, len(C) - 1)] - vwap[min(i, len(C) - 1)]) / vsd[min(i, len(C) - 1)] if vsd[min(i, len(C) - 1)] > 0 else np.nan)
        ext_t = r["utad_time"] if pd.notna(r.get("utad_time")) else r.get("ut_time")
        ext_p = r["utad_price"] if pd.notna(r.get("utad_time")) else r.get("ut_price")
        if pd.notna(ext_t):
            j = min(int(np.searchsorted(t5, np.datetime64(ext_t))), len(C) - 1)
            zs.append(sg * (float(ext_p) - vwap[j]) / vsd[j] if vsd[j] > 0 else np.nan)
        else:
            zs.append(np.nan)
        zc.append(zs[0])
        ze.append(zs[1])
    out = df.copy()
    out["vwap_z"], out["ext_z"] = zc, ze
    out["vwap_out"], out["ext_out"] = out["vwap_z"] >= k, out["ext_z"] >= k
    return out


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
    from src.market_config import in_entry_window, macro_at
    s = sig[sig.kind.isin(["UT", "UTAD"])].copy()
    sg = np.where(s.side == "buy", 1, -1)
    ext = np.where(s.kind == "UTAD", s.utad_price, s.ut_price)
    lvl = np.where(s.side == "buy", s.level, -s.level)
    a, kz_hi = sg * ext, sg * np.where(s.side == "buy", s.kz_hi, s.kz_hi)
    s["in_kz"] = (a <= np.maximum(sg * s.kz_hi, sg * s.kz_lo)) & (a >= lvl - p.abort_ext * s.leg1_len)
    s["macro"] = [macro_at(t.to_pydatetime()) for t in s.index]
    s["in_ny"] = [in_entry_window(t.to_pydatetime()) for t in s.index]       # CHoCH tra le 15:30 e le 18:30 Roma
    return s


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    tf = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    mode = sys.argv[3] if len(sys.argv) > 3 else "full"            # full | test
    vmode = sys.argv[4] if len(sys.argv) > 4 else "macd"           # macd | tick
    m5 = load_ohlc(f"data/{sym}_BID_M5.csv.gz")
    if mode == "test":
        m5 = m5.loc["2018":"2019"]
    st: dict = {}
    sig = generate_gold(m5, GoldParams(struct_tf_min=tf, mode=vmode), st)
    print(f"{sym} struttura M{tf} - modalità volumi: {vmode} - Funnel:", st, flush=True)
    print(f"dati: {m5.index[0]} → {m5.index[-1]} · segnali: {len(sig)}")
    if len(sig):
        sig.to_pickle(f"data/gold_signals_{sym}_M{tf}_{vmode}.pkl")
        report(simulate_gold(m5, sig), f"{sym} M{tf}")
        fs = filters(sig)
        res = simulate_gold(m5, fs)
        key = lambda df: list(zip(df.index, df.kind, df.side))
        fm = {k: (a, b) for k, a, b in zip(key(fs), fs.in_kz, fs.macro)}
        fm_ny = {k: a for k, a in zip(key(fs), fs.in_ny)}
        res["in_kz"] = [fm[(t, k, s_)][0] for t, k, s_ in zip(res.time, res.kind, res.side)]
        res["macro"] = [fm[(t, k, s_)][1] for t, k, s_ in zip(res.time, res.kind, res.side)]
        res["in_ny"] = [fm_ny[(t, k, s_)] for t, k, s_ in zip(res.time, res.kind, res.side)]
        for name, m in [("ORARIO: CHoCH tra le 15:30 e le 18:30 Roma", res.in_ny), ("ORARIO: fuori dalle 15:30-18:30", ~res.in_ny),
                        ("Kill Zone", res.in_kz), ("Londra+NY", res.macro.notna()), ("solo Londra", res.macro == "Londra"),
                        ("solo New York", res.macro == "New York"), ("KZ + Londra/NY", res.in_kz & res.macro.notna())]:
            print(f"\n--- {sym} M{tf} | filtro: {name} ---")
            for col, nm in [("R_tp1", "tutto a TP1 (2,5R)"), ("R", "gestita 60% a 2,5R + BE")]:
                print(_line(nm, res[m].sort_values("time"), col))
        sw = {(t, k, sd): f for t, k, sd, f in zip(sig.index, sig.kind, sig.side, sig.sweep_h1)}
        res["sweep"] = [bool(sw.get((t, k, sd), False)) for t, k, sd in zip(res.time, res.kind, res.side)]
        for name, m in [("CON sweep H1 (ST/UT, Spring/UTAD)", res.sweep), ("SENZA sweep H1", ~res.sweep)]:
            print(f"\n--- {sym} M{tf} | {name} ---")
            for col, nm in [("R_tp1", "tutto a TP1 (2,5R)"), ("R", "gestita 60% a 2,5R + BE")]:
                print(_line(nm, res[m].sort_values("time"), col))
        for name, m in [("15:30-18:30 E sweep H1", res.in_ny & res.sweep), ("15:30-18:30 SENZA sweep H1", res.in_ny & ~res.sweep)]:
            print(f"\n--- {sym} M{tf} | {name} ---")
            for col, nm in [("R_tp1", "tutto a TP1 (2,5R)"), ("R", "gestita 60% a 2,5R + BE")]:
                print(_line(nm, res[m].sort_values("time"), col))
        vo = {(t, k, sd): (a, b) for t, k, sd, a, b in zip(sig.index, sig.kind, sig.side, sig.vwap_out, sig.ext_out)}
        res["vwap_out"] = [bool(vo.get((t, k, sd), (False, False))[0]) for t, k, sd in zip(res.time, res.kind, res.side)]
        res["ext_out"] = [bool(vo.get((t, k, sd), (False, False))[1]) for t, k, sd in zip(res.time, res.kind, res.side)]
        for name, m in [("VWAP: CHoCH OLTRE la banda 2σ", res.vwap_out), ("VWAP: CHoCH DENTRO le bande (da scartare)", ~res.vwap_out),
                        ("VWAP: estremo ST/UT-Spring/UTAD oltre 2σ", res.ext_out),
                        ("15:30-18:30 + CHoCH oltre 2σ", res.in_ny & res.vwap_out),
                        ("15:30-18:30 + CHoCH oltre 2σ + sweep H1", res.in_ny & res.vwap_out & res.sweep)]:
            print(f"\n--- {sym} M{tf} | {name} ---")
            for col, nm in [("R_tp1", "tutto a TP1 (2,5R)"), ("R", "gestita 60% a 2,5R + BE")]:
                print(_line(nm, res[m].sort_values("time"), col))
        ps = sig[sig.sweep_h1] if "sweep_h1" in sig else sig
        if len(ps):
            plw = pd.concat([simulate_gold(m5, placebo(m5, ps, sd)) for sd in range(5)])
            print(f"\n--- {sym} M{tf} | PLACEBO dei soli segnali con sweep H1 ---")
            for col, nm in [("R_tp1", "tutto a TP1 (2,5R)"), ("R", "gestita 60% a 2,5R + BE")]:
                print(_line(nm, plw.sort_values("time"), col))
        pl = pd.concat([simulate_gold(m5, placebo(m5, sig, sd)) for sd in range(5)])
        print(f"\n--- {sym} M{tf} | PLACEBO (barre casuali, 5 ripetizioni) ---")
        for col, nm in [("R_tp1", "tutto a TP1 (2,5R)"), ("R", "gestita 60% a 2,5R + BE")]:
            print(_line(nm, pl.sort_values("time"), col))
