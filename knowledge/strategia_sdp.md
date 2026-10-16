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

## DECISIONI AGGIORNATE (utente, 15 ott 2026)
- Struttura (range): doppi massimi/minimi, tolleranza 0,25 × ATR, picchi a 30 min–8 h; rilevati su M15 oppure M5.
- Leg 1 misurata dai minimi uguali (induzione rialzista) o dai massimi uguali (induzione ribassista); riconosciuta quando la Leg 2 rompe il livello opposto.
- Kill Zone: estensione 1.272–1.618 della Leg 1. POI: candela istituzionale (Order Block) non mitigata a sinistra, anche un po' fuori zona.
- Ingresso: CHoCH M5 (M1 se disponibili i dati). SL sull'estremo della candela H1 dello shakeout. Bersaglio: fine Leg 1 (o origine, "spring" della Leg 1); R:R minimo 1:3 nel documento.
- Bias: HH/HL su H4 e H1. Nei test non migliora i risultati.
- Macro (ora italiana, ora legale inclusa): Londra 9:00–11:00, New York 14:30–17:00; applicate all'orario del CHoCH. Per il backtest iniziale tutte le sessioni; le macro si valutano dopo.
- VWAP: ancorato all'apertura Asia (00:00 UTC) per tutta la giornata; ingresso oltre la **banda esterna 2σ** (confronto con 1σ).
- MACD (3, 10, 16): divergenza rialzista/ribassista tra shakeout e swing precedente (linea MACD, M5).
- Costi (spread, commissioni, slippage): ignorati per ora, da inserire quando serviranno.

## AMBIGUITÀ ANCORA APERTE
1. TP definitivo: fine Leg 1 / origine Leg 1 / banda opposta del VWAP; gestione BE + parziale 50% a 1:3.
2. Il documento cita anche Box Asiatico, volumi tick, Session Volume Profile: non ancora implementati.
3. CHoCH M1: servono i dati M1 (disponibili sul Mac in data/raw, non ancora caricati qui).
4. Asset: finora solo EURUSD; oro, argento, indici e GBPUSD da scaricare per la verifica su dati nuovi.

## Strumenti da validare (aggiornato)
EURUSD (fatto), XAUUSD, XAGUSD, NASDAQ (USATECHIDXUSD), SP500 (USA500IDXUSD), Dow (USA30IDXUSD), GBPUSD, EURCAD, BTCUSD, ETHUSD.
Scale prezzi Dukascopy: forex 1e5; JPY/oro/argento/indici 1e3; BTC/ETH 10 (verificati su BTC 2021-01-05 = 32.007; ETH = 1.040).
Crypto: mercato 24/7 (sabato incluso). Il documento dà finestre proprie per BTC/ETH (14:00–18:00 sovrapposizione NY e 00:00–02:00 reset/Asia, ora italiana)
diverse dalle macro Londra/NY del forex: da testare a parte, non mischiare con le macro forex.
