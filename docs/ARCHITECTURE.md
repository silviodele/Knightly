# Architettura (bozza)

- **Scheduler**: gestisce i trigger (cron, intervallo, una tantum) e la coda dei job
- **Executor**: lancia KNIME in batch mode, cattura stdout/stderr ed exit code
- **Storage**: database (job, schedule, run, log)
- **API/UI**: gestione job, avvio manuale, consultazione storico
- **Notifier**: email/webhook su fallimento

## Comando KNIME batch
knime -nosplash -consoleLog -reset -nosave -application org.knime.product.KNIME_BATCH_APPLICATION -workflowFile="<path.knwf>" -workflow.variable=nome,valore,String
