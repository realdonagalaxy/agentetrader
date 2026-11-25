# Registro delle modifiche

Versioni nel formato MAJOR.MINOR.PATCH:
- **PATCH** (1.0.1): correzioni di errori, senza funzioni nuove.
- **MINOR** (1.1.0): funzioni o comportamenti nuovi compatibili con l'esistente. Ogni modifica a come si aprono o chiudono gli ordini conta come MINOR.
- **MAJOR** (2.0.0): cambi di architettura o modifiche non compatibili con dati e impostazioni esistenti.
Quando sale MINOR, PATCH torna a 0; quando sale MAJOR, MINOR e PATCH tornano a 0. Una correzione che cambia il comportamento degli ordini va comunque annotata qui.

## 1.1.0 — 25/11/2026
- Angoli sempre vivi in tutta l'interfaccia (nessun bordo tondo, anche nella pagina del PIN); etichetta della versione con lo stesso colore dell'ora.

## 1.0.0 — 25/11/2026
Prima versione numerata. Stato del programma:
- Gestione Conti come app desktop (finestra, icona nell'area di notifica, avvio unico di server e ascolto segnali); ramo `backup-webapp-2026-11-20` con la versione solo-web.
- Pagina Trade con equity curve e posizioni/ordini in corso; calendario; pagina Automatico con segnali per canale ed esiti (❌ SL, 🟰 BE, cerchio verde TP).
- Segnali da più canali Telegram (Cedric, AuraKage) con scarto di prezzo per canale e canali associati a ogni conto; un trade alla volta per conto.
- Ordini: mercato oppure LIMIT/STOP sull'entry se il prezzo è oltre 1,5 $ dall'entry atteso; parzializzazione a catena (una posizione con TP1, a TP1 si apre la seconda con SL all'entry della prima).
- Pulsanti «Dividi» e «BE», conti reali con conferma REALE; MT5 dedicato per conto; pulizia degli accessi salvati.
