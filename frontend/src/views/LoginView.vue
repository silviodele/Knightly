<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { auth } from '@/auth'

const route = useRoute()
const router = useRouter()

const setup = computed(() => auth.needsSetup)
const username = ref('')
const fullName = ref('')
const password = ref('')
const password2 = ref('')
const showPassword = ref(false)
const loading = ref(false)
const error = ref<string | null>(route.query.expired ? 'La sessione è scaduta: accedi di nuovo.' : null)
const formRef = ref()

const required = (v: string) => !!v?.trim() || 'Campo obbligatorio'
const minLength = (v: string) => (v?.length ?? 0) >= 8 || 'Almeno 8 caratteri'
const matches = (v: string) => v === password.value || 'Le password non coincidono'

async function submit() {
  const { valid } = await formRef.value.validate()
  if (!valid) return
  loading.value = true
  error.value = null
  try {
    auth.user = setup.value
      ? await api.setup({ username: username.value.trim(), full_name: fullName.value.trim(), password: password.value })
      : await api.login(username.value.trim(), password.value)
    auth.needsSetup = false
    const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') ? route.query.next : '/'
    router.replace(next)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    password.value = ''
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page d-flex align-center justify-center">
    <div class="w-100" style="max-width: 420px">
      <div class="d-flex align-center ga-3 mb-8 justify-center">
        <img src="/favicon.svg" width="44" height="44" alt="" />
        <div>
          <div class="text-h6 font-weight-bold">knime-scheduler</div>
          <div class="text-caption text-subtle">Workflow automation per KNIME</div>
        </div>
      </div>

      <v-card class="pa-2" elevation="2" :border="false">
        <v-card-item>
          <v-card-title class="text-h5 font-weight-bold">{{ setup ? 'Configurazione iniziale' : 'Accedi' }}</v-card-title>
          <v-card-subtitle class="text-wrap">
            {{ setup ? 'Crea l’account amministratore: potrai poi aggiungere gli altri utenti.' : 'Inserisci le tue credenziali' }}
          </v-card-subtitle>
        </v-card-item>

        <v-card-text>
          <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-4">{{ error }}</v-alert>

          <v-form ref="formRef" @submit.prevent="submit">
            <v-text-field
              v-model="username"
              label="Nome utente"
              prepend-inner-icon="mdi-account-outline"
              autocomplete="username"
              autofocus
              :rules="[required]"
            />
            <v-text-field
              v-if="setup"
              v-model="fullName"
              label="Nome e cognome (facoltativo)"
              prepend-inner-icon="mdi-card-account-details-outline"
              class="mt-2"
            />
            <v-text-field
              v-model="password"
              label="Password"
              prepend-inner-icon="mdi-lock-outline"
              :type="showPassword ? 'text' : 'password'"
              :append-inner-icon="showPassword ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
              :autocomplete="setup ? 'new-password' : 'current-password'"
              :rules="setup ? [required, minLength] : [required]"
              class="mt-2"
              @click:append-inner="showPassword = !showPassword"
            />
            <v-text-field
              v-if="setup"
              v-model="password2"
              label="Ripeti la password"
              prepend-inner-icon="mdi-lock-check-outline"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="new-password"
              :rules="[required, matches]"
              class="mt-2"
            />
            <v-btn type="submit" color="primary" size="large" block :loading="loading" class="mt-4">
              {{ setup ? 'Crea amministratore ed entra' : 'Accedi' }}
            </v-btn>
          </v-form>
        </v-card-text>
      </v-card>

      <div v-if="!setup" class="text-caption text-subtle text-center mt-6">
        Password dimenticata? Chiedi a un amministratore di reimpostarla.
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  padding: 24px;
  background:
    radial-gradient(circle at 15% 20%, rgba(var(--v-theme-primary), 0.12), transparent 40%),
    radial-gradient(circle at 85% 80%, rgba(var(--v-theme-accent), 0.14), transparent 40%),
    rgb(var(--v-theme-background));
}
</style>
