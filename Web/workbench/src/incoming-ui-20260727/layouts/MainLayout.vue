<script setup>
import { computed } from 'vue'
import { RouterView, useRouter } from 'vue-router'
import {
  Activity, Bell, Bot, Building2, Check, ChevronDown, ChevronRight,
  CircleAlert, CircleDotDashed, Command, Cpu, Database, FileOutput,
  FolderKanban, LayoutDashboard, LogOut, MessageSquare, MoreHorizontal,
  Plus, Puzzle, Search, Send, ShieldCheck, Sparkles, UserRound, Users, X,
  ClipboardList, ListTodo,
} from '@lucide/vue'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useKnowledgeStore } from '@/stores/knowledge'
import { notifications as notificationData } from '@/utils/demo-data'
import RightPanel from '@/components/RightPanel.vue'
import LeftSidebar from '@/components/LeftSidebar.vue'
import ProjectDialog from '@/components/ProjectDialog.vue'
import ConversationDialog from '@/components/ConversationDialog.vue'
import ToastNotification from '@/components/ToastNotification.vue'

const router = useRouter()
const { toast, showToast } = useToast()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const capabilities = useCapabilitiesStore()
const knowledge = useKnowledgeStore()

const contextLabel = computed(() => {
  if (knowledge.knowledgeManagement.active) return `知识库对话管理 · ${knowledge.knowledgeManagement.action === 'grant' ? knowledge.selectedGrantKnowledge?.governanceCode ?? '管理责任' : knowledge.managedKnowledgeBase?.name ?? '从当前对话新建'}`
  const label = capabilities.agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'
  if (capabilities.agentManagement.active && capabilities.agentManagement.action === 'create' && !capabilities.managedCapability) return `新建自创 ${label}`
  if (capabilities.agentManagement.active && capabilities.managedCapability) return `${label} 管理 · ${capabilities.managedCapability.name}`
  if (workspace.accountCenterActive) return '综合指挥中心'
  if (workspace.currentConversation) return `${workspace.currentProject?.name ?? ''} · ${workspace.currentConversation.title}`
  return `${workspace.currentProject?.name ?? ''} · Project 指挥中心`
})

const centerTitle = computed(() => {
  if (knowledge.knowledgeManagement.active) {
    return knowledge.knowledgeManagement.action === 'grant'
      ? `知识库治理 · ${knowledge.selectedGrantKnowledge?.governanceCode ?? '管理责任配权'}`
      : knowledge.knowledgeManagement.action === 'create'
        ? '从当前对话新建知识库'
        : `知识库${knowledge.knowledgeManagement.action === 'supplement' ? '补材料' : '维护'} · ${knowledge.managedKnowledgeBase?.name ?? ''}`
  }
  if (capabilities.agentManagement.active) {
    return capabilities.managedCapability
      ? `${capabilities.agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'} 管理 · ${capabilities.managedCapability.name}`
      : `新建自创 ${capabilities.agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'}`
  }
  if (workspace.accountCenterActive) return '综合指挥中心'
  if (workspace.currentConversation) return workspace.currentConversation.title
  return 'Project 专属指挥中心'
})

const centerEyebrow = computed(() => {
  if (knowledge.knowledgeManagement.active) return 'KNOWLEDGE MANAGEMENT CONVERSATION'
  if (capabilities.agentManagement.active) return 'AGENT MANAGEMENT CONVERSATION'
  if (workspace.accountCenterActive) return 'ACCOUNT COMMAND CENTER'
  return workspace.currentProject?.name ?? ''
})

const visibleNotifications = computed(() => {
  return (notificationData || []).filter((item) => auth.hasPermission(item.permission))
})

const sortedProjects = computed(() => {
  const fixed = workspace.workspaceProjects.filter(p => p.fixed)
  const pinned = workspace.workspaceProjects.filter(p => !p.fixed && workspace.isProjectPinned(p.id))
  const unpinned = workspace.workspaceProjects.filter(p => !p.fixed && !workspace.isProjectPinned(p.id))
  return [...fixed, ...pinned, ...unpinned]
})

