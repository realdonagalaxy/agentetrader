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

## SDP v1 — Leg 1/Leg 2 + Kill Zone 1.272–1.618 + OB non mitigato + CHoCH M5 (15 ott 2026)
EURUSD BID 2003-05 → 2025-12, costi ignorati. SL = estremo candela H1 dello shakeout; TP = rr × rischio.
Leg 1 misurata dai minimi (massimi) uguali del range; OB: ultima candela opposta prima di impulso ≥ 1 ATR, mai ritoccata.
Parametri provvisori: tol 0.25 ATR, distanza picchi 30 min–8 h, pad OB 0.25×Leg 1, Leg 1 ≥ 1 ATR.

Funnel struttura M15: 41.640 doppi → 32.834 livello rotto → 30.497 Kill Zone → 9.763 OB → 6.967 OB toccato → 1.979 CHoCH → 1.453 segnali.
Funnel struttura M5: 102.706 doppi → 90.010 → 84.171 → 26.818 OB → 17.396 toccato → 4.734 CHoCH → 3.008 segnali.

| Struttura | Filtro bias | rr | n | win | pareggio | expectancy | IS | OOS |
|---|---|---|---|---|---|---|---|---|
| M15 | nessuno | 1 | 1375 | 50,0% | 50,0% | +0,001R | +0,008 | −0,017 |
| M15 | nessuno | 2 | 1375 | 33,5% | 33,3% | +0,006R | +0,017 | −0,019 |
| M15 | nessuno | 3 | 1375 | 24,3% | 25,0% | −0,028R | −0,002 | −0,090 |
| M15 | pre-Leg 2 | 1 | 192 | 44,8% | 50,0% | −0,104R | −0,090 | −0,138 |
| M15 | pre-Leg 2 | 3 | 192 | 21,9% | 25,0% | −0,125R | −0,134 | −0,103 |
| M5 | nessuno | 1 | 2786 | 49,0% | 50,0% | −0,021R | −0,049 | +0,045 |
| M5 | nessuno | 2 | 2786 | 33,0% | 33,3% | −0,009R | −0,043 | +0,069 |
| M5 | nessuno | 3 | 2786 | 24,4% | 25,0% | −0,022R | −0,073 | +0,096 |
| M5 | pre-Leg 2 | 1 | 333 | 51,4% | 50,0% | +0,027R | −0,004 | +0,100 |
| M5 | pre-Leg 2 | 2 | 333 | 32,4% | 33,3% | −0,027R | −0,124 | +0,200 |
| M5 | pre-Leg 2 | 3 | 333 | 24,0% | 25,0% | −0,039R | −0,142 | +0,200 |

Lettura: nessuna evidenza di vantaggio. Win rate ≈ win rate di pareggio ovunque; IS e OOS cambiano segno tra M15 e M5
(errore standard dei sottogruppi 0,05–0,2R): rumore. Nessuna selezione a posteriori della variante migliore.
