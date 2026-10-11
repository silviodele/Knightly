<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '@/api'
import { notify, notifyError } from '@/notify'

const open = defineModel<boolean>({ required: true })
const current = ref('')
const next = ref('')
const repeat = ref('')
const saving = ref(false)
const formRef = ref()

watch(open, (value) => {
  if (value) current.value = next.value = repeat.value = ''
})

const required = (v: string) => !!v || 'Campo obbligatorio'
const minLength = (v: string) => v.length >= 8 || 'Almeno 8 caratteri'
const matches = (v: string) => v === next.value || 'Le password non coincidono'

async function save() {
  const { valid } = await formRef.value.validate()
  if (!valid) return
  saving.value = true
  try {
    await api.changePassword(current.value, next.value)
    notify('Password cambiata. Le altre sessioni aperte sono state chiuse.')
    open.value = false
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <v-dialog v-model="open" max-width="440">
    <v-card>
      <v-card-title class="pt-5 px-6">Cambia password</v-card-title>
      <v-card-text class="px-6">
        <v-form ref="formRef" @submit.prevent="save">
          <v-text-field v-model="current" label="Password attuale" type="password" autocomplete="current-password" :rules="[required]" />
          <v-text-field v-model="next" label="Nuova password" type="password" autocomplete="new-password" :rules="[required, minLength]" class="mt-2" />
          <v-text-field v-model="repeat" label="Ripeti la nuova password" type="password" autocomplete="new-password" :rules="[required, matches]" class="mt-2" />
          <button type="submit" hidden />
        </v-form>
      </v-card-text>
      <v-card-actions class="px-6 pb-5">
        <v-spacer />
        <v-btn variant="text" @click="open = false">Annulla</v-btn>
        <v-btn color="primary" variant="flat" :loading="saving" @click="save">Cambia password</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
