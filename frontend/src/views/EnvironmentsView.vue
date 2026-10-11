<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type Environment, type Schedule } from '@/api'
import { can } from '@/auth'
import { notifyError } from '@/notify'

const environments = ref<(Environment & { installed: number | null; schedules: number })[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    const [envs, schedules] = await Promise.all([api.environments(), api.schedules()])
    const counts = (id: number) => schedules.filter((s: Schedule) => s.environment_id === id).length
    environments.value = envs.map((e) => ({ ...e, installed: null, schedules: counts(e.id) }))
    // le estensioni installate si leggono dal disco: le carichiamo dopo
    await Promise.all(
      environments.value.map(async (e) => {
        e.installed = Object.keys(await api.installedFeatures(e.id)).length
      }),
    )
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <div class="d-flex align-center flex-wrap ga-4 mb-6">
      <div>
        <div class="page-title">Environment</div>
        <div class="text-subtle">Installazioni KNIME locali con estensioni, preferenze e impostazioni JVM</div>
      </div>
      <v-spacer />
      <v-btn v-if="can('operator')" color="primary" prepend-icon="mdi-plus" to="/environments/new">Nuovo environment</v-btn>
    </div>

    <v-row v-if="loading">
      <v-col v-for="i in 3" :key="i" cols="12" md="6" xl="4"><v-skeleton-loader type="article" /></v-col>
    </v-row>

    <v-row v-else-if="environments.length">
      <v-col v-for="env in environments" :key="env.id" cols="12" md="6" xl="4">
        <v-card :to="`/environments/${env.id}`" hover class="h-100">
          <v-card-item>
            <template #prepend>
              <v-avatar color="primary" variant="tonal" rounded="lg"><v-icon icon="mdi-server-outline" /></v-avatar>
            </template>
            <v-card-title>{{ env.name }}</v-card-title>
            <v-card-subtitle class="mono">{{ env.knime_path }}</v-card-subtitle>
          </v-card-item>
          <v-card-text>
            <div v-if="env.notes" class="mb-3 text-body-2">{{ env.notes }}</div>
            <div class="d-flex flex-wrap ga-2">
              <v-chip v-if="env.installed === null" size="small" variant="tonal" label>
                <v-progress-circular indeterminate size="12" width="2" class="mr-2" /> estensioni…
              </v-chip>
              <v-chip v-else-if="env.installed === 0" size="small" color="error" variant="tonal" label prepend-icon="mdi-alert">
                Cartella KNIME non trovata
              </v-chip>
              <v-chip v-else size="small" color="success" variant="tonal" label prepend-icon="mdi-puzzle-check-outline">
                {{ env.installed }} estensioni installate
              </v-chip>
              <v-chip size="small" variant="tonal" label prepend-icon="mdi-calendar-clock">{{ env.schedules }} schedule</v-chip>
              <v-chip v-for="arg in env.jvm_args" :key="arg" size="small" variant="outlined" label class="mono">{{ arg }}</v-chip>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-card v-else>
      <v-empty-state
        icon="mdi-server-plus-outline"
        title="Nessun environment"
        text="Un environment indica quale installazione KNIME usare per eseguire i workflow."
      >
        <template v-if="can('operator')" #actions>
          <v-btn color="primary" to="/environments/new">Crea il primo environment</v-btn>
        </template>
      </v-empty-state>
    </v-card>
  </div>
</template>
