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


# --- Macro di alta liquidità (Strategia SDP): orari in ora italiana, ora legale inclusa ---
from zoneinfo import ZoneInfo  # noqa: E402

MACRO_TZ = ZoneInfo("Europe/Rome")
MACROS_LOCAL = {"Londra": ((9, 0), (11, 0)), "New York": ((14, 30), (17, 0))}  # (inizio, fine) h:m locali, fine esclusa


def macro_at(ts: datetime) -> str | None:
    """Nome della macro attiva all'istante `ts` (naive = UTC), oppure None."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    loc = ts.astimezone(MACRO_TZ)
    m = loc.hour * 60 + loc.minute
    for name, ((h0, m0), (h1, m1)) in MACROS_LOCAL.items():
        if h0 * 60 + m0 <= m < h1 * 60 + m1:
            return name
    return None
