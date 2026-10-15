# Registro backtest

## SDP v0 — EURUSD BID, 2003-05 → 2025-12, costi ignorati (15 ott 2026)
Regole: bias H4+H1 (HH/HL) · doppio min/max M15 (tol 0.25 ATR, 30 min–8 h) · shakeout M5 (rientro entro 12 barre) ·
CHoCH M5 (entro 24 barre) · SL sotto/sopra estremo candela H1 dello shakeout · TP = rr × rischio · tutte le sessioni.
NON include: Leg 1/Leg 2, Kill Zone Fibo, POI (OB/imbalance), VWAP, MACD, macro orarie.

| rr | n | win rate | win rate di pareggio | expectancy | PF | IS exp | OOS exp |
|---|---|---|---|---|---|---|---|
| 1 | 847 | 48.9% | 50.0% | -0.022R | 0.96 | -0.027 | -0.012 |
| 2 | 847 | 32.1% | 33.3% | -0.037R | 0.95 | -0.052 | 0.000 |
| 3 | 847 | 23.8% | 25.0% | -0.046R | 0.94 | -0.068 | +0.004 |

Senza filtro bias (rr 2): 8305 trade, win 33.2% vs pareggio 33.3%, expectancy -0.005R.
Conclusione: nessun vantaggio statistico; win rate = win rate di pareggio. Per anno expectancy tra -0.56R e +0.55R (rumore).
Sotto-gruppi (sessione, lato) non significativi: n piccoli, errore standard ~0.05–0.15R; non selezionare a posteriori.
