import { reactive } from 'vue'
import { ApiError } from './api'

export interface Toast {
  id: number
  text: string
  color: 'success' | 'error' | 'info' | 'warning'
}

let counter = 0
export const toasts = reactive<Toast[]>([])

export function notify(text: string, color: Toast['color'] = 'success') {
  const toast = { id: ++counter, text, color }
  toasts.push(toast)
  setTimeout(() => dismiss(toast.id), color === 'error' ? 8000 : 4000)
}

export function notifyError(error: unknown) {
  notify(error instanceof ApiError || error instanceof Error ? error.message : String(error), 'error')
}

export function dismiss(id: number) {
  const index = toasts.findIndex((t) => t.id === id)
  if (index >= 0) toasts.splice(index, 1)
}
