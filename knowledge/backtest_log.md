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

## SDP v1 — bersaglio alla fine / origine della Leg 1 (15 ott 2026) — risultati CORRETTI
Errore trovato e corretto: TP dal lato sbagliato dell'ingresso contati come vittorie istantanee (tp_origin: 82% dei casi, tp_end: 18%).
Il simulatore ora scarta i setup con TP non valido. Costi ignorati. EURUSD BID 2003-05 → 2025-12.

| Struttura | Bias | Bersaglio | R:R min | n | win | pareggio | exp | IS | OOS |
|---|---|---|---|---|---|---|---|---|---|
| M15 | nessuno | fine Leg 1 | 0 | 1119 | 53,5% | 55,4% | −0,033R | −0,051 | +0,010 |
| M15 | nessuno | fine Leg 1 | 1 | 536 | 32,5% | 35,4% | −0,082R | −0,131 | +0,031 |
| M15 | nessuno | fine Leg 1 | 2 | 231 | 21,6% | 25,4% | −0,149R | −0,255 | +0,096 |
| M15 | nessuno | fine Leg 1 | 3 | 115 | 12,2% | 19,1% | −0,362R | −0,527 | +0,017 |
| M15 | nessuno | origine Leg 1 | 0 | 244 | 70,9% | 75,9% | −0,066R | −0,071 | −0,056 |
| M5 | nessuno | fine Leg 1 | 0 | 2031 | 52,7% | 54,7% | −0,037R | −0,082 | +0,065 |
| M5 | nessuno | fine Leg 1 | 1 | 944 | 33,4% | 34,9% | −0,044R | −0,135 | +0,167 |
| M5 | nessuno | fine Leg 1 | 2 | 440 | 21,4% | 24,9% | −0,143R | −0,238 | +0,077 |
| M5 | nessuno | fine Leg 1 | 3 | 221 | 14,0% | 19,0% | −0,261R | −0,378 | +0,010 |
| M5 | pre-Leg 2 | fine Leg 1 | 2 | 64 | 21,9% | 22,1% | −0,010R | −0,251 | +0,520 |
| M5 | pre-Leg 2 | fine Leg 1 | 3 | 40 | 15,0% | 16,3% | −0,079R | −0,305 | +0,449 |
| M5 | nessuno | origine Leg 1 | 0 | 436 | 68,1% | 73,5% | −0,074R | −0,118 | +0,028 |

Lettura: win rate sempre sotto il pareggio; peggiora al crescere del R:R minimo. OOS positivo solo in sottogruppi piccoli
(n 40–230) con IS fortemente negativo: segno che cambia = rumore. Nessuna evidenza di vantaggio.

## SDP v1 + macro orarie (ingresso in Londra 9:00–11:00 o New York 14:30–17:00, ora italiana) — 15 ott 2026
Filtro applicato all'orario del CHoCH M5 (fuso Europe/Rome con ora legale). Segnali invariati, filtri a posteriori. Costi ignorati.
Celle esaminate: 2 timeframe × 4 gruppi orari × 4 bersagli × 2 bias = 64 → alcune apparirebbero "significative" per caso.

| Struttura | Gruppo | Bersaglio | n | win | pareggio | exp | IS | OOS |
|---|---|---|---|---|---|---|---|---|
| M15 | tutte le ore | rr 2 | 1375 | 33,5% | 33,3% | +0,006R | +0,017 | −0,019 |
| M15 | macro | rr 2 | 488 | 34,6% | 33,3% | +0,039R | +0,091 | −0,082 |
| M15 | macro | fine Leg 1 | 366 | 60,7% | 57,8% | +0,050R | +0,066 | +0,012 |
| M15 | solo Londra | rr 2 | 243 | 32,5% | 33,3% | −0,025R | +0,041 | −0,178 |
| M15 | solo New York | rr 2 | 245 | 36,7% | 33,3% | +0,102R | +0,158 | −0,027 |
| M15 | solo New York | fine Leg 1 | 178 | 64,0% | 58,6% | +0,093R | +0,176 | −0,099 |
| M5 | tutte le ore | rr 2 | 2786 | 33,0% | 33,3% | −0,009R | −0,043 | +0,069 |
| M5 | macro | rr 2 | 892 | 34,3% | 33,3% | +0,029R | −0,010 | +0,119 |
| M5 | solo Londra | rr 2 | 441 | 32,2% | 33,3% | −0,034R | −0,055 | +0,015 |
| M5 | solo New York | rr 1 | 451 | 51,0% | 50,0% | +0,020R | −0,022 | +0,118 |
| M5 | solo New York | rr 2 | 451 | 36,4% | 33,3% | +0,091R | +0,019 | +0,257 |
| M5 | solo New York | fine Leg 1 | 306 | 62,4% | 58,1% | +0,074R | +0,036 | +0,163 |

Con bias pre-Leg 2 (M15, macro): n 52–68, expectancy −0,10/−0,21R. Nessun filtro bias risulta utile.
Lettura: New York è l'unico gruppo con segno positivo in entrambi i timeframe (+0,07/+0,10R), ma errore standard ~0,06R
(t ≈ 1,4) e IS/OOS discordanti su M15: ipotesi da confermare su dati non ancora usati, NON risultato.
Londra: nessun effetto. Prossimo passo proposto: ipotesi fissata a priori "macro New York" da verificare su altri strumenti.
