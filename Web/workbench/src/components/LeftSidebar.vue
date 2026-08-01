<script setup>
import { ref } from 'vue'
import { Bell, CheckCircle2, ChevronRight, CircleAlert, CircleDotDashed, Clock3, Command, Edit3, FolderKanban, LayoutDashboard, MessageSquare, MoreHorizontal, Pin, Plus, Search, Trash2, X } from '@lucide/vue'

defineProps({
  notifications: { type: Array, default: () => [] }, notificationUnreadCount: { type: Number, default: 0 },
  notificationIsUnread: { type: Function, required: true }, notificationKind: { type: Function, required: true },
  projectSearch: { type: String, default: '' }, projects: { type: Array, default: () => [] },
  expandedProjectIds: { type: Object, required: true }, accountCenterActive: { type: Boolean, default: false },
  isProjectCenter: { type: Boolean, default: false }, currentConversationId: { type: String, default: null },
  conversationMenuId: { type: String, default: null }, getConversationGroups: { type: Function, required: true },
  projectIcon: { type: Function, required: true }, conversationUnread: { type: Function, required: true },
  conversationStatusKind: { type: Function, required: true }, conversationStatusLabel: { type: Function, required: true },
})

const emit = defineEmits([
  'update:projectSearch', 'open-notification', 'open-project-dialog', 'toggle-project', 'select-project',
  'select-conversation', 'toggle-conversation-menu', 'pin-conversation', 'toggle-conversation-unread',
  'rename-conversation', 'delete-conversation', 'create-conversation', 'select-account-center',
  'rename-project', 'delete-project', 'pin-project',
])

const projectManagementOpen = ref(false)
</script>

<template>
  <aside class="left-column">
    <section class="notice-panel">
      <div class="section-title"><span><Bell :size="14" />提醒</span><b>{{ notificationUnreadCount }}</b></div>
      <button v-for="item in notifications" :key="item.id" class="notice-row" @click="emit('open-notification', item)"><i :class="[item.tone, { unread: notificationIsUnread(item) }]" /><span><strong>{{ item.title }}</strong><small>{{ notificationKind(item) }} · {{ item.meta }}</small></span><em class="notice-kind">{{ notificationKind(item) }}</em><ChevronRight :size="12" /></button>
    </section>
    <section class="projects-panel">
      <div class="section-title projects-title"><span>我的 PROJECT</span><div class="projects-title-actions"><button :class="{ active: projectManagementOpen }" :title="projectManagementOpen ? '收起项目管理' : '管理 Project'" @click="projectManagementOpen = !projectManagementOpen"><MoreHorizontal :size="14" /></button><button title="新建 Project" @click="emit('open-project-dialog')"><Plus :size="14" /></button></div></div>
      <label class="rail-project-search"><Search :size="13" /><input :value="projectSearch" placeholder="搜 Project / 对话名……" @input="emit('update:projectSearch', $event.target.value)" /></label>
      <div v-for="project in projects" :key="project.id" class="project-node" :class="{ open: expandedProjectIds.has(project.id) && !accountCenterActive, fixed: project.fixed }">
        <div class="project-row-wrap"><button class="project-row" :class="{ pinned: project.pinned || project.fixed }" @click="emit('toggle-project', project.id)"><component :is="projectIcon(project.type)" :size="15" /><span><strong>{{ project.name }}</strong><small>{{ project.description }}</small></span><em v-if="project.fixed">固定</em><ChevronRight :size="13" class="arrow" /></button><div v-if="projectManagementOpen && !project.fixed" class="project-row-actions"><button :title="project.pinned ? '取消置顶' : '置顶 Project'" @click.stop="emit('pin-project', project)"><Pin :size="13" /></button><button title="重命名 Project" @click.stop="emit('rename-project', project)"><Edit3 :size="13" /></button><button title="删除 Project" class="danger" @click.stop="emit('delete-project', project)"><Trash2 :size="13" /></button></div></div>
        <div v-if="expandedProjectIds.has(project.id) && !accountCenterActive" class="project-children">
          <button :class="{ active: isProjectCenter }" @click="emit('select-project', project.id)"><LayoutDashboard :size="13" /><span>Project 专属指挥中心</span></button>
          <div class="child-label">对话列表</div>
          <template v-for="group in getConversationGroups(project)" :key="group.label">
            <div class="conversation-time-group">{{ group.label }}</div>
            <div v-for="conversation in group.conversations" :key="conversation.id" class="conversation-list-item" :class="{ unread: conversationUnread(conversation), pinned: conversation.pinned }">
              <button class="conversation-nav-row" :class="{ active: currentConversationId === conversation.id }" @click="emit('select-conversation', project.id, conversation.id)"><MessageSquare :size="12" /><span>{{ conversation.title }}</span><i v-if="conversationUnread(conversation)" class="unread-dot" /><span class="conversation-status-icon" :class="conversationStatusKind(conversation)" :title="conversationStatusLabel(conversation)"><CheckCircle2 v-if="conversationStatusKind(conversation) === 'done'" :size="12" /><Clock3 v-else-if="conversationStatusKind(conversation) === 'pending'" :size="12" /><CircleAlert v-else :size="12" /></span></button>
              <div class="conversation-more"><button class="conversation-more-trigger" title="更多操作" @click.stop="emit('toggle-conversation-menu', conversation.id)"><MoreHorizontal :size="14" /></button><div v-if="conversationMenuId === conversation.id" class="conversation-more-menu" @click.stop><button @click="emit('pin-conversation', conversation)"><Pin :size="13" />{{ conversation.pinned ? '取消置顶' : '置顶会话' }}</button><button @click="emit('toggle-conversation-unread', conversation)"><CircleDotDashed :size="13" />{{ conversationUnread(conversation) ? '标记已读' : '标记未读' }}</button><button @click="emit('rename-conversation', conversation)"><MoreHorizontal :size="13" />重命名</button><button class="danger" @click="emit('delete-conversation', conversation)"><X :size="13" />删除会话</button></div></div>
            </div>
          </template>
          <button class="new-conversation" @click="emit('create-conversation', project.id)"><Plus :size="12" />新建对话</button>
        </div>
      </div>
      <div v-if="!projects.length" class="project-empty-state"><FolderKanban :size="18" /><span>未找到匹配的 Project</span></div>
    </section>
    <section class="account-center-entry"><button :class="{ active: accountCenterActive }" @click="emit('select-account-center')"><Command :size="16" /><span><strong>综合指挥中心</strong><small>统管账号下全部 Projects</small></span><ChevronRight :size="13" /></button></section>
  </aside>
</template>
