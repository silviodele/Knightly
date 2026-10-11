<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, type Schedule, type Stats } from '@/api'
import RunsChart from '@/components/RunsChart.vue'
import StatusChip from '@/components/StatusChip.vue'
import { formatRelative, formatWhen } from '@/format'
import { notifyError } from '@/notify'
import { usePolling } from '@/polling'

const stats = ref<Stats | null>(null)
const schedules = ref<Schedule[]>([])
const loaded = ref(false)

async function load() {
  try {
    ;[stats.value, schedules.value] = await Promise.all([api.stats(), api.schedules()])
  } catch (e) {
    notifyError(e)
  } finally {
    loaded.value = true
  }
}
const { now } = usePolling(load, 10_000)

const kpis = computed(() => {
  const s = stats.value
  if (!s) return []
  const rate = s.success_rate_7d
  return [
    {
      title: 'Schedule attivi',
      value: `${s.schedules_active}`,
      sub: `su ${s.schedules_total} totali`,
      icon: 'mdi-calendar-check',
      color: 'primary',
      to: '/schedules',
    },
    {
      title: 'In esecuzione',
      value: `${s.runs_active}`,
      sub: s.runs_active ? 'run attivi ora' : 'nessun run attivo',
      icon: 'mdi-play-circle-outline',
      color: 'info',
      to: '/runs?status=running',
    },
    {
      title: 'Run oggi',
      value: `${s.runs_today}`,
      sub: 'avviati da mezzanotte',
      icon: 'mdi-chart-timeline-variant',
      color: 'secondary',
      to: '/runs',
    },
    {
      title: 'Falliti nelle ultime 24h',
      value: `${s.failed_24h}`,
      sub: s.failed_24h ? 'da controllare' : 'tutto regolare',
      icon: 'mdi-alert-circle-outline',
      color: s.failed_24h ? 'error' : 'success',
      to: '/runs?status=failed',
    },
    {
      title: 'Successo (7 giorni)',
      value: rate === null ? '—' : `${Math.round(rate * 100)}%`,
      sub: 'run conclusi con successo',
      icon: 'mdi-percent-circle-outline',
      color: rate === null || rate >= 0.9 ? 'success' : rate >= 0.7 ? 'warning' : 'error',
      to: '/runs',
    },
  ]
})

const withMissingDeps = computed(() => schedules.value.filter((s) => s.active && s.missing_dependencies > 0))
</script>

<template>
  <div>
    <div class="d-flex align-center mb-6">
      <div>
        <div class="page-title">Dashboard</div>
        <div class="text-subtle">Panoramica delle esecuzioni dei workflow KNIME</div>
      </div>
    </div>

    <v-row v-if="!loaded">
      <v-col v-for="i in 5" :key="i" cols="12" sm="6" lg>
        <v-skeleton-loader type="article" />
      </v-col>
    </v-row>

    <template v-else-if="stats">
      <v-alert
        v-if="withMissingDeps.length"
        type="warning"
        variant="tonal"
        class="mb-6"
        icon="mdi-puzzle-remove-outline"
        :title="withMissingDeps.length === 1 ? 'Uno schedule attivo ha estensioni mancanti' : `${withMissingDeps.length} schedule attivi hanno estensioni mancanti`"
      >
        <span v-for="(s, i) in withMissingDeps" :key="s.id">
          <router-link :to="`/schedules/${s.id}`">{{ s.name }}</router-link>{{ i < withMissingDeps.length - 1 ? ', ' : '' }}
        </span>
        — {{ withMissingDeps.length === 1 ? 'i suoi run falliranno' : 'i loro run falliranno' }} finché le estensioni non saranno installate.
      </v-alert>

      <v-row>
        <v-col v-for="kpi in kpis" :key="kpi.title" cols="12" sm="6" lg>
          <v-card :to="kpi.to" class="h-100" hover>
            <v-card-text class="d-flex align-start">
              <div>
                <div class="text-body-2 text-subtle mb-2">{{ kpi.title }}</div>
                <div class="kpi-value">{{ kpi.value }}</div>
                <div class="text-caption text-subtle mt-1">{{ kpi.sub }}</div>
              </div>
              <v-spacer />
              <v-avatar :color="kpi.color" variant="tonal" rounded="lg">
                <v-icon :icon="kpi.icon" />
              </v-avatar>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mt-2">
        <v-col cols="12" lg="8">
          <v-card class="h-100">
            <v-card-item>
              <v-card-title class="section-title">Esecuzioni ultimi 14 giorni</v-card-title>
            </v-card-item>
            <v-card-text>
              <RunsChart :days="stats.daily" />
            </v-card-text>
          </v-card>
        </v-col>

        <v-col cols="12" lg="4">
          <v-card class="h-100">
            <v-card-item>
              <v-card-title class="section-title">Prossime esecuzioni</v-card-title>
            </v-card-item>
            <v-list v-if="stats.upcoming.length" density="comfortable" class="pt-0">
              <v-list-item
                v-for="u in stats.upcoming"
                :key="u.schedule_id"
                :to="`/schedules/${u.schedule_id}`"
                prepend-icon="mdi-clock-outline"
              >
                <v-list-item-title>{{ u.schedule_name }}</v-list-item-title>
                <v-list-item-subtitle>{{ formatWhen(u.next_run_time) }}</v-list-item-subtitle>
                <template #append>
                  <span class="text-caption text-subtle">{{ formatRelative(u.next_run_time, now) }}</span>
                </template>
              </v-list-item>
            </v-list>
            <v-card-text v-else class="text-subtle">Nessuno schedule attivo.</v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mt-2">
        <v-col cols="12">
          <v-card>
            <v-card-item>
              <v-card-title class="section-title">Ultimi errori</v-card-title>
              <template #append>
                <v-btn variant="text" size="small" to="/runs?status=failed" append-icon="mdi-arrow-right">Tutti</v-btn>
              </template>
            </v-card-item>
            <v-list v-if="stats.recent_failures.length" lines="two" class="pt-0">
              <v-list-item v-for="r in stats.recent_failures" :key="r.id" :to="`/runs/${r.id}`">
                <template #prepend>
                  <StatusChip :status="r.status" class="mr-4" />
                </template>
                <v-list-item-title>
                  {{ r.schedule_name }} <span class="text-subtle text-body-2">· run #{{ r.id }}</span>
                </v-list-item-title>
                <v-list-item-subtitle>{{ r.error }}</v-list-item-subtitle>
                <template #append>
                  <span class="text-caption text-subtle">{{ formatRelative(r.finished_at ?? r.queued_at, now) }}</span>
                </template>
              </v-list-item>
            </v-list>
            <v-card-text v-else>
              <div class="d-flex align-center ga-2 text-success">
                <v-icon icon="mdi-check-decagram" /> Nessun errore recente.
              </div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </template>
  </div>
</template>
