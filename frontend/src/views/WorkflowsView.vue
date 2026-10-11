<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Workflow } from '@/api'
import { can } from '@/auth'
import { formatDateTime } from '@/format'
import { notify, notifyError } from '@/notify'

const router = useRouter()
const workflows = ref<Workflow[]>([])
const loading = ref(true)
const search = ref('')
const dragging = ref(false)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

async function load() {
  try {
    workflows.value = await api.workflows()
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function upload(files: FileList | File[] | null | undefined) {
  const list = Array.from(files ?? [])
  if (!list.length) return
  uploading.value = true
  let last: Workflow | null = null
  for (const file of list) {
    try {
      last = await api.uploadWorkflow(file)
      notify(`“${last.name}” caricato: ${last.dependencies.length} dipendenze rilevate`)
    } catch (e) {
      notifyError(e)
    }
  }
  uploading.value = false
  if (list.length === 1 && last) router.push(`/workflows/${last.id}`)
  else await load()
}

function onDrop(event: DragEvent) {
  dragging.value = false
  upload(event.dataTransfer?.files)
}

const headers = [
  { title: 'Workflow', key: 'name' },
  { title: 'Dipendenze', key: 'dependencies', sortable: false },
  { title: 'Caricato', key: 'uploaded_at' },
]
</script>

<template>
  <div>
    <div class="d-flex align-center flex-wrap ga-4 mb-6">
      <div>
        <div class="page-title">Workflow</div>
        <div class="text-subtle">I file .knwf eseguibili e le estensioni KNIME di cui hanno bisogno</div>
      </div>
      <v-spacer />
      <v-text-field
        v-model="search"
        prepend-inner-icon="mdi-magnify"
        placeholder="Cerca workflow…"
        hide-details
        density="compact"
        style="max-width: 300px"
        clearable
      />
    </div>

    <v-card
      v-if="can('operator')"
      class="dropzone mb-6"
      :class="{ dragging }"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
      @click="fileInput?.click()"
    >
      <v-card-text class="d-flex flex-column align-center py-8 text-center">
        <v-progress-circular v-if="uploading" indeterminate color="primary" size="40" class="mb-3" />
        <v-icon v-else icon="mdi-cloud-upload-outline" size="44" color="primary" class="mb-3" />
        <div class="text-h6">Trascina qui i file .knwf</div>
        <div class="text-subtle">oppure clicca per sceglierli — le dipendenze vengono rilevate automaticamente</div>
        <input ref="fileInput" type="file" accept=".knwf" multiple hidden @change="upload(($event.target as HTMLInputElement).files)" />
      </v-card-text>
    </v-card>

    <v-card>
      <v-data-table
        :headers="headers"
        :items="workflows"
        :search="search"
        :loading="loading"
        items-per-page="25"
        class="clickable-rows"
        @click:row="(_e: Event, { item }: { item: Workflow }) => router.push(`/workflows/${item.id}`)"
      >
        <template #item.name="{ item }">
          <div class="py-3 d-flex align-center ga-3">
            <v-avatar color="primary" variant="tonal" rounded="lg" size="36"><v-icon icon="mdi-sitemap-outline" /></v-avatar>
            <div>
              <div class="font-weight-medium">{{ item.name }}</div>
              <div v-if="item.notes" class="text-caption text-subtle">{{ item.notes }}</div>
            </div>
          </div>
        </template>
        <template #item.dependencies="{ item }">
          <v-chip
            v-for="d in item.dependencies.slice(0, 3)"
            :key="d.id"
            size="small"
            variant="tonal"
            class="mr-1 mb-1"
            label
          >
            {{ d.name || d.feature_id }}
          </v-chip>
          <span v-if="item.dependencies.length > 3" class="text-caption text-subtle">+{{ item.dependencies.length - 3 }}</span>
          <span v-if="!item.dependencies.length" class="text-caption text-subtle">nessuna</span>
        </template>
        <template #item.uploaded_at="{ item }">{{ formatDateTime(item.uploaded_at) }}</template>
        <template #no-data>
          <div class="pa-6 text-subtle">Nessun workflow caricato.</div>
        </template>
      </v-data-table>
    </v-card>
  </div>
</template>

<style scoped>
.dropzone {
  border: 2px dashed rgba(var(--v-theme-primary), 0.35) !important;
  background: rgba(var(--v-theme-primary), 0.03);
  cursor: pointer;
  transition: all 0.15s ease;
}
.dropzone:hover,
.dropzone.dragging {
  border-color: rgb(var(--v-theme-primary)) !important;
  background: rgba(var(--v-theme-primary), 0.08);
}
</style>
