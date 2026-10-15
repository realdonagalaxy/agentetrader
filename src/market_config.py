"""Asset e sessioni di mercato su cui lavora l'agente.

ATTENZIONE: gli orari delle sessioni (UTC) sono valori PROVVISORI, da confermare
(l'ora legale sposta Londra/New York di 1h). I nomi simbolo dipendono dal broker cTrader.
"""
from datetime import datetime, timezone

# nome logico -> simbolo broker (da verificare sul tuo conto cTrader)
ASSETS = {
    "forex": {"EURUSD": "EURUSD"},
    "indici": {"NASDAQ": "US TECH 100", "SP500": "US 500", "DOW JONES": "US 30"},
    "metalli": {"ORO": "XAUUSD", "ARGENTO": "XAGUSD"},
}

# (ora inizio, ora fine) UTC, fine esclusa. Le sessioni si sovrappongono.
SESSIONS_UTC = {
    "Asia": (0, 8),
    "Londra": (7, 16),
    "New York": (12, 21),
}


def sessions_at(ts: datetime) -> list[str]:
    """Sessioni attive all'istante `ts` (naive = UTC)."""
    if ts.tzinfo:
        ts = ts.astimezone(timezone.utc)
    return [n for n, (a, b) in SESSIONS_UTC.items() if a <= ts.hour < b]


def session_label(ts: datetime) -> str:
    return "+".join(sessions_at(ts)) or "Off-hours"
