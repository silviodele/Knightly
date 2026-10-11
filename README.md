# knime-scheduler

Scheduler open source per workflow KNIME, ispirato a [NodePit Runner](https://nodepit.com/product/runner).

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
Python 3.11+ · FastAPI · APScheduler · SQLAlchemy/SQLite · Jinja2 + HTMX

## Sviluppo
```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## Struttura
- `knime_scheduler/` - codice applicativo
  - `models.py` - Environment, Workflow, WorkflowDependency, Schedule, Run
  - `dependencies.py` - lettura dipendenze dal .knwf e confronto con l'environment
  - `executor.py` - esecuzione di KNIME in batch mode
  - `scheduler.py` - trigger, coda dei run, concorrenza, annullamento, pulizia storico
- `tests/` - test (con un finto eseguibile KNIME)
- `docs/` - architettura e note di progetto
- `workflows/` - workflow KNIME di esempio (.knwf)
