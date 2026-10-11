import { reactive } from 'vue'
import { api, type Role, type User } from './api'

const LEVEL: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 }

export const ROLES: Record<Role, { title: string; subtitle: string; color: string; icon: string }> = {
  viewer: { title: 'Lettore', subtitle: 'Vede dashboard, run e log', color: 'secondary', icon: 'mdi-eye-outline' },
  operator: {
    title: 'Operatore',
    subtitle: 'Gestisce schedule, workflow ed environment e avvia i run',
    color: 'info',
    icon: 'mdi-account-wrench-outline',
  },
  admin: { title: 'Amministratore', subtitle: 'Tutto, compresa la gestione utenti', color: 'primary', icon: 'mdi-shield-account-outline' },
}

export const auth = reactive<{ user: User | null; needsSetup: boolean; loaded: boolean }>({
  user: null,
  needsSetup: false,
  loaded: false,
})

export async function loadAuth() {
  const status = await api.authStatus()
  auth.user = status.user
  auth.needsSetup = status.needs_setup
  auth.loaded = true
}

/** true se l'utente collegato ha almeno il ruolo indicato */
export function can(role: Role): boolean {
  return !!auth.user && LEVEL[auth.user.role] >= LEVEL[role]
}

export async function logout() {
  try {
    await api.logout()
  } finally {
    auth.user = null
  }
}
