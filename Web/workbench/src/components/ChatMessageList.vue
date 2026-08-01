<script setup>
import { Activity, Bot, CheckCircle2, Copy, Edit3, Forward, Sparkles, Star, Trash2 } from '@lucide/vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'

const props = defineProps({ messages: { type: Array, default: () => [] }, currentAvatar: { type: String, default: '' }, latestUserMessageId: { type: String, default: null }, latestAssistantMessageId: { type: String, default: null }, editingMessageId: { type: String, default: null }, messageActionMenuId: { type: String, default: null }, streamRef: { type: Object, default: null } })
const emit = defineEmits(['edit', 'copy', 'forward', 'toggle-menu', 'favorite', 'delete', 'open-adjustment', 'cancel-adjustment', 'submit-adjustment', 'confirm-intent'])

const streamEl = ref(null)
const scrollKey = computed(() => {
  const messages = props.messages || []
  const last = messages[messages.length - 1] || {}
  return [
    messages.length,
    last.id || '',
    last.text?.length || 0,
    last.task?.status || '',
    last.task?.items?.length || 0,
    last.resultLines?.length || 0,
    last.userResult?.findings?.length || 0,
  ].join('|')
})

function setStreamRef(el) {
  streamEl.value = el
  if (props.streamRef && typeof props.streamRef === 'object' && 'value' in props.streamRef) {
    props.streamRef.value = el
  }
}

async function scrollToBottom() {
  await nextTick()
  const apply = () => {
    const stream = streamEl.value
    if (!stream) return
    stream.scrollTop = stream.scrollHeight
    stream.querySelector('.message:last-child')?.scrollIntoView({ block: 'end' })
  }
  apply()
  window.requestAnimationFrame(() => {
    apply()
    window.requestAnimationFrame(apply)
  })
}

onMounted(scrollToBottom)
watch(scrollKey, scrollToBottom, { flush: 'post', immediate: true })

function formatEvidenceItem(item) {
  if (item == null || item === '') return ''
  if (typeof item === 'string') return item
  if (typeof item !== 'object') return String(item)
  const source = item.source && typeof item.source === 'object' ? item.source : {}
  const fileName = item.file_name || item.original_name || source.file_name
  const sheet = item.sheet || source.sheet
  const row = item.row || source.row
  const field = item.field_name || item.field
  const value = item.value
  const parts = []
  if (fileName) parts.push(String(fileName))
  if (sheet) parts.push(String(sheet))
  if (row) parts.push(`第 ${row} 行`)
  if (field) parts.push(`${field}${value != null && value !== '' ? `: ${value}` : ''}`)
  if (parts.length) return parts.join(' ')
  return [item.module, item.capability || item.platform_capability || item.upstream_key, item.state || item.status || item.status_code].filter(Boolean).join(' / ')
}

function formatEvidence(evidence) {
  if (!Array.isArray(evidence)) return ''
  return evidence.map(formatEvidenceItem).filter(Boolean).join('；')
}

function shouldShowExecutionDetails(message) {
  return message.userResult?.display_mode !== 'chat_answer' && Array.isArray(message.userResult?.findings) && message.userResult.findings.length > 0
}
</script>

<template>
  <div :ref="setStreamRef" class="center-scroll chat-stream">
    <div v-for="message in messages" :key="message.id" class="message" :class="[message.role, { favorited: message.favorite, editing: editingMessageId === message.id }]">
      <span v-if="message.role === 'assistant'" class="message-avatar"><Bot :size="17" /></span>
      <div class="bubble" :class="{ receipt: message.receipt }">
        <div v-if="message.favorite" class="favorite-badge"><Star :size="12" :fill="'currentColor'" />已收藏</div><p>{{ message.text }}</p>
        <div v-if="shouldShowExecutionDetails(message)" class="execution-result"><article v-for="finding in message.userResult.findings" :key="finding.finding_id || finding.title"><strong>{{ finding.title }}</strong><p v-if="finding.detail">{{ finding.detail }}</p><p v-if="finding.evidence?.length"><span>依据：</span>{{ formatEvidence(finding.evidence) }}</p><p v-if="finding.impact"><span>影响：</span>{{ finding.impact }}</p><p v-if="finding.recommendation"><span>建议：</span>{{ finding.recommendation }}</p></article><p v-if="message.userResult.next_action?.prompt" class="execution-next-action">{{ message.userResult.next_action.prompt }}</p></div>
        <ul v-else-if="message.resultLines?.length" class="execution-result"><li v-for="line in message.resultLines" :key="line"><CheckCircle2 :size="13" />{{ line }}</li></ul>
        <div v-if="message.task" class="intent-card"><div><span><Sparkles :size="14" />{{ message.task.title }}</span><em>{{ message.task.label || '意图确认' }}</em></div><ul><li v-for="item in message.task.items" :key="item"><CheckCircle2 :size="13" />{{ item }}</li></ul><div v-if="message.task.adjustmentOpen" class="intent-adjustment"><textarea v-model="message.task.adjustmentText" rows="3" placeholder="描述需要重新识别的目标与范围" /><div><button :disabled="message.task.status !== 'pending'" @click="emit('cancel-adjustment', message)">取消</button><button class="primary" :disabled="message.task.status !== 'pending' || !message.task.adjustmentText.trim()" @click="emit('submit-adjustment', message)">重新识别</button></div></div><div class="intent-actions"><button :disabled="message.task.status !== 'pending'" @click="emit('open-adjustment', message)">调整意图</button><button class="primary" :disabled="message.task.status !== 'pending'" @click="emit('confirm-intent', message)">{{ message.task.status === 'running' ? '执行中...' : message.task.status === 'confirmed' ? '已确认' : '确认并执行' }}</button></div></div>
        <small v-if="message.source"><Activity :size="11" />{{ message.source }}</small>      </div>
      <div v-if="message.role === 'assistant'" class="message-actions assistant-message-actions" :class="{ latest: message.id === latestAssistantMessageId }" @click.stop>
        <button class="action-btn" title="复制" @click="emit('copy', message)"><Copy :size="14" /></button>
      </div>
      <div v-if="message.role === 'user'" class="message-actions" @click.stop>
        <button class="action-btn" title="编辑" @click="emit('edit', message)"><Edit3 :size="14" /></button>
        <button class="action-btn" title="复制" @click="emit('copy', message)"><Copy :size="14" /></button>
        <button class="action-btn" title="转发" @click="emit('forward', message)"><Forward :size="14" /></button>
        <button class="action-btn danger" title="删除" @click="emit('delete', message)"><Trash2 :size="14" /></button>
      </div>
      <span v-if="message.role === 'user'" class="message-avatar user">{{ currentAvatar }}</span>
    </div>
  </div>
</template>
