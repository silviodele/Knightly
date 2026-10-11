<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type EnvironmentIn } from '@/api'
import KeyValueEditor from '@/components/KeyValueEditor.vue'
import { confirm } from '@/confirm'
import { notify, notifyError } from '@/notify'

const props = defineProps<{ id?: string }>()
const router = useRouter()
const isNew = computed(() => !props.id)

const form = ref<EnvironmentIn>({
  name: '',
  notes: '',
  knime_path: '',
  update_sites: [],
  extensions: [],
  preferences_file: null,
  preference_entries: {},
  jvm_args: ['-Xmx4g'],
  env_vars: {},
})
const title = ref('')
const installed = ref<Record<string, string>>({})
const featureSearch = ref('')
const loading = ref(!isNew.value)
const saving = ref(false)
const formRef = ref()

onMounted(async () => {
  if (isNew.value) return
  try {
    const env = await api.environment(Number(props.id))
    const { id: _id, created_at: _c, ...rest } = env
    form.value = rest
    title.value = env.name
    installed.value = await api.installedFeatures(env.id)
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
})

const required = (v: unknown) => (typeof v === 'string' && v.trim() !== '') || 'Campo obbligatorio'

async function save() {
  const { valid } = await formRef.value.validate()
  if (!valid) return
  saving.value = true
  try {
    const payload = { ...form.value, preferences_file: form.value.preferences_file || null }
    if (isNew.value) {
      const env = await api.createEnvironment(payload)
      notify(`Environment “${env.name}” creato`)
      router.replace(`/environments/${env.id}`)
    } else {
      const env = await api.updateEnvironment(Number(props.id), payload)
      title.value = env.name
      installed.value = await api.installedFeatures(env.id)
      notify('Modifiche salvate')
    }
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}

async function remove() {
  const ok = await confirm({
    title: 'Eliminare l’environment?',
    text: 'L’installazione KNIME sul disco non viene toccata.',
    confirmText: 'Elimina',
    color: 'error',
  })
  if (!ok) return
  try {
    await api.deleteEnvironment(Number(props.id))
    notify('Environment eliminato')
    router.push('/environments')
  } catch (e) {
    notifyError(e)
  }
}

const installedRows = computed(() =>
  Object.entries(installed.value)
    .map(([feature, version]) => ({ feature, version }))
    .sort((a, b) => a.feature.localeCompare(b.feature)),
)
const requestedMissing = computed(() => form.value.extensions.filter((f) => !(f in installed.value)))
</script>

<template>
  <div>
    <v-skeleton-loader v-if="loading" type="heading, article" />
    <v-form v-else ref="formRef" @submit.prevent="save">
      <div class="d-flex align-center flex-wrap ga-3 mb-6">
        <v-btn icon="mdi-arrow-left" variant="text" to="/environments" />
        <div>
          <div class="page-title">{{ isNew ? 'Nuovo environment' : title }}</div>
          <div class="text-subtle">Dove vengono eseguiti i workflow</div>
        </div>
        <v-spacer />
        <v-btn v-if="!isNew" variant="text" color="error" prepend-icon="mdi-delete-outline" @click="remove">Elimina</v-btn>
      </div>

      <v-row>
        <v-col cols="12" lg="7">
          <v-card class="mb-4">
            <v-card-item prepend-icon="mdi-server-outline">
              <v-card-title class="section-title">Installazione KNIME</v-card-title>
            </v-card-item>
            <v-card-text>
              <v-text-field v-model="form.name" label="Nome" placeholder="KNIME 5.3 produzione" :rules="[required]" />
              <v-text-field
                v-model="form.knime_path"
                label="Cartella dell’installazione"
                placeholder="C:\knime_5.3.0"
                class="mono mt-2"
                hint="La cartella che contiene knime.exe e la sottocartella features/"
                persistent-hint
                :rules="[required]"
                prepend-inner-icon="mdi-folder-outline"
              />
              <v-textarea v-model="form.notes" label="Note" rows="2" auto-grow class="mt-4" hide-details />
            </v-card-text>
          </v-card>

          <v-card class="mb-4">
            <v-card-item prepend-icon="mdi-puzzle-outline">
              <v-card-title class="section-title">Estensioni</v-card-title>
              <v-card-subtitle>Estensioni che questo environment deve avere installate</v-card-subtitle>
            </v-card-item>
            <v-card-text>
              <v-combobox
                v-model="form.extensions"
                label="Estensioni richieste"
                multiple
                chips
                closable-chips
                class="mono"
                hint="Identificativo della feature, invio per aggiungere"
                persistent-hint
              />
              <v-alert v-if="!isNew && requestedMissing.length" type="warning" variant="tonal" density="compact" class="mt-3">
                {{ requestedMissing.length }} estensioni richieste non risultano installate. L’installazione automatica
                arriverà a breve: per ora installale da KNIME (File → Install KNIME Extensions).
              </v-alert>
              <v-combobox
                v-model="form.update_sites"
                label="Update site"
                multiple
                chips
                closable-chips
                class="mono mt-4"
                placeholder="https://update.knime.com/analytics-platform/5.3"
              />
            </v-card-text>
          </v-card>

          <v-card class="mb-4">
            <v-card-item prepend-icon="mdi-tune-variant">
              <v-card-title class="section-title">Preferenze KNIME</v-card-title>
              <v-card-subtitle>Ad esempio l’ambiente Python usato dai nodi Python</v-card-subtitle>
            </v-card-item>
            <v-card-text>
              <v-text-field
                v-model="form.preferences_file"
                label="File di preferenze (.epf)"
                placeholder="C:\knime-prefs\produzione.epf"
                class="mono"
                hint="Esportato da KNIME con File → Export Preferences"
                persistent-hint
                prepend-inner-icon="mdi-file-cog-outline"
              />
              <div class="text-body-2 font-weight-medium mt-5 mb-2">Preferenze aggiuntive (sovrascrivono il file)</div>
              <KeyValueEditor v-model="form.preference_entries" key-label="Chiave" key-placeholder="/instance/org.knime…" />
            </v-card-text>
          </v-card>
        </v-col>

        <v-col cols="12" lg="5">
          <v-card class="mb-4">
            <v-card-item prepend-icon="mdi-language-java">
              <v-card-title class="section-title">JVM e processo</v-card-title>
            </v-card-item>
            <v-card-text>
              <v-combobox
                v-model="form.jvm_args"
                label="Argomenti JVM"
                multiple
                chips
                closable-chips
                class="mono"
                hint="es. -Xmx8g"
                persistent-hint
              />
              <div class="text-body-2 font-weight-medium mt-5 mb-2">Variabili d’ambiente</div>
              <KeyValueEditor v-model="form.env_vars" key-label="Nome" key-placeholder="HTTP_PROXY" />
            </v-card-text>
          </v-card>

          <v-card v-if="!isNew" class="mb-4">
            <v-card-item prepend-icon="mdi-puzzle-check-outline">
              <v-card-title class="section-title">Estensioni installate</v-card-title>
              <v-card-subtitle>Lette da <span class="mono">features/</span> · {{ installedRows.length }}</v-card-subtitle>
            </v-card-item>
            <v-card-text v-if="!installedRows.length">
              <v-alert type="error" variant="tonal" density="compact">
                Nessuna estensione trovata: verifica che la cartella esista e contenga <span class="mono">features/</span>.
              </v-alert>
            </v-card-text>
            <template v-else>
              <v-card-text class="pb-0">
                <v-text-field
                  v-model="featureSearch"
                  density="compact"
                  prepend-inner-icon="mdi-magnify"
                  placeholder="Cerca…"
                  hide-details
                  clearable
                />
              </v-card-text>
              <v-data-table
                :items="installedRows"
                :headers="[{ title: 'Feature', key: 'feature' }, { title: 'Versione', key: 'version' }]"
                :search="featureSearch"
                density="compact"
                items-per-page="10"
              >
                <template #item.feature="{ item }">
                  <span class="mono" style="word-break: break-all">{{ item.feature.replace(/\.feature\.group$/, '') }}</span>
                </template>
                <template #item.version="{ item }">
                  <span class="text-no-wrap" :title="item.version">{{ item.version.split('.').slice(0, 3).join('.') }}</span>
                </template>
              </v-data-table>
            </template>
          </v-card>
        </v-col>
      </v-row>

      <div class="sticky-actions d-flex align-center ga-3 py-3 px-1 mt-2">
        <v-spacer />
        <v-btn variant="text" to="/environments">Annulla</v-btn>
        <v-btn type="submit" color="primary" :loading="saving" prepend-icon="mdi-content-save-outline">
          {{ isNew ? 'Crea environment' : 'Salva modifiche' }}
        </v-btn>
      </div>
    </v-form>
  </div>
</template>
