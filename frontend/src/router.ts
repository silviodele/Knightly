import { createRouter, createWebHistory } from 'vue-router'
import { setUnauthorizedHandler, type Role } from './api'
import { auth, can, loadAuth } from './auth'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    public?: boolean // accessibile senza login (pagina di login / primo setup)
    role?: Role // ruolo minimo richiesto
  }
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue'), meta: { title: 'Accesso', public: true } },
    { path: '/', name: 'dashboard', component: () => import('./views/DashboardView.vue'), meta: { title: 'Dashboard' } },
    { path: '/schedules', name: 'schedules', component: () => import('./views/SchedulesView.vue'), meta: { title: 'Schedule' } },
    { path: '/schedules/new', name: 'schedule-new', component: () => import('./views/ScheduleEditView.vue'), meta: { title: 'Nuovo schedule', role: 'operator' } },
    { path: '/schedules/:id(\\d+)', name: 'schedule', component: () => import('./views/ScheduleEditView.vue'), props: true, meta: { title: 'Schedule' } },
    { path: '/workflows', name: 'workflows', component: () => import('./views/WorkflowsView.vue'), meta: { title: 'Workflow' } },
    { path: '/workflows/:id(\\d+)', name: 'workflow', component: () => import('./views/WorkflowDetailView.vue'), props: true, meta: { title: 'Workflow' } },
    { path: '/environments', name: 'environments', component: () => import('./views/EnvironmentsView.vue'), meta: { title: 'Environment' } },
    { path: '/environments/new', name: 'environment-new', component: () => import('./views/EnvironmentEditView.vue'), meta: { title: 'Nuovo environment', role: 'operator' } },
    { path: '/environments/:id(\\d+)', name: 'environment', component: () => import('./views/EnvironmentEditView.vue'), props: true, meta: { title: 'Environment' } },
    { path: '/runs', name: 'runs', component: () => import('./views/RunsView.vue'), meta: { title: 'Run' } },
    { path: '/runs/:id(\\d+)', name: 'run', component: () => import('./views/RunDetailView.vue'), props: true, meta: { title: 'Run' } },
    { path: '/users', name: 'users', component: () => import('./views/UsersView.vue'), meta: { title: 'Utenti', role: 'admin' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  if (!auth.loaded) await loadAuth()
  if (to.meta.public) return true
  if (!auth.user) return { name: 'login', query: to.fullPath !== '/' ? { next: to.fullPath } : {} }
  if (to.meta.role && !can(to.meta.role)) return { name: 'dashboard' }
  return true
})

router.afterEach((to) => {
  document.title = `${to.meta.title ?? 'knime-scheduler'} · knime-scheduler`
})

// Sessione scaduta durante l'uso: torna al login mantenendo la pagina corrente
setUnauthorizedHandler(() => {
  if (!auth.user) return
  auth.user = null
  const current = router.currentRoute.value
  if (!current.meta.public) router.push({ name: 'login', query: { next: current.fullPath, expired: '1' } })
})
