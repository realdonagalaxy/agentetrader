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

## SDP-Wyckoff (climax = gobba più grande dell'istogramma MACD 3,10,16 nella Leg 2; test con gobba minore + volume minore) — 15 ott 2026
EURUSD BID 2003-05 → 2025-12, costi ignorati. Per ogni struttura si prende il primo candidato CHoCH M5 che soddisfa la variante (causale).
Variante macro = ingresso in Londra 9–11 o New York 14:30–17 (ora italiana). Target 1:2. SL = estremo candela H1.

Controllo di attribuzione (struttura M15, tol 0,25 ATR, macro, 1:2):
| Variante | n | expectancy (±errore) |
|---|---|---|
| PLACEBO: qualsiasi CHoCH dopo la rottura (senza Wyckoff) | 7142 | +0,041R (±0,017) |
| solo Kill Zone | 3553 | +0,067R (±0,024) |
| Wyckoff + volume (solo) | 2419 | +0,068R (±0,029) |
| Kill Zone + Wyckoff + volume | 1075 | +0,102R (±0,044) |
| Wyckoff senza volume | 3080 | +0,069R (±0,026) |

Tutte le ore: expectancy ≈ 0 (es. Wy+volume solo: −0,002R ±0,016). Con tol 0,5 ATR: stessi ordini di grandezza (Wy+volume solo macro: +0,054R ±0,023).
Anni positivi: 13/23 (Wy+volume solo). Rischio mediano ≈ 21 pips. Sensibilità ai costi (Wy+volume solo): 0,5 pip → +0,042R; 1,0 pip → +0,015R.
Lettura: il vantaggio compare solo nelle macro di Londra/New York; la condizione Wyckoff NON aggiunge informazione rispetto al placebo
(+0,068 vs +0,041, differenza ~1 errore standard). L'effetto è piccolo (t ≈ 2,3–2,4) e i costi lo erodono. Non è un vantaggio operativo.
Ipotesi emersa, coerente con il documento SDP (Leg 2 che liquida il Box Asiatico all'apertura di Londra): inversioni dopo sweep
di liquidità alle aperture di Londra/New York. Da testare in modo specifico (Box Asiatico) e su altri strumenti.

Controllo di attribuzione, struttura M5 (tol 0,25 ATR, macro, 1:2):
| Variante | n | expectancy (±errore) | anni positivi |
|---|---|---|---|
| PLACEBO: qualsiasi CHoCH (macro) | 15171 | +0,049R (±0,012) | — |
| solo Kill Zone | 6948 | +0,067R (±0,017) | — |
| Wyckoff + volume (solo) | 4422 | +0,096R (±0,022) | 14/23 |
| Kill Zone + Wyckoff + volume (no OB) | 1565 | +0,114R (±0,037) | 17/23 |
| Wyckoff senza volume | 5610 | +0,086R (±0,019) | — |
IS/OOS (Wy+volume solo): +0,070 / +0,157. Con costo 1,0 pip/trade (rischio mediano ≈ 21 pips): +0,044R (solo) e +0,059R (no OB).
Lettura: la maggior parte dell'effetto (+0,05R) è presente anche nel placebo (macro + CHoCH dopo sweep); la condizione Wyckoff
aggiunge circa +0,05R (≈ 2 errori standard, borderline). Effetto piccolo, stabile in IS/OOS, ma da validare su dati non usati
(altri strumenti) e con costi reali prima di qualsiasi uso operativo.

## SDP-Wyckoff su XAUUSD (struttura M5, tol 0,25 ATR, macro Londra+NY, TP 1:2) — 16 ott 2026 (eseguito dall'utente sul Mac)
Dati: 1.470.654 barre M5, 2003-05-05 → 2025-12-31, close 339–4548. **Mancano gli anni 2007 e 2021** (download incompleto: da riscaricare).
| Variante | n | expectancy (±errore) |
|---|---|---|
| PLACEBO: qualsiasi CHoCH | 15128 | −0,011R (±0,011) |
| solo Kill Zone | 7618 | −0,039R (±0,016) |
| Wyckoff + volume (solo) | 4259 | +0,016R (±0,022) |
| Kill Zone + Wyckoff + volume | 1795 | +0,046R (±0,034) |
| Wyckoff senza volume | 5743 | −0,017R (±0,019) |
Wy+volume (solo): anni positivi 11/21; prima metà +0,085R, seconda metà −0,054R. Rischio mediano 28,7 "pip" (1 pip = 0,1 USD) ≈ 2,9 USD.
Con 1,0 pip di costo: −0,023R (solo) / +0,004R (KZ+Wy+vol). Spread reale dell'oro tipicamente > 1 pip in questa unità (da confermare col broker).
Lettura: l'effetto macro visto su EURUSD (placebo +0,049R) NON si ripete sull'oro (placebo −0,011R); il vantaggio di Wy+volume (+0,016R) è dentro l'errore e
instabile nel tempo (+0,085 → −0,054). Nessuna evidenza di vantaggio sull'oro.

## SDP v3 (regole calibrate sui trade dell'utente) — XAUUSD struttura M15, 2003-05 → 2025-12 (eseguito dall'utente sul Mac, 16 ott 2026)
Regole v3: Leg 1 = prima induzione fuori dalla lateralizzazione (primo ritracciamento ≥ 25%); finestre in giorni; sforamento Kill Zone fino a estensione 2,0;
CHoCH M5 sullo swing dopo l'ultimo test; ingresso sul ritorno al livello rotto; SL oltre l'ultimo test; TP = fine Leg 1; R:R ≥ 1:3. Costi ignorati. Dati senza 2007 e 2021.
Funnel: 43.803 doppi → 18.181 con Leg 1 valida → 30.100 CHoCH → 8.500 trade (18.647 scartati per R:R < 1:3, 1.513 senza ritorno).
Risultati (primo candidato per struttura):
| Scopo | Uscita | Variante | n | win | expectancy (±err) | IS | OOS |
|---|---|---|---|---|---|---|---|
| tutte le ore | TP unico | tutti i setup | 3921 | 17,0% | −0,020R (±0,040) | −0,058 | +0,069 |
| tutte le ore | BE+50% a 3R | tutti i setup | 3921 | 25,4% | +0,001R (±0,031) | −0,028 | +0,067 |
| tutte le ore | BE+50% a 3R | KZ + Wyckoff+volume | 2084 | 26,1% | +0,029R (±0,044) | +0,019 | +0,052 |
| macro | TP unico | tutti i setup | 859 | 19,7% | +0,052R (±0,075) | −0,036 | +0,256 |
| macro | BE+50% a 3R | tutti i setup | 859 | 28,5% | +0,105R (±0,063) | +0,030 | +0,278 |
| macro | BE+50% a 3R | Kill Zone | 837 | 28,6% | +0,101R (±0,064) | +0,048 | +0,224 |
| macro | BE+50% a 3R | KZ + OB + Wy+vol | 129 | 26,4% | +0,055R (±0,166) | +0,011 | +0,159 |
Lettura: nessuna variante si distingue dallo zero oltre ~1,7 errori standard; Kill Zone, OB e Wyckoff non migliorano rispetto ai setup di base (la parte che conta è
geometria + ritorno + R:R ≥ 3). L'unico segno coerente (IS e OOS positivi) è macro + gestione BE/50%: +0,10R, da verificare su altri strumenti e con i costi.

## SDP v3 — EURUSD struttura M15 (16 ott 2026, regole v3, costi ignorati)
Funnel: 41.640 doppi → 18.010 Leg 1 valida → 29.413 CHoCH → 9.567 trade (16.348 scartati per R:R < 1:3).
| Scopo | Uscita | Variante | n | exp (±err) | IS | OOS |
|---|---|---|---|---|---|---|
| tutte le ore | TP unico | tutti i setup | 4367 | −0,028R (±0,040) | −0,040 | −0,001 |
| tutte le ore | BE+50% a 3R | tutti i setup | 4368 | −0,044R (±0,029) | −0,046 | −0,040 |
| macro | TP unico | tutti i setup | 922 | +0,011R (±0,072) | +0,010 | +0,012 |
| macro | BE+50% a 3R | tutti i setup | 922 | +0,017R (±0,061) | +0,016 | +0,019 |
| macro | BE+50% a 3R | KZ + Wyckoff+volume | 437 | +0,063R (±0,092) | +0,152 | −0,142 |
| macro | BE+50% a 3R | KZ + OB + Wy+vol | 127 | +0,292R (±0,186) | +0,300 | +0,275 |
Lettura: su EURUSD con le regole v3 non c'è vantaggio (tutte le ore negativo, macro ≈ 0). La variante più selettiva (KZ+OB+Wy+vol, macro) è positiva ma con
127 trade e ±0,19R (≈1,6 errori standard); sull'oro la stessa variante dà +0,055R: non coerente. Nessuna evidenza robusta su due strumenti.

## SDP v3 — XAUUSD struttura M5 (16 ott 2026, eseguito dall'utente; regole v3, costi ignorati, mancano 2007 e 2021)
Funnel: 114.340 doppi → 34.014 Leg 1 valida → 46.983 CHoCH → 10.830 trade (31.625 scartati per R:R < 1:3, 2.144 senza ritorno).
| Scopo | Uscita | Variante | n | exp (±err) | IS | OOS |
|---|---|---|---|---|---|---|
| tutte le ore | TP unico | tutti i setup | 5034 | −0,080R (±0,033) | −0,132 | +0,041 |
| tutte le ore | BE+50% a 3R | tutti i setup | 5034 | −0,050R (±0,026) | −0,096 | +0,059 |
| tutte le ore | BE+50% a 3R | KZ + Wyckoff+volume | 2646 | −0,020R (±0,037) | −0,058 | +0,069 |
| macro | TP unico | tutti i setup | 1063 | −0,048R (±0,064) | −0,039 | −0,070 |
| macro | BE+50% a 3R | tutti i setup | 1063 | +0,028R (±0,055) | +0,024 | +0,037 |
| macro | BE+50% a 3R | KZ + OB + Wy+vol | 198 | +0,066R (±0,132) | +0,071 | +0,055 |
Lettura: su M5 l'oro è negativo su tutte le ore (−0,05/−0,08R, ≈2–2,4 errori standard) e nelle macro ≈ 0 (+0,03R ±0,055). Il +0,105R visto su M15 (macro, BE+50%) non si ripete su M5.
Nessun filtro (Kill Zone, OB, Wyckoff) migliora in modo coerente. Nessuna evidenza di vantaggio sull'oro.

## SDP v3 — USATECHIDXUSD (Nasdaq 100) struttura M15, 2011-09 → 2025-12 (eseguito dall'utente, 16 ott 2026)
Funnel: 15.927 doppi → 7.359 Leg 1 valida → 10.898 CHoCH → 4.468 trade (4.883 scartati per R:R < 1:3).
| Scopo | Uscita | Variante | n | exp (±err) | IS | OOS |
|---|---|---|---|---|---|---|
| tutte le ore | TP unico | tutti i setup | 1951 | +0,007R (±0,061) | +0,031 | −0,049 |
| tutte le ore | BE+50% a 3R | tutti i setup | 1951 | −0,011R (±0,044) | +0,013 | −0,066 |
| macro | BE+50% a 3R | tutti i setup | 649 | −0,041R (±0,073) | +0,047 | −0,245 |
| tutte le ore | BE+50% a 3R | KZ+OB+Wy+vol | 357 | +0,076R (±0,107) | +0,041 | +0,156 |
Lettura: tutto ≈ 0 entro l'errore; le macro Londra+NY (non specifiche per l'indice) sono negative fuori campione. Nessuna evidenza di vantaggio.
Da fare: separare "solo New York 14:30–17:00" (finestra indicata nel documento per gli indici USA) con `python -m src.sdp_v3 USATECHIDXUSD 15 report`.

