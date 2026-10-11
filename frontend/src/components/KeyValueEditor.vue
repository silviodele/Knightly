<script setup lang="ts">
import { ref, watch } from 'vue'

// Editor di coppie chiave/valore (preferenze, variabili d'ambiente).
const model = defineModel<Record<string, string>>({ required: true })
defineProps<{ keyLabel?: string; valueLabel?: string; keyPlaceholder?: string }>()

const rows = ref<{ key: string; value: string }[]>([])

watch(
  model,
  (value) => {
    const current = Object.fromEntries(rows.value.filter((r) => r.key).map((r) => [r.key, r.value]))
    if (JSON.stringify(current) !== JSON.stringify(value)) {
      rows.value = Object.entries(value).map(([key, v]) => ({ key, value: v }))
    }
  },
  { immediate: true },
)

watch(
  rows,
  (value) => {
    model.value = Object.fromEntries(value.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value]))
  },
  { deep: true },
)
</script>

<template>
  <div>
    <div v-for="(row, i) in rows" :key="i" class="d-flex ga-2 align-start">
      <v-text-field v-model="row.key" :label="keyLabel ?? 'Chiave'" :placeholder="keyPlaceholder" class="mono" />
      <v-text-field v-model="row.value" :label="valueLabel ?? 'Valore'" class="mono" />
      <v-btn icon="mdi-close" variant="text" size="small" class="mt-2" @click="rows.splice(i, 1)" />
    </div>
    <v-btn variant="tonal" size="small" prepend-icon="mdi-plus" @click="rows.push({ key: '', value: '' })">Aggiungi</v-btn>
  </div>
</template>
