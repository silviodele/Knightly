# Architettura

Modello concettuale ripreso da NodePit Runner
([Environments](https://docs.nodepit.com/runner/environments.html),
[Schedules](https://docs.nodepit.com/runner/schedules.html)).

## Componenti
- **Scheduler** (APScheduler): trigger cron / intervallo / una tantum, coda dei run, politica di concorrenza
- **Executor** (`executor.py`): lancia KNIME in batch mode, cattura output ed exit code, timeout e annullamento
- **Dependencies** (`dependencies.py`): legge dal .knwf le estensioni usate e le confronta con l'environment
- **Storage** (SQLAlchemy + SQLite): environment, workflow, dipendenze, schedule, run
- **API** (FastAPI): `/api/...` JSON, unico contratto con il frontend; log live via Server-Sent Events
- **UI** (Vue 3 + Vuetify, in `frontend/`): single page app compilata in `knime_scheduler/webapp/` e servita da FastAPI
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

## Interfaccia web
Layout dashboard con menu laterale, tema chiaro/scuro.
- **Dashboard**: KPI (schedule attivi, run in corso, run oggi, falliti 24h, % successo 7 giorni), grafico
  dei run degli ultimi 14 giorni, prossime esecuzioni, ultimi errori, avviso per schedule con estensioni mancanti.
- **Schedule**: tabella con ricerca, prossimo/ultimo run, attiva/pausa, avvio manuale. Il form ha il
  **pannello dipendenze** (aggiornato al cambio di workflow/environment, "Aggiungi all'environment"),
  editor del trigger con modelli e **anteprima dei prossimi 5 orari**, scelta della concorrenza,
  variabili e credenziali, storico run in una scheda.
- **Run**: elenco filtrabile per stato e schedule; dettaglio con **log in tempo reale** (SSE), filtro,
  evidenziazione di WARN/ERROR, download, annullamento e riesecuzione.
- **Workflow**: caricamento .knwf trascinando i file, dipendenze rilevate e manuali, nuova versione del file.
- **Environment**: configurazione ed estensioni installate lette da `features/`.

Endpoint pensati per la UI: `/api/stats`, `/api/triggers/preview`, `/api/dependency-check`,
`/api/environments/{id}/extensions`, `PATCH /api/schedules/{id}/active`, `/api/runs/{id}/log/stream`.

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

## Note
- Cron in formato standard (0/7 = domenica): APScheduler 3 conta da 0 = lunedi', quindi `make_trigger`
  converte il giorno della settimana in nomi (`mon`…`sun`).

## Da verificare su una installazione KNIME reale
- Le chiavi `node-feature-*` nei `settings.xml` (il parser e' testato su file sintetici)
- Su Windows `knime.exe` resta in attesa fino alla fine del workflow e scrive l'output su stdout?
- Le credenziali passate con `-credential` sono visibili nella riga di comando del processo
