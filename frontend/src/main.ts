import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'
import './styles.css'

import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi'
import { it } from 'vuetify/locale'

import App from './App.vue'
import { router } from './router'

const savedTheme = localStorage.getItem('theme') ?? 'light'

const vuetify = createVuetify({
  locale: { locale: 'it', messages: { it } },
  icons: { defaultSet: 'mdi', aliases, sets: { mdi } },
  theme: {
    defaultTheme: savedTheme,
    themes: {
      light: {
        dark: false,
        colors: {
          primary: '#2F5BEA',
          secondary: '#5B6475',
          accent: '#FFD43B',
          background: '#F4F6FB',
          surface: '#FFFFFF',
          success: '#1E9E5A',
          error: '#D93A3A',
          warning: '#E8A317',
          info: '#2F80ED',
        },
      },
      dark: {
        dark: true,
        colors: {
          primary: '#6E8EFF',
          secondary: '#9AA3B5',
          accent: '#FFD43B',
          background: '#0E1320',
          surface: '#161D2E',
          success: '#3CCB7F',
          error: '#FF6B6B',
          warning: '#F5B942',
          info: '#5AA2FF',
        },
      },
    },
  },
  defaults: {
    VCard: { rounded: 'lg', elevation: 0, border: true },
    VBtn: { rounded: 'lg', style: 'text-transform: none; letter-spacing: normal' },
    VTextField: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VTextarea: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VSelect: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VAutocomplete: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VCombobox: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VFileInput: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VChip: { rounded: 'lg' },
    VDataTable: { hover: true },
  },
})

createApp(App).use(vuetify).use(router).mount('#app')
