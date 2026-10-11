// Client tipizzato per le API REST del backend (/api).

export type RunStatus = 'queued' | 'running' | 'success' | 'failed' | 'cancelled' | 'timeout'
export type TriggerType = 'cron' | 'interval' | 'date'
export type Concurrency = 'skip' | 'queue' | 'replace' | 'allow'
export type VariableType = 'String' | 'int' | 'double'
export type Role = 'viewer' | 'operator' | 'admin'

export interface User {
  id: number
  username: string
  full_name: string
  role: Role
  active: boolean
  created_at: string
  last_login_at: string | null
}

export interface UserIn {
  username: string
  full_name: string
  role: Role
  active: boolean
  password?: string | null
}

export interface Environment {
  id: number
  name: string
  notes: string
  knime_path: string
  update_sites: string[]
  extensions: string[]
  preferences_file: string | null
  preference_entries: Record<string, string>
  jvm_args: string[]
  env_vars: Record<string, string>
  created_at: string
}
export type EnvironmentIn = Omit<Environment, 'id' | 'created_at'>

export interface Dependency {
  id: number
  feature_id: string
  name: string
  vendor: string
  version: string
  update_site: string | null
  source: 'detected' | 'manual'
}

export interface Workflow {
  id: number
  name: string
  notes: string
  file_path: string
  uploaded_at: string
  dependencies: Dependency[]
}

export interface Variable {
  name: string
  type: VariableType
  value: string
}

export interface Credential {
  name: string
  login: string
  password?: string
}

export interface Run {
  id: number
  schedule_id: number
  schedule_name: string
  status: RunStatus
  triggered_by: 'schedule' | 'manual'
  triggered_by_user: string | null
  queued_at: string
  started_at: string | null
  finished_at: string | null
  exit_code: number | null
  error: string | null
}

export interface ScheduleIn {
  name: string
  notes: string
  workflow_id: number | null
  environment_id: number | null
  active: boolean
  trigger_type: TriggerType
  trigger_value: string
  variables: Variable[]
  credentials: Credential[]
  reset_before_run: boolean
  concurrency: Concurrency
  timeout_minutes: number | null
  retention_days: number | null
  notify_on: string[]
}

export interface Schedule extends ScheduleIn {
  id: number
  workflow_id: number
  environment_id: number
  workflow_name: string
  environment_name: string
  next_run_time: string | null
  last_run: Run | null
  missing_dependencies: number
}

export interface DependencyCheck {
  feature_id: string
  name: string
  required_version: string
  installed_version: string | null
  status: 'ok' | 'missing' | 'outdated'
  requested: boolean
}

export interface TriggerPreview {
  valid: boolean
  error: string | null
  next_runs: string[]
}

export interface Stats {
  schedules_total: number
  schedules_active: number
  runs_active: number
  runs_today: number
  failed_24h: number
  success_rate_7d: number | null
  daily: { day: string; success: number; failed: number; other: number }[]
  upcoming: { schedule_id: number; schedule_name: string; next_run_time: string }[]
  recent_failures: Run[]
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown })?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // errori di validazione Pydantic
    return detail
      .map((e: { loc?: (string | number)[]; msg?: string }) => {
        const field = (e.loc ?? []).filter((p) => p !== 'body').join('.')
        return field ? `${field}: ${e.msg}` : e.msg
      })
      .join(' · ')
  }
  return fallback
}

// Chiamata quando una richiesta riceve 401 (sessione scaduta): impostata dal router
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  // L'header X-Knightly-CSRF e' richiesto dal backend per le modifiche: un sito esterno non puo' inviarlo
  const init: RequestInit = { method, headers: { 'X-Knightly-CSRF': '1' }, credentials: 'same-origin' }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  const response = await fetch(`/api${url}`, init)
  if (!response.ok) {
    if (response.status === 401 && !url.startsWith('/auth/')) onUnauthorized?.()
    let parsed: unknown = null
    try {
      parsed = await response.json()
    } catch {
      /* risposta non JSON */
    }
    throw new ApiError(errorMessage(parsed, `Errore ${response.status}`), response.status)
  }
  if (response.status === 204) return undefined as T
  const type = response.headers.get('content-type') ?? ''
  return (type.includes('application/json') ? response.json() : response.text()) as Promise<T>
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  return entries.length ? '?' + new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString() : ''
}

