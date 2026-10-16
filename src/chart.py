"""Screenshot del setup (candele + zone + livelli + istogramma MACD) da allegare ai messaggi Telegram."""
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from src.data_loader import resample  # noqa: E402
from src.live_analysis import decimals  # noqa: E402

BG0, FG0, GRID0 = "#131722", "#d1d4dc", "#2a2e39"
UP, DOWN = "#26a69a", "#ef5350"


def render_chart(sym: str, m5: pd.DataFrame, tf: int, rec: dict, tps: list[float] | None = None, bars: int = 360,
                 macd_par: tuple[int, int, int] = (3, 10, 16)) -> bytes:
    gold = rec.get("kind") in ("UT", "UTAD", "watch")
    # tema: oro = stile TradingView dell'utente (sfondo grigio, candele nere); altri strumenti = tema scuro
    BG, FG, GRID = ("#9e9e9e", "#161616", "#858585") if gold else (BG0, FG0, GRID0)
    LAT, DOT_EDGE = ("#4a148c", "#222222") if gold else ("#ce93d8", "#131722")
    if gold:
        macd_par = (8, 21, 5)
        tf, bars = 5, max(bars, 900)         # la sequenza BC/UT/UTAD e il MACD (8,21,5) sono calcolati su M5: grafico M5 coerente
    full = m5 if tf == 5 else resample(m5, f"{tf}min")
    cl = full["close"]
    macd = cl.ewm(span=macd_par[0], adjust=False).mean() - cl.ewm(span=macd_par[1], adjust=False).mean()
    hist_full = macd - macd.ewm(span=macd_par[2], adjust=False).mean()
    t_end = full.index[-1]
    if gold:                                  # solo lo schema: dalla lateralizzazione (con un po' di margine) fino al segnale
        t_start = pd.Timestamp(rec["lat_t1"]) - pd.Timedelta(minutes=5 * 30)
    else:
        t_start = min(pd.Timestamp(rec["lat_t1"]) - pd.Timedelta(hours=12), t_end - pd.Timedelta(days=3))
    df = full.loc[t_start:].iloc[-bars:]
    hist = hist_full.reindex(df.index)
    n = len(df)
    pos = lambda t: int(np.clip(df.index.searchsorted(pd.Timestamp(t)), 0, n - 1))
    d = decimals(sym)
    buy = rec["side"] == "buy"

    fig, (ax, axm) = plt.subplots(2, 1, figsize=(11, 6.6), gridspec_kw={"height_ratios": [4, 1], "hspace": 0.04}, sharex=True)
    fig.patch.set_facecolor(BG)
    for a in (ax, axm):
        a.set_facecolor(BG)
        a.tick_params(colors=FG, labelsize=8)
        a.grid(False) if gold else a.grid(color=GRID, linewidth=0.5)
        for sp in a.spines.values():
            sp.set_color(GRID)
    x = np.arange(n)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    if gold:        # Buy: corpo vuoto con bordo verde · Sell: corpo bianco con bordo verde
        ax.vlines(x, l, h, colors="#111111", linewidth=0.9)
        ax.bar(x, np.maximum(np.abs(c - o), 1e-9), bottom=np.minimum(o, c), width=0.7, linewidth=0.9, edgecolor="#111111",
               color=np.where(c >= o, BG, "#111111"))
    else:
        col = np.where(c >= o, UP, DOWN)
        ax.vlines(x, l, h, colors=col, linewidth=0.8)
        ax.bar(x, np.abs(c - o), bottom=np.minimum(o, c), color=col, width=0.7)
    right = n - 1 + max(8, int(n * 0.14))

    # lateralizzazione
    lo_lat, hi_lat = sorted((float(rec["level"]), float(rec["lat_hi"])))
    x1, x2 = pos(rec["lat_t1"]), pos(rec["lat_t2"])
    if gold:                                   # solo rette: contorno del riquadro della lateralizzazione, senza riempimento
        ax.add_patch(Rectangle((x1, lo_lat), max(x2 - x1, 1), hi_lat - lo_lat, fill=False, edgecolor=LAT, linewidth=1.2))
    else:
        ax.add_patch(Rectangle((x1, lo_lat), max(x2 - x1, 1), hi_lat - lo_lat, color="#9c27b0", alpha=0.25, lw=0))
    ax.text(x1, hi_lat, " lateralizzazione", color=LAT, fontsize=8, va="bottom")
    ax.hlines(float(rec["level"]), x1, right, colors=LAT, linestyles=":", linewidth=0.9)
    gold_marks = []
    # Leg 1 e Kill Zone
    xb = pos(rec["b_time"])
    ax.plot([x2, xb], [float(rec["level"]), float(rec["b_price"])], color="#444444" if gold else "#9e9e9e", linestyle="--", linewidth=1)
    ax.text(xb, float(rec["b_price"]), " fine Leg 1", color=FG if gold else "#bdbdbd", fontsize=8, va="bottom" if buy else "top")
    kz_lo, kz_hi = sorted((float(rec["kz_lo"]), float(rec["kz_hi"])))
    if not gold:
        ax.add_patch(Rectangle((xb, kz_lo), right - xb, kz_hi - kz_lo, color="#42a5f5", alpha=0.22, lw=0))
        ax.text(xb + 1, kz_hi, " Kill Zone", color="#90caf9", fontsize=8, va="bottom")
    if gold:                                   # sequenza Wyckoff: freccia BC/SC, pallino giallo UT, pallino rosso UTAD
        YEL, GRN = "#ffeb3b", "#4caf50"
        marks = [("bc", "SC" if buy else "BC", YEL)]
        if rec.get("ut_time") is not None and pd.notna(rec.get("ut_time")):
            marks.append(("ut", "ST" if buy else "UT", YEL))
        if rec.get("utad_time") is not None and pd.notna(rec.get("utad_time")):
            marks.append(("utad", "Spring" if buy else "UTAD", GRN))
        for i_m, (k, name, colr) in enumerate(marks):
            xi, yv = pos(rec[f"{k}_time"]), float(rec[f"{k}_price"])
            ax.plot([xi], [yv], "o", color=colr, markersize=10, zorder=5, markeredgecolor=DOT_EDGE)
            ax.annotate(name, (xi, yv), xytext=(0, (-1 if buy else 1) * (14 + 13 * (i_m % 2))), textcoords="offset points", color=FG if gold else colr, fontsize=9,
                        fontweight="bold", ha="center", va="top" if buy else "bottom")
            gold_marks.append((xi, name, colr))
    else:
        ax.plot([pos(rec["sw_time"])], [float(rec["sw_price"])], "o", color="#ffeb3b", markersize=5)
    # piano
    ymin, ymax = float(df["low"].min()), float(df["high"].max())
    if gold:
        ymin, ymax = min(ymin, float(rec["bc_price"])), max(ymax, float(rec["bc_price"]))
    if pd.notna(rec.get("entry")):
        entry, sl = float(rec["entry"]), float(rec["sl"])
        ts = tps or [float(rec["tp"])]
        ts = ts if not gold else [float(rec["tp1"]), float(rec["tp"])]
        xs = pos(rec["choch_time"])
        if not gold:
            ax.add_patch(Rectangle((xs, min(entry, sl)), right - xs, abs(entry - sl), color=DOWN, alpha=0.22, lw=0))
            ax.add_patch(Rectangle((xs, min(entry, ts[-1])), right - xs, abs(ts[-1] - entry), color=UP, alpha=0.15, lw=0))
        for y, name, colr in [(entry, "Entry", "#ffeb3b"), (sl, "SL", DOWN)] + [(t, f"TP{i + 1}" if len(ts) > 1 else "TP", UP) for i, t in enumerate(ts)]:
            ax.hlines(y, 0 if gold else xs, right, colors=colr, linewidth=1.1)       # oro: linea su tutta la larghezza del grafico
            ax.text(right, y, f" {name} {y:.{d}f}", color=("#0b6b3a" if (gold and colr == UP) else ("#b8860b" if (gold and name == "Entry") else colr)), fontsize=8, va="center", fontweight="bold" if gold else "normal")
            ymin, ymax = min(ymin, y), max(ymax, y)
    ymin, ymax = (min(ymin, lo_lat), max(ymax, hi_lat)) if gold else (min(ymin, kz_lo), max(ymax, kz_hi, hi_lat))
    pad = (ymax - ymin) * (0.14 if gold else 0.06)
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.set_xlim(-1, right + int(n * 0.12))
    ax.yaxis.tick_right()
    ax.set_title(f"{sym} · M{tf} · {'BUY' if buy else 'SELL'}{' · ' + rec['kind'] if gold else ''} · {pd.Timestamp(t_end):%d/%m/%Y %H:%M} UTC", color=FG, fontsize=11, loc="left")
    # MACD
    tick = False                                            # grafico sempre con MACD (i volumi tick sono rimossi dalla grafica)
    hv = df["volume"].to_numpy(dtype=float) if tick else hist.to_numpy()
    if gold:                                                   # stile TradingView: bastoncini sottili blu-viola
        axm.vlines(x, 0, np.nan_to_num(hv), colors="#3f4fd1", linewidth=1.1)
    else:
        axm.bar(x, hv, color="#ffffff" if tick else np.where(hv >= 0, UP, DOWN), width=1.0 if tick else 0.7, linewidth=0)
    for xi, name, colr in (gold_marks if tick else []):           # tick: pallino sulla barra col volume massimo attorno al punto
        a0, a1 = max(xi - 6, 0), min(xi + 7, n)
        pk = a0 + int(np.nanargmax(hv[a0:a1]))
        axm.plot([pk], [hv[pk]], "o", color=colr, markersize=8, zorder=5, markeredgecolor=DOT_EDGE)
    for xi, name, colr in ([] if tick else gold_marks):                       # pallino sulla gobba del MACD (picco della gobba che contiene la barra)
        if np.isnan(hv[xi]):
            continue
        sg = hv[xi] >= 0
        lo_i = hi_i = xi
        while lo_i > 0 and not np.isnan(hv[lo_i - 1]) and (hv[lo_i - 1] >= 0) == sg:
            lo_i -= 1
        while hi_i < n - 1 and not np.isnan(hv[hi_i + 1]) and (hv[hi_i + 1] >= 0) == sg:
            hi_i += 1
        pk = lo_i + int(np.nanargmax(np.abs(hv[lo_i:hi_i + 1])))
        axm.plot([pk], [hv[pk]], "o", color=colr, markersize=8, zorder=5, markeredgecolor=DOT_EDGE)
    axm.axhline(0, color=GRID, linewidth=0.8)
    if np.isfinite(hv).any():
        lo_, hi_ = float(np.nanmin(hv)), float(np.nanmax(hv))
        axm.set_ylim(min(lo_, 0) - 0.12 * (hi_ - lo_), max(hi_, 0) + 0.08 * (hi_ - lo_))
    axm.text(0.005, 0.85, "Volumi tick" if tick else f"MACD {macd_par}", transform=axm.transAxes, color=FG, fontsize=8)
    axm.yaxis.tick_right()
    step = max(n // 8, 1)
    axm.set_xticks(x[::step])
    axm.set_xticklabels([f"{t:%d/%m %H:%M}" for t in df.index[::step]], rotation=0, fontsize=7)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
