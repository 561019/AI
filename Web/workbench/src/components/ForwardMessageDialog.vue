<script setup>
import { computed, ref, watch } from 'vue'
import { Send } from '@lucide/vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  projects: { type: Array, default: () => [] },
  currentProjectId: { type: String, default: '' },
  currentConversationId: { type: String, default: '' },
})

const emit = defineEmits(['forward', 'cancel'])
const selectedProjectId = ref('')
const selectedConversationId = ref('')

const conversations = computed(() => {
  return props.projects.find((project) => project.id === selectedProjectId.value)?.conversations ?? []
})

const canForward = computed(() => Boolean(
  selectedProjectId.value
  && selectedConversationId.value
  && !(selectedProjectId.value === props.currentProjectId
    && selectedConversationId.value === props.currentConversationId),
))

watch(() => props.open, (open) => {
  if (open) {
    selectedProjectId.value = props.currentProjectId
    selectedConversationId.value = ''
  }
})

watch(selectedProjectId, () => {
  selectedConversationId.value = ''
})

function submit() {
  if (canForward.value) {
    emit('forward', {
      targetProjectId: selectedProjectId.value,
      targetConversationId: selectedConversationId.value,
    })
  }
}
</script>

<template>
  <div v-if="open" class="dialog-overlay" @click.self="emit('cancel')">
    <form class="dialog-box forward-dialog" role="dialog" aria-modal="true" aria-labelledby="forward-message-title" @submit.prevent="submit">
      <div class="dialog-header">
        <Send :size="20" />
        <h3 id="forward-message-title">转发消息</h3>
      </div>
      <div class="forward-form">
        <label class="form-group">
          <span>选择 Project</span>
          <select v-model="selectedProjectId" class="form-select">
            <option value="">请选择 Project</option>
            <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
          </select>
        </label>
        <label class="form-group">
          <span>选择会话</span>
          <select v-model="selectedConversationId" class="form-select" :disabled="!selectedProjectId">
            <option value="">请选择会话</option>
            <option
              v-for="conversation in conversations"
              :key="conversation.id"
              :value="conversation.id"
              :disabled="selectedProjectId === currentProjectId && conversation.id === currentConversationId"
            >
              {{ conversation.title }}
            </option>
          </select>
        </label>
        <p v-if="selectedConversationId && !canForward" class="warning-text">不能转发到当前会话。</p>
      </div>
      <div class="dialog-actions">
        <button type="button" class="cancel-btn" @click="emit('cancel')">取消</button>
        <button type="submit" class="primary-btn" :disabled="!canForward">转发</button>
      </div>
    </form>
  </div>
</template>
