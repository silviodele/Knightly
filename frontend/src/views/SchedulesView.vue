<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Schedule } from '@/api'
import StatusChip from '@/components/StatusChip.vue'
import { can } from '@/auth'
import { confirm } from '@/confirm'
import { describeTrigger, formatRelative, formatWhen } from '@/format'
import { notify, notifyError } from '@/notify'
import { usePolling } from '@/polling'

const router = useRouter()
const schedules = ref<Schedule[]>([])
const loading = ref(true)
const search = ref('')

async function load() {
  try {
    schedules.value = await api.schedules()
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
const { now } = usePolling(load, 10_000)

const headers = [
  { title: 'Schedule', key: 'name' },
  { title: 'Pianificazione', key: 'trigger', sortable: false },
  { title: 'Prossimo run', key: 'next_run_time' },
  { title: 'Ultimo run', key: 'last_run', sortable: false },
  { title: 'Attivo', key: 'active', width: 90 },
  { title: '', key: 'actions', sortable: false, align: 'end' as const, width: 120 },
]

async function runNow(s: Schedule) {
  try {
    const run = await api.runSchedule(s.id)
    notify(`Run #${run.id} di “${s.name}” avviato`)
    await load()
  } catch (e) {
    notifyError(e)
  }
}

async function toggle(s: Schedule, active: boolean) {
  try {
    Object.assign(s, await api.setScheduleActive(s.id, active))
    notify(active ? `“${s.name}” riattivato` : `“${s.name}” in pausa`, 'info')
  } catch (e) {
    notifyError(e)
  }
}

async function remove(s: Schedule) {
  const ok = await confirm({
    title: 'Eliminare lo schedule?',
    text: `“${s.name}” verrà eliminato insieme al suo storico di esecuzioni.`,
    confirmText: 'Elimina',
    color: 'error',
  })
  if (!ok) return
  try {
    await api.deleteSchedule(s.id)
    notify('Schedule eliminato')
    await load()
  } catch (e) {
    notifyError(e)
  }
}
</script>

<template>
  <div>
    <div class="d-flex align-center flex-wrap ga-4 mb-6">
      <div>
        <div class="page-title">Schedule</div>
        <div class="text-subtle">Quando e dove vengono eseguiti i workflow</div>
      </div>
      <v-spacer />
      <v-text-field
        v-model="search"
        prepend-inner-icon="mdi-magnify"
        placeholder="Cerca schedule, workflow, environment…"
        hide-details
        density="compact"
        style="max-width: 340px"
        clearable
      />
      <v-btn v-if="can('operator')" color="primary" prepend-icon="mdi-plus" to="/schedules/new">Nuovo schedule</v-btn>
    </div>

    <v-card>
      <v-data-table
        :headers="headers"
        :items="schedules"
        :search="search"
        :loading="loading"
        :custom-filter="(_v: unknown, q: string, item: any) => [item.raw.name, item.raw.workflow_name, item.raw.environment_name].join(' ').toLowerCase().includes(q.toLowerCase())"
        items-per-page="25"
        class="clickable-rows"
        @click:row="(_e: Event, { item }: { item: Schedule }) => router.push(`/schedules/${item.id}`)"
      >
        <template #item.name="{ item }">
          <div class="py-3">
            <div class="d-flex align-center ga-2">
              <span class="font-weight-medium">{{ item.name }}</span>
              <v-tooltip v-if="item.missing_dependencies" location="top">
                <template #activator="{ props }">
                  <v-icon v-bind="props" icon="mdi-puzzle-remove-outline" color="error" size="small" />
                </template>
                {{ item.missing_dependencies }} estensioni mancanti nell’environment
              </v-tooltip>
            </div>
            <div class="text-caption text-subtle">
              <v-icon icon="mdi-sitemap-outline" size="x-small" /> {{ item.workflow_name }}
              <v-icon icon="mdi-server-outline" size="x-small" class="ml-2" /> {{ item.environment_name }}
            </div>
          </div>
        </template>

        <template #item.trigger="{ item }">
          <div>{{ describeTrigger(item) }}</div>
          <div v-if="item.trigger_type === 'cron'" class="text-caption text-subtle mono">{{ item.trigger_value }}</div>
        </template>

        <template #item.next_run_time="{ item }">
          <template v-if="item.active && item.next_run_time">
            <div>{{ formatWhen(item.next_run_time) }}</div>
            <div class="text-caption text-subtle">{{ formatRelative(item.next_run_time, now) }}</div>
          </template>
          <span v-else class="text-subtle">—</span>
        </template>

        <template #item.last_run="{ item }">
          <div v-if="item.last_run" class="d-flex align-center ga-2" @click.stop>
            <router-link :to="`/runs/${item.last_run.id}`"><StatusChip :status="item.last_run.status" /></router-link>
            <span class="text-caption text-subtle">{{ formatRelative(item.last_run.queued_at, now) }}</span>
          </div>
          <span v-else class="text-caption text-subtle">mai eseguito</span>
        </template>

        <template #item.active="{ item }">
          <v-switch
            :model-value="item.active"
            color="primary"
            hide-details
            density="compact"
            inset
            :disabled="!can('operator')"
            @click.stop
            @update:model-value="(v) => toggle(item, !!v)"
          />
        </template>

        <template #item.actions="{ item }">
          <div class="d-flex justify-end" @click.stop>
            <v-btn v-if="can('operator')" icon="mdi-play" variant="text" color="primary" size="small" title="Avvia ora" @click="runNow(item)" />
            <v-menu>
              <template #activator="{ props }">
                <v-btn v-bind="props" icon="mdi-dots-vertical" variant="text" size="small" />
              </template>
              <v-list density="compact">
                <v-list-item
                  :prepend-icon="can('operator') ? 'mdi-pencil-outline' : 'mdi-eye-outline'"
                  :title="can('operator') ? 'Modifica' : 'Dettagli'"
                  :to="`/schedules/${item.id}`"
                />
                <v-list-item prepend-icon="mdi-history" title="Storico run" :to="`/runs?schedule=${item.id}`" />
                <v-list-item v-if="can('operator')" prepend-icon="mdi-delete-outline" title="Elimina" base-color="error" @click="remove(item)" />
              </v-list>
            </v-menu>
          </div>
        </template>

        <template #no-data>
          <v-empty-state
            icon="mdi-calendar-blank-outline"
            title="Nessuno schedule"
            text="Crea uno schedule per eseguire un workflow in automatico."
          >
            <template v-if="can('operator')" #actions>
              <v-btn color="primary" to="/schedules/new">Nuovo schedule</v-btn>
            </template>
          </v-empty-state>
        </template>
      </v-data-table>
    </v-card>
  </div>
</template>