function sortedConvList(project) {
  const convs = (project?.conversations ?? []).filter(c => auth.hasPermission(c.permission))
  const byLatestActivity = (a, b) => (b.lastActivityAt ?? 0) - (a.lastActivityAt ?? 0)
  const pinned = convs.filter(c => workspace.isConversationPinned(project.id, c.id)).sort(byLatestActivity)
  const unpinned = convs.filter(c => !workspace.isConversationPinned(project.id, c.id)).sort(byLatestActivity)
  return [...pinned, ...unpinned]
}

function openNotification(item) {
  workspace.selectConversation(item.projectId, item.conversationId)
  router.push(`/project/${item.projectId}/chat/${item.conversationId}`)
  showToast('已定位到对应 Project 和对话')
}

function projectIcon(type) {
  if (type === 'report') return ClipboardList
  if (type === 'team') return Users
  return FolderKanban
}

function onSelectProject(projectId) {
  workspace.selectProject(projectId)
  router.push(`/project/${projectId}`)
}

function onSelectConversation(projectId, conversationId) {
  workspace.selectConversation(projectId, conversationId)
  router.push(`/project/${projectId}/chat/${conversationId}`)
}

function onSelectAccountCenter() {
  workspace.selectAccountCenter()
  router.push('/account-center')
}

function onCloseManagement() {
  capabilities.closeAgentManagement()
  knowledge.closeKnowledgeManagement()
  if (workspace.currentConversation) {
    router.push(`/project/${workspace.currentProjectId}/chat/${workspace.currentConversationId}`)
  } else {
    router.push(`/project/${workspace.currentProjectId}`)
  }
}

function onQuickCreateConversation(projectId) {
  const project = workspace.workspaceProjects.find(p => p.id === projectId)
  if (!project) return
  const id = `conversation-${Date.now()}`
  const title = `新对话`
  project.conversations.unshift({
    id, title, updated: '刚刚', badge: '新对话', hasHistory: false, contextUsage: 0, lastActivityAt: Date.now(), unread: false,
    messages: [{ id: `${id}-welcome`, role: 'assistant', text: `已在"${project.name}"创建新对话。告诉我目标、范围和交付物即可开始。`, source: '新对话 · 尚未携带历史上下文' }],
    files: [],
  })
  workspace.selectConversation(projectId, id)
  router.push(`/project/${projectId}/chat/${id}`)
  showToast(`已创建对话：${title}`)
}

function onPinConversation(projectId, conversationId) {
  workspace.pinConversation(projectId, conversationId)
  showToast(workspace.isConversationPinned(projectId, conversationId) ? '已置顶该对话' : '已取消置顶')
}

function onRenameConversation(projectId, conversationId, newTitle) {
  const project = workspace.workspaceProjects.find(p => p.id === projectId)
  if (!project) return
  const conv = project.conversations.find(c => c.id === conversationId)
  if (conv && newTitle.trim()) {
    conv.title = newTitle.trim()
  }
  showToast('已重命名')
}

function onDeleteConversation(projectId, conversationId) {
  const project = workspace.workspaceProjects.find(p => p.id === projectId)
  if (!project) return
  const idx = project.conversations.findIndex(c => c.id === conversationId)
  if (idx === -1) return
  if (workspace.isConversationPinned(projectId, conversationId)) workspace.pinConversation(projectId, conversationId)
  if (workspace.currentConversationId === conversationId) {
    workspace.currentConversationId = null
    router.push(`/project/${projectId}`)
  }
  project.conversations.splice(idx, 1)
  showToast('已删除该对话')
}

function onPinProject(projectId) {
  workspace.pinProject(projectId)
  showToast(workspace.isProjectPinned(projectId) ? '已置顶该 Project' : '已取消置顶')
}

function onRenameProject(projectId, newName) {
  const project = workspace.workspaceProjects.find(p => p.id === projectId)
  if (project && newName.trim()) {
    project.name = newName.trim()
    project.short = newName.trim().length > 6 ? newName.trim().slice(0, 6) : newName.trim()
  }
  showToast('已重命名')
}

function onDeleteProject(projectId) {
  const idx = workspace.workspaceProjects.findIndex(p => p.id === projectId)
  if (idx === -1) return
  if (workspace.isProjectPinned(projectId)) workspace.pinProject(projectId)
  if (workspace.currentProjectId === projectId) {
    workspace.selectProject(workspace.workspaceProjects[0]?.id ?? null)
    router.push(`/project/${workspace.currentProjectId}`)
  }
  workspace.workspaceProjects.splice(idx, 1)
  showToast('已删除该 Project')
}

