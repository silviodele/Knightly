import { reactive } from 'vue'

interface ConfirmState {
  open: boolean
  title: string
  text: string
  confirmText: string
  color: string
  resolve: ((ok: boolean) => void) | null
}

export const confirmState = reactive<ConfirmState>({
  open: false,
  title: '',
  text: '',
  confirmText: 'Conferma',
  color: 'primary',
  resolve: null,
})

/** Finestra di conferma globale: `if (await confirm({...})) ...` */
export function confirm(options: { title: string; text: string; confirmText?: string; color?: string }) {
  return new Promise<boolean>((resolve) => {
    Object.assign(confirmState, {
      open: true,
      confirmText: 'Conferma',
      color: 'primary',
      ...options,
      resolve,
    })
  })
}

export function closeConfirm(ok: boolean) {
  confirmState.open = false
  confirmState.resolve?.(ok)
  confirmState.resolve = null
}
