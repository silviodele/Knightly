import type { Concurrency, Run, RunStatus, Schedule } from './api'

export const STATUS: Record<RunStatus, { label: string; color: string; icon: string }> = {
  queued: { label: 'In coda', color: 'warning', icon: 'mdi-timer-sand' },
  running: { label: 'In esecuzione', color: 'info', icon: 'mdi-progress-clock' },
  success: { label: 'Riuscito', color: 'success', icon: 'mdi-check-circle' },
  failed: { label: 'Fallito', color: 'error', icon: 'mdi-alert-circle' },
  cancelled: { label: 'Annullato', color: 'secondary', icon: 'mdi-cancel' },
  timeout: { label: 'Timeout', color: 'error', icon: 'mdi-clock-alert' },
}

export const CONCURRENCY: Record<Concurrency, { title: string; subtitle: string }> = {
  skip: { title: 'Salta', subtitle: 'Non avvia il nuovo run se ce n’è già uno attivo' },
  queue: { title: 'Accoda', subtitle: 'Un run alla volta, gli altri aspettano il loro turno' },
  replace: { title: 'Sostituisci', subtitle: 'Annulla il run attivo e avvia quello nuovo' },
  allow: { title: 'In parallelo', subtitle: 'Avvia comunque, più run insieme' },
}

export const isActive = (status: RunStatus) => status === 'queued' || status === 'running'

const dateTime = new Intl.DateTimeFormat('it-IT', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})
const timeOnly = new Intl.DateTimeFormat('it-IT', { hour: '2-digit', minute: '2-digit' })
const dayName = new Intl.DateTimeFormat('it-IT', { weekday: 'short', day: 'numeric', month: 'short' })
const relative = new Intl.RelativeTimeFormat('it-IT', { numeric: 'auto' })

export function formatDateTime(value: string | null | undefined): string {
  return value ? dateTime.format(new Date(value)) : '—'
}

/** "oggi 06:00", "domani 06:00", "lun 12 ott 06:00" */
export function formatWhen(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  const today = new Date()
  const days = Math.round(
    (new Date(date.toDateString()).getTime() - new Date(today.toDateString()).getTime()) / 86_400_000,
  )
  const time = timeOnly.format(date)
  if (days === 0) return `oggi ${time}`
  if (days === 1) return `domani ${time}`
  if (days === -1) return `ieri ${time}`
  return `${dayName.format(date)} ${time}`
}

/** "tra 3 ore", "5 minuti fa" */
export function formatRelative(value: string | null | undefined, now = Date.now()): string {
  if (!value) return '—'
  const seconds = (new Date(value).getTime() - now) / 1000
  const abs = Math.abs(seconds)
  if (abs < 45) return seconds >= 0 ? 'tra pochi secondi' : 'pochi secondi fa'
  if (abs < 3600) return relative.format(Math.round(seconds / 60), 'minute')
  if (abs < 86_400) return relative.format(Math.round(seconds / 3600), 'hour')
  const startOfDay = (t: number) => new Date(new Date(t).toDateString()).getTime()
  return relative.format(Math.round((startOfDay(new Date(value).getTime()) - startOfDay(now)) / 86_400_000), 'day')
}

export function runDuration(run: Pick<Run, 'started_at' | 'finished_at'>, now = Date.now()): string {
  if (!run.started_at) return '—'
  const end = run.finished_at ? new Date(run.finished_at).getTime() : now
  return formatSeconds(Math.max(0, Math.round((end - new Date(run.started_at).getTime()) / 1000)))
}

export function formatSeconds(total: number): string {
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h) return `${h}h ${m}m`
  if (m) return `${m}m ${s}s`
  return `${s}s`
}

const DAYS = ['domenica', 'lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato']
const pad = (n: string) => n.padStart(2, '0')

/** Descrizione leggibile di un trigger; per i cron copre i casi comuni, altrimenti l'espressione. */
export function describeTrigger(s: Pick<Schedule, 'trigger_type' | 'trigger_value'>): string {
  if (s.trigger_type === 'interval') {
    const minutes = Number(s.trigger_value)
    if (minutes % 1440 === 0) return minutes === 1440 ? 'Ogni giorno' : `Ogni ${minutes / 1440} giorni`
    if (minutes % 60 === 0) return minutes === 60 ? 'Ogni ora' : `Ogni ${minutes / 60} ore`
    return `Ogni ${minutes} minuti`
  }
  if (s.trigger_type === 'date') return `Una volta, ${formatDateTime(s.trigger_value)}`

  const parts = s.trigger_value.trim().split(/\s+/)
  if (parts.length !== 5) return s.trigger_value
  const [min, hour, dom, month, dow] = parts
  const simple = (v: string) => /^\d+$/.test(v)
  if (month !== '*') return s.trigger_value
  if (simple(min) && hour === '*' && dom === '*' && dow === '*') return `Ogni ora al minuto ${min}`
  if (/^\*\/\d+$/.test(min) && hour === '*' && dom === '*' && dow === '*') return `Ogni ${min.slice(2)} minuti`
  if (!simple(min) || !simple(hour)) return s.trigger_value
  const at = `alle ${pad(hour)}:${pad(min)}`
  if (dom === '*' && dow === '*') return `Ogni giorno ${at}`
  if (dom === '*' && (dow === '1-5' || dow === 'mon-fri')) return `Giorni feriali ${at}`
  if (dom === '*' && (dow === '0,6' || dow === '6,0' || dow === 'sat,sun')) return `Weekend ${at}`
  if (dom === '*' && /^[0-7]$/.test(dow)) return `Ogni ${DAYS[Number(dow) % 7]} ${at}`
  if (simple(dom) && dow === '*') return `Il giorno ${dom} di ogni mese ${at}`
  return s.trigger_value
}
