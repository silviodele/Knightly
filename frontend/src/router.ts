import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('./views/DashboardView.vue'), meta: { title: 'Dashboard' } },
    { path: '/schedules', name: 'schedules', component: () => import('./views/SchedulesView.vue'), meta: { title: 'Schedule' } },
    { path: '/schedules/new', name: 'schedule-new', component: () => import('./views/ScheduleEditView.vue'), meta: { title: 'Nuovo schedule' } },
    { path: '/schedules/:id(\\d+)', name: 'schedule', component: () => import('./views/ScheduleEditView.vue'), props: true, meta: { title: 'Schedule' } },
    { path: '/workflows', name: 'workflows', component: () => import('./views/WorkflowsView.vue'), meta: { title: 'Workflow' } },
    { path: '/workflows/:id(\\d+)', name: 'workflow', component: () => import('./views/WorkflowDetailView.vue'), props: true, meta: { title: 'Workflow' } },
    { path: '/environments', name: 'environments', component: () => import('./views/EnvironmentsView.vue'), meta: { title: 'Environment' } },
    { path: '/environments/new', name: 'environment-new', component: () => import('./views/EnvironmentEditView.vue'), meta: { title: 'Nuovo environment' } },
    { path: '/environments/:id(\\d+)', name: 'environment', component: () => import('./views/EnvironmentEditView.vue'), props: true, meta: { title: 'Environment' } },
    { path: '/runs', name: 'runs', component: () => import('./views/RunsView.vue'), meta: { title: 'Run' } },
    { path: '/runs/:id(\\d+)', name: 'run', component: () => import('./views/RunDetailView.vue'), props: true, meta: { title: 'Run' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) ?? 'knime-scheduler'} · knime-scheduler`
})
