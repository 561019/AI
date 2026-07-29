<script setup>
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import {
  Activity, Bot, Camera, CheckCircle2, CircleAlert, FileText,
  Image, Mic, Send, ShieldCheck, Sparkles,
} from '@lucide/vue'

const workspace = useWorkspaceStore()
const auth = useAuthStore()
const { showToast } = useToast()

defineProps({
  projectId: { type: String, required: true },
  conversationId: { type: String, required: true },
})
</script>

<template>
  <div class="center-scroll chat-stream">
    <div v-for="message in workspace.currentMessages" :key="message.id" class="message" :class="message.role">
      <span v-if="message.role === 'assistant'" class="message-avatar"><Bot :size="17" /></span>
      <div class="bubble" :class="{ receipt: message.receipt }">
        <p>{{ message.text }}</p>
        <div v-if="message.task" class="intent-card">
          <div><span><Sparkles :size="14" />{{ message.task.title }}</span><em>意图确认</em></div>
          <ul><li v-for="item in message.task.items" :key="item"><CheckCircle2 :size="13" />{{ item }}</li></ul>
          <div class="intent-actions"><button @click="showToast('调整范围入口已预留')">调整范围</button><button class="primary" @click="workspace.confirmIntent(); showToast('任务已确认并开始执行')">确认并执行</button></div>
        </div>
        <small v-if="message.source"><Activity :size="11" />{{ message.source }}</small>
      </div>
      <span v-if="message.role === 'user'" class="message-avatar user">{{ auth.currentAccount?.avatar }}</span>
    </div>
  </div>

  <footer class="composer">
    <div v-if="workspace.currentConversation && workspace.currentContextUsage >= 75" class="context-alert" :class="workspace.contextLevel(workspace.currentConversation)">
      <CircleAlert :size="14" /><span><strong>上下文已占 {{ workspace.currentContextUsage }}%</strong><small>{{ workspace.currentContextUsage >= 90 ? '即将触达存储上限，请立即沉淀并续接对话。' : '接近存储上限，建议沉淀当前要点后新建续接对话。' }}</small></span>
      <button @click="workspace.startFreshConversationFromContext(); showToast('已沉淀上下文并创建续接对话')">沉淀并续接</button>
    </div>

    <div class="composer-attach">
      <button @click="showToast('文件上传接口已预留')"><FileText :size="14" /><span>文件</span></button>
      <button @click="showToast('图片上传接口已预留')"><Image :size="14" /><span>图片</span></button>
      <button @click="showToast('拍照接口已预留')"><Camera :size="14" /><span>拍照</span></button>
      <button @click="showToast('语音输入接口已预留')"><Mic :size="14" /><span>语音</span></button>
    </div>

    <div class="composer-input">
      <textarea v-model="workspace.inputText" rows="2" placeholder="向 AI 提出需求，Enter 发送，Shift+Enter 换行..." @keydown.enter.exact.prevent="workspace.sendMessage()"></textarea>
      <span v-if="workspace.currentConversation" class="context-indicator" :class="workspace.contextLevel(workspace.currentConversation)">{{ workspace.currentContextUsage }}%</span>
      <button class="send-button" title="发送" :disabled="!workspace.inputText.trim()" @click="workspace.sendMessage()"><Send :size="17" /></button>
    </div>
  </footer>
</template>

