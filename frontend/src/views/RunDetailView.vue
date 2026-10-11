<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type Run } from '@/api'
import LogViewer from '@/components/LogViewer.vue'
import StatusChip from '@/components/StatusChip.vue'
import { confirm } from '@/confirm'
import { formatDateTime, isActive, runDuration } from '@/format'
import { notify, notifyError } from '@/notify'
import { usePolling } from '@/polling'

const props = defineProps<{ id: string }>()
const run = ref<Run | null>(null)
// "live" si decide una volta all'apertura: se il run e' attivo seguiamo il log in streaming
const live = ref(false)

async function load() {
  try {
    run.value = await api.run(Number(props.id))
  } catch (e) {
    notifyError(e)
  }
}
onMounted(async () => {
  await load()
  live.value = !!run.value && isActive(run.value.status)
})
const { now } = usePolling(async () => {
  if (run.value && isActive(run.value.status)) await load()
}, 2000)

async function cancel() {
  const ok = await confirm({
    title: 'Annullare il run?',
    text: 'Il processo KNIME verrà terminato.',
    confirmText: 'Annulla run',
    color: 'error',
  })
  if (!ok) return
  try {
    await api.cancelRun(Number(props.id))
    notify('Annullamento richiesto', 'info')
  } catch (e) {
    notifyError(e)
  }
}

async function rerun() {
  try {
    const next = await api.runSchedule(run.value!.schedule_id)
    notify(`Run #${next.id} avviato`)
  } catch (e) {
    notifyError(e)
  }
}

const facts = computed(() =>
  run.value
    ? [
        { label: 'In coda dal', value: formatDateTime(run.value.queued_at), icon: 'mdi-timer-sand' },
        { label: 'Avviato', value: formatDateTime(run.value.started_at), icon: 'mdi-play-outline' },
        { label: 'Terminato', value: formatDateTime(run.value.finished_at), icon: 'mdi-flag-checkered' },
        { label: 'Durata', value: runDuration(run.value, now.value), icon: 'mdi-timer-outline' },
        { label: 'Exit code', value: run.value.exit_code ?? '—', icon: 'mdi-numeric' },
        {
          label: 'Origine',
          value: run.value.triggered_by === 'manual' ? 'Manuale' : 'Pianificato',
          icon: run.value.triggered_by === 'manual' ? 'mdi-hand-back-right-outline' : 'mdi-calendar-clock',
        },
      ]
    : [],
)
</script>

<template>
  <div v-if="run">
    <div class="d-flex align-center flex-wrap ga-3 mb-6">
      <v-btn icon="mdi-arrow-left" variant="text" to="/runs" />
      <div>
        <div class="d-flex align-center ga-3">
          <span class="page-title">Run #{{ run.id }}</span>
          <StatusChip :status="run.status" size="default" />
        </div>
        <router-link :to="`/schedules/${run.schedule_id}`" class="text-subtle">{{ run.schedule_name }}</router-link>
      </div>
      <v-spacer />
      <v-btn v-if="isActive(run.status)" color="error" variant="tonal" prepend-icon="mdi-stop" @click="cancel">Annulla run</v-btn>
      <v-btn v-else color="primary" variant="tonal" prepend-icon="mdi-replay" @click="rerun">Esegui di nuovo</v-btn>
    </div>

    <v-alert v-if="run.error" type="error" variant="tonal" class="mb-4" :title="run.status === 'timeout' ? 'Timeout' : 'Errore'">
      {{ run.error }}
    </v-alert>

    <v-card class="mb-4">
      <v-card-text>
        <v-row dense>
          <v-col v-for="f in facts" :key="f.label" cols="6" md="4" lg="2">
            <div class="d-flex align-center ga-2 text-caption text-subtle">
              <v-icon :icon="f.icon" size="small" /> {{ f.label }}
            </div>
            <div class="text-body-1 font-weight-medium mt-1">{{ f.value }}</div>
          </v-col>
        </v-row>
      </v-card-text>
      <v-progress-linear v-if="isActive(run.status)" indeterminate color="info" />
    </v-card>

    <LogViewer :run-id="run.id" :live="live" @done="load" />
  </div>
  <v-skeleton-loader v-else type="heading, article" />
</template>
