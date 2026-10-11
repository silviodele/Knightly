<script setup lang="ts">
import { computed } from 'vue'
import type { RunStatus } from '@/api'
import { STATUS } from '@/format'

const props = withDefaults(defineProps<{ status: RunStatus; size?: 'x-small' | 'small' | 'default' }>(), {
  size: 'small',
})
const meta = computed(() => STATUS[props.status] ?? { label: props.status, color: 'secondary', icon: 'mdi-help' })
</script>

<template>
  <v-chip :color="meta.color" :size="size" variant="tonal" label class="font-weight-medium">
    <v-progress-circular v-if="status === 'running'" indeterminate size="12" width="2" class="mr-2" />
    <v-icon v-else :icon="meta.icon" start />
    {{ meta.label }}
  </v-chip>
</template>
