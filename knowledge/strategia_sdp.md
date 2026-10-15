# Strategia SDP (Donatello Pugliese)
Fonte: Google Doc "Strategia_SDP" (Drive, mod. 2026-02-05). Riassunto fedele, senza integrazioni.

## 1. Bias (H1/H4)
Direzione da Price Action + indicatore Session Volume Profile. La Leg 3 deve andare a favore del bias.

## 2. Le gambe (dopo un Accumulo laterale o spinta lenta)
- **Leg 1 (Induzione)**: primo drive che esce dall'accumulo (idealmente a favore del bias). Si misura con Fibonacci extension.
- **Leg 2 (Distribuzione/Eccesso)**: drive opposto alla Leg 1, prende la liquidità residua dell'accumulo e arriva alla **Kill Zone Fibo**.
- **Leg 3 (Reversal)**: parte dalla Kill Zone, nella direzione della Leg 1, a favore del bias. Target naturale: spring/origine della Leg 1.
- **Leg 4**: dopo la Leg 3, nuovo CHoCH M5; target = spring della Leg 2 (ciclo completo).

## 3. Kill Zone Fibo
Extension della Leg 1: range **1.272 – 1.168** (il doc nota che forse l'intento è 1.618; altrove: 1.272–1.618).
Dentro la zona serve un POI: Imbalance, Order Block non mitigato, chiusura di struttura o sweep M15.

## 4. Confluenze
Box Asiatico · VWAP con 2 bande esterne · Divergenza MACD (fast 3, slow 10, signal 16) · Volumi tick.

## 5. Macro / trigger
Leg 3 durante macro di alta liquidità: **Londra 9:00–11:00** (tabella: 9:00–11:30) o **NY 14:30–17:00**.
- EURUSD, AUDUSD: attendere CHoCH M1, poi test dell'OB M1 (protezione dietro OB istituzionale mitigato).
- Indici USA, commodities, crypto: dopo CHoCH M1 attendere UT/ST o UTAD/SPRING; SL oltre la struttura.
- CHoCH M1 = aggressivo; M5 = conservativo/conferma.

## 6. Gestione trade
TP su OB della Leg 1 o banda opposta del VWAP. R:R minimo 1:3. A 1:3: BE + parziale 50%.

## 7. Asset e finestre (doc)
EURUSD, AUDUSD (Londra 9:00–11:30, NY 14:30–17:00) · NASDAQ/SP500/Dow (solo NY 14:30–17:00; setup A+++ nei giorni CPI/NFP/FED) ·
XAUUSD 9:00–17:00 · BTC/ETH/SOL 14:00–18:00 e 00:00–02:00.

## 8. Wyckoff (indici/commodities/crypto)
PS, AC, UT, UTAD, ST, SPRING: il CHoCH M1 può essere sbilanciato da deep mitigation (UT/ST, poi UTAD/SPRING).

## DECISIONI (utente)
- Kill Zone: **1.272 – 1.618** (scritto "1.1618": interpretato come 1.618 — da riconfermare).
- Backtest: usare **tutti gli orari delle tre sessioni** (Asia, Londra, New York); le fasce macro (Londra 9–11, NY 14:30–17) servono solo per il **journaling**, da valutare dopo i dati del backtest.
- Costi ignorati nel backtest; focus su rischio/rendimento.
- Trend/bias: struttura HH/HL su H4 e H1.
- Stop Loss: sul **massimo/minimo di H1** (interpretazione da confermare: estremo della candela H1 che contiene l'estremo della Leg 2, oltre di esso).

## AMBIGUITÀ ANCORA APERTE
1. TP: fisso 1:3, oppure OB della Leg 1 / banda VWAP? Se < 1:3 si salta il trade?
2. SL: conferma dell'interpretazione sopra (quale candela H1, buffer sì/no).
3. Definizioni operative: accumulo, spinta lenta, OB non mitigato, imbalance (FVG 3 candele?), CHoCH M1/M5 (finestra swing).
4. Dati M1/M5/M15 (fonte) per i simboli.
5. Asset: doc ha AUDUSD/crypto; utente EURUSD, indici, oro, argento.
