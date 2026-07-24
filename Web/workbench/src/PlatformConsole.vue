<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  Activity,
  Boxes,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Database,
  ListTree,
  Network,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  WifiOff,
  X,
} from '@lucide/vue'
import './platform-console.css'

const baseUrl = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? '').replace(/\/$/, '')
const overview = ref(null)
const loading = ref(true)
const error = ref('')
const activeTab = ref('services')
const selectedLayer = ref('all')
const searchText = ref('')
const selectedService = ref(null)
const selectedCall = ref(null)

const tabs = [
  { id: 'services', label: '服务模块', icon: Server },
  { id: 'capabilities', label: '能力登记', icon: Boxes },
  { id: 'calls', label: '调用审计', icon: Network },
  { id: 'datasets', label: '数据目录', icon: Database },
]

const layerLabels = {
  business_application: 'L4 应用层',
  business_engine: 'L2 业务引擎层',
  foundation: 'L1 基础层',
}

const visibleServices = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  return (overview.value?.modules ?? []).filter((item) => {
    const matchesLayer = selectedLayer.value === 'all' || item.layer === selectedLayer.value
    const haystack = [item.name_cn, item.code, item.service, ...item.capabilities].join(' ').toLowerCase()
    return matchesLayer && (!keyword || haystack.includes(keyword))
  })
})

const selectedModule = computed(() => (
  visibleServices.value.find((item) => item.service === selectedService.value)
  ?? visibleServices.value[0]
  ?? null
))

const capabilityModules = computed(() => (overview.value?.modules ?? []).filter((item) => item.capabilities.length))

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch(`${baseUrl}/api/v1/platform/overview`)
    const body = await response.json()
    if (!response.ok) throw new Error(body?.error?.code ?? 'PLATFORM_OVERVIEW_FAILED')
    overview.value = body
    if (!selectedService.value && body.modules?.length) selectedService.value = body.modules[0].service
  } catch (cause) {
    error.value = cause.message || '平台控制台无法连接应用网关'
  } finally {
    loading.value = false
  }
}

function chooseModule(service) {
  selectedService.value = service
}

function layerLabel(layer) {
  return layerLabels[layer] ?? layer
}

function timeText(value) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value))
}

function stateLabel(state) {
  return { online: '在线', offline: '离线', degraded: '异常' }[state] ?? '未知'
}

function callState(status) {
  if (status >= 200 && status < 300) return 'success'
  if (status >= 500) return 'error'
  return 'warning'
}

async function selectCall(call) {
  if (selectedCall.value?.call_id === call.call_id) {
    selectedCall.value = null
    return
  }
  selectedCall.value = { ...call, request: null, response: null, loading: true, error: '' }
  try {
    const response = await fetch(`${baseUrl}/api/v1/traces/${encodeURIComponent(call.trace_id)}/calls`)
    const body = await response.json()
    if (!response.ok) throw new Error(body?.error?.code ?? 'TRACE_CALLS_FAILED')
    const detail = (body.items ?? []).find((item) => item.call_id === call.call_id)
    if (!detail) throw new Error('CALL_NOT_FOUND')
    selectedCall.value = { ...detail, loading: false, error: '' }
  } catch (cause) {
    selectedCall.value = { ...call, request: null, response: null, loading: false, error: cause.message || 'CALL_DETAIL_FAILED' }
  }
}

function formatJson(value) {
  return JSON.stringify(value ?? {}, null, 2)
}

onMounted(refresh)
</script>

