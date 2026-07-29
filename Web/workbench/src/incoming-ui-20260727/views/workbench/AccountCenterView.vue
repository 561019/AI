<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  Activity, Camera, ChevronRight, ClipboardList, Command, FileText,
  FolderKanban, Image, Mic, Send, ShieldCheck, Users,
} from '@lucide/vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'

const workspace = useWorkspaceStore()
const auth = useAuthStore()
const router = useRouter()
const { showToast } = useToast()

const canReadTeamReports = computed(() => auth.hasPermission('report.read.team'))

function projectIcon(type) {
  if (type === 'report') return ClipboardList
  if (type === 'team') return Users
  return FolderKanban
}

function goToProject(projectId) {
  workspace.selectProject(projectId)
  router.push(`/project/${projectId}`)
}
</script>

<template>
  <div class="center-scroll command-chat-stream">
    <div class="assistant-intro command-intro">
      <span class="ai-avatar"><Command :size="18" /></span>
      <div><strong>{{ auth.currentAccount?.name }}的综合指挥中心</strong><p>用自然语言下发账号级指令；系统在当前权限范围内统筹 Project、待办与风险，并全程留痕。</p></div>
    </div>
    <div class="metric-grid account-metrics command-metrics">
      <div><span>全部 Projects</span><b>{{ workspace.workspaceProjects.length }}</b><small>{{ workspace.workspaceProjects.filter(p => p.fixed).length }} 个固定 · {{ workspace.workspaceProjects.filter(p => !p.fixed).length }} 个自建</small></div>
      <div><span>进行中任务</span><b>9</b><small>跨 Project 汇总</small></div>
      <div class="warning"><span>待我处理</span><b>{{ canReadTeamReports ? 4 : 2 }}</b><small>确认与待办</small></div>
      <div class="danger"><span>风险预警</span><b>2</b><small>来自风险监控</small></div>
    </div>
    <div v-for="message in workspace.commandMessages" :key="message.id" class="message command-message" :class="message.role">
      <span v-if="message.role === 'assistant'" class="message-avatar"><Command :size="16" /></span>
      <div class="bubble"><p>{{ message.text }}</p><button v-if="message.action" class="command-action" @click="goToProject(message.action.projectId)"><FolderKanban :size="13" />{{ message.action.label }}</button><small v-if="message.source"><Activity :size="11" />{{ message.source }}</small></div>
      <span v-if="message.role === 'user'" class="message-avatar user">{{ auth.currentAccount?.avatar }}</span>
    </div>
    <section class="overview-section command-overview"><div class="content-heading"><span><FolderKanban :size="15" />Project 运行概览</span><small>点击进入专属指挥中心</small></div><button v-for="project in workspace.workspaceProjects" :key="project.id" class="overview-project" @click="goToProject(project.id)"><component :is="projectIcon(project.type)" :size="17" /><span><strong>{{ project.name }}</strong><small>{{ project.description }}</small></span><em>{{ project.status }}</em><ChevronRight :size="14" /></button></section>
  </div>

  <footer class="composer command-composer">
    <div class="composer-attach">
      <button @click="showToast('文件上传接口已预留')"><FileText :size="14" /><span>文件</span></button>
      <button @click="showToast('图片上传接口已预留')"><Image :size="14" /><span>图片</span></button>
      <button @click="showToast('拍照接口已预留')"><Camera :size="14" /><span>拍照</span></button>
      <button @click="showToast('语音输入接口已预留')"><Mic :size="14" /><span>语音</span></button>
    </div>
    <div class="composer-input">
      <textarea v-model="workspace.commandInput" rows="2" placeholder="例如：汇总今天需要我处理的风险，并催办未提交的工作汇报" @keydown.enter.exact.prevent="workspace.sendCommandMessage()"></textarea>
      <button class="send-button" title="发送指令" :disabled="!workspace.commandInput.trim()" @click="workspace.sendCommandMessage()"><Send :size="17" /></button>
    </div>
  </footer>
</template>
