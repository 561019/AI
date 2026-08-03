<script setup>
import { Activity, CircleAlert, CircleDotDashed, Database, FileText, History } from '@lucide/vue'

defineProps({
  currentConversation: { type: Object, default: null }, currentProject: { type: Object, default: null },
  accountCenterActive: { type: Boolean, default: false }, isProjectCenter: { type: Boolean, default: false },
  currentContextUsage: { type: Number, default: 0 }, contextLevel: { type: Function, required: true },
  contextHint: { type: Function, required: true }, handoffGenerating: { type: Boolean, default: false }, sessionTimeline: { type: Array, default: () => [] },
  projectFlowRecords: { type: Array, default: () => [] }, commandPendingCount: { type: Number, default: 0 },
  commandDispatches: { type: Array, default: () => [] }, commandAlerts: { type: Array, default: () => [] },
})

const emit = defineEmits(['select-conversation', 'open-command-record', 'dispatch-alert', 'generate-handoff'])
</script>

<template>
  <template v-if="currentConversation">
    <div class="session-state"><span><Activity :size="14" />执行中</span><em>62%</em><small>当前卡点：负责人确认</small></div>
    <div class="context-storage-state" :class="contextLevel(currentConversation)">
      <CircleDotDashed :size="14" />
      <span><strong>上下文占用 {{ currentContextUsage }}%</strong><small>{{ contextHint(currentConversation) }}</small></span>
      <b>{{ currentContextUsage }}%</b>
      <button v-if="currentConversation.contextCapacityState === 'handoff_required' || currentContextUsage >= 85" type="button" class="context-handoff-action" :disabled="handoffGenerating" @click="emit('generate-handoff')">
        <FileText :size="13" />{{ handoffGenerating ? '生成中' : '生成交接包' }}
      </button>
    </div>
    <section class="session-section"><div class="resource-heading"><span><History :size="14" />业务链路</span><em>{{ sessionTimeline.length }} 个节点</em></div><div class="session-timeline"><article v-for="node in sessionTimeline" :key="node.title" class="timeline-node" :class="[node.status, node.kind === '人工' ? 'manual' : 'automatic']"><div class="timeline-mark"><i /><span>{{ node.time }}</span></div><div class="timeline-content"><div><strong>{{ node.title }}</strong><em>{{ node.kind }}</em></div><p>{{ node.detail }}</p><small><FileText :size="11" />核对依据：{{ node.evidence }}</small></div></article></div></section>
    <section class="session-section asset-section"><div class="resource-heading"><span><Database :size="14" />已沉淀业务资产</span><em>可追溯</em></div><div class="asset-tags"><span>客户画像</span><span>专家经验</span><span>采购单据</span><span>业务规则</span><span>流程模板</span></div><p>标准作业流程、客户资料和操作证据都绑定追踪编号；重复校验与流转由系统自动承担。</p></section>
  </template>
  <template v-else-if="accountCenterActive">
    <div class="session-state account-session-state"><span><Activity :size="14" />全局流程同步</span><em>{{ commandPendingCount }}</em><small>待调度事项 · 账号级跨 Project 视图</small></div>
    <section class="session-section"><div class="resource-heading"><span><History :size="14" />全局处理留痕</span><em>{{ commandDispatches.length }} 条</em></div><div class="session-timeline command-timeline"><button v-for="task in commandDispatches.slice(0, 4)" :key="task.id" class="timeline-node project-flow-node" :class="[task.status === '已完成' ? 'done' : 'blocked', task.kind === '人工' ? 'manual' : 'automatic']" @click="emit('open-command-record', task)"><div class="timeline-mark"><i /><span>{{ task.kind }}</span></div><div class="timeline-content"><div><strong>{{ task.title }}</strong><em>{{ task.status }}</em></div><p>{{ task.owner }} · {{ task.due }}</p><small><FileText :size="11" />来源：{{ task.projectId }}</small></div></button></div></section>
    <section class="session-section asset-section"><div class="resource-heading"><span><CircleAlert :size="14" />待跟进预警</span><em>{{ commandAlerts.length }} 条</em></div><div class="asset-tags command-alert-tags"><button v-for="alert in commandAlerts" :key="alert.id" @click="emit('dispatch-alert', alert)">{{ alert.severity }} · {{ alert.title }}</button></div></section>
  </template>
  <template v-else-if="isProjectCenter">
    <div class="session-state"><span><Activity :size="14" />{{ projectFlowRecords.some((item) => item.status === 'blocked') ? '存在待处理卡点' : '流程正常' }}</span><em>{{ projectFlowRecords.length }}</em><small>按对话聚合的全链路数据</small></div>
    <section class="session-section"><div class="resource-heading"><span><History :size="14" />Project 处理链路</span><em>{{ projectFlowRecords.length }} 条</em></div><div class="session-timeline"><button v-for="node in projectFlowRecords" :key="node.conversationId" class="timeline-node project-flow-node" :class="[node.status, node.kind === '人工' ? 'manual' : 'automatic']" @click="emit('select-conversation', currentProject?.id, node.conversationId)"><div class="timeline-mark"><i /><span>可下钻</span></div><div class="timeline-content"><div><strong>{{ node.title }}</strong><em>{{ node.kind }}</em></div><p>{{ node.detail }}</p><small><FileText :size="11" />{{ node.evidence }}</small></div></button></div></section>
  </template>
  <div v-else class="right-empty"><CircleDotDashed :size="25" /><strong>选择一个 Project 查看流程数据</strong><p>综合指挥中心不混合不同 Project 的流程记录。</p></div>
</template>
