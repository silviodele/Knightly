<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type DependencyCheck } from '@/api'
import { can } from '@/auth'
import { notify, notifyError } from '@/notify'

const props = defineProps<{ workflowId: number | null; environmentId: number | null }>()

const report = ref<DependencyCheck[]>([])
const loading = ref(false)

async function load() {
  if (!props.workflowId || !props.environmentId) {
    report.value = []
    return
  }
  loading.value = true
  try {
    report.value = await api.dependencyCheck(props.workflowId, props.environmentId)
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch(() => [props.workflowId, props.environmentId], load, { immediate: true })

const missing = computed(() => report.value.filter((d) => d.status === 'missing'))
const outdated = computed(() => report.value.filter((d) => d.status === 'outdated'))

const summary = computed(() => {
  if (missing.value.length)
    return {
      type: 'error' as const,
      title: missing.value.length === 1 ? 'Manca un’estensione' : `Mancano ${missing.value.length} estensioni`,
      text: 'I run falliranno finché non saranno installate nell’environment.',
    }
  if (outdated.value.length)
    return {
      type: 'warning' as const,
      title: outdated.value.length === 1 ? 'Un’estensione ha una versione più vecchia' : `${outdated.value.length} estensioni hanno una versione più vecchia`,
      text: 'Il workflow è stato salvato con versioni più recenti: potrebbe comportarsi diversamente.',
    }
  return {
    type: 'success' as const,
    title: 'Tutte le dipendenze sono soddisfatte',
    text: `${report.value.length} estensioni richieste, tutte installate.`,
  }
})

const STATUS = {
  ok: { color: 'success', icon: 'mdi-check-circle', label: 'Installata' },
  outdated: { color: 'warning', icon: 'mdi-alert', label: 'Versione vecchia' },
  missing: { color: 'error', icon: 'mdi-close-circle', label: 'Mancante' },
}

async function requestExtension(dep: DependencyCheck) {
  try {
    await api.requestExtension(props.environmentId!, dep.feature_id)
    notify(`${dep.name || dep.feature_id} aggiunta alle estensioni dell’environment`)
    await load()
  } catch (e) {
    notifyError(e)
  }
}

defineExpose({ reload: load })
</script>

<template>
  <div>
    <v-alert v-if="!workflowId || !environmentId" type="info" variant="tonal" density="compact" icon="mdi-information-outline">
      Scegli workflow ed environment per verificare le dipendenze.
    </v-alert>

    <template v-else>
      <v-skeleton-loader v-if="loading && !report.length" type="list-item-two-line@3" />

      <v-alert v-else-if="!report.length" type="warning" variant="tonal" density="compact">
        Nessuna dipendenza nota per questo workflow.
        <router-link :to="`/workflows/${workflowId}`">Aggiungile dalla pagina del workflow</router-link>.
      </v-alert>

      <template v-else>
        <v-alert :type="summary.type" variant="tonal" density="compact" class="mb-3" :title="summary.title">
          {{ summary.text }}
        </v-alert>

        <div v-for="dep in report" :key="dep.feature_id" class="dep d-flex ga-3 py-2">
          <v-icon :icon="STATUS[dep.status].icon" :color="STATUS[dep.status].color" class="mt-1" />
          <div class="flex-grow-1" style="min-width: 0">
            <div class="d-flex align-center ga-2">
              <span class="font-weight-medium">{{ dep.name || dep.feature_id }}</span>
              <v-chip :color="STATUS[dep.status].color" size="x-small" variant="tonal" label>{{ STATUS[dep.status].label }}</v-chip>
            </div>
            <div class="text-caption text-subtle">
              <span class="mono" style="word-break: break-all">{{ dep.feature_id }}</span>
            </div>
            <div class="text-caption text-subtle">
              <span v-if="dep.required_version">richiesta {{ dep.required_version }}</span>
              <span v-if="dep.installed_version"> · installata {{ dep.installed_version.split('.').slice(0, 3).join('.') }}</span>
            </div>
            <template v-if="dep.status !== 'ok'">
              <v-chip v-if="dep.requested" size="small" variant="tonal" color="info" label class="mt-2">
                <v-icon start icon="mdi-playlist-check" /> Richiesta all’environment
              </v-chip>
              <v-btn
                v-else-if="can('operator')"
                size="small"
                variant="tonal"
                color="primary"
                prepend-icon="mdi-plus"
                class="mt-2"
                @click="requestExtension(dep)"
              >
                Aggiungi all’environment
              </v-btn>
            </template>
          </div>
        </div>

        <div class="d-flex flex-wrap ga-2 mt-3">
          <v-btn size="small" variant="text" prepend-icon="mdi-sitemap-outline" :to="`/workflows/${workflowId}`">
            Dipendenze del workflow
          </v-btn>
          <v-btn size="small" variant="text" prepend-icon="mdi-server-outline" :to="`/environments/${environmentId}`">
            Apri environment
          </v-btn>
        </div>
        <div class="text-caption text-subtle mt-1">L’installazione automatica delle estensioni arriverà a breve.</div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.dep + .dep {
  border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}
</style>