## SDP v3 — USATECHIDXUSD (Nasdaq 100) struttura M5, 2011-09 → 2025-12 (eseguito dall'utente, 16 ott 2026)
Funnel: 38.033 doppi → 12.841 Leg 1 valida → 15.870 CHoCH → 5.764 trade (7.709 scartati per R:R < 1:3).
| Scopo | Uscita | Variante | n | exp (±err) | IS | OOS |
|---|---|---|---|---|---|---|
| tutte le ore | TP unico | tutti i setup | 2590 | +0,052R (±0,056) | +0,044 | +0,069 |
| tutte le ore | BE+50% a 3R | tutti i setup | 2590 | +0,041R (±0,040) | +0,047 | +0,027 |
| tutte le ore | BE+50% a 3R | KZ + OB | 960 | +0,081R (±0,072) | +0,071 | +0,106 |
| macro | BE+50% a 3R | tutti i setup | 829 | −0,014R (±0,065) | +0,019 | −0,092 |
Lettura: su M5 il Nasdaq è leggermente positivo su tutte le ore (+0,04/+0,05R, ≈1 errore standard, IS e OOS concordi), le macro Londra+NY sono ≈ 0 o negative.
Il segno è opposto a quello di oro/EURUSD per le macro: nessun effetto orario coerente tra strumenti.

