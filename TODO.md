# TODO

- [ ] **Costi realistici nel backtest** (RIMANDATO: per ora il backtest li ignora) (`src/backtest_engine.py`): servono
  1. spread tipico per simbolo
  2. commissione broker (per lotto / per milione)
  3. modello di slippage (pip fissi o in funzione della volatilità)
  Ora c'è solo il parametro unico `cost` (default 0).
- [ ] **Riempire `knowledge/`** con i manuali SMC / VSA / Price Action.
- [ ] **Storico dati**: aggiungere `data/historical_ticks.csv` (export cTrader).
- [ ] **Confermare orari sessioni** (`src/market_config.py`, ora provvisori UTC: Asia 0-8, Londra 7-16, New York 12-21) e gestione ora legale.
- [ ] **Confermare simboli cTrader** del tuo broker (NASDAQ/SP500/DOW/ORO/ARGENTO) e se oltre a EURUSD servono altre coppie USD.
- [x] Criterio di trend: struttura HH/HL su H4+H1 (`src/market_structure.py`). Da confermare: finestra swing (`SWING_N=2`).
- [ ] **Strategia SDP**: chiarire le 7 ambiguità in `knowledge/strategia_sdp.md`, poi implementare il generatore di segnali e backtestare.
- [ ] **Dati M1/M5/M15** per i simboli: la strategia richiede CHoCH M1/M5, il backtest H1 non basta.
