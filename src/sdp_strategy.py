"""SDP v1 — doppio min/max M15 + Leg 1/Leg 2 + Kill Zone Fibonacci + Order Block non mitigato + CHoCH M5.

Long (lo short è lo specchio: prezzi cambiati di segno):
 1. doppio minimo M15 (livello L) = estremo dell'accumulo; bias H4+H1 = UP;
 2. Leg 2: il prezzo M5 scende sotto L. In quel momento si riconosce la Leg 1 = spinta dal doppio minimo al massimo B
    precedente alla rottura; lunghezza = B - L;
 3. Kill Zone = [L - 0.618*len, L - 0.272*len] (estensione 1.272–1.618 della Leg 1 da B);
 4. POI: Order Block rialzista (ultima candela M15 ribassista prima di un impulso) NON mitigato, formatosi prima della rottura
    di L, la cui zona interseca la Kill Zone (± kz_pad*len: "a volte è un po' fuori");
 5. reazione: il prezzo tocca l'OB, poi CHoCH M5 (chiusura sopra l'ultimo pivot high M5 prima del minimo) -> ingresso a mercato;
 6. SL sotto il minimo della candela H1 che contiene il minimo di Leg 2; TP = rr * rischio.
Tutti i parametri sono PROVVISORI (SDPParams). Mancano ancora VWAP, MACD, volumi tick, macro orarie.
"""
from bisect import bisect_right
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest_engine import evaluate, simulate_trades
from src.data_loader import load_ohlc, resample
from src.market_structure import multi_tf_trend
from src.range_detector import atr, double_extremes, pivots


@dataclass
class SDPParams:
    n_swing: int = 2
    tol: float = 0.25            # tolleranza doppio min/max (x ATR14 M15)
    min_sep_min: int = 30
    max_sep_min: int = 480       # 8 ore
    max_wait_bars: int = 144     # barre M5 per vedere la rottura del livello dopo la conferma
    leg2_bars: int = 144         # barre M5 massime di Leg 2 (da rottura a ingresso)
    choch_wait_bars: int = 24    # barre M5 dal tocco OB per il CHoCH
    fib_lo: float = 1.272        # Kill Zone: estensioni della Leg 1
    fib_hi: float = 1.618
    kz_pad: float = 0.25         # tolleranza OB "un po' fuori" (frazione lunghezza Leg 1)
    min_leg_atr: float = 1.0     # Leg 1 minima (x ATR14 M15)
    ob_disp_atr: float = 1.0     # impulso minimo dopo la candela OB (x ATR14 M15, entro 3 candele)
    ob_lookback_min: int = 14400 # vita massima di un OB (10 giorni, in minuti)
    struct_tf_min: int = 15      # timeframe della struttura (doppi, ATR, OB): 15 o 5
    rr: float = 3.0
    bias_h1_bars: int = 400
    require_bias: bool = False    # i filtri di bias si applicano a posteriori (colonne bias_entry / bias_pre_leg2)


