# Stato del progetto (passaggio di consegne) — 16 ott 2026

Leggi prima: `CLAUDE.md` (regole), `knowledge/strategia_sdp.md` (strategia e decisioni), `knowledge/backtest_log.md` (tutti i risultati), `TODO.md`.

## Obiettivo
Agente che analizza il grafico (dati cTrader) con la **Strategia SDP + Wyckoff** e invia l'analisi su **Telegram**.
Il trade lo decide l'utente. Esecuzione automatica solo dopo validazione statistica (non ancora raggiunta). Costi di trading ignorati nei test per ora.

## Cosa esiste (src/)
- `data_loader.py`, `make_timeframes.py`, `dukascopy_fetch.py`: dati Dukascopy (M1 → M5/M15/H1/H4). Scale: forex 1e5, JPY/oro/argento/indici 1e3, BTC/ETH 10. Crypto 24/7.
- `range_detector.py` (doppi massimi/minimi), `market_structure.py` (bias HH/HL H4+H1), `market_config.py` (sessioni, macro Londra 9–11 e NY 14:30–17 ora di Roma).
- `sdp_strategy.py` (v1: Kill Zone Fibo + OB + CHoCH), `sdp_wyckoff.py` (v2: climax = gobba più grande dell'istogramma MACD 3,10,16 nella Leg 2; test con gobba minore e volume minore).
- `backtest_engine.py` (R-multipli, IS/OOS, TP validi solo dal lato giusto).
- `live_analysis.py`: genera il messaggio Telegram (collaudato in replay storico). `telegram_bot.py`: invio e ricerca chat id. `ctrader_auth.py`: OAuth cTrader.

## Risultati chiave (EURUSD 2003–2025, senza costi)
- v1 e filtri VWAP/MACD-linea: nessun vantaggio.
- v2 (struttura M5, ingresso nelle macro Londra/NY, Wyckoff+volume, TP 1:2): +0,096R (±0,022). Il placebo (qualsiasi CHoCH in macro) fa +0,049R (±0,012): il Wyckoff aggiunge ≈ +0,05R (borderline). Fuori macro ≈ 0.
- Con 1 pip di costo e rischio mediano ≈ 21 pip resta ≈ +0,04R: piccolo. **Da validare su altri strumenti.**

## In corso / da fare
1. Dati sul Mac dell'utente (scaricati con `dukascopy_fetch`, poi `make_timeframes`): XAUUSD (completo, file `XAUUSD_BID_M5.csv.gz` ≈ 32 MB da allegare), USATECHIDXUSD, GBPUSD (con anni mancanti da ricompletare), poi EURCAD, BTCUSD, ETHUSD (finestre macro proprie del documento), argento, SP500, Dow.
2. Eseguire su ogni strumento lo stesso test: `python -m src.sdp_wyckoff 5 0.25 full <SIMBOLO>` (serve `data/<SIMBOLO>_BID_M5.csv.gz`) e il controllo placebo (vedi `knowledge/backtest_log.md`). Verificare la scala dei prezzi degli indici.
3. cTrader: l'applicazione Open API è "Submitted", non "Active" (errore "OA client is not in active state"). Quando sarà attiva: `ctrader_auth` (--url, --code, --accounts, --set-account), poi fonte dati live in `live_analysis.fetch_ctrader` e ciclo ogni 5 minuti con deduplica.
4. Telegram: bot già collegato e testato (`config.env` sul Mac dell'utente; mai committare).
5. Idee aperte: Box Asiatico, volumi tick, Session Volume Profile, gestione trade (BE + 50% a 1:3), imbalance/FVG come POI, CHoCH M1 (servono dati M1).

## Note di metodo
- Nessun parametro inventato senza dirlo; chiedere all'utente in caso di ambiguità (CLAUDE.md).
- Confronto sempre con il placebo, errore standard e in/fuori campione; molte combinazioni testate = attenzione al caso.
- File dati e segnali (`data/`) non sono su git: vanno riallegati nella nuova sessione.