## Sintesi v3 — caso base ("tutti i setup", tutte le ore, gestione BE+50% a 3R)
EURUSD M15 −0,044R (±0,029) · XAUUSD M15 +0,001R (±0,031) · XAUUSD M5 −0,050R (±0,026) · NASDAQ M15 −0,011R (±0,044) · NASDAQ M5 +0,041R (±0,040).
Media ≈ −0,01R: compatibile con zero. Nessun vantaggio meccanico dimostrato (costi ancora ignorati).

## FRVP H1 + CHoCH M5 (17 ott 2026) — EURUSD 2003-2025, R:R min 2,0, TP = fine gamba, costi ignorati
Regole in `src/frvp_h1.py` (gamba H1 LH→LL / HL→HH, profilo tick a range fisso, tocco POC/VAH/VAL ±0,25 ATR M15, CHoCH M5, SL oltre l'estremo del ritracciamento).
- Profilo (primo tra POC/VAH/VAL): n=1548, win 21,4% (pareggio 23,5%), −0,088R ±0,048, IS −0,100 / OOS −0,062.
- Solo POC −0,009R ±0,070 · solo VAH −0,186R ±0,074 · solo VAL −0,068R ±0,079.
- Controllo "50% della gamba" (senza volumi) −0,118R ±0,055 · Placebo +0,011R ±0,015.
- Su 2018-2019 (n=119) usciva +0,39R ±0,23: rumore, scomparso sull'intero periodo. Nessun vantaggio dimostrato.