<template>
  <div class="platform-console">
    <header class="console-header">
      <div class="brand-lockup">
        <div class="brand-mark"><ListTree :size="22" /></div>
        <div>
          <p>HANHE PLATFORM</p>
          <h1>平台控制台</h1>
        </div>
      </div>
      <div class="header-status" v-if="overview">
        <span><CheckCircle2 :size="14" /> {{ overview.summary.online_count }} 在线</span>
        <span><CircleAlert :size="14" /> {{ overview.summary.offline_count }} 离线</span>
        <button class="icon-button" type="button" title="刷新运行状态" :class="{ spinning: loading }" @click="refresh"><RefreshCw :size="17" /></button>
      </div>
    </header>

    <nav class="console-nav" aria-label="平台控制台导航">
      <button v-for="tab in tabs" :key="tab.id" type="button" :class="{ active: activeTab === tab.id }" @click="activeTab = tab.id">
        <component :is="tab.icon" :size="16" />{{ tab.label }}
      </button>
    </nav>

    <main v-if="overview" class="console-main">
      <section class="metrics" aria-label="平台概览">
        <div class="metric"><span>服务总数</span><strong>{{ overview.summary.service_count }}</strong><small>应用、引擎、基础模块</small></div>
        <div class="metric"><span>已登记能力</span><strong>{{ overview.summary.capability_count }}</strong><small>能力中心启用项</small></div>
        <div class="metric"><span>运行中任务</span><strong>{{ overview.summary.task_counts.running ?? 0 }}</strong><small>等待与执行中的任务</small></div>
        <div class="metric"><span>数据集目录</span><strong>{{ overview.datasets.length }}</strong><small>受控数据资产</small></div>
      </section>

      <section v-if="activeTab === 'services'" class="console-section">
        <div class="section-title"><div><h2>服务模块</h2><span>运行状态与平台注册信息</span></div><small>{{ visibleServices.length }} / {{ overview.modules.length }}</small></div>
        <div class="service-toolbar">
          <div class="segmented" role="group" aria-label="模块层级筛选">
            <button type="button" :class="{ active: selectedLayer === 'all' }" @click="selectedLayer = 'all'">全部</button>
            <button type="button" :class="{ active: selectedLayer === 'business_application' }" @click="selectedLayer = 'business_application'">L4</button>
            <button type="button" :class="{ active: selectedLayer === 'business_engine' }" @click="selectedLayer = 'business_engine'">L2</button>
            <button type="button" :class="{ active: selectedLayer === 'foundation' }" @click="selectedLayer = 'foundation'">L1</button>
          </div>
          <label class="search-box"><Search :size="16" /><input v-model="searchText" type="search" placeholder="搜索模块或能力" /></label>
        </div>
        <div class="service-layout">
          <div class="service-list">
            <button v-for="module in visibleServices" :key="module.service" class="service-row" type="button" :class="{ selected: selectedModule?.service === module.service }" @click="chooseModule(module.service)">
              <span class="status-dot" :class="module.health.state"></span>
              <span class="service-name"><strong>{{ module.name_cn }}</strong><small>{{ module.code }}</small></span>
              <span class="layer-pill">{{ layerLabel(module.layer) }}</span>
              <span class="service-port">:{{ module.port }}</span>
              <ChevronRight :size="16" />
            </button>
          </div>
          <aside v-if="selectedModule" class="module-detail">
            <div class="detail-heading"><div><span class="status-label" :class="selectedModule.health.state">{{ stateLabel(selectedModule.health.state) }}</span><h3>{{ selectedModule.name_cn }}</h3></div><Activity :size="20" /></div>
            <dl>
              <div><dt>服务标识</dt><dd>{{ selectedModule.service }}</dd></div>
              <div><dt>运行端口</dt><dd>127.0.0.1:{{ selectedModule.port }}</dd></div>
              <div><dt>层级</dt><dd>{{ layerLabel(selectedModule.layer) }}</dd></div>
              <div><dt>标准入口</dt><dd>{{ selectedModule.interface }}</dd></div>
              <div><dt>登记能力</dt><dd>{{ selectedModule.registered_capability_count }}</dd></div>
              <div><dt>接入状态</dt><dd>{{ selectedModule.integration_status }}</dd></div>
            </dl>
            <div class="capability-chips"><span v-for="capability in selectedModule.capabilities" :key="capability">{{ capability }}</span><small v-if="!selectedModule.capabilities.length">平台支撑服务</small></div>
          </aside>
        </div>
      </section>

      <section v-else-if="activeTab === 'capabilities'" class="console-section">
        <div class="section-title"><div><h2>能力登记</h2><span>已启用的 L1/L2 平台能力</span></div><small>{{ overview.summary.capability_count }} 项</small></div>
        <div class="capability-table">
          <article v-for="module in capabilityModules" :key="module.service">
            <div><span class="layer-pill">{{ layerLabel(module.layer) }}</span><h3>{{ module.name_cn }}</h3><small>{{ module.code }} · {{ module.registered_capability_count }} 项登记</small></div>
            <p><span v-for="capability in module.capabilities" :key="capability">{{ capability }}</span></p>
          </article>
        </div>
      </section>

      <section v-else-if="activeTab === 'calls'" class="console-section">
        <div class="section-title"><div><h2>最近调用</h2><span>所有模块写入的接口审计记录</span></div><small>{{ overview.recent_calls.length }} 条</small></div>
        <div class="audit-table">
          <div class="audit-head"><span>时间</span><span>调用路径</span><span>能力</span><span>状态</span><span>耗时</span></div>
          <template v-for="call in overview.recent_calls" :key="call.call_id">
            <button type="button" class="audit-row audit-button" :class="{ selected: selectedCall?.call_id === call.call_id }" :aria-expanded="selectedCall?.call_id === call.call_id" @click="selectCall(call)">
              <span>{{ timeText(call.created_at) }}</span><span class="call-path">{{ call.source_module || 'external' }} <ChevronRight :size="13" /> {{ call.target_module || 'runtime' }}</span><span>{{ call.capability }}</span><span class="call-status" :class="callState(call.status_code)">{{ call.status_code ?? '--' }}</span><span>{{ call.duration_ms ? `${Math.round(call.duration_ms)} ms` : '--' }}</span>
            </button>
            <section v-if="selectedCall?.call_id === call.call_id" class="call-detail audit-inline-detail">
              <div class="detail-heading"><div><span class="status-label" :class="callState(selectedCall.status_code)">{{ selectedCall.status_code ?? '--' }}</span><h3>{{ selectedCall.capability }}</h3></div><button class="icon-button" type="button" title="收起调用详情" @click="selectedCall = null"><X :size="16" /></button></div>
              <dl class="call-metadata"><div><dt>Trace ID</dt><dd>{{ selectedCall.trace_id }}</dd></div><div><dt>调用路径</dt><dd>{{ selectedCall.source_module || 'external' }} -> {{ selectedCall.target_module || 'runtime' }}</dd></div><div><dt>请求地址</dt><dd>{{ selectedCall.method }} {{ selectedCall.url }}</dd></div><div><dt>执行耗时</dt><dd>{{ selectedCall.duration_ms ? `${Math.round(selectedCall.duration_ms)} ms` : '--' }}</dd></div></dl>
              <p v-if="selectedCall.loading" class="detail-loading"><RefreshCw class="spin" :size="15" /> 正在读取调用输入输出</p>
              <p v-else-if="selectedCall.error" class="detail-error">{{ selectedCall.error }}</p>
              <div v-else class="payload-grid"><article><h4>输入</h4><pre>{{ formatJson(selectedCall.request) }}</pre></article><article><h4>输出</h4><pre>{{ formatJson(selectedCall.response) }}</pre></article></div>
            </section>
          </template>
        </div>
      </section>

      <section v-else class="console-section">
        <div class="section-title"><div><h2>数据目录</h2><span>平台受控数据集与归属模块</span></div><small>{{ overview.datasets.length }} 个</small></div>
        <div class="dataset-grid">
          <article v-for="dataset in overview.datasets" :key="dataset.name">
            <div><Database :size="17" /><strong>{{ dataset.name }}</strong></div>
            <span>{{ dataset.owner_module }}</span><small>{{ dataset.classification }} · {{ dataset.retention_policy }}</small><em v-if="dataset.sensitive"><ShieldCheck :size="13" /> 敏感</em>
          </article>
        </div>
      </section>
    </main>

    <main v-else-if="loading" class="console-state"><RefreshCw class="spin" :size="22" /> 正在读取平台状态</main>
    <main v-else class="console-state error"><WifiOff :size="22" /> {{ error }}<button type="button" @click="refresh">重试</button></main>
  </div>
</template>
