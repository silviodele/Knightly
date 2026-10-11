<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Environment, type Run, type Schedule, type ScheduleIn, type Workflow } from '@/api'
import DependencyPanel from '@/components/DependencyPanel.vue'
import StatusChip from '@/components/StatusChip.vue'
import TriggerEditor from '@/components/TriggerEditor.vue'
import { can } from '@/auth'
import { confirm } from '@/confirm'
import { CONCURRENCY, describeTrigger, formatRelative, formatWhen, isActive, runDuration } from '@/format'
import { notify, notifyError } from '@/notify'
import { usePolling } from '@/polling'

const props = defineProps<{ id?: string }>()
const router = useRouter()
const isNew = computed(() => !props.id)

const blank = (): ScheduleIn => ({
  name: '',
  notes: '',
  workflow_id: null,
  environment_id: null,
  active: true,
  trigger_type: 'cron',
  trigger_value: '0 6 * * 1-5',
  variables: [],
  credentials: [],
  reset_before_run: true,
  concurrency: 'skip',
  timeout_minutes: null,
  retention_days: null,
  notify_on: ['failed'],
})

const form = ref<ScheduleIn>(blank())
const schedule = ref<Schedule | null>(null)
const workflows = ref<Workflow[]>([])
const environments = ref<Environment[]>([])
const runs = ref<Run[]>([])
const loading = ref(true)
const saving = ref(false)
const tab = ref('config')
const formRef = ref()
const deps = ref<InstanceType<typeof DependencyPanel>>()

