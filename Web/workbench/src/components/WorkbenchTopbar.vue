<script setup>
import { Bell, Check, ChevronDown, Command, LogOut, Search, ShieldCheck, Sparkles } from '@lucide/vue'

defineProps({
  contextLabel: { type: String, default: '' },
  notificationUnreadCount: { type: Number, default: 0 },
  account: { type: Object, required: true },
  accounts: { type: Array, default: () => [] },
  currentAccountId: { type: String, default: null },
  accountMenuOpen: { type: Boolean, default: false },
})

const emit = defineEmits(['search', 'notifications', 'toggle-account-menu', 'select-account', 'logout'])
</script>

<template>
  <header class="topbar">
    <div class="brand"><Sparkles :size="17" /><strong>AI 工作台</strong></div>
    <div class="context-pill"><Command :size="13" />{{ contextLabel }}</div>
    <button class="search-trigger" title="全局搜索" @click="emit('search')"><Search :size="14" /><span>搜索 Project、对话和文件</span><kbd>Ctrl K</kbd></button>
    <div class="top-spacer" />
    <button class="icon-button" title="消息通知" @click="emit('notifications')"><Bell :size="17" /><i v-if="notificationUnreadCount" /></button>
    <div class="account-switch">
      <button class="account-trigger" @click.stop="emit('toggle-account-menu')"><span class="avatar">{{ account.avatar }}</span><span><strong>{{ account.name }}</strong><small>{{ account.role }}</small></span><ChevronDown :size="14" /></button>
      <div v-if="accountMenuOpen" class="account-menu">
        <div class="menu-note"><ShieldCheck :size="14" /><span>权限由登录账号返回。</span></div>
        <button v-for="item in accounts" :key="item.id" :class="{ active: item.id === currentAccountId }" @click="emit('select-account', item.id)"><span class="avatar small">{{ item.avatar }}</span><span><strong>{{ item.name }}</strong><small>{{ item.role }} · {{ item.id }}</small></span><Check v-if="item.id === currentAccountId" :size="15" /></button>
        <button class="account-logout" @click="emit('logout')"><LogOut :size="15" /><span><strong>退出当前账号</strong><small>返回登录页面</small></span></button>
      </div>
    </div>
  </header>
</template>
