<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ChevronRight, CircleAlert, FolderKanban, LayoutDashboard, MessageSquare, MoreHorizontal, Pencil, Plus, Settings2, Command } from '@lucide/vue'

const props = defineProps({
  notifications: { type: Array, default: () => [] },
  projects: { type: Array, default: () => [] },
  currentProjectId: { type: String, default: null },
  currentConversationId: { type: String, default: null },
  accountCenterActive: { type: Boolean, default: false },
  getContextUsage: { type: Function, required: true },
  hasConversationHistory: { type: Function, required: true },
  contextLevel: { type: Function, required: true },
  contextHint: { type: Function, required: true },
  hasPermission: { type: Function, required: true },
  projectIcon: { type: Function, required: true },
  isProjectPinned: { type: Function, required: true },
  isConversationPinned: { type: Function, required: true },
  getSortedConversations: { type: Function, required: true },
})

const emit = defineEmits([
  'selectProject', 'selectConversation', 'selectAccountCenter',
  'openProjectDialog', 'openNotification',
  'pinConversation', 'renameConversation', 'deleteConversation',
  'pinProject', 'renameProject', 'deleteProject',
  'quickCreateConversation',
])

const expandedProjectId = ref(null)
const manageMode = ref(false)
const contextMenuConvId = ref(null)
const contextMenuProjId = ref(null)
const renamingConvId = ref(null)
const renamingProjId = ref(null)
const renameText = ref('')

function closeContextMenus() {
  contextMenuConvId.value = null
  contextMenuProjId.value = null
}

onMounted(() => {
  document.addEventListener('click', closeContextMenus)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeContextMenus)
})

const visibleConversations = (project) => {
  return (project.conversations || []).filter((item) => props.hasPermission(item.permission))
}

function toggleProject(projectId) {
  if (manageMode.value) return
  if (expandedProjectId.value === projectId) {
    expandedProjectId.value = null
  } else {
    expandedProjectId.value = projectId
  }
  emit('selectProject', projectId)
}

function toggleManage() {
  manageMode.value = !manageMode.value
  contextMenuProjId.value = null
  renamingProjId.value = null
}

/* Conversation ops */
function pinConversation(projectId, convId)   { contextMenuConvId.value = null; emit('pinConversation', projectId, convId) }
function startConvRename(convId, currentTitle) { contextMenuConvId.value = null; renamingConvId.value = convId; renameText.value = currentTitle }
function confirmConvRename(projectId, convId)  { emit('renameConversation', projectId, convId, renameText.value); renamingConvId.value = null }
function cancelConvRename()                    { renamingConvId.value = null }
function deleteConversation(projectId, convId) { contextMenuConvId.value = null; emit('deleteConversation', projectId, convId) }

/* Project ops */
function pinProject(projectId)    { contextMenuProjId.value = null; emit('pinProject', projectId) }
function startProjRename(projId, currentName) { contextMenuProjId.value = null; renamingProjId.value = projId; renameText.value = currentName }
function confirmProjRename(projId) { emit('renameProject', projId, renameText.value); renamingProjId.value = null }
function cancelProjRename()        { renamingProjId.value = null }
function deleteProject(projectId)  { contextMenuProjId.value = null; emit('deleteProject', projectId) }
function formatConversationTime(timestamp) {
  if (!timestamp) return ''
  const current = new Date()
  const date = new Date(timestamp)
  if (current.toDateString() === date.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }

  const yesterday = new Date(current)
  yesterday.setDate(current.getDate() - 1)
  if (yesterday.toDateString() === date.toDateString()) return '昨天'

  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}
</script>

