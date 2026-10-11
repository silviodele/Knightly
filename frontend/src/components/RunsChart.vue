<script setup lang="ts">
import { computed } from 'vue'
import type { Stats } from '@/api'

const props = defineProps<{ days: Stats['daily'] }>()

const HEIGHT = 160
const max = computed(() => Math.max(1, ...props.days.map((d) => d.success + d.failed + d.other)))
const dayLabel = new Intl.DateTimeFormat('it-IT', { day: 'numeric', month: 'short' })
const weekday = new Intl.DateTimeFormat('it-IT', { weekday: 'narrow' })

const bars = computed(() =>
  props.days.map((d) => {
    const date = new Date(`${d.day}T12:00:00`)
    const scale = (n: number) => (n / max.value) * HEIGHT
    return {
      ...d,
      total: d.success + d.failed + d.other,
      label: dayLabel.format(date),
      short: weekday.format(date).toUpperCase(),
      dom: date.getDate(),
      success: scale(d.success),
      failed: scale(d.failed),
      other: scale(d.other),
      raw: d,
    }
  }),
)
</script>

<template>
  <div class="chart">
    <div v-for="bar in bars" :key="bar.day" class="col">
      <v-tooltip location="top">
        <template #activator="{ props: tip }">
          <div v-bind="tip" class="stack" :style="{ height: `${HEIGHT}px` }">
            <div class="seg other" :style="{ height: `${bar.other}px` }" />
            <div class="seg failed" :style="{ height: `${bar.failed}px` }" />
            <div class="seg success" :style="{ height: `${bar.success}px` }" />
            <div v-if="!bar.total" class="seg empty" />
          </div>
        </template>
        <div class="font-weight-bold">{{ bar.label }}</div>
        <div>{{ bar.raw.success }} riusciti · {{ bar.raw.failed }} falliti · {{ bar.raw.other }} altri</div>
      </v-tooltip>
      <div class="text-caption text-subtle mt-1 lh-1">{{ bar.short }}<br />{{ bar.dom }}</div>
    </div>
  </div>
  <div class="d-flex ga-4 mt-3 text-caption text-subtle">
    <span><span class="dot success" /> Riusciti</span>
    <span><span class="dot failed" /> Falliti</span>
    <span><span class="dot other" /> Annullati / timeout</span>
  </div>
</template>

<style scoped>
.chart {
  display: grid;
  grid-template-columns: repeat(14, 1fr);
  gap: 6px;
  align-items: end;
}
.col {
  text-align: center;
}
.lh-1 {
  line-height: 1.2;
}
.stack {
  display: flex;
  flex-direction: column-reverse;
  justify-content: flex-start;
  border-radius: 6px;
  overflow: hidden;
  background: rgba(var(--v-theme-on-surface), 0.04);
  cursor: default;
}
.seg {
  width: 100%;
  transition: height 0.4s ease;
}
.success {
  background: rgb(var(--v-theme-success));
}
.failed {
  background: rgb(var(--v-theme-error));
}
.other {
  background: rgb(var(--v-theme-secondary));
}
.empty {
  height: 3px;
  background: rgba(var(--v-theme-on-surface), 0.12);
}
.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
  margin-right: 4px;
  vertical-align: middle;
}
</style>
