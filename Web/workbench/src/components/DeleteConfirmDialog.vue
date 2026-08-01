<script setup>
import { AlertTriangle } from '@lucide/vue'

defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '确认删除' },
  message: { type: String, default: '确定要删除这条消息吗？此操作无法撤销。' },
  confirmLabel: { type: String, default: '删除' },
})

const emit = defineEmits(['confirm', 'cancel'])
</script>

<template>
  <div v-if="open" class="dialog-overlay" @click.self="emit('cancel')">
    <div class="dialog-box delete-confirm" role="dialog" aria-modal="true" aria-labelledby="delete-message-title">
      <div class="dialog-header">
        <AlertTriangle :size="20" class="warning-icon" />
        <h3 id="delete-message-title">{{ title }}</h3>
      </div>
      <p class="dialog-message">{{ message }}</p>
      <div class="dialog-actions">
        <button type="button" class="cancel-btn" @click="emit('cancel')">取消</button>
        <button type="button" class="danger-btn" @click="emit('confirm')">{{ confirmLabel }}</button>
      </div>
    </div>
  </div>
</template>