export const api = {
  authStatus: () => request<{ needs_setup: boolean; user: User | null }>('GET', '/auth/status'),
  login: (username: string, password: string) => request<User>('POST', '/auth/login', { username, password }),
  setup: (data: { username: string; full_name: string; password: string }) => request<User>('POST', '/auth/setup', data),
  logout: () => request<void>('POST', '/auth/logout'),
  changePassword: (current_password: string, new_password: string) =>
    request<void>('POST', '/auth/password', { current_password, new_password }),

  users: () => request<User[]>('GET', '/users'),
  createUser: (data: UserIn) => request<User>('POST', '/users', data),
  updateUser: (id: number, data: UserIn) => request<User>('PUT', `/users/${id}`, data),
  deleteUser: (id: number) => request<void>('DELETE', `/users/${id}`),

  stats: () => request<Stats>('GET', '/stats'),

  environments: () => request<Environment[]>('GET', '/environments'),
  environment: (id: number) => request<Environment>('GET', `/environments/${id}`),
  createEnvironment: (data: EnvironmentIn) => request<Environment>('POST', '/environments', data),
  updateEnvironment: (id: number, data: EnvironmentIn) => request<Environment>('PUT', `/environments/${id}`, data),
  deleteEnvironment: (id: number) => request<void>('DELETE', `/environments/${id}`),
  installedFeatures: (id: number) => request<Record<string, string>>('GET', `/environments/${id}/features`),
  requestExtension: (id: number, feature_id: string) =>
    request<Environment>('POST', `/environments/${id}/extensions`, { feature_id }),

  workflows: () => request<Workflow[]>('GET', '/workflows'),
  workflow: (id: number) => request<Workflow>('GET', `/workflows/${id}`),
  uploadWorkflow: (file: File, name = '', notes = '') => {
    const form = new FormData()
    form.append('file', file)
    form.append('name', name)
    form.append('notes', notes)
    return request<Workflow>('POST', '/workflows', form)
  },
  replaceWorkflowFile: (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Workflow>('PUT', `/workflows/${id}/file`, form)
  },
  deleteWorkflow: (id: number) => request<void>('DELETE', `/workflows/${id}`),
  addDependency: (id: number, data: { feature_id: string; name?: string; version?: string; update_site?: string | null }) =>
    request<Dependency>('POST', `/workflows/${id}/dependencies`, data),
  deleteDependency: (id: number, depId: number) => request<void>('DELETE', `/workflows/${id}/dependencies/${depId}`),

  schedules: () => request<Schedule[]>('GET', '/schedules'),
  schedule: (id: number) => request<Schedule>('GET', `/schedules/${id}`),
  createSchedule: (data: ScheduleIn) => request<Schedule>('POST', '/schedules', data),
  updateSchedule: (id: number, data: ScheduleIn) => request<Schedule>('PUT', `/schedules/${id}`, data),
  setScheduleActive: (id: number, active: boolean) => request<Schedule>('PATCH', `/schedules/${id}/active`, { active }),
  deleteSchedule: (id: number) => request<void>('DELETE', `/schedules/${id}`),
  runSchedule: (id: number) => request<Run>('POST', `/schedules/${id}/run`),
  dependencyCheck: (workflow_id: number, environment_id: number) =>
    request<DependencyCheck[]>('GET', `/dependency-check${qs({ workflow_id, environment_id })}`),
  triggerPreview: (trigger_type: TriggerType, trigger_value: string) =>
    request<TriggerPreview>('GET', `/triggers/preview${qs({ trigger_type, trigger_value })}`),

  runs: (params: { schedule_id?: number; status?: string; limit?: number } = {}) =>
    request<Run[]>('GET', `/runs${qs(params)}`),
  run: (id: number) => request<Run>('GET', `/runs/${id}`),
  cancelRun: (id: number) => request<{ ok: boolean }>('POST', `/runs/${id}/cancel`),
  runLog: (id: number) => request<string>('GET', `/runs/${id}/log`),
  runLogStreamUrl: (id: number) => `/api/runs/${id}/log/stream`,
}
