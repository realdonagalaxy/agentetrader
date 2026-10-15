# TODO

- [ ] **Costi realistici nel backtest** (`src/backtest_engine.py`): servono
  1. spread tipico per simbolo
  2. commissione broker (per lotto / per milione)
  3. modello di slippage (pip fissi o in funzione della volatilità)
  Ora c'è solo il parametro unico `cost` (default 0).
- [ ] **Riempire `knowledge/`** con i manuali SMC / VSA / Price Action.
- [ ] **Storico dati**: aggiungere `data/historical_ticks.csv` (export cTrader).
