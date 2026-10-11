# Knightly

**Scheduler open source per workflow [KNIME](https://www.knime.com/)**: pianifica, esegue e monitora i
workflow in batch su installazioni KNIME locali, con dashboard web, log in tempo reale e gestione delle
dipendenze (estensioni KNIME). Ispirato a [NodePit Runner](https://nodepit.com/product/runner).

> Knightly è un progetto indipendente: non è affiliato, sponsorizzato né approvato da KNIME AG.
> KNIME® è un marchio registrato di KNIME AG.

## Obiettivi
- Gestire gli **Environment**: installazioni KNIME locali con estensioni, preferenze (.epf) e argomenti JVM
- Gestire gli **Schedule**: workflow schedulabili (cron / intervalli / una tantum) collegati a un environment
- Rilevare le **dipendenze** di ogni workflow (estensioni KNIME) e verificarle sull'environment scelto
- Eseguire in batch mode tramite `knime -nosplash -application org.knime.product.KNIME_BATCH_APPLICATION`
- Passare variabili di flusso e credenziali per ogni esecuzione
- Storico esecuzioni con stato, durata e log (anche in tempo reale)
- Notifiche in caso di errore
- Interfaccia web + API REST

## Stack
Backend: Python 3.11+ · FastAPI · APScheduler · SQLAlchemy/SQLite

Frontend: Vue 3 · Vite · TypeScript · Vuetify 4 (tutte dipendenze MIT/Apache)

## Sviluppo
Backend:
```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
python -m knightly          # API su http://127.0.0.1:8000
```
Frontend (serve Node.js solo in sviluppo):
```
cd frontend
npm install
npm run dev                        # http://localhost:5173, le chiamate /api vanno al backend
npm run build                      # compila in knightly/webapp/, servita da FastAPI
```

## Avvio
```
python -m knightly            # http://127.0.0.1:8000
python -m knightly --host 0.0.0.0 --port 8080 --data-dir D:\knightly-data
```
- Al primo accesso l'interfaccia chiede di creare l'amministratore. In alternativa:
  `python -m knightly create-user admin --role admin` (chiede la password).
- Password dimenticata: `python -m knightly reset-password <utente>`.
- Interfaccia web: `/` (Dashboard, Schedule, Run, Workflow, Environment, Utenti) — richiede `npm run build`
- API REST: `/api/...`, documentazione interattiva su `/docs` (serve il login)
- Dati (database SQLite, workflow caricati, log dei run) in `./data` o nella cartella `--data-dir`

## Utenti e ruoli
| Ruolo | Può |
|---|---|
| Lettore | vedere dashboard, schedule, run e log |
| Operatore | anche creare/modificare schedule, workflow, environment e avviare/annullare run |
| Amministratore | anche gestire gli utenti |

## Struttura
- `knightly/` - codice applicativo
  - `models.py` - Environment, Workflow, WorkflowDependency, Schedule, Run
  - `dependencies.py` - lettura dipendenze dal .knwf e confronto con l'environment
  - `executor.py` - esecuzione di KNIME in batch mode
  - `scheduler.py` - trigger, coda dei run, concorrenza, annullamento, pulizia storico
  - `crud.py` - operazioni sul dominio condivise da API e pagine
  - `api.py` - API REST JSON (`/api`)
  - `auth.py` - login, sessioni, ruoli e gestione utenti
  - `webapp/` - build del frontend (generata, non versionata)
- `frontend/` - interfaccia web Vue 3 + Vuetify
- `tests/` - test (con un finto eseguibile KNIME)
- `docs/` - architettura e note di progetto
- `workflows/` - workflow KNIME di esempio (.knwf)

## Licenza
[MIT](LICENSE) © 2026 Antonio Silvio de Letteriis
