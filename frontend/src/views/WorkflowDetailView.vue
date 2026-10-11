<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Schedule, type Workflow } from '@/api'
import { confirm } from '@/confirm'
import { describeTrigger, formatDateTime } from '@/format'
import { notify, notifyError } from '@/notify'

const props = defineProps<{ id: string }>()
const router = useRouter()
const workflow = ref<Workflow | null>(null)
const schedules = ref<Schedule[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const dialog = ref(false)
const newDep = ref({ feature_id: '', name: '', version: '', update_site: '' })

async function load() {
  try {
    const [wf, all] = await Promise.all([api.workflow(Number(props.id)), api.schedules()])
    workflow.value = wf
    schedules.value = all.filter((s) => s.workflow_id === wf.id)
  } catch (e) {
    notifyError(e)
  }
}
onMounted(load)

const fileName = computed(() => workflow.value?.file_path.split(/[\\/]/).pop()?.replace(/^[0-9a-f]{8}_/, '') ?? '')

async function replaceFile(files: FileList | null) {
  const file = files?.[0]
  if (!file) return
  try {
    workflow.value = await api.replaceWorkflowFile(Number(props.id), file)
    notify('Nuova versione caricata, dipendenze aggiornate')
  } catch (e) {
    notifyError(e)
  }
}

async function addDependency() {
  try {
    await api.addDependency(Number(props.id), { ...newDep.value, update_site: newDep.value.update_site || null })
    dialog.value = false
    newDep.value = { feature_id: '', name: '', version: '', update_site: '' }
    notify('Dipendenza aggiunta')
    await load()
  } catch (e) {
    notifyError(e)
  }
}

async function removeDependency(depId: number, name: string) {
  const ok = await confirm({ title: 'Rimuovere la dipendenza?', text: name, confirmText: 'Rimuovi', color: 'error' })
  if (!ok) return
  try {
    await api.deleteDependency(Number(props.id), depId)
    await load()
  } catch (e) {
    notifyError(e)
  }
}

async function remove() {
  const ok = await confirm({
    title: 'Eliminare il workflow?',
    text: 'Il file .knwf verrà eliminato dal server.',
    confirmText: 'Elimina',
    color: 'error',
  })
  if (!ok) return
  try {
    await api.deleteWorkflow(Number(props.id))
    notify('Workflow eliminato')
    router.push('/workflows')
  } catch (e) {
    notifyError(e)
  }
}

const headers = [
  { title: 'Estensione', key: 'name' },
  { title: 'Versione', key: 'version' },
  { title: 'Origine', key: 'source' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]
</script>

<template>
  <div v-if="workflow">
    <div class="d-flex align-center flex-wrap ga-3 mb-6">
      <v-btn icon="mdi-arrow-left" variant="text" to="/workflows" />
      <v-avatar color="primary" variant="tonal" rounded="lg" size="44"><v-icon icon="mdi-sitemap-outline" /></v-avatar>
      <div>
        <div class="page-title">{{ workflow.name }}</div>
        <div class="text-subtle">
          <span class="mono">{{ fileName }}</span> · caricato il {{ formatDateTime(workflow.uploaded_at) }}
        </div>
      </div>
      <v-spacer />
      <v-btn variant="tonal" prepend-icon="mdi-file-replace-outline" @click="fileInput?.click()">Carica nuova versione</v-btn>
      <input ref="fileInput" type="file" accept=".knwf" hidden @change="replaceFile(($event.target as HTMLInputElement).files)" />
      <v-btn
        variant="text"
        color="error"
        prepend-icon="mdi-delete-outline"
        :disabled="schedules.length > 0"
        :title="schedules.length ? 'Usato da uno o più schedule' : ''"
        @click="remove"
      >
        Elimina
      </v-btn>
    </div>

    <v-row>
      <v-col cols="12" lg="8">
        <v-card>
          <v-card-item prepend-icon="mdi-puzzle-outline">
            <v-card-title class="section-title">Dipendenze</v-card-title>
            <v-card-subtitle>
              Rilevate dal file a ogni caricamento; quelle aggiunte a mano restano anche con una nuova versione.
            </v-card-subtitle>
            <template #append>
              <v-btn color="primary" variant="tonal" size="small" prepend-icon="mdi-plus" @click="dialog = true">Aggiungi</v-btn>
            </template>
          </v-card-item>
          <v-data-table :headers="headers" :items="workflow.dependencies" items-per-page="-1" hide-default-footer>
            <template #item.name="{ item }">
              <div class="py-2">
                <div class="font-weight-medium">{{ item.name || item.feature_id }}</div>
                <div class="text-caption text-subtle mono">{{ item.feature_id }}</div>
              </div>
            </template>
            <template #item.version="{ item }">{{ item.version || '—' }}</template>
            <template #item.source="{ item }">
              <v-chip size="small" variant="tonal" :color="item.source === 'detected' ? 'info' : 'secondary'" label>
                <v-icon start :icon="item.source === 'detected' ? 'mdi-magnify-scan' : 'mdi-hand-back-right-outline'" />
                {{ item.source === 'detected' ? 'Rilevata' : 'Manuale' }}
              </v-chip>
            </template>
            <template #item.actions="{ item }">
              <v-btn icon="mdi-close" variant="text" size="small" @click="removeDependency(item.id, item.name || item.feature_id)" />
            </template>
            <template #no-data><div class="pa-6 text-subtle">Nessuna dipendenza.</div></template>
          </v-data-table>
        </v-card>
      </v-col>

      <v-col cols="12" lg="4">
        <v-card>
          <v-card-item prepend-icon="mdi-calendar-clock">
            <v-card-title class="section-title">Usato da</v-card-title>
          </v-card-item>
          <v-list v-if="schedules.length" class="pt-0">
            <v-list-item
              v-for="s in schedules"
              :key="s.id"
              :to="`/schedules/${s.id}`"
              :title="s.name"
              :subtitle="`${s.environment_name} · ${describeTrigger(s)}`"
            >
              <template #append>
                <v-icon v-if="s.missing_dependencies" icon="mdi-puzzle-remove-outline" color="error" size="small" />
              </template>
            </v-list-item>
          </v-list>
          <v-card-text v-else class="text-subtle">
            Nessuno schedule.
            <router-link to="/schedules/new">Crea uno schedule</router-link>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-dialog v-model="dialog" max-width="560">
      <v-card>
        <v-card-title class="pt-5 px-6">Aggiungi dipendenza</v-card-title>
        <v-card-text class="px-6">
          <v-text-field
            v-model="newDep.feature_id"
            label="Feature"
            class="mono"
            placeholder="org.knime.features.ext.jfreechart.feature.group"
            hint="Il suffisso .feature.group viene aggiunto se manca"
            persistent-hint
          />
          <v-text-field v-model="newDep.name" label="Nome leggibile" class="mt-3" />
          <v-row dense>
            <v-col cols="5"><v-text-field v-model="newDep.version" label="Versione minima" /></v-col>
            <v-col cols="7"><v-text-field v-model="newDep.update_site" label="Update site" /></v-col>
          </v-row>
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" @click="dialog = false">Annulla</v-btn>
          <v-btn color="primary" variant="flat" :disabled="!newDep.feature_id.trim()" @click="addDependency">Aggiungi</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
  <v-skeleton-loader v-else type="heading, table" />
</template>
