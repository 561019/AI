<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Building2, ChevronRight, CircleAlert, ClipboardList,
  KeyRound, LogIn, Plus, UserRound,
} from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const authState = reactive({
  mode: 'login',
  loginId: 'account-leader-001',
  password: '123456',
  name: '',
  department: '',
  role: '业务员',
  confirmPassword: '',
  error: '',
})

function switchAuthMode(mode) {
  authState.mode = mode
  authState.error = ''
}



function submitLogin() {
  const identifier = authState.loginId.trim()
  const result = auth.login(identifier, authState.password)
  if (!result.success) {
    authState.error = '未找到该账号或密码不正确。'
    return
  }
  localStorage.setItem('auth_logged_in', 'true')
  router.push('/workbench')
}

function submitRegistration() {
  const name = authState.name.trim()
  const department = authState.department.trim()
  if (!name || !department) {
    authState.error = '请填写姓名和所属部门。'
    return
  }
  if (authState.password.length < 6) {
    authState.error = '密码至少需要 6 位。'
    return
  }
  if (authState.password !== authState.confirmPassword) {
    authState.error = '两次输入的密码不一致。'
    return
  }
  const result = auth.register(name, department, authState.role, authState.password)
  if (result.success) {
    authState.confirmPassword = ''
    localStorage.setItem('auth_logged_in', 'true')
    router.push('/workbench')
  }
}
</script>

<template>
  <div class="auth-shell">
    <section class="auth-panel">
      <div class="auth-brand"><div><strong>AI 工作台</strong></div></div>
      <div class="auth-copy"><span class="eyebrow">HANHE WORKBENCH</span><h1>{{ authState.mode === 'login' ? '进入你的工作台' : '创建一个工作账号' }}</h1><p>{{ authState.mode === 'register' ? '账号创建后默认只拥有本人工作汇报权限，后续权限由组织管理员配置。' : '' }}</p></div>
      <div class="auth-tabs"><button :class="{ active: authState.mode === 'login' }" @click="switchAuthMode('login')"><LogIn :size="14" />登录</button><button :class="{ active: authState.mode === 'register' }" @click="switchAuthMode('register')"><Plus :size="14" />创建账号</button></div>
      <form v-if="authState.mode === 'login'" class="auth-form" @submit.prevent="submitLogin">
        <label><span>账号 ID 或姓名</span><div class="auth-input"><UserRound :size="15" /><input v-model="authState.loginId" autocomplete="username" placeholder="例如 account-leader-001" /></div></label>
        <label><span>密码</span><div class="auth-input"><KeyRound :size="15" /><input v-model="authState.password" autocomplete="current-password" type="password" placeholder="请输入密码" /></div></label>
        <p v-if="authState.error" class="auth-error"><CircleAlert :size="14" />{{ authState.error }}</p>
        <button class="auth-submit" type="submit">进入工作台<ChevronRight :size="16" /></button>
      </form>
      <form v-else class="auth-form" @submit.prevent="submitRegistration">
        <div class="auth-form-grid"><label><span>姓名</span><div class="auth-input"><UserRound :size="15" /><input v-model="authState.name" autocomplete="name" placeholder="例如：陈晓" /></div></label><label><span>所属部门</span><div class="auth-input"><Building2 :size="15" /><input v-model="authState.department" placeholder="例如：华南大区业务部" /></div></label></div>
        <label><span>岗位</span><div class="auth-input"><ClipboardList :size="15" /><select v-model="authState.role"><option>业务员</option><option>采购员</option><option>财务人员</option><option>项目成员</option></select></div></label>
        <div class="auth-form-grid"><label><span>设置密码</span><div class="auth-input"><KeyRound :size="15" /><input v-model="authState.password" autocomplete="new-password" type="password" placeholder="至少 6 位" /></div></label><label><span>确认密码</span><div class="auth-input"><KeyRound :size="15" /><input v-model="authState.confirmPassword" autocomplete="new-password" type="password" placeholder="再次输入密码" /></div></label></div>
        <p v-if="authState.error" class="auth-error"><CircleAlert :size="14" />{{ authState.error }}</p>
        <button class="auth-submit" type="submit">创建并进入工作台<ChevronRight :size="16" /></button>
      </form>
    </section>
  </div>
</template>