function logout() {
  auth.logout()
  localStorage.removeItem('auth_logged_in')
  router.push('/login')
}
</script>

<template>
  <div class="page-shell" @click.self="auth.accountMenuOpen = false">
    <div class="workbench">
      <header class="topbar">
        <div class="brand"><Sparkles :size="17" /><strong>AI 工作台</strong></div>
        <div class="context-pill"><Command :size="13" />{{ contextLabel }}</div>
        <button class="search-trigger" title="全局搜索" @click="showToast('全局搜索接口已预留')"><Search :size="14" /><span>搜索 Project、对话和文件</span><kbd>Ctrl K</kbd></button>
        <div class="top-spacer"></div>
        <button class="icon-button" title="消息通知" @click="showToast(`当前有 ${visibleNotifications.length} 条消息`)"><Bell :size="17" /><i></i></button>
        <div class="account-switch">
          <button class="account-trigger" @click.stop="auth.accountMenuOpen = !auth.accountMenuOpen">
            <span class="avatar">{{ auth.currentAccount.avatar }}</span>
            <span><strong>{{ auth.currentAccount.name }}</strong><small>{{ auth.currentAccount.role }}</small></span>
            <ChevronDown :size="14" />
          </button>
          <div v-if="auth.accountMenuOpen" class="account-menu">
            <div class="menu-note"><ShieldCheck :size="14" /><span>演示阶段切换账号 ID，正式系统由登录账号返回权限。</span></div>
            <button v-for="account in auth.accountRecords" :key="account.id" :class="{ active: account.id === auth.currentAccountId }" @click="auth.selectAccount(account.id); showToast(`已切换账号：${account.name}`)">
              <span class="avatar small">{{ account.avatar }}</span>
              <span><strong>{{ account.name }}</strong><small>{{ account.role }} · {{ account.id }}</small></span>
              <Check v-if="account.id === auth.currentAccountId" :size="15" />
            </button>
            <button class="account-logout" @click="logout"><LogOut :size="15" /><span><strong>退出当前账号</strong><small>返回登录页面</small></span></button>
          </div>
        </div>
      </header>

      <div class="columns">
        <LeftSidebar
          :notifications="visibleNotifications"
          :projects="sortedProjects"
          :current-project-id="workspace.currentProjectId"
          :current-conversation-id="workspace.currentConversationId"
          :account-center-active="workspace.accountCenterActive"
          :get-context-usage="workspace.getContextUsage"
          :has-conversation-history="workspace.hasConversationHistory"
          :context-level="workspace.contextLevel"
          :context-hint="workspace.contextHint"
          :has-permission="auth.hasPermission"
          :project-icon="projectIcon"
          :is-project-pinned="(id) => workspace.isProjectPinned(id)"
          :is-conversation-pinned="(pid, cid) => workspace.isConversationPinned(pid, cid)"
          :get-sorted-conversations="(project) => sortedConvList(project)"
          @select-project="onSelectProject"
          @select-conversation="onSelectConversation"
          @select-account-center="onSelectAccountCenter"
          @open-project-dialog="workspace.openProjectDialog"
          @open-notification="openNotification"
          @quick-create-conversation="onQuickCreateConversation"
          @pin-conversation="onPinConversation"
          @rename-conversation="onRenameConversation"
          @delete-conversation="onDeleteConversation"
          @pin-project="onPinProject"
          @rename-project="onRenameProject"
          @delete-project="onDeleteProject"
        />

        <main class="center-column">
          <header class="center-header">
            <div>
              <span class="eyebrow">{{ centerEyebrow }}</span>
              <h1>{{ centerTitle }}</h1>
            </div>
            <div class="header-actions">
              <span class="scope-chip"><ShieldCheck :size="13" />{{ auth.currentAccount.role }}权限</span>
              <button v-if="knowledge.knowledgeManagement.active || capabilities.agentManagement.active" class="icon-button plain" title="返回当前对话" @click="onCloseManagement"><X :size="16" /></button>
              <button class="icon-button plain" title="更多操作"><MoreHorizontal :size="17" /></button>
            </div>
          </header>

          <RouterView v-slot="{ Component: ViewComponent }">
            <component :is="ViewComponent" />
          </RouterView>
        </main>

        <RightPanel
          :right-tab="workspace.rightTab"
          :current-project="workspace.currentProject"
          :current-conversation="workspace.currentConversation"
          :account-center-active="workspace.accountCenterActive"
          :is-project-center="workspace.isProjectCenter"
          :project-flow-records="workspace.projectFlowRecords"
          :file-search="workspace.fileSearch"
          :uploaded-conversation-files="workspace.uploadedConversationFiles"
          :produced-conversation-files="workspace.producedConversationFiles"
          :project-files="workspace.projectFiles"
          :generated-files="workspace.generatedFiles"
          :right-tab-label="workspace.rightTabLabel"
          :agent-records="capabilities.agentRecords"
          :skill-records="capabilities.skillRecords"
          :selected-agent-id="capabilities.selectedAgentId"
          :selected-skill-id="capabilities.selectedSkillId"
          :disabled-resource-ids="capabilities.disabledResourceIds"
          :knowledge-scope="knowledge.knowledgeScope"
          :personal-knowledge="knowledge.personalKnowledge"
          :group-knowledge-records="knowledge.groupKnowledgeRecords"
          :selected-personal-knowledge-id="knowledge.selectedPersonalKnowledgeId"
          :knowledge-governance-audit="knowledge.knowledgeGovernanceAudit"
          :has-permission="auth.hasPermission"
          :current-account-id="auth.currentAccountId"
          @update:right-tab="tab => workspace.rightTab = tab"
          @update:file-search="val => workspace.fileSearch = val"
          @update:knowledge-scope="val => knowledge.knowledgeScope = val"
          @update:selected-personal-knowledge-id="val => knowledge.selectedPersonalKnowledgeId = val"
          @select-conversation="onSelectConversation"
          @select-project="onSelectProject"
          @open-agent-creation="type => { capabilities.openCapabilityCreation(type); router.push('/agent-management') }"
          @open-skill-creation="() => { capabilities.openCapabilityCreation('skill'); router.push('/agent-management') }"
          @open-agent-management="(item, action) => { capabilities.openCapabilityManagement(item, action, 'agent'); router.push('/agent-management') }"
          @open-skill-management="(item, action) => { capabilities.openCapabilityManagement(item, action, 'skill'); router.push('/agent-management') }"
          @select-skill="capabilities.selectSkill"
          @select-agent="capabilities.selectAgent"
          @operate-personal-knowledge="(action, item) => { knowledge.openKnowledgeManagement(action, item, 'personal', workspace.currentConversation?.title ?? ''); router.push('/knowledge-management') }"
          @operate-group-knowledge="(action, item) => { knowledge.openKnowledgeManagement(action, item, 'group', workspace.currentConversation?.title ?? ''); router.push('/knowledge-management') }"
          @create-knowledge-from-conversation="() => { knowledge.createKnowledgeFromConversation(workspace.currentConversation?.title); router.push('/knowledge-management') }"
          @open-knowledge-grant-dialog="() => knowledge.openKnowledgeGrantDialog(true)"
        />
      </div>
    </div>

    <ProjectDialog
      :open="workspace.projectDialogOpen"
      :name="workspace.newProjectName"
      @update:name="val => workspace.newProjectName = val"
      @close="workspace.projectDialogOpen = false"
      @confirm="() => { const name = workspace.createProject(); if (name) { router.push(`/project/${workspace.currentProjectId}`); showToast(`已创建 Project：${name}`) } }"
    />

    <ConversationDialog
      :open="workspace.conversationDialogOpen"
      :project-name="workspace.currentProject?.name ?? ''"
      :title="workspace.newConversationTitle"
      @update:title="val => workspace.newConversationTitle = val"
      @close="workspace.conversationDialogOpen = false"
      @confirm="() => { const title = workspace.createConversation(); if (title) { router.push(`/project/${workspace.currentProjectId}/chat/${workspace.currentConversationId}`); showToast(`已创建对话：${title}`) } }"
    />

    <ToastNotification :toast="toast" />
  </div>
</template>
