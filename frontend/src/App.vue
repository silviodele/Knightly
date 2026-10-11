<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useDisplay, useTheme } from 'vuetify'
import ConfirmDialog from './components/ConfirmDialog.vue'
import { dismiss, toasts } from './notify'

const route = useRoute()
const theme = useTheme()
const { mobile } = useDisplay()

const drawer = ref(true)
const rail = ref(localStorage.getItem('rail') === '1')

const items = [
  { title: 'Dashboard', icon: 'mdi-view-dashboard-outline', to: '/' },
  { title: 'Schedule', icon: 'mdi-calendar-clock', to: '/schedules' },
  { title: 'Run', icon: 'mdi-play-circle-outline', to: '/runs' },
  { title: 'Workflow', icon: 'mdi-sitemap-outline', to: '/workflows' },
  { title: 'Environment', icon: 'mdi-server-outline', to: '/environments' },
]

const isDark = computed(() => theme.global.current.value.dark)

function toggleTheme() {
  const next = isDark.value ? 'light' : 'dark'
  theme.change(next)
  localStorage.setItem('theme', next)
}

function toggleRail() {
  if (mobile.value) {
    drawer.value = !drawer.value
  } else {
    rail.value = !rail.value
    localStorage.setItem('rail', rail.value ? '1' : '0')
  }
}

const showNewSchedule = computed(() => !route.path.startsWith('/schedules'))

const isSelected = (to: string) => (to === '/' ? route.path === '/' : route.path.startsWith(to))
</script>

<template>
  <v-app>
    <v-navigation-drawer v-model="drawer" :rail="rail && !mobile" :permanent="!mobile" width="232">
      <div class="d-flex align-center px-3 py-4 ga-3">
        <img src="/favicon.svg" width="32" height="32" alt="" />
        <div v-if="!rail || mobile" class="text-truncate">
          <div class="font-weight-bold">knime-scheduler</div>
          <div class="text-caption text-subtle">Workflow automation</div>
        </div>
      </div>
      <v-list nav density="comfortable" color="primary">
        <v-list-item
          v-for="item in items"
          :key="item.to"
          :to="item.to"
          :prepend-icon="item.icon"
          :title="item.title"
          :active="isSelected(item.to)"
          rounded="lg"
        />
      </v-list>
      <template #append>
        <v-list nav density="comfortable">
          <v-list-item
            :prepend-icon="isDark ? 'mdi-weather-sunny' : 'mdi-weather-night'"
            :title="isDark ? 'Tema chiaro' : 'Tema scuro'"
            rounded="lg"
            @click="toggleTheme"
          />
          <v-list-item
            href="/docs"
            target="_blank"
            prepend-icon="mdi-api"
            title="API"
            rounded="lg"
          />
        </v-list>
      </template>
    </v-navigation-drawer>

    <v-app-bar flat density="comfortable" border="b">
      <v-app-bar-nav-icon @click="toggleRail" />
      <v-app-bar-title class="text-body-1 text-subtle">{{ route.meta.title }}</v-app-bar-title>
      <template #append>
        <v-btn v-if="showNewSchedule" color="primary" variant="flat" prepend-icon="mdi-plus" to="/schedules/new" class="mr-2">
          Nuovo schedule
        </v-btn>
      </template>
    </v-app-bar>

    <v-main>
      <v-container fluid class="pa-4 pa-md-6" style="max-width: 1440px">
        <router-view v-slot="{ Component }">
          <v-fade-transition mode="out-in">
            <component :is="Component" :key="route.fullPath" />
          </v-fade-transition>
        </router-view>
      </v-container>
    </v-main>

    <ConfirmDialog />

    <div class="toasts">
      <v-slide-y-reverse-transition group>
        <v-alert
          v-for="toast in toasts"
          :key="toast.id"
          :type="toast.color"
          variant="flat"
          density="compact"
          closable
          class="mb-2 elevation-4"
          @click:close="dismiss(toast.id)"
        >
          {{ toast.text }}
        </v-alert>
      </v-slide-y-reverse-transition>
    </div>
  </v-app>
</template>

<style scoped>
.toasts {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 3000;
  width: min(420px, calc(100vw - 48px));
}
</style>