<template>
  <aside class="left-column">
    <section class="notice-panel">
      <div class="section-title"><span><CircleAlert :size="14" />消息与通知</span><b>{{ notifications.length }}</b></div>
      <button v-for="item in notifications" :key="item.id" class="notice-row" @click="$emit('openNotification', item)">
        <i :class="item.tone"></i>
        <span><strong>{{ item.title }}</strong><small>{{ item.meta }}</small></span>
        <ChevronRight :size="12" />
      </button>
    </section>

    <section class="projects-panel">
      <div class="section-title projects-title">
        <span>PROJECTS</span>
        <div class="projects-title-actions">
          <button :class="{ active: manageMode }" title="管理 Project" @click="toggleManage"><Settings2 :size="22" /></button>
          <button title="新建 Project" @click="$emit('openProjectDialog')"><Plus :size="22" /></button>
        </div>
      </div>
      <div v-for="project in projects" :key="project.id" class="project-node" :class="{ open: expandedProjectId === project.id && !manageMode }">
        <button class="project-row" :class="{ pinned: !project.fixed && isProjectPinned(project.id) }" @click="toggleProject(project.id)">
          <component :is="projectIcon(project.type)" :size="15" />
          <span v-if="renamingProjId === project.id">
            <input class="rename-input" v-model="renameText" @keydown.enter.stop="confirmProjRename(project.id)" @keydown.escape.stop="cancelProjRename" @click.stop autofocus />
          </span>
          <span v-else><strong>{{ project.name }}</strong><small>{{ project.description }}</small></span>
          <em v-if="project.fixed">固定</em>
          <span v-if="manageMode && !project.fixed" class="proj-more" @click.stop="contextMenuProjId = contextMenuProjId === project.id ? null : project.id"><MoreHorizontal :size="13" /></span>
          <div v-if="manageMode && contextMenuProjId === project.id" class="conv-menu" @click.stop>
            <button @click="pinProject(project.id)">{{ isProjectPinned(project.id) ? '取消置顶' : '置顶' }}</button>
            <button @click="startProjRename(project.id, project.name)">重命名</button>
            <button class="danger" @click="deleteProject(project.id)">删除</button>
          </div>
          <ChevronRight v-if="!manageMode" :size="13" class="arrow" />
        </button>
        <div v-if="expandedProjectId === project.id && !manageMode" class="project-children">
          <button :class="{ active: currentProjectId === project.id && !accountCenterActive && !currentConversationId }" @click="$emit('selectProject', project.id)">
            <LayoutDashboard :size="13" /><span>Project 专属指挥中心</span>
          </button>
          <div class="child-label">对话列表</div>
          <button v-for="conversation in getSortedConversations(project)" :key="conversation.id" :class="{ active: currentConversationId === conversation.id, pinned: isConversationPinned(project.id, conversation.id) }" @click="$emit('selectConversation', project.id, conversation.id)">
            <MessageSquare :size="12" />
            <span v-if="renamingConvId === conversation.id">
              <input class="rename-input" v-model="renameText" @keydown.enter.stop="confirmConvRename(project.id, conversation.id)" @keydown.escape.stop="cancelConvRename" @click.stop autofocus />
            </span>
            <span v-else class="conversation-title">{{ conversation.title }}</span>
            <span class="conversation-meta">
              <time :datetime="new Date(conversation.lastActivityAt || 0).toISOString()">{{ formatConversationTime(conversation.lastActivityAt) }}</time>
              <i v-if="conversation.unread" class="unread-dot" aria-label="有未读 AI 回复" title="有未读 AI 回复"></i>
            </span>
            <em v-if="conversation.badge">{{ conversation.badge }}</em>
            <span class="conv-more" @click.stop="contextMenuConvId = contextMenuConvId === conversation.id ? null : conversation.id"><MoreHorizontal :size="12" /></span>
            <div v-if="contextMenuConvId === conversation.id" class="conv-menu" @click.stop>
              <button @click="pinConversation(project.id, conversation.id)">{{ isConversationPinned(project.id, conversation.id) ? '取消置顶' : '置顶' }}</button>
              <button @click="startConvRename(conversation.id, conversation.title)">重命名</button>
              <button class="danger" @click="deleteConversation(project.id, conversation.id)">删除</button>
            </div>
          </button>
          <button class="new-conversation" @click="$emit('quickCreateConversation', project.id)"><Plus :size="12" />新建对话</button>
        </div>
      </div>
    </section>

    <section class="account-center-entry">
      <button :class="{ active: accountCenterActive }" @click="$emit('selectAccountCenter')">
        <Command :size="16" />
        <span><strong>综合指挥中心</strong><small>统管账号下全部 Projects</small></span>
        <ChevronRight :size="13" />
      </button>
    </section>
  </aside>
</template>
