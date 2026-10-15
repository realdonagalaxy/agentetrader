# Wyckoff 2.0 (Rubén Villahermosa Chaves) — appunti operativi

Fonte: "Wyckoff 2.0: Structures, Volume Profile and Order Flow" (Drive). Letto: Prefazione, Parte 1 (1.1–1.7.2) e Parte 2 fino a 2.2.
Corrispondenza con le pagine richieste (11–32 e 33–34) ricavata dal contenuto (Parte 1 ≈ 11–32; 2.1–2.1.1 ≈ 33–34): il testo estratto non ha numeri di pagina.
NB: il libro dà per noti gli eventi base (PS, SC, AR, ST, Spring, UT, UTAD, SOS, LPS, BUEC...), spiegati nel primo libro, che qui non è presente.

## Principi
- Conta la logica, non le etichette: causa (accumulo/distribuzione) -> effetto (trend). Per salire serve un accumulo, per scendere una distribuzione. Non forzare l'identificazione degli eventi di Fase A: basta che il mercato abbia fermato il trend e sia passato a laterale (1.1, 1.7.2).
- Il prezzo prevale sul volume. Il volume intraday dipende dall'orario di sessione: confrontare volumi solo a parità di orario (1.2).
- Si pianifica solo la mossa successiva, mai oltre; il contesto più recente pesa di più; gli scenari si aggiornano (2.2).
- Le linee da sole non danno segnale: non comprare/vendere solo perché il prezzo tocca una linea. Uso corretto: (1) leggere la dinamica, (2) aspettare un estremo per il bias, (3) cercare lì una struttura di accumulo/distribuzione a timeframe inferiore (2.1).

## Il Shakeout (Spring / UT / UTAD) è l'evento dominante (1.4)
- Si opera a favore dell'ultimo shakeout: long dopo un potenziale Spring, short dopo un Upthrust/UTAD.
- Struttura "fallita" (failed accumulation/distribution): tutte le tracce a favore di un lato, ma nel test dopo il breakout (BUEC) il lato opposto spinge e la struttura ruota.
- Più lo shakeout è marcato (cattura più liquidità), più forte il movimento successivo.
- Se un potenziale Spring non produce nemmeno un minor SOS, va rietichettato come semplice test di debolezza (2.2).

## Fallimento strutturale (1.5)
- Struttura = due zone di offerta/domanda con più tocchi. Si assume che il prezzo continui da estremo a estremo.
- **Strength**: il prezzo non raggiunge il fondo della struttura e gira prima = forza (acquirenti difendono). Se in più spazza un minimo rilevante = Spring con forza maggiore.
- **Weakness**: non raggiunge il massimo e gira = debolezza.
- LPS/LPSY sono fallimenti strutturali. Non è un segnale di inversione immediata: è un elemento di contesto.

## Shortening of the Thrust — SOT (1.6)
- Ogni nuovo estremo percorre meno del precedente. Servono almeno 3 spinte; cercare l'accorciamento dalla 3ª/4ª. Oltre 4 spinte con accorciamento persistente il trend può essere troppo forte per il controtrend.
- Con volume alto: divergenza sforzo/risultato (assorbimento). Con volume basso: esaurimento.
- Conferma: forte impulso opposto con volume alto; poi pullback per entrare con il nuovo impulso.
- Va sempre letto nel contesto: dopo un UT, un SOT rialzista NON giustifica un buy; dopo uno Spring, un SOT ribassista NON giustifica uno short (il bias lo decide lo shakeout).

## Strutture inclinate (1.7.1)
- Accumulo con pendenza rialzista = massima forza; con pendenza ribassista = massima debolezza ma con SOT e fallimento strutturale; distribuzione ribassista = massima debolezza; distribuzione rialzista = forza di fondo poi rotazione.
- Si tracciano gli estremi su Fase A/B/C; devono contenere quasi tutto il prezzo; non servono tocchi perfetti.
- Confluenze usate negli esempi: VWAP (settimanale/mensile), VPOC, High Volume Node, Value Area High, Weis wave.
- Strutture insolite (V, pattern chartisti): da non tradare.

## Collegamento con la SDP
| Libro | SDP |
|---|---|
| Accumulo/distribuzione (causa) | Accumulo laterale o spinta lenta |
| Fase A: stop del trend | Origine della Leg 1 |
| Spring / UTAD (Fase C, shakeout) | Leg 2 che spazza la liquidità fino alla Kill Zone Fibo |
| Minor SOS / SOW dopo lo shakeout; test | CHoCH M1/M5 dopo la Kill Zone |
| BUEC / LPS / LPSY | Test dell'OB M1 e ingresso a mercato |
| SOT, fallimento strutturale, sforzo/risultato | Confluenze aggiuntive (MACD divergence, volumi tick, VWAP) |
| Salita verso l'altro estremo (Fase D/E) | Leg 3 verso lo spring/origine della Leg 1 |

## Come usarlo per l'ingresso (proposta, da validare)
Ingresso solo se, nella Kill Zone: (1) c'è uno shakeout di un estremo della struttura (Spring/UTAD); (2) segue una reazione di forza opposta (minor SOS/SOW = CHoCH M5); (3) opzionali come filtri/confluenze: SOT sulle ultime spinte, fallimento strutturale, sforzo/risultato anomalo sul volume. Se la reazione manca, lo shakeout è un semplice test: niente ingresso.

## Parametri da definire (il libro non li dà numericamente)
- Come individuare gli estremi del range/struttura (swing? min. tocchi?).
- Cosa conta come shakeout: quanto oltre l'estremo e entro quante barre deve rientrare?
- Cosa conta come reazione di forza (minor SOS): ampiezza minima, volume?
- Soglia di SOT: numero minimo di spinte (libro: 3) e rapporto di accorciamento.

## DECISIONI (utente)
- Estremi della struttura = **doppi massimi / doppi minimi** (equal highs/lows). Rilevatore: `src/range_detector.py`.
- Tolleranza, timeframe e distanza tra i due pivot: da fissare (provvisori: 0.25*ATR14, H1, 4–48 barre).
