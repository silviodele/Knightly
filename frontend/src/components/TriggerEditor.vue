<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type TriggerPreview, type TriggerType } from '@/api'
import { describeTrigger, formatDateTime, formatRelative } from '@/format'

const type = defineModel<TriggerType>('type', { required: true })
const value = defineModel<string>('value', { required: true })

const presets = [
  { title: 'Ogni giorno alle 6:00', type: 'cron' as const, value: '0 6 * * *' },
  { title: 'Giorni feriali alle 7:00', type: 'cron' as const, value: '0 7 * * 1-5' },
  { title: 'Ogni lunedì alle 8:00', type: 'cron' as const, value: '0 8 * * 1' },
  { title: 'Il primo del mese alle 5:00', type: 'cron' as const, value: '0 5 1 * *' },
  { title: 'Ogni ora', type: 'interval' as const, value: '60' },
  { title: 'Ogni 15 minuti', type: 'interval' as const, value: '15' },
]

const types: { title: string; value: TriggerType; icon: string }[] = [
  { title: 'Cron', value: 'cron', icon: 'mdi-calendar-sync' },
  { title: 'Intervallo', value: 'interval', icon: 'mdi-timer-refresh-outline' },
  { title: 'Una tantum', value: 'date', icon: 'mdi-calendar-star' },
]

// La data "una tantum" usa l'input nativo datetime-local (YYYY-MM-DDTHH:mm)
const dateValue = computed({
  get: () => (type.value === 'date' ? value.value.slice(0, 16) : ''),
  set: (v: string) => (value.value = v),
})

function onTypeChange(next: TriggerType) {
  type.value = next
  if (next === 'interval' && !/^\d+$/.test(value.value)) value.value = '60'
  if (next === 'cron' && value.value.trim().split(/\s+/).length !== 5) value.value = '0 6 * * *'
  if (next === 'date') {
    const tomorrow = new Date(Date.now() + 86_400_000)
    tomorrow.setHours(6, 0, 0, 0)
    const local = new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60_000)
    value.value = local.toISOString().slice(0, 16)
  }
}

const preview = ref<TriggerPreview | null>(null)
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

watch(
  [type, value],
  () => {
    clearTimeout(timer)
    if (!value.value) {
      preview.value = null
      return
    }
    timer = setTimeout(async () => {
      loading.value = true
      try {
        preview.value = await api.triggerPreview(type.value, value.value)
      } catch {
        preview.value = null
      } finally {
        loading.value = false
      }
    }, 300)
  },
  { immediate: true },
)

const description = computed(() =>
  preview.value?.valid ? describeTrigger({ trigger_type: type.value, trigger_value: value.value }) : '',
)
</script>

<template>
  <div>
    <v-btn-toggle
      :model-value="type"
      mandatory
      color="primary"
      variant="outlined"
      divided
      density="comfortable"
      class="mb-4"
      @update:model-value="onTypeChange"
    >
      <v-btn v-for="t in types" :key="t.value" :value="t.value" :prepend-icon="t.icon">{{ t.title }}</v-btn>
    </v-btn-toggle>

    <v-row>
      <v-col cols="12" md="6">
        <v-text-field
          v-if="type === 'cron'"
          v-model="value"
          label="Espressione cron"
          class="mono"
          hint="minuto ora giorno mese giorno-settimana · es. 0 6 * * 1-5"
          persistent-hint
          :error-messages="preview && !preview.valid ? preview.error ?? '' : ''"
        >
          <template #append-inner>
            <v-menu>
              <template #activator="{ props: menu }">
                <v-btn v-bind="menu" size="small" variant="text" icon="mdi-lightning-bolt-outline" title="Modelli" />
              </template>
              <v-list density="compact">
                <v-list-subheader>Modelli</v-list-subheader>
                <v-list-item
                  v-for="p in presets"
                  :key="p.title"
                  :title="p.title"
                  :subtitle="p.type === 'cron' ? p.value : `ogni ${p.value} min`"
                  @click="(type = p.type), (value = p.value)"
                />
              </v-list>
            </v-menu>
          </template>
        </v-text-field>

        <v-text-field
          v-else-if="type === 'interval'"
          v-model="value"
          type="number"
          min="1"
          label="Ogni"
          suffix="minuti"
          :error-messages="preview && !preview.valid ? preview.error ?? '' : ''"
        />

        <v-text-field
          v-else
          v-model="dateValue"
          type="datetime-local"
          label="Data e ora"
          :error-messages="preview && !preview.valid ? preview.error ?? '' : ''"
        />
      </v-col>

      <v-col cols="12" md="6">
        <v-sheet rounded="lg" class="pa-4 preview" :class="{ invalid: preview && !preview.valid }">
          <div class="d-flex align-center ga-2 mb-2">
            <v-icon icon="mdi-calendar-clock" size="small" color="primary" />
            <span class="font-weight-medium">{{ description || 'Prossime esecuzioni' }}</span>
            <v-progress-circular v-if="loading" indeterminate size="14" width="2" class="ml-auto" />
          </div>
          <template v-if="preview?.valid">
            <div v-if="!preview.next_runs.length" class="text-subtle text-body-2">Nessuna esecuzione futura.</div>
            <div v-for="(run, i) in preview.next_runs" :key="run" class="d-flex text-body-2 py-1">
              <span :class="{ 'font-weight-bold': i === 0 }">{{ formatDateTime(run) }}</span>
              <span class="ml-auto text-subtle">{{ formatRelative(run) }}</span>
            </div>
          </template>
          <div v-else-if="preview" class="text-error text-body-2">Pianificazione non valida.</div>
        </v-sheet>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.preview {
  background: rgba(var(--v-theme-primary), 0.06);
  border: 1px solid rgba(var(--v-theme-primary), 0.18);
}
.preview.invalid {
  background: rgba(var(--v-theme-error), 0.06);
  border-color: rgba(var(--v-theme-error), 0.25);
}
</style>