onMounted(async () => {
  try {
    const [wfs, envs] = await Promise.all([api.workflows(), api.environments()])
    workflows.value = wfs
    environments.value = envs
    if (props.id) {
      const s = await api.schedule(Number(props.id))
      schedule.value = s
      form.value = {
        ...blank(),
        ...s,
        credentials: s.credentials.map((c) => ({ ...c, password: '' })),
      }
    } else {
      if (wfs.length === 1) form.value.workflow_id = wfs[0].id
      if (envs.length === 1) form.value.environment_id = envs[0].id
    }
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
})

async function loadRuns() {
  if (props.id) runs.value = await api.runs({ schedule_id: Number(props.id), limit: 50 })
}
const { now } = usePolling(loadRuns, 4000)

const required = (v: unknown) => (v !== null && v !== undefined && `${v}`.trim() !== '') || 'Campo obbligatorio'
const positive = (v: unknown) => v === null || v === '' || Number(v) > 0 || 'Deve essere maggiore di zero'

async function save() {
  const { valid } = await formRef.value.validate()
  if (!valid) {
    notify('Controlla i campi evidenziati', 'warning')
    return
  }
  saving.value = true
  const payload: ScheduleIn = {
    ...form.value,
    timeout_minutes: form.value.timeout_minutes ? Number(form.value.timeout_minutes) : null,
    retention_days: form.value.retention_days ? Number(form.value.retention_days) : null,
    variables: form.value.variables.filter((v) => v.name.trim()),
    credentials: form.value.credentials.filter((c) => c.name.trim()),
  }
  try {
    if (isNew.value) {
      const created = await api.createSchedule(payload)
      notify(`Schedule “${created.name}” creato`)
      router.replace(`/schedules/${created.id}`)
    } else {
      schedule.value = await api.updateSchedule(Number(props.id), payload)
      notify('Modifiche salvate')
    }
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}

async function runNow() {
  try {
    const run = await api.runSchedule(Number(props.id))
    notify(`Run #${run.id} avviato`)
    tab.value = 'runs'
    await loadRuns()
  } catch (e) {
    notifyError(e)
  }
}

async function remove() {
  const ok = await confirm({
    title: 'Eliminare lo schedule?',
    text: 'Verrà eliminato anche tutto lo storico delle esecuzioni e dei log.',
    confirmText: 'Elimina',
    color: 'error',
  })
  if (!ok) return
  try {
    await api.deleteSchedule(Number(props.id))
    notify('Schedule eliminato')
    router.push('/schedules')
  } catch (e) {
    notifyError(e)
  }
}

const runHeaders = [
  { title: '#', key: 'id', width: 70 },
  { title: 'Stato', key: 'status' },
  { title: 'Avvio', key: 'queued_at' },
  { title: 'Durata', key: 'duration', sortable: false },
  { title: 'Origine', key: 'triggered_by' },
  { title: 'Dettaglio', key: 'error', sortable: false },
]

const selectedWorkflow = computed(() => workflows.value.find((w) => w.id === form.value.workflow_id))
const selectedEnvironment = computed(() => environments.value.find((e) => e.id === form.value.environment_id))
</script>

<template>
  <div>
    <v-skeleton-loader v-if="loading" type="heading, article, article" />

    <template v-else>
      <div class="d-flex align-center flex-wrap ga-3 mb-4">
        <v-btn icon="mdi-arrow-left" variant="text" to="/schedules" />
        <div>
          <div class="page-title">{{ isNew ? 'Nuovo schedule' : schedule?.name }}</div>
          <div v-if="schedule" class="text-subtle d-flex align-center ga-2">
            <v-chip :color="schedule.active ? 'success' : 'secondary'" size="x-small" variant="flat" label>
              {{ schedule.active ? 'Attivo' : 'In pausa' }}
            </v-chip>
            <span>{{ describeTrigger(schedule) }}</span>
            <span v-if="schedule.active && schedule.next_run_time">
              · prossimo run {{ formatWhen(schedule.next_run_time) }} ({{ formatRelative(schedule.next_run_time, now) }})
            </span>
          </div>
        </div>
        <v-spacer />
        <template v-if="!isNew && can('operator')">
          <v-btn color="primary" variant="tonal" prepend-icon="mdi-play" @click="runNow">Avvia ora</v-btn>
          <v-btn variant="text" color="error" prepend-icon="mdi-delete-outline" @click="remove">Elimina</v-btn>
        </template>
      </div>

      <v-tabs v-if="!isNew" v-model="tab" color="primary" class="mb-4">
        <v-tab value="config" prepend-icon="mdi-cog-outline">Configurazione</v-tab>
        <v-tab value="runs" prepend-icon="mdi-history">
          Storico run
          <v-badge
            v-if="runs.some((r) => isActive(r.status))"
            color="info"
            dot
            inline
            class="ml-1"
          />
        </v-tab>
      </v-tabs>

      <v-window v-model="tab">
        <v-window-item value="config">
          <v-alert v-if="!can('operator')" type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-eye-outline">
        Sola lettura: il tuo ruolo permette di consultare ma non di modificare.
      </v-alert>
      <v-form ref="formRef" :readonly="!can('operator')" @submit.prevent="save">
            <v-row>
              <v-col cols="12" lg="7">
                <v-card class="mb-4">
                  <v-card-item prepend-icon="mdi-information-outline">
                    <v-card-title class="section-title">Generale</v-card-title>
                  </v-card-item>
                  <v-card-text>
                    <v-text-field v-model="form.name" label="Nome" :rules="[required]" autofocus />
                    <v-row>
                      <v-col cols="12" md="6">
                        <v-autocomplete
                          v-model="form.workflow_id"
                          :items="workflows"
                          item-title="name"
                          item-value="id"
                          label="Workflow"
                          prepend-inner-icon="mdi-sitemap-outline"
                          :rules="[required]"
                          :hint="selectedWorkflow ? `${selectedWorkflow.dependencies.length} dipendenze` : ''"
                          persistent-hint
                        >
                          <template #no-data>
                            <v-list-item title="Nessun workflow" subtitle="Caricane uno dalla pagina Workflow" to="/workflows" />
                          </template>
                        </v-autocomplete>
                      </v-col>
                      <v-col cols="12" md="6">
                        <v-autocomplete
                          v-model="form.environment_id"
                          :items="environments"
                          item-title="name"
                          item-value="id"
                          label="Environment"
                          prepend-inner-icon="mdi-server-outline"
                          :rules="[required]"
                          :hint="selectedEnvironment?.knime_path ?? ''"
                          persistent-hint
                        >
                          <template #no-data>
                            <v-list-item title="Nessun environment" subtitle="Creane uno dalla pagina Environment" to="/environments/new" />
                          </template>
                        </v-autocomplete>
                      </v-col>
                    </v-row>
                    <v-textarea v-model="form.notes" label="Note" rows="2" auto-grow class="mt-4" hide-details />
                    <v-switch v-model="form.active" color="primary" inset hide-details class="mt-2">
                      <template #label>
                        <div>
                          <div>Schedule attivo</div>
                          <div class="text-caption text-subtle">Se disattivato, il workflow parte solo manualmente</div>
                        </div>
                      </template>
                    </v-switch>
                  </v-card-text>
                </v-card>

                <v-card class="mb-4">
                  <v-card-item prepend-icon="mdi-calendar-clock">
                    <v-card-title class="section-title">Pianificazione</v-card-title>
                  </v-card-item>
                  <v-card-text>
                    <TriggerEditor v-model:type="form.trigger_type" v-model:value="form.trigger_value" :readonly="!can('operator')" />
                    <div class="text-body-2 font-weight-medium mt-2 mb-2">Se scatta mentre un run è ancora attivo</div>
                    <v-item-group v-model="form.concurrency" mandatory :disabled="!can('operator')">
                      <v-row dense>
                        <v-col v-for="(c, key) in CONCURRENCY" :key="key" cols="12" sm="6">
                          <v-item v-slot="{ isSelected, toggle }" :value="key">
                            <v-card
                              :color="isSelected ? 'primary' : undefined"
                              :variant="isSelected ? 'tonal' : 'outlined'"
                              class="pa-3 h-100"
                              @click="toggle"
                            >
                              <div class="d-flex align-center ga-2">
                                <v-icon :icon="isSelected ? 'mdi-radiobox-marked' : 'mdi-radiobox-blank'" size="small" />
                                <span class="font-weight-medium">{{ c.title }}</span>
                              </div>
                              <div class="text-caption text-subtle mt-1">{{ c.subtitle }}</div>
                            </v-card>
                          </v-item>
                        </v-col>
                      </v-row>
                    </v-item-group>
                  </v-card-text>
                </v-card>

                <v-card class="mb-4">
                  <v-card-item prepend-icon="mdi-variable">
                    <v-card-title class="section-title">Variabili di flusso</v-card-title>
                    <v-card-subtitle>Passate a KNIME come <span class="mono">-workflow.variable</span></v-card-subtitle>
                  </v-card-item>
                  <v-card-text>
                    <div v-for="(v, i) in form.variables" :key="i" class="d-flex ga-2 align-start">
                      <v-text-field v-model="v.name" label="Nome" class="mono" :rules="[required]" />
                      <v-select v-model="v.type" :items="['String', 'int', 'double']" label="Tipo" style="max-width: 130px" />
                      <v-text-field v-model="v.value" label="Valore" class="mono" />
                      <v-btn v-if="can('operator')" icon="mdi-close" variant="text" size="small" class="mt-2" @click="form.variables.splice(i, 1)" />
                    </div>
                    <v-btn
                      v-if="can('operator')"
                      variant="tonal"
                      size="small"
                      prepend-icon="mdi-plus"
                      @click="form.variables.push({ name: '', type: 'String', value: '' })"
                    >
                      Aggiungi variabile
                    </v-btn>
                  </v-card-text>
                </v-card>

                <v-card class="mb-4">
                  <v-card-item prepend-icon="mdi-key-outline">
                    <v-card-title class="section-title">Credenziali</v-card-title>
                    <v-card-subtitle>
                      Passate a KNIME come <span class="mono">-credential</span>.
                      <span v-if="!isNew">Lascia la password vuota per mantenere quella salvata.</span>
                    </v-card-subtitle>
                  </v-card-item>
                  <v-card-text>
                    <div v-for="(c, i) in form.credentials" :key="i" class="d-flex ga-2 align-start">
                      <v-text-field v-model="c.name" label="Nome credenziale" :rules="[required]" />
                      <v-text-field v-model="c.login" label="Login" autocomplete="off" />
                      <v-text-field
                        v-model="c.password"
                        label="Password"
                        type="password"
                        autocomplete="new-password"
                        :placeholder="isNew ? '' : '••••••• (invariata)'"
                        persistent-placeholder
                      />
                      <v-btn v-if="can('operator')" icon="mdi-close" variant="text" size="small" class="mt-2" @click="form.credentials.splice(i, 1)" />
                    </div>
                    <v-btn
                      v-if="can('operator')"
                      variant="tonal"
                      size="small"
                      prepend-icon="mdi-plus"
                      @click="form.credentials.push({ name: '', login: '', password: '' })"
                    >
                      Aggiungi credenziale
                    </v-btn>
                  </v-card-text>
                </v-card>
              </v-col>

              <v-col cols="12" lg="5">
                <v-card class="mb-4">
                  <v-card-item prepend-icon="mdi-puzzle-outline">
                    <v-card-title class="section-title">Dipendenze KNIME</v-card-title>
                    <v-card-subtitle>Estensioni del workflow confrontate con l’environment</v-card-subtitle>
                    <template #append>
                      <v-btn icon="mdi-refresh" variant="text" size="small" title="Ricontrolla" @click="deps?.reload()" />
                    </template>
                  </v-card-item>
                  <v-card-text>
                    <DependencyPanel ref="deps" :workflow-id="form.workflow_id" :environment-id="form.environment_id" />
                  </v-card-text>
                </v-card>

                <v-card class="mb-4">
                  <v-card-item prepend-icon="mdi-tune-variant">
                    <v-card-title class="section-title">Opzioni di esecuzione</v-card-title>
                  </v-card-item>
                  <v-card-text>
                    <v-row dense>
                      <v-col cols="6">
                        <v-text-field
                          v-model="form.timeout_minutes"
                          type="number"
                          min="1"
                          label="Timeout"
                          suffix="min"
                          placeholder="nessuno"
                          persistent-placeholder
                          :rules="[positive]"
                        />
                      </v-col>
                      <v-col cols="6">
                        <v-text-field
                          v-model="form.retention_days"
                          type="number"
                          min="1"
                          label="Conserva storico"
                          suffix="giorni"
                          placeholder="sempre"
                          persistent-placeholder
                          :rules="[positive]"
                        />
                      </v-col>
                    </v-row>
                    <v-checkbox v-model="form.reset_before_run" color="primary" hide-details density="compact">
                      <template #label>Reset del workflow prima dell’esecuzione</template>
                    </v-checkbox>
                  </v-card-text>
                </v-card>

                <v-card class="mb-4">
                  <v-card-item prepend-icon="mdi-bell-outline">
                    <v-card-title class="section-title">Notifiche</v-card-title>
                    <v-card-subtitle>Quando avvisare (invio in arrivo)</v-card-subtitle>
                  </v-card-item>
                  <v-card-text>
                    <v-chip-group v-model="form.notify_on" multiple column selected-class="text-primary" :disabled="!can('operator')">
                      <v-chip value="failed" filter variant="outlined">Fallito</v-chip>
                      <v-chip value="success" filter variant="outlined">Riuscito</v-chip>
                      <v-chip value="cancelled" filter variant="outlined">Annullato</v-chip>
                    </v-chip-group>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>

            <div v-if="can('operator')" class="sticky-actions d-flex align-center ga-3 py-3 px-1 mt-2">
              <span class="text-caption text-subtle">
                {{ isNew ? 'Lo schedule partirà automaticamente secondo la pianificazione.' : '' }}
              </span>
              <v-spacer />
              <v-btn variant="text" to="/schedules">Annulla</v-btn>
              <v-btn type="submit" color="primary" :loading="saving" prepend-icon="mdi-content-save-outline">
                {{ isNew ? 'Crea schedule' : 'Salva modifiche' }}
              </v-btn>
            </div>
          </v-form>
        </v-window-item>

        <v-window-item value="runs">
          <v-card>
            <v-data-table
              :headers="runHeaders"
              :items="runs"
              items-per-page="20"
              class="clickable-rows"
              @click:row="(_e: Event, { item }: { item: Run }) => router.push(`/runs/${item.id}`)"
            >
              <template #item.status="{ item }"><StatusChip :status="item.status" /></template>
              <template #item.queued_at="{ item }">{{ formatWhen(item.started_at ?? item.queued_at) }}</template>
              <template #item.duration="{ item }">{{ runDuration(item, now) }}</template>
              <template #item.triggered_by="{ item }">
                <v-icon :icon="item.triggered_by === 'manual' ? 'mdi-hand-back-right-outline' : 'mdi-calendar-clock'" size="small" class="mr-1" />
                {{ item.triggered_by === 'manual' ? `Manuale${item.triggered_by_user ? ` · ${item.triggered_by_user}` : ''}` : 'Pianificato' }}
              </template>
              <template #item.error="{ item }">
                <span class="text-caption text-error">{{ item.error }}</span>
              </template>
              <template #no-data>
                <div class="pa-6 text-subtle">Nessun run. Usa “Avvia ora” per eseguirlo subito.</div>
              </template>
            </v-data-table>
          </v-card>
        </v-window-item>
      </v-window>
    </template>
  </div>
</template>
