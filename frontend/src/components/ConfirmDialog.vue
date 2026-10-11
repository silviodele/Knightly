<script setup lang="ts">
import { closeConfirm, confirmState } from '@/confirm'
</script>

<template>
  <v-dialog :model-value="confirmState.open" max-width="440" @update:model-value="(v: boolean) => !v && closeConfirm(false)">
    <v-card>
      <v-card-title class="pt-5 px-6">{{ confirmState.title }}</v-card-title>
      <v-card-text class="px-6 text-subtle">{{ confirmState.text }}</v-card-text>
      <v-card-actions class="px-6 pb-5">
        <v-spacer />
        <v-btn variant="text" @click="closeConfirm(false)">Annulla</v-btn>
        <v-btn :color="confirmState.color" variant="flat" @click="closeConfirm(true)">
          {{ confirmState.confirmText }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