def _order_blocks(O, H, L, C, A, p: SDPParams):
    """OB 'rialzisti' (domanda): array (pos, lo, hi, mit_pos). Per gli short si passano prezzi specchiati."""
    n = len(C)
    i = np.arange(n - 4)
    imp = np.maximum.reduce([H[i + 1], H[i + 2], H[i + 3]]) - H[i]
    ok = (C[i] < O[i]) & (imp >= p.ob_disp_atr * A[i]) & ~np.isnan(A[i])
    pos = i[ok]
    mit = np.full(len(pos), n + 10**9, dtype=np.int64)
    for k, ix in enumerate(pos):
        seg = L[ix + 4: ix + 4 + p.ob_lookback_min // p.struct_tf_min]
        hit = seg <= H[ix]
        if hit.any():
            mit[k] = ix + 4 + int(hit.argmax())
    return pos, L[pos], H[pos], mit


def generate_signals(m5: pd.DataFrame, p: SDPParams = SDPParams(), stats: dict | None = None) -> pd.DataFrame:
    tf = p.struct_tf_min
    m15 = m5 if tf == 5 else resample(m5, f"{tf}min")   # "m15" = timeframe della struttura
    h1 = resample(m5, "1h")
    A15 = atr(m15).to_numpy()
    dbl = double_extremes(m15, p.n_swing, p.tol, max(2, p.min_sep_min // tf), p.max_sep_min // tf)
    t5, t15 = m5.index.values, m15.index.values
    H, L, C = m5["high"].to_numpy(), m5["low"].to_numpy(), m5["close"].to_numpy()
    o15, h15, l15, c15 = (m15[c].to_numpy() for c in ("open", "high", "low", "close"))
    ph, pl = (list(x) for x in pivots(m5, p.n_swing))
    obs = {True: _order_blocks(o15, h15, l15, c15, A15, p),
           False: _order_blocks(-o15, -l15, -h15, -c15, A15, p)}
    bias_cache: dict = {}
    st = stats if stats is not None else {}
    def bump(k): st[k] = st.get(k, 0) + 1

    def bias_at(ts):
        hour = ts.astype("datetime64[h]")
        if hour not in bias_cache:
            k = h1.index.values.searchsorted(hour)
            bias_cache[hour] = multi_tf_trend(h1.iloc[max(0, k - p.bias_h1_bars):k])["bias"] if k > 50 else "MISTO"
        return bias_cache[hour]

    out, seen = [], set()
    for d in dbl.itertuples():
        bump("doppi")
        long = d.kind == "bottom"
        adv, fav, cl = (L, H, C) if long else (-H, -L, -C)   # adv: estremo avverso (più basso = più estremo)
        piv = ph if long else pl
        lvl = d.level if long else -d.level
        avail = np.datetime64(d.confirmed) + np.timedelta64(tf, "m")
        start = int(np.searchsorted(t5, avail))
        end = min(start + p.max_wait_bars, len(t5) - 1)
        k0 = next((k for k in range(start, end) if adv[k] < lvl), None)
        if k0 is None:
            continue
        bump("livello rotto (Leg 2)")
        p2 = int(np.searchsorted(t5, np.datetime64(d.t2)))
        B = fav[p2:k0 + 1].max()
        length = B - lvl
        i15 = min(int(np.searchsorted(t15, np.datetime64(d.confirmed))), len(A15) - 1)
        if not (length >= p.min_leg_atr * A15[i15]):
            continue
        bump("Leg 1 valida")
        kz_hi, kz_lo = lvl - (p.fib_lo - 1) * length, lvl - (p.fib_hi - 1) * length
        pad = p.kz_pad * length
        o_pos, o_lo, o_hi, o_mit = obs[long]
        form_limit = int(np.searchsorted(t15, t5[k0].astype("datetime64[m]") - np.timedelta64(tf, "m"), "right")) - 1
        sw_low, sw_idx = adv[k0], k0
        cand = None
        touch = None
        last = min(k0 + p.leg2_bars, len(t5) - 1)
        for j in range(k0, last + 1):
            if adv[j] < sw_low:
                sw_low, sw_idx = adv[j], j
            if sw_low < kz_lo - pad:           # Leg 2 oltre il 1.618: Kill Zone fallita
                break
            if cand is None:
                if adv[j] <= kz_hi + pad:      # il prezzo è arrivato nella Kill Zone (con tolleranza)
                    bump("Kill Zone raggiunta")
                    tpos = int(np.searchsorted(t15, t5[j] - np.timedelta64(tf - 5, "m"), "right")) - 1
                    lo_i = int(np.searchsorted(o_pos, tpos - p.ob_lookback_min // tf))
                    hi_i = int(np.searchsorted(o_pos, form_limit, "right"))
                    sl_ = slice(lo_i, hi_i)
                    m = (o_mit[sl_] > tpos) & (o_hi[sl_] >= kz_lo - pad) & (o_lo[sl_] <= kz_hi + pad)
                    if not m.any():
                        break
                    bump("OB non mitigato in Kill Zone")
                    cand = (o_lo[sl_][m], o_hi[sl_][m])
                else:
                    continue
            if touch is None:
                if adv[j] <= cand[1].max():    # tocca la zona di un OB candidato
                    touch = j
                    bump("OB toccato")
                else:
                    continue
            if j - touch > p.choch_wait_bars:
                break
            mm = bisect_right(piv, sw_idx - p.n_swing) - 1
            if mm < 0:
                break
            if cl[j] > fav[piv[mm]] and cl[j] > sw_low and j > sw_idx:
                bump("CHoCH M5")
                key = (t5[j], long)
                if key in seen:
                    break
                seen.add(key)
                h_start = int(np.searchsorted(t5, t5[sw_idx].astype("datetime64[h]")))
                extreme = adv[h_start:j + 1].min()
                risk = cl[j] - extreme
                if risk <= 0:
                    break
                b_entry, b_leg = bias_at(t5[j]), bias_at(t5[k0])   # al CHoCH e prima della Leg 2
                want = "UP" if long else "DOWN"
                if p.require_bias and b_leg != want:
                    break
                bump("segnale")
                sgn = 1 if long else -1
                out.append({"time": pd.Timestamp(t5[j]), "side": "buy" if long else "sell", "entry": sgn * cl[j],
                            "risk": risk, "sl": sgn * extreme, "tp": sgn * (cl[j] + p.rr * risk),
                            "bias_entry": b_entry, "bias_pre_leg2": b_leg, "want": want,
                            "tp_end": sgn * B, "tp_origin": sgn * lvl, "level": d.level, "leg1_pips": length * 1e4, "risk_pips": risk * 1e4})
                break
    return pd.DataFrame(out).set_index("time").sort_index() if out else pd.DataFrame()


def with_rr(sig: pd.DataFrame, rr: float) -> pd.DataFrame:
    """Ricalcola il TP a rr multipli del rischio (entry e rischio sono già nel segnale)."""
    out = sig.copy()
    sgn = np.where(out["side"] == "buy", 1.0, -1.0)
    out["tp"] = out["entry"] + sgn * rr * out["risk"]
    return out


def run(m5: pd.DataFrame, p: SDPParams = SDPParams(), stats: dict | None = None) -> pd.DataFrame:
    sig = generate_signals(m5, p, stats)
    return simulate_trades(m5, sig, with_trend=False) if len(sig) else pd.DataFrame()


def report(sig: pd.DataFrame, m5: pd.DataFrame, label: str) -> None:
    """TP al fine Leg 1 (tp_end) e all'origine Leg 1 (tp_origin), con filtro sul rapporto R:R minimo e sul bias."""
    bias_variants = {"nessun bias": sig, "bias pre-Leg 2": sig[sig.bias_pre_leg2 == sig.want]}
    for bname, sg in bias_variants.items():
        for target in ("tp_end", "tp_origin"):
            for min_rr in (0.0, 1.0, 2.0, 3.0):
                x = sg.copy()
                x["tp"] = x[target]
                ok_side = ((x.side == "buy") & (x.tp > x.entry)) | ((x.side == "sell") & (x.tp < x.entry))
                x = x[ok_side]
                x = x[(x.tp - x.entry).abs() / x.risk >= min_rr]
                if len(x) < 20:
                    print(f"{label} | {bname:14s} | {target:9s} | R:R>={min_rr:.0f}: n={len(x)} (troppo pochi)", flush=True)
                    continue
                t = simulate_trades(m5, x, with_trend=False)
                e = evaluate(t)
                a_, i_, o_ = e["all"], e["in_sample"], e["out_of_sample"]
                print(f"{label} | {bname:14s} | {target:9s} | R:R>={min_rr:.0f}: n={a_['n']:5.0f} win={a_['win_rate']:.3f} "
                      f"pareggio={a_['breakeven_win_rate']:.3f} payoff={a_['payoff_ratio']:.2f} exp={a_['expectancy_R']:+.3f}R "
                      f"PF={a_['profit_factor']:.2f} | IS {i_['expectancy_R']:+.3f} OOS {o_['expectancy_R']:+.3f}", flush=True)


if __name__ == "__main__":
    import sys
    tf = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    m5 = load_ohlc("data/EURUSD_BID_M5.csv.gz")
    if len(sys.argv) > 2 and sys.argv[2] == "report":      # riusa i segnali già generati
        sig = pd.read_pickle(f"data/sdp_signals_v1_M{tf}.pkl")
    else:
        st: dict = {}
        sig = generate_signals(m5, SDPParams(struct_tf_min=tf), st)
        sig.to_pickle(f"data/sdp_signals_v1_M{tf}.pkl")
        print(f"STRUTTURA M{tf} - Funnel:", st, flush=True)
    report(sig, m5, f"M{tf}")
