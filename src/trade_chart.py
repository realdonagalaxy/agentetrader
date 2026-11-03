"""Grafico di un'operazione chiusa: candele del periodo del trade con le linee di Entry, SL e TP (prezzi di ActivTrades) e il punto di chiusura. Restituisce un PNG (bytes).
Usato da src.mt5_orders per inviare su Telegram lo screenshot quando una posizione arriva a TP o SL."""
import io
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                     # noqa: E402
from matplotlib.patches import Rectangle            # noqa: E402

BG, FG, GRID = "#0e1621", "#e6ebf2", "#263548"
UP, DOWN = "#3fb68b", "#e0605a"
ENTRY_C, SL_C, TP_C = "#7aa3d6", "#e0605a", "#3fb68b"


def render(candles: list[tuple], entry: float, sl: float | None, tp: float | None, close: float, side: str, symbol: str, title: str, digits: int = 2,
           t_entry: int | None = None, t_close: int | None = None) -> bytes:
    """candles: elenco di (tempo_epoch, apertura, massimo, minimo, chiusura) in orario del server. Disegna le candele, le zone di rischio (rosso) e di obiettivo (verde),
    le linee con i prezzi di Entry, SL e TP e un marcatore sul punto di chiusura."""
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=130)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    n = len(candles)
    w = 0.6
    for i, (_, o, h, l, c) in enumerate(candles):
        col = UP if c >= o else DOWN
        ax.plot([i, i], [l, h], color=col, linewidth=1, zorder=2)
        ax.add_patch(Rectangle((i - w / 2, min(o, c)), w, max(abs(c - o), (h - l) * 0.02 or 1e-9), facecolor=col, edgecolor=col, zorder=3))
    levels = [(entry, "Entry", ENTRY_C)] + ([(sl, "SL", SL_C)] if sl else []) + ([(tp, "TP", TP_C)] if tp else [])
    if sl:
        ax.axhspan(min(entry, sl), max(entry, sl), color=SL_C, alpha=0.10, zorder=1)
    if tp:
        ax.axhspan(min(entry, tp), max(entry, tp), color=TP_C, alpha=0.10, zorder=1)
    for price, name, col in levels:
        ax.axhline(price, color=col, linewidth=1.3, linestyle="--", zorder=4)
        ax.text(n - 0.4, price, f" {name}  {price:.{digits}f}", color=col, va="center", ha="left", fontsize=9, fontweight="bold", clip_on=False)
    def near(t):
        return min(range(n), key=lambda i: abs(candles[i][0] - t)) if t else None
    ie, ic = near(t_entry), near(t_close)
    if ie is not None:
        ax.plot([ie], [entry], marker="o", color=ENTRY_C, markersize=7, zorder=6)
    if ic is not None:
        ax.plot([ic], [close], marker="*", color="#ffd166", markersize=13, zorder=6)
        ax.annotate(f"chiusura {close:.{digits}f}", (ic, close), xytext=(-8, 14), textcoords="offset points", color="#ffd166", fontsize=8, ha="right", zorder=6)
    lo = min([c[3] for c in candles] + [p for p, _, _ in levels] + [close])
    hi = max([c[2] for c in candles] + [p for p, _, _ in levels] + [close])
    pad = (hi - lo) * 0.08 or 1
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(-1, n + 0.5)
    step = max(1, n // 8)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([datetime.fromtimestamp(candles[i][0], tz=timezone.utc).strftime("%H:%M") for i in range(0, n, step)], color=FG, fontsize=8)
    ax.set_xlabel("ore: server del broker", color=FG, fontsize=8)
    ax.tick_params(axis="y", colors=FG, labelsize=8)
    ax.yaxis.tick_left()
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)
    for sp in ax.spines.values():
        sp.set_color(GRID)
    ax.set_title(f"{side.upper()} {symbol}   {title}", color=FG, fontsize=12, fontweight="bold", loc="left")
    fig.subplots_adjust(left=0.07, right=0.84, top=0.92, bottom=0.11)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
