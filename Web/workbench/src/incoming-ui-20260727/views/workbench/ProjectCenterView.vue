<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  Activity, Camera, ClipboardList, FileText, Image, LayoutDashboard, ListTodo,
  MessageSquare, Mic, Send, Users, ChevronRight,
} from '@lucide/vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import { teamMembers } from '@/utils/demo-data'

const workspace = useWorkspaceStore()
const auth = useAuthStore()
const router = useRouter()
const { showToast } = useToast()

const canReadTeamReports = auth.hasPermission('report.read.team')
const canReadTeam = auth.hasPermission('team.read')

const visibleProjectMetrics = computed(() => {
  if (workspace.currentProject?.type === 'team' && !canReadTeam) {
    return (workspace.currentProject?.metrics ?? []).map((metric) => ({ ...metric, value: '--', tone: '' }))
  }
  return workspace.currentProject?.metrics ?? []
})

const visibleConversations = computed(() => {
  return (workspace.currentProject?.conversations ?? []).filter((item) => auth.hasPermission(item.permission))
})

const projectMessages = computed(() => {
  return workspace.projectCommandMessages[workspace.currentProjectId] ?? []
})
</script>

<template>
  <div class="center-scroll command-view">
    <div class="assistant-intro project-intro">
      <span class="ai-avatar"><LayoutDashboard :size="18" /></span>
      <div><strong>{{ workspace.currentProject?.name }} · 专属指挥中心</strong><p>{{ workspace.currentProject?.description }}。本中心只统筹当前 Project 内的对话、任务和资料。</p></div>
    </div>
    <div class="metric-grid">
      <div v-for="metric in visibleProjectMetrics" :key="metric.label" :class="metric.tone"><span>{{ metric.label }}</span><b>{{ metric.value }}</b><small>{{ workspace.currentProject?.type === 'team' && !canReadTeam ? '需要队伍管理权限' : '当前 Project' }}</small></div>
    </div>

    <div v-for="message in projectMessages" :key="message.id" class="message command-message" :class="message.role">
      <span v-if="message.role === 'assistant'" class="message-avatar" style="background:var(--purple);color:var(--purple-text)"><LayoutDashboard :size="16" /></span>
      <div class="bubble"><p>{{ message.text }}</p><small v-if="message.source"><Activity :size="11" />{{ message.source }}</small></div>
      <span v-if="message.role === 'user'" class="message-avatar user">{{ auth.currentAccount?.avatar }}</span>
    </div>

    <section v-if="workspace.currentProject?.type === 'report'" class="domain-section">
      <div class="content-heading"><span><ClipboardList :size="15" />{{ canReadTeamReports ? '汇报管理' : '我的本周汇报' }}</span><small>权限来自 {{ auth.currentAccount?.id }}</small></div>
      <template v-if="canReadTeamReports">
        <button v-for="member in teamMembers" :key="member.id" class="member-row" @click="router.push(`/project/project-report/chat/report-team-review`)">
          <span class="member-avatar">{{ member.name.slice(0, 1) }}</span><span><strong>{{ member.name }}</strong><small>{{ member.role }} · {{ member.activity }}</small></span><em :class="{ pending: member.report === '待提交' }">{{ member.report }}</em><ChevronRight :size="14" />
        </button>
      </template>
      <div v-else class="personal-report">
        <div><span>本周完成</span><strong>客户拜访 4 次，推进重点事项 3 项</strong></div>
        <div><span>下周计划</span><strong>完成续约方案并推进客户确认</strong></div>
        <div><span>需要协助</span><strong>绿城续约价格需要负责人拍板</strong></div>
        <button @click="router.push('/project/project-report/chat/report-current')">继续完善汇报</button>
      </div>
    </section>

    <section v-else-if="workspace.currentProject?.type === 'team'" class="domain-section">
      <div class="content-heading"><span><Users :size="15" />队伍状态</span><small>账号权限实时判定</small></div>
      <template v-if="canReadTeam">
        <div class="team-table-head"><span>成员</span><span>状态</span><span>工作负载</span><span>汇报</span></div>
        <div v-for="member in teamMembers" :key="member.id" class="team-table-row">
          <span><i class="status-dot" :class="member.status"></i><b>{{ member.name }}</b><small>{{ member.role }}</small></span><span>{{ member.status }}</span><span><i class="load-track"><b :style="{ width: `${member.load}%` }"></b></i>{{ member.load }}%</span><span :class="{ pending: member.report === '待提交' }">{{ member.report }}</span>
        </div>
      </template>
      <div v-else class="permission-empty"><span><Users :size="24" /></span><strong>当前账号没有队伍管理权限</strong><p>"我的队伍"Project 仍然保留。正式系统会根据账号 ID 返回可管理成员范围。</p></div>
    </section>

    <section v-else class="domain-section">
      <div class="content-heading"><span><ListTodo :size="15" />当前对话与任务</span><small>{{ visibleConversations.length }} 个对话</small></div>
      <button v-for="conversation in visibleConversations" :key="conversation.id" class="conversation-summary" @click="router.push(`/project/${workspace.currentProjectId}/chat/${conversation.id}`)">
        <MessageSquare :size="15" /><span><strong>{{ conversation.title }}</strong><small>{{ conversation.updated }} · 上下文和文件已同步</small></span>
        <span v-if="workspace.hasConversationHistory(conversation)" class="context-ring summary" :class="workspace.contextLevel(conversation)" :title="workspace.contextHint(conversation)">
          <svg viewBox="0 0 36 36"><circle class="context-track" cx="18" cy="18" r="14" pathLength="100" /><circle class="context-value" cx="18" cy="18" r="14" pathLength="100" :stroke-dasharray="`${workspace.getContextUsage(conversation)} 100`" /></svg><b>{{ workspace.getContextUsage(conversation) }}</b>
        </span>
        <em v-if="conversation.badge">{{ conversation.badge }}</em>
        <em v-if="workspace.hasConversationHistory(conversation) && workspace.getContextUsage(conversation) >= 75" class="context-warning" :class="workspace.contextLevel(conversation)">{{ workspace.getContextUsage(conversation) >= 90 ? '将满' : '偏高' }}</em>
        <ChevronRight :size="14" />
      </button>
    </section>
  </div>

  <footer class="composer">
    <div class="composer-attach">
      <button @click="showToast('文件上传接口已预留')"><FileText :size="14" /><span>文件</span></button>
      <button @click="showToast('图片上传接口已预留')"><Image :size="14" /><span>图片</span></button>
      <button @click="showToast('拍照接口已预留')"><Camera :size="14" /><span>拍照</span></button>
      <button @click="showToast('语音输入接口已预留')"><Mic :size="14" /><span>语音</span></button>
    </div>
    <div class="composer-input">
      <textarea v-model="workspace.projectCommandInput" rows="2" placeholder="在本 Project 内下发调度指令，Enter 发送，Shift+Enter 换行..." @keydown.enter.exact.prevent="workspace.sendProjectCommand()"></textarea>
      <button class="send-button" title="发送指令" :disabled="!workspace.projectCommandInput.trim()" @click="workspace.sendProjectCommand()"><Send :size="17" /></button>
    </div>
  </footer>
</template>
