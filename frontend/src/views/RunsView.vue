<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type Run, type RunStatus, type Schedule } from '@/api'
import StatusChip from '@/components/StatusChip.vue'
import { STATUS, formatWhen, formatRelative, runDuration } from '@/format'
import { notifyError } from '@/notify'
import { usePolling } from '@/polling'

const route = useRoute()
const router = useRouter()
const runs = ref<Run[]>([])
const schedules = ref<Schedule[]>([])
const loading = ref(true)

const status = ref<RunStatus | null>((route.query.status as RunStatus) || null)
const scheduleId = ref<number | null>(route.query.schedule ? Number(route.query.schedule) : null)

async function load() {
  try {
    const [r, s] = await Promise.all([
      api.runs({ status: status.value ?? undefined, schedule_id: scheduleId.value ?? undefined, limit: 500 }),
      schedules.value.length ? Promise.resolve(schedules.value) : api.schedules(),
    ])
    runs.value = r
    schedules.value = s
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
const { now } = usePolling(load, 4000)

watch([status, scheduleId], () => {
  router.replace({
    query: { ...(status.value ? { status: status.value } : {}), ...(scheduleId.value ? { schedule: scheduleId.value } : {}) },
  })
  loading.value = true
  load()
})

const statusOptions = computed(() => Object.entries(STATUS).map(([value, s]) => ({ value: value as RunStatus, ...s })))

const headers = [
  { title: '#', key: 'id', width: 80 },
  { title: 'Schedule', key: 'schedule_name' },
  { title: 'Stato', key: 'status' },
  { title: 'Avvio', key: 'queued_at' },
  { title: 'Durata', key: 'duration', sortable: false },
  { title: 'Origine', key: 'triggered_by' },
]
</script>

<template>
  <div>
    <div class="d-flex align-center flex-wrap ga-4 mb-4">
      <div>
        <div class="page-title">Run</div>
        <div class="text-subtle">Storico di tutte le esecuzioni</div>
      </div>
      <v-spacer />
      <v-autocomplete
        v-model="scheduleId"
        :items="schedules"
        item-title="name"
        item-value="id"
        placeholder="Tutti gli schedule"
        prepend-inner-icon="mdi-calendar-clock"
        hide-details
        density="compact"
        clearable
        style="max-width: 300px; min-width: 240px"
      />
    </div>

    <v-chip-group v-model="status" selected-class="text-primary" class="mb-3">
      <v-chip v-for="s in statusOptions" :key="s.value" :value="s.value" filter variant="outlined" :prepend-icon="s.icon">
        {{ s.label }}
      </v-chip>
    </v-chip-group>

    <v-card>
      <v-data-table
        :headers="headers"
        :items="runs"
        :loading="loading"
        items-per-page="25"
        class="clickable-rows"
        @click:row="(_e: Event, { item }: { item: Run }) => router.push(`/runs/${item.id}`)"
      >
        <template #item.id="{ item }"><span class="text-subtle">#{{ item.id }}</span></template>
        <template #item.schedule_name="{ item }">
          <div class="py-2">
            <div class="font-weight-medium">{{ item.schedule_name }}</div>
            <div v-if="item.error" class="text-caption text-error text-truncate" style="max-width: 520px">{{ item.error }}</div>
          </div>
        </template>
        <template #item.status="{ item }"><StatusChip :status="item.status" /></template>
        <template #item.queued_at="{ item }">
          <div>{{ formatWhen(item.started_at ?? item.queued_at) }}</div>
          <div class="text-caption text-subtle">{{ formatRelative(item.started_at ?? item.queued_at, now) }}</div>
        </template>
        <template #item.duration="{ item }">{{ runDuration(item, now) }}</template>
        <template #item.triggered_by="{ item }">
          <v-icon :icon="item.triggered_by === 'manual' ? 'mdi-hand-back-right-outline' : 'mdi-calendar-clock'" size="small" class="mr-1" />
          {{ item.triggered_by === 'manual' ? 'Manuale' : 'Pianificato' }}
        </template>
        <template #no-data><div class="pa-6 text-subtle">Nessun run con questi filtri.</div></template>
      </v-data-table>
    </v-card>
  </div>
</template>
