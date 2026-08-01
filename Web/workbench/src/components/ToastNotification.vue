<script setup>
import { CheckCircle2 } from '@lucide/vue'

defineProps({
  message: { type: String, default: '' },
})
</script>

<template>
  <transition name="toast">
    <div v-if="message" class="toast" role="status" aria-live="polite">
      <CheckCircle2 :size="16" />{{ message }}
    </div>
  </transition>
</template>
