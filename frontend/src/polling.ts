import { onBeforeUnmount, onMounted, ref } from 'vue'

/** Esegue `load` subito e poi ogni `ms` millisecondi finche' il componente e' montato. */
export function usePolling(load: () => Promise<unknown>, ms: number) {
  const now = ref(Date.now())
  let timer: ReturnType<typeof setInterval> | undefined
  onMounted(() => {
    load()
    timer = setInterval(() => {
      now.value = Date.now()
      if (document.visibilityState === 'visible') load()
    }, ms)
  })
  onBeforeUnmount(() => clearInterval(timer))
  return { now }
}
