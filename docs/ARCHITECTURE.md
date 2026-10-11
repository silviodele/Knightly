# Architettura

Modello concettuale ripreso da NodePit Runner
([Environments](https://docs.nodepit.com/runner/environments.html),
[Schedules](https://docs.nodepit.com/runner/schedules.html)).

## Componenti
- **Scheduler** (APScheduler): trigger cron / intervallo / una tantum, coda dei run, politica di concorrenza
- **Executor** (`executor.py`): lancia KNIME in batch mode, cattura output ed exit code, timeout e annullamento
- **Dependencies** (`dependencies.py`): legge dal .knwf le estensioni usate e le confronta con l'environment
- **Storage** (SQLAlchemy + SQLite): environment, workflow, dipendenze, schedule, run
- **API/UI** (FastAPI + Jinja2/HTMX): `/api/...` JSON, `/` pagine HTML; log live via Server-Sent Events
- **Notifier**: email/webhook su fallimento

## Modello dati
```
Environment ──< Schedule >── Workflow ──< WorkflowDependency
                   │
                   └──< Run
```
- **Environment** - *dove* gira: cartella dell'installazione KNIME, update site, estensioni richieste,
  file .epf + singole preferenze (es. ambiente Python usato da KNIME), argomenti JVM, variabili d'ambiente.
- **Workflow** - file .knwf caricato e le sue **dipendenze** (feature KNIME), rilevate automaticamente o aggiunte a mano.
- **Schedule** - *come e quando* gira: workflow + environment, trigger, attivo/pausa, variabili di flusso,
  credenziali, reset, concorrenza (allow / skip / queue / replace), timeout, conservazione, notifiche.
- **Run** - singola esecuzione: stato, tempi, exit code, log, origine (schedule / manuale).

## Dipendenze
1. Al caricamento del .knwf si leggono i `settings.xml` dei nodi (`node-feature-symbolic-name`, `node-feature-version`).
2. Le estensioni installate si ricavano da `<knime_path>/features/`.
3. La pagina dello schedule mostra ogni dipendenza come ok / mancante / versione vecchia rispetto all'environment.
4. Lo stesso controllo viene fatto prima di ogni run.
5. (Da fare) installazione automatica delle mancanti con il p2 director:
   `knime -application org.eclipse.equinox.p2.director -nosplash -r <update site> -i <feature.group>`

## Scheduler (`scheduler.py`)
- Gli Schedule stanno nel nostro DB; all'avvio vengono caricati in APScheduler (job store in memoria).
  Dopo ogni modifica di uno Schedule va chiamato `sync_schedule()`. I run persi a servizio spento non vengono recuperati.
- `trigger_run()` crea un Run in coda applicando la concorrenza:
  - `skip`: non crea il run se ce n'e' gia' uno attivo
  - `queue`: un run alla volta, gli altri aspettano in ordine
  - `replace`: annulla quello attivo e parte il nuovo
  - `allow`: tutti in parallelo (limite globale `max_workers`)
- Prima del lancio verifica le dipendenze: se manca un'estensione il run fallisce subito con un messaggio chiaro.
- Exit code KNIME tradotti in messaggi; stati finali: success / failed / cancelled / timeout.
- All'avvio i run rimasti `running` vengono chiusi come falliti, quelli `queued` ripartono.
- Ogni notte alle 3 elimina run e log piu' vecchi della retention dello schedule.
- `on_run_finished` permette di agganciare notifiche e aggiornamenti della UI.

## Interfaccia web e API
- **Schedule**: elenco con prossimo/ultimo run, avvio manuale, pausa. Il form ha il **pannello dipendenze**
  che si aggiorna (HTMX) quando cambiano workflow o environment, con il pulsante "Aggiungi all'environment"
  per le estensioni mancanti; variabili e credenziali a righe dinamiche; storico dei run aggiornato ogni 3s.
- **Workflow**: caricamento .knwf con rilevamento dipendenze, aggiunta/rimozione manuale, nuova versione del file
  (le dipendenze manuali restano).
- **Environment**: configurazione ed elenco delle estensioni installate lette da `features/`.
- **Run**: elenco filtrabile, dettaglio con log in tempo reale (Server-Sent Events) e annullamento.
- Le password delle credenziali non vengono mai restituite da API e pagine (campo vuoto = mantieni).
- API REST sotto `/api` (documentazione OpenAPI su `/docs`), stessa logica delle pagine (`crud.py`).

## Isolamento
Ogni Environment e' una installazione KNIME locale (cartella su disco). L'esecuzione e' dietro
`RunSpec`/`run_workflow`, cosi' un runner Docker si potra' aggiungere in seguito.

## Comando KNIME batch
```
knime -nosplash -consoleLog -nosave -reset -application org.knime.product.KNIME_BATCH_APPLICATION
      -workflowFile="<path.knwf>" -workflow.variable=nome,valore,String
      -credential=nome;login;password -preferences=<file.epf> -vmargs -Xmx4g
```
Exit code: 0 successo, 2 parametri errati, 3 errore di caricamento, 4 errore in esecuzione.

## Da verificare su una installazione KNIME reale
- Le chiavi `node-feature-*` nei `settings.xml` (il parser e' testato su file sintetici)
- Su Windows `knime.exe` resta in attesa fino alla fine del workflow e scrive l'output su stdout?
- Le credenziali passate con `-credential` sono visibili nella riga di comando del processo
