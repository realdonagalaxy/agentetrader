# Esempi reali di trade SDP forniti dall'utente (screenshot TradingView) — 16 ott 2026

Legenda dell'utente: quadrato rosa = lateralizzazione; rettangolo celeste = reversal zone = Kill Zone; "ISTITUZIONI" = candela istituzionale (OB non mitigato).
Orari dei grafici in UTC+2 (UTC+1 per il Dow di marzo). Le linee tratteggiate diagonali disegnano la Leg 3 dall'ingresso al target.

| # | Strumento / TF | Data | Dir. | Entry | SL | TP | R:R | Note |
|---|---|---|---|---|---|---|---|---|
| 1 | Dow Jones M5 (Pepperstone) | 12/3/2026 | short | 47.177,7 (choch) | 47.214,6 | 46.797,8 | ≈10,3 | lateralizzazione 46.890–47.040; Leg 1 giù fino a ≈46.813; KZ calcolata 47.102–47.180; zona ISTITUZIONI 47.230–47.255 |
| 2 | Oro M5 | 14/4/2026 | short | 4.782,10 | 4.790,19 | 4.757,00 | ≈3,1 | lateralizzazione 4.761–4.777; Leg 1 giù a ≈4.758; KZ 4.782–4.789 (celeste 4.783–4.789); VWAP banda alta 4.789,28; picco a 4.796 sopra la zona |
| 3 | US100 M15 | 7/5/2026 | long | 28.555,9 | 28.464,2 | 28.853,4 | ≈3,2 | lateralizzazione ≈28.600; Leg 1 su a 28.853; KZ calcolata 28.444–28.531; SMT (box giallo) |
| 4 | Oro M15 | 11/5/2026 | long | 4.662,25 | 4.646,61 | 4.749,46 | ≈5,6 | lateralizzazione 6/5 (4.677–4.722); Leg 1 a 4.749,5 (8/5); KZ 4.632–4.657; zona ISTITUZIONI 4.636–4.662 |
| 5 | Oro M15 | 21/5/2026 | long | 4.501,08 | 4.488,21 | 4.542,99 | ≈3,3 | trade aperto **sulla Leg 1** (non sul reversal); zona celeste sopra il range (4.531–4.547) = zona bersaglio |

## Cosa è confermato
- Kill Zone = estensione 1,272–1,618 della Leg 1 misurata dai massimi (minimi) uguali della lateralizzazione, proiettata oltre il range: coincide con la geometria del codice (`sdp_wyckoff.py`).
- TP = fine della Leg 1 (estremo opposto). R:R sempre ≥ 1:3. SL appena oltre la zona/test (non sull'estremo della candela H1).
- Ingresso dopo CHoCH e ritorno sulla zona; VWAP banda esterna usata come confluenza (es. 2 e 3).

## Replay del codice sui trade con prezzi Dukascopy (struttura M5/M15)
- Oro 14/4: il codice trova livello 4.777,08 (tuo ≈4.777), Kill Zone 4.782,36–4.789,09 (tua 4.783–4.789), fine Leg 1 4.757,64 (tuo TP 4.757,00): **geometria identica**.
  Nessun segnale perché il picco (4.796, ≈ estensione 1,98) supera la tolleranza della zona e il CHoCH arriva oltre la finestra di 2 ore.
- Oro 11/5 (M15): il codice NON trova la struttura: la tua Leg 2 torna dopo ≈2,5 giorni (lateralizzazione 6/5, Leg 1 8/5, ingresso 11/5); il codice aspetta solo 12 ore.
- Oro 21/5: segnale a 4.517,86 con SL 4.488,34 (tuo SL 4.488,21 identico), ma entri tu prima, a 4.501, sulla Leg 1.

## Correzioni da fare al modello
1. Finestre temporali di giorni (non ore) tra lateralizzazione, Leg 1 e ritorno della Leg 2, soprattutto su M15.
2. Tollerare lo sforamento della Kill Zone (fino a ≈ estensione 2,0?) — da confermare.
3. SL = oltre l'ultimo test/zona; ingresso dopo CHoCH + ritorno; filtro R:R ≥ 1:3 verso la fine della Leg 1.
4. Aggiungere (da decidere) i trade "sulla Leg 1" come l'esempio 5.
