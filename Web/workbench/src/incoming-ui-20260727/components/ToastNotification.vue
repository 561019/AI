<script setup>
import { CheckCircle2 } from '@lucide/vue'

defineProps({
  toast: { type: String, default: '' },
})
</script>

<template>
  <transition name="toast">
    <div v-if="toast" class="toast"><CheckCircle2 :size="16" />{{ toast }}</div>
  </transition>
</template>
