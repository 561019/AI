<script setup>
import {
  Activity,
  ChevronRight,
  CircleAlert,
  Command,
  FolderKanban,
  LayoutDashboard,
  ListTodo,
} from '@lucide/vue'

defineProps({
  account: { type: Object, required: true },
  workspaceProjects: { type: Array, required: true },
  commandProjectRollup: { type: Array, required: true },
  commandAlerts: { type: Array, required: true },
  commandDispatches: { type: Array, required: true },
  commandMessages: { type: Array, required: true },
  commandPendingCount: { type: Number, required: true },
  canReadTeamReports: { type: Boolean, required: true },
  projectIcon: { type: Function, required: true },
})

const emit = defineEmits([
  'select-project',
  'dispatch-alert',
  'open-command-record',
  'dispatch-command-task',
])
</script>

<template>
  <div class="center-scroll command-chat-stream">
    <div class="assistant-intro command-intro">
      <span class="ai-avatar"><Command :size="18" /></span>
      <div>
        <strong>{{ account.name }}的综合指挥中心</strong>
        <p>用自然语言下发账号级指令；系统在当前权限范围内统筹 Project、待办与风险，并全程留痕。</p>
      </div>
    </div>

    <div class="metric-grid account-metrics command-metrics">
      <div><span>全部 Projects</span><b>{{ workspaceProjects.length }}</b><small>2 个固定 · {{ workspaceProjects.length - 2 }} 个自建</small></div>
      <div><span>进行中任务</span><b>9</b><small>跨 Project 汇总</small></div>
      <div class="warning"><span>待我处理</span><b>{{ canReadTeamReports ? 4 : 2 }}</b><small>确认与待办</small></div>
      <div class="danger"><span>风险预警</span><b>2</b><small>来自风险监控</small></div>
    </div>

    <div class="command-control-strip">
      <span><Activity :size="14" />全局运行态势</span>
      <span class="live-indicator"><i></i>实时同步</span>
      <small>覆盖 {{ workspaceProjects.length }} 个 Project · 自动汇总任务、预警与处理证据</small>
    </div>

    <section class="command-dashboard-grid">
      <article class="command-panel command-portfolio-panel">
        <div class="content-heading"><span><LayoutDashboard :size="15" />跨 Project 运行态势</span><small>按账号权限汇总</small></div>
        <div class="command-project-rollup">
          <button v-for="project in commandProjectRollup" :key="project.id" class="command-project-row" @click="emit('select-project', project.id)">
            <span class="command-project-main"><component :is="projectIcon(project.type)" :size="15" /><span><strong>{{ project.name }}</strong><small>{{ project.total }} 个会话 · {{ project.active }} 个需关注</small></span></span>
            <span class="command-progress"><i><b :style="{ width: `${project.progress}%` }"></b></i><em>{{ project.progress }}%</em></span>
            <ChevronRight :size="14" />
          </button>
        </div>
      </article>

      <article class="command-panel command-alert-panel">
        <div class="content-heading"><span><CircleAlert :size="15" />预警归集</span><small>{{ commandAlerts.length }} 条待跟进</small></div>
        <button v-for="alert in commandAlerts" :key="alert.id" class="command-alert-row" :class="alert.tone" @click="emit('dispatch-alert', alert)">
          <span class="alert-mark"><CircleAlert :size="14" /></span><span><strong>{{ alert.title }}</strong><small>{{ alert.detail }}</small><em>{{ alert.age }} · {{ alert.severity }}级</em></span><ChevronRight :size="14" />
        </button>
      </article>
    </section>

    <section class="command-panel command-queue-panel">
      <div class="content-heading"><span><ListTodo :size="15" />统一任务队列</span><small>{{ commandPendingCount }} 项待调度 · 人工 / 自动全程留痕</small></div>
      <div class="command-queue-head"><span>事项</span><span>来源与负责人</span><span>到期 / 状态</span><span>动作</span></div>
      <div v-for="task in commandDispatches" :key="task.id" class="command-queue-row" :class="task.tone">
        <button class="queue-title" @click="emit('open-command-record', task)"><strong>{{ task.title }}</strong><small>{{ task.kind }}环节 · {{ task.projectId === 'project-team' ? '我的团队' : workspaceProjects.find((project) => project.id === task.projectId)?.name }}</small></button>
        <span class="queue-owner">{{ task.owner }}</span>
        <span class="queue-status"><small>{{ task.due }}</small><em>{{ task.status }}</em></span>
        <button class="queue-action" @click="emit('dispatch-command-task', task)">{{ task.status === '已完成' ? '查看' : task.kind === '自动' ? '执行' : '催办' }}</button>
      </div>
    </section>

    <div v-for="message in commandMessages" :key="message.id" class="message command-message" :class="message.role">
      <span v-if="message.role === 'assistant'" class="message-avatar"><Command :size="16" /></span>
      <div class="bubble"><p>{{ message.text }}</p><button v-if="message.action" class="command-action" @click="emit('select-project', message.action.projectId)"><FolderKanban :size="13" />{{ message.action.label }}</button><small v-if="message.source"><Activity :size="11" />{{ message.source }}</small></div>
      <span v-if="message.role === 'user'" class="message-avatar user">{{ account.avatar }}</span>
    </div>

    <section class="overview-section command-overview">
      <div class="content-heading"><span><FolderKanban :size="15" />Project 运行概览</span><small>点击进入专属指挥中心</small></div>
      <button v-for="project in workspaceProjects" :key="project.id" class="overview-project" @click="emit('select-project', project.id)"><component :is="projectIcon(project.type)" :size="17" /><span><strong>{{ project.name }}</strong><small>{{ project.description }}</small></span><em>{{ project.status }}</em><ChevronRight :size="14" /></button>
    </section>
  </div>
</template>
