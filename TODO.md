# TODO

- [ ] **Costi realistici nel backtest** (`src/backtest_engine.py`): servono
  1. spread tipico per simbolo
  2. commissione broker (per lotto / per milione)
  3. modello di slippage (pip fissi o in funzione della volatilità)
  Ora c'è solo il parametro unico `cost` (default 0).
- [ ] **Riempire `knowledge/`** con i manuali SMC / VSA / Price Action.
- [ ] **Storico dati**: aggiungere `data/historical_ticks.csv` (export cTrader).
- [ ] **Confermare orari sessioni** (`src/market_config.py`, ora provvisori UTC: Asia 0-8, Londra 7-16, New York 12-21) e gestione ora legale.
- [ ] **Confermare simboli cTrader** del tuo broker (NASDAQ/SP500/DOW/ORO/ARGENTO) e se oltre a EURUSD servono altre coppie USD.
- [ ] **Criterio di trend** (controtendenza sì/no) per classificare il contesto dei trade.
