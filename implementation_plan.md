# Aggiunta Anagrafica Partecipanti alla Dashboard Premium

Per rispondere alla tua domanda: **Sì, è assolutamente essenziale censire ogni partecipante**. Il sistema ha bisogno di sapere non solo chi vota (grazie al numero di telefono), ma soprattutto *che ruolo ha* quel numero (Leader o Follower) per poter bilanciare le coppie e generare i Match alla fine.

Farlo dal brutto pannello Admin di Django è macchinoso, quindi, come hai giustamente richiesto, andremo ad aggiungere un'elegante **Rubrica (Anagrafica)** direttamente nella tua Dashboard Premium.

## Modifiche Proposte

### 1. Nuovi Endpoint Backend (Django)
Aggiungeremo a `core/views.py` e `core/urls.py` delle nuove API per gestire i partecipanti in modo dinamico senza ricaricare la pagina:
- **GET** `/api/participants/` (Recupera la lista di tutti i partecipanti)
- **POST** `/api/participants/save/` (Crea o aggiorna un partecipante)
- **POST** `/api/participants/delete/` (Elimina un partecipante)

### 2. Nuova Scheda nella Dashboard (`dashboard.html`)
- Aggiungeremo un nuovo bottone di navigazione: **Rubrica Partecipanti**.
- Creeremo un nuovo pannello `tab-roster` in perfetto stile glassmorphism.
- Il pannello conterrà una **tabella dinamica o griglia di card** con tutti i partecipanti, i loro ruoli (con badge colorati) e i loro numeri.
- Inseriremo una barra di ricerca veloce per filtrare i partecipanti.

### 3. Modale Interattiva per Inserimento/Modifica
- Un pulsante "➕ Aggiungi Partecipante" farà scendere una modale animata.
- Campi del form:
  - Nome e Cognome
  - Numero di Telefono (con avviso che le ultime 10 cifre sono la chiave di matching)
  - Ruolo (Tendina: Leader / Follower / Entrambi)
  - Livello (Tendina: Base / Intermedio / Avanzato)
- Il salvataggio aggiornerà la lista all'istante.

### 4. Styling Premium (`dashboard.css`)
- Estenderemo il tuo CSS vanilla esistente per stilizzare le tabelle, i badge di ruolo (es. azzurro per Leader, rosa per Follower, viola per Entrambi) e le modali con gli stessi effetti glassmorphism vibranti già presenti.

## Verifica
- Aggiungeremo alcuni partecipanti di prova usando la nuova UI.
- Verificheremo che vengano salvati correttamente nel Database.
- Potrai subito inserire il tuo numero vero, eliminare i partecipanti farlocchi (Follower 1, Leader 2) e finalmente far funzionare il ciclo completo dei sondaggi!

---

Procedo con l'implementazione?
