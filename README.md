# knime-scheduler

Scheduler open source per workflow KNIME, ispirato a NodePit Runner.

## Obiettivi
- Schedulare l'esecuzione di workflow KNIME (cron / intervalli / una tantum)
- Eseguirli in batch mode tramite `knime -nosplash -application org.knime.product.KNIME_BATCH_APPLICATION`
- Passare variabili di flusso (flow variables) per ogni esecuzione
- Storico esecuzioni con stato, durata e log
- Notifiche in caso di errore
- Interfaccia web + API REST

## Struttura
- `docs/` - architettura e note di progetto
- `workflows/` - workflow KNIME di esempio (.knwf)

## Stato
Progetto appena creato: stack tecnologico ancora da definire.
