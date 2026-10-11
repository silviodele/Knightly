<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type Role, type User, type UserIn } from '@/api'
import { auth, ROLES } from '@/auth'
import { confirm } from '@/confirm'
import { formatDateTime, formatRelative } from '@/format'
import { notify, notifyError } from '@/notify'

const users = ref<User[]>([])
const loading = ref(true)
const dialog = ref(false)
const editing = ref<User | null>(null)
const saving = ref(false)
const showPassword = ref(false)
const formRef = ref()
const form = ref<UserIn>({ username: '', full_name: '', role: 'viewer', active: true, password: '' })

async function load() {
  try {
    users.value = await api.users()
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function open(user: User | null) {
  editing.value = user
  form.value = user
    ? { username: user.username, full_name: user.full_name, role: user.role, active: user.active, password: '' }
    : { username: '', full_name: '', role: 'operator', active: true, password: '' }
  showPassword.value = false
  dialog.value = true
}

const required = (v: string) => !!v?.trim() || 'Campo obbligatorio'
const usernameRule = (v: string) => /^[A-Za-z0-9._@-]+$/.test(v) || 'Solo lettere, numeri e . _ @ -'
const passwordRule = (v: string | null | undefined) => {
  if (!v) return editing.value ? true : 'Campo obbligatorio'
  return v.length >= 8 || 'Almeno 8 caratteri'
}

async function save() {
  const { valid } = await formRef.value.validate()
  if (!valid) return
  saving.value = true
  const payload = { ...form.value, password: form.value.password || null }
  try {
    if (editing.value) {
      await api.updateUser(editing.value.id, payload)
      notify(`Utente “${payload.username}” aggiornato`)
    } else {
      await api.createUser(payload)
      notify(`Utente “${payload.username}” creato`)
    }
    dialog.value = false
    await load()
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}

async function remove(user: User) {
  const ok = await confirm({
    title: 'Eliminare l’utente?',
    text: `“${user.username}” non potrà più accedere. Lo storico dei run resta invariato.`,
    confirmText: 'Elimina',
    color: 'error',
  })
  if (!ok) return
  try {
    await api.deleteUser(user.id)
    notify('Utente eliminato')
    await load()
  } catch (e) {
    notifyError(e)
  }
}

function generatePassword() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  const bytes = crypto.getRandomValues(new Uint8Array(14))
  form.value.password = Array.from(bytes, (b) => chars[b % chars.length]).join('')
  showPassword.value = true
}

const headers = [
  { title: 'Utente', key: 'username' },
  { title: 'Ruolo', key: 'role' },
  { title: 'Stato', key: 'active' },
  { title: 'Ultimo accesso', key: 'last_login_at' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]
const initials = (u: User) =>
  (u.full_name || u.username)
    .split(/[\s._@-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('')
</script>

<template>
  <div>
    <div class="d-flex align-center flex-wrap ga-4 mb-6">
      <div>
        <div class="page-title">Utenti</div>
        <div class="text-subtle">Chi può accedere alla piattaforma e con quali permessi</div>
      </div>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-account-plus-outline" @click="open(null)">Nuovo utente</v-btn>
    </div>

    <v-row class="mb-2">
      <v-col v-for="(r, key) in ROLES" :key="key" cols="12" md="4">
        <v-card class="h-100">
          <v-card-text class="d-flex ga-3">
            <v-avatar :color="r.color" variant="tonal" rounded="lg"><v-icon :icon="r.icon" /></v-avatar>
            <div>
              <div class="font-weight-medium">
                {{ r.title }} <span class="text-subtle">· {{ users.filter((u) => u.role === key).length }}</span>
              </div>
              <div class="text-caption text-subtle">{{ r.subtitle }}</div>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-card>
      <v-data-table :headers="headers" :items="users" :loading="loading" items-per-page="25">
        <template #item.username="{ item }">
          <div class="d-flex align-center ga-3 py-2">
            <v-avatar :color="ROLES[item.role as Role].color" variant="tonal" size="36">
              <span class="text-caption font-weight-bold">{{ initials(item) }}</span>
            </v-avatar>
            <div>
              <div class="font-weight-medium">
                {{ item.full_name || item.username }}
                <v-chip v-if="item.id === auth.user?.id" size="x-small" variant="tonal" label class="ml-1">tu</v-chip>
              </div>
              <div class="text-caption text-subtle">{{ item.username }}</div>
            </div>
          </div>
        </template>
        <template #item.role="{ item }">
          <v-chip :color="ROLES[item.role as Role].color" size="small" variant="tonal" label :prepend-icon="ROLES[item.role as Role].icon">
            {{ ROLES[item.role as Role].title }}
          </v-chip>
        </template>
        <template #item.active="{ item }">
          <v-chip :color="item.active ? 'success' : 'secondary'" size="small" variant="flat" label>
            {{ item.active ? 'Attivo' : 'Disattivato' }}
          </v-chip>
        </template>
        <template #item.last_login_at="{ item }">
          <span v-if="item.last_login_at" :title="formatDateTime(item.last_login_at)">{{ formatRelative(item.last_login_at) }}</span>
          <span v-else class="text-subtle">mai</span>
        </template>
        <template #item.actions="{ item }">
          <v-btn icon="mdi-pencil-outline" variant="text" size="small" title="Modifica" @click="open(item)" />
          <v-btn
            icon="mdi-delete-outline"
            variant="text"
            size="small"
            color="error"
            title="Elimina"
            :disabled="item.id === auth.user?.id"
            @click="remove(item)"
          />
        </template>
      </v-data-table>
    </v-card>

    <v-dialog v-model="dialog" max-width="560">
      <v-card>
        <v-card-title class="pt-5 px-6">{{ editing ? 'Modifica utente' : 'Nuovo utente' }}</v-card-title>
        <v-card-text class="px-6">
          <v-form ref="formRef" @submit.prevent="save">
            <v-row dense>
              <v-col cols="12" sm="6">
                <v-text-field v-model="form.username" label="Nome utente" :rules="[required, usernameRule]" autocomplete="off" />
              </v-col>
              <v-col cols="12" sm="6">
                <v-text-field v-model="form.full_name" label="Nome e cognome" />
              </v-col>
            </v-row>

            <div class="text-body-2 font-weight-medium mt-2 mb-2">Ruolo</div>
            <v-item-group v-model="form.role" mandatory>
              <v-item v-for="(r, key) in ROLES" :key="key" v-slot="{ isSelected, toggle }" :value="key">
                <v-card
                  :color="isSelected ? r.color : undefined"
                  :variant="isSelected ? 'tonal' : 'outlined'"
                  class="pa-3 mb-2 d-flex align-center ga-3"
                  @click="toggle"
                >
                  <v-icon :icon="isSelected ? 'mdi-radiobox-marked' : 'mdi-radiobox-blank'" />
                  <div>
                    <div class="font-weight-medium">{{ r.title }}</div>
                    <div class="text-caption text-subtle">{{ r.subtitle }}</div>
                  </div>
                </v-card>
              </v-item>
            </v-item-group>

            <v-text-field
              v-model="form.password"
              :label="editing ? 'Nuova password' : 'Password'"
              :placeholder="editing ? 'Lascia vuoto per non cambiarla' : ''"
              persistent-placeholder
              :type="showPassword ? 'text' : 'password'"
              autocomplete="new-password"
              :rules="[passwordRule]"
              class="mt-3"
              :hint="editing ? 'Cambiandola, l’utente viene disconnesso dalle sessioni aperte' : 'Almeno 8 caratteri'"
              persistent-hint
            >
              <template #append-inner>
                <v-btn :icon="showPassword ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" variant="text" size="small" @click="showPassword = !showPassword" />
                <v-btn icon="mdi-dice-5-outline" variant="text" size="small" title="Genera password" @click="generatePassword" />
              </template>
            </v-text-field>

            <v-switch
              v-model="form.active"
              color="primary"
              inset
              hide-details
              class="mt-2"
              label="Utente attivo"
              :disabled="editing?.id === auth.user?.id"
            />
          </v-form>
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" @click="dialog = false">Annulla</v-btn>
          <v-btn color="primary" variant="flat" :loading="saving" @click="save">{{ editing ? 'Salva' : 'Crea utente' }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>
