<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { api, type RunStatus } from '@/api'

const props = defineProps<{ runId: number; live: boolean }>()
const emit = defineEmits<{ done: [status: RunStatus] }>()

const lines = ref<string[]>([])
const filter = ref('')
const follow = ref(true)
const wrap = ref(true)
const connected = ref(false)
const box = ref<HTMLElement | null>(null)
let source: EventSource | null = null

function close() {
  source?.close()
  source = null
  connected.value = false
}

async function start() {
  close()
  lines.value = []
  if (!props.live) {
    const text = await api.runLog(props.runId)
    lines.value = text ? text.replace(/\r?\n$/, '').split(/\r?\n/) : []
    return
  }
  source = new EventSource(api.runLogStreamUrl(props.runId))
  source.onopen = () => (connected.value = true)
  source.addEventListener('line', (event) => {
    lines.value.push(JSON.parse((event as MessageEvent).data))
  })
  source.addEventListener('done', (event) => {
    close()
    emit('done', JSON.parse((event as MessageEvent).data))
  })
  source.onerror = () => (connected.value = false)
}

watch(() => [props.runId, props.live], start, { immediate: true })
onBeforeUnmount(close)

const visible = computed(() => {
  const q = filter.value.trim().toLowerCase()
  const numbered = lines.value.map((text, i) => ({ n: i + 1, text }))
  return q ? numbered.filter((l) => l.text.toLowerCase().includes(q)) : numbered
})

const levelClass = (text: string) => {
  if (/\b(ERROR|SEVERE|FATAL|Exception)\b/.test(text)) return 'lvl-error'
  if (/\bWARN(ING)?\b/.test(text)) return 'lvl-warn'
  if (/\bDEBUG\b/.test(text)) return 'lvl-debug'
  return ''
}

watch(
  () => lines.value.length,
  async () => {
    if (!follow.value) return
    await nextTick()
    box.value?.scrollTo({ top: box.value.scrollHeight })
  },
)

function onScroll() {
  const el = box.value
  if (el) follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

function download() {
  const blob = new Blob([lines.value.join('\n')], { type: 'text/plain' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `run-${props.runId}.log`
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<template>
  <v-card>
    <v-toolbar density="compact" color="transparent" class="px-2">
      <v-icon icon="mdi-console-line" class="ml-2 mr-2" />
      <span class="font-weight-medium">Log</span>
      <v-chip v-if="live" size="x-small" :color="connected ? 'success' : 'secondary'" variant="flat" class="ml-3">
        <v-icon start :icon="connected ? 'mdi-access-point' : 'mdi-access-point-off'" />
        {{ connected ? 'In tempo reale' : 'Connessione…' }}
      </v-chip>
      <span class="text-caption text-subtle ml-3">{{ lines.length }} righe</span>
      <v-spacer />
      <v-text-field
        v-model="filter"
        density="compact"
        variant="solo-filled"
        flat
        hide-details
        placeholder="Filtra…"
        prepend-inner-icon="mdi-magnify"
        clearable
        style="max-width: 240px"
      />
      <v-btn
        :icon="wrap ? 'mdi-wrap' : 'mdi-wrap-disabled'"
        variant="text"
        size="small"
        :title="wrap ? 'A capo automatico' : 'Senza a capo'"
        @click="wrap = !wrap"
      />
      <v-btn
        icon="mdi-arrow-collapse-down"
        variant="text"
        size="small"
        :color="follow ? 'primary' : undefined"
        title="Segui la fine del log"
        @click="(follow = true), box?.scrollTo({ top: box.scrollHeight })"
      />
      <v-btn icon="mdi-download" variant="text" size="small" title="Scarica" :disabled="!lines.length" @click="download" />
    </v-toolbar>
    <div ref="box" class="log" :class="{ wrap }" @scroll="onScroll">
      <div v-if="!lines.length" class="empty">{{ live ? 'In attesa dell’output di KNIME…' : 'Nessun log disponibile.' }}</div>
      <div v-for="line in visible" :key="line.n" class="line" :class="levelClass(line.text)">
        <span class="n">{{ line.n }}</span><span class="t">{{ line.text }}</span>
      </div>
    </div>
  </v-card>
</template>

<style scoped>
.log {
  height: 60vh;
  overflow: auto;
  background: #0d1117;
  color: #d1d9e3;
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.55;
  padding: 10px 0;
}
.line {
  display: flex;
  white-space: pre;
  padding: 0 12px;
}
.wrap .line {
  white-space: pre-wrap;
  word-break: break-word;
}
.line:hover {
  background: rgba(255, 255, 255, 0.04);
}
.n {
  flex: 0 0 48px;
  color: #56606e;
  text-align: right;
  padding-right: 14px;
  user-select: none;
}
.lvl-error .t {
  color: #ff7b72;
}
.lvl-warn .t {
  color: #e3b341;
}
.lvl-debug .t {
  color: #7d8590;
}
.empty {
  color: #7d8590;
  padding: 12px 20px;
}
</style>
