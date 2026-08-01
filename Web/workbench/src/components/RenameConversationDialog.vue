<script setup>
import { Edit3 } from '@lucide/vue'

defineProps({
  open: { type: Boolean, default: false },
  value: { type: String, default: '' },
})

const emit = defineEmits(['update:value', 'confirm', 'cancel'])
</script>

<template>
  <div v-if="open" class="dialog-overlay" @click.self="emit('cancel')">
    <form class="dialog-box rename-dialog" role="dialog" aria-modal="true" aria-labelledby="rename-conversation-title" @submit.prevent="emit('confirm')">
      <div class="dialog-header">
        <Edit3 :size="20" class="warning-icon" />
        <h3 id="rename-conversation-title">重命名会话</h3>
      </div>
      <p class="dialog-message">更新会话名称后，历史消息和关联资料不会受到影响。</p>
      <label class="form-group">
        <span>会话名称</span>
        <input :value="value" autofocus maxlength="80" @input="emit('update:value', $event.target.value)" />
      </label>
      <div class="dialog-actions">
        <button type="button" class="cancel-btn" @click="emit('cancel')">取消</button>
        <button type="submit" class="primary-btn" :disabled="!value.trim()">保存名称</button>
      </div>
    </form>
  </div>
</template>
