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


# Orario operativo per APRIRE i trade (ora italiana): dall'apertura di New York; prima si individua solo il setup.
ENTRY_FROM, ENTRY_TO = (15, 30), (18, 30)        # confermato dall'utente: CHoCH M5 tra le 15:30 e le 18:30 ora italiana


def in_entry_window(ts: datetime, start=ENTRY_FROM, end=ENTRY_TO) -> bool:
    """True se `ts` (naive = UTC) cade nell'orario in cui è permesso aprire un trade."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    loc = ts.astimezone(MACRO_TZ)
    m = loc.hour * 60 + loc.minute
    return start[0] * 60 + start[1] <= m < end[0] * 60 + end[1]

# Filtro VWAP (banda 2σ, VWAP giornaliero): "choch" = la chiusura del CHoCH M5 deve essere oltre la banda (lettura letterale);
# "extreme" = basta che l'estremo ST/UT, Spring/UTAD sia oltre la banda; None = nessun filtro. DA CONFERMARE con l'utente.
VWAP_RULE = "choch"

# Messaggi con Entry/SL/TP (UT/UTAD): spenti dopo il cambio di approccio (17 ott 2026): l'assistente segnala la CONFORMAZIONE
# (setup, climax, ST/Spring) e il contesto lo valuta l'utente. Rimettere True per riavere i piani di trade.
SEND_TRADE_PLAN = False

# Tipi di avviso da inviare. "approach" = foto + direzione quando la Leg 2 sta per arrivare sulla Kill Zone (richiesta dell'utente, 17 ott 2026).
# Altri disponibili: "setup" (rottura del livello), "climax" (🚨 SC/BC), "st" (ST oltre SC / UT oltre BC), "spring" (Spring oltre ST / UTAD oltre UT).
ALERT_STAGES = ("approach",)
KZ_APPROACH = 0.10      # ASSUNZIONE: "quasi all'arrivo" = prezzo a meno di 0,10 x lunghezza Leg 1 dall'inizio della Kill Zone (estensione 1,272), o già dentro
ALERT_LEG_ATR = 2.0     # ASSUNZIONE: avvisi solo con Leg 1 >= 2 ATR (M15)
ALERT_COOLDOWN_MIN = 60 # al massimo un avviso per direzione ogni 60 minuti (tra più strutture sovrapposte vale la Leg 1 più lunga)
