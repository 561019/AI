<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  Activity,
  ArrowUpCircle,
  Bell,
  BookOpen,
  Camera,
  Bot,
  Building2,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleDotDashed,
  ClipboardList,
  Clock3,
  Command,
  Cpu,
  Database,
  Download,
  FileOutput,
  FileText,
  FolderKanban,
  History,
  Image as ImageIcon,
  KeyRound,
  LayoutDashboard,
  ListTodo,
  LogIn,
  LogOut,
  LockKeyhole,
  MessageSquare,
  Mic,
  MoreHorizontal,
  Paperclip,
  Pin,
  Power,
  Plus,
  Puzzle,
  Search,
  Send,
  ShieldCheck,
  ShieldPlus,
  Sparkles,
  Settings2,
  Upload,
  UserRound,
  Users,
  Wrench,
  X,
} from '@lucide/vue'
import {
  agentCatalog,
  groupKnowledgeBases,
  notifications,
  personalKnowledgeBases,
  projects as projectSeed,
  sessionTimeline,
  skillCatalog,
  teamMembers,
} from './data/demo'
import { AgentManagementOperations, agentManagementApplicationApi } from './services/agent-management-api'
import { KnowledgeGovernanceOperations, knowledgeGovernanceApplicationApi } from './services/knowledge-governance-api'
import { AuthOperations, authApplicationApi } from './services/auth-api'
import { createInstructionEnvelope, platformApi } from './services/platform-api'
import { workspaceApplicationApi } from './services/workspace-api'

const accountRecords = ref([])
const authState = reactive({
  loggedIn: false,
  mode: 'login',
  loginId: '',
  loginName: '',
  password: '',
  name: '',
  department: '',
  role: '业务员',
  confirmPassword: '',
  error: '',
  loading: false,
  restoring: true,
})
const currentAccountId = ref(null)
const currentProjectId = ref('project-customer')
const currentConversationId = ref('customer-expert')
const conversationMenuId = ref(null)
const expandedProjectIds = ref(new Set(['project-customer']))
const accountCenterActive = ref(false)
const accountMenuOpen = ref(false)
const rightTab = ref('session')
const inputText = ref('')
const fileInput = ref(null)
const imageInput = ref(null)
const cameraInput = ref(null)
const voiceRecording = ref(false)
const toast = ref('')
const sessionMessages = reactive({})
const notificationReadIds = ref([])
const notificationRecords = ref(structuredClone(notifications))
const knowledgeScope = ref('personal')
const fileSearch = ref('')
const projectSearch = ref('')
const disabledResourceIds = ref([])
const personalKnowledge = ref([...personalKnowledgeBases])
const groupKnowledgeRecords = ref(structuredClone(groupKnowledgeBases))
const selectedPersonalKnowledgeId = ref(personalKnowledge.value[0]?.id ?? null)
const knowledgeGrantTargetId = ref(groupKnowledgeRecords.value[0]?.id ?? null)
const knowledgeGrantAssigneeId = ref('account-sales-001')
const knowledgeGovernanceAudit = ref([])
const knowledgeManagement = reactive({
  active: false,
  action: '',
  scope: 'personal',
  knowledgeBaseId: null,
  input: '',
  messages: [],
  stage: 'idle',
})
const workspaceProjects = ref(structuredClone(projectSeed))
const agentRecords = ref(structuredClone(agentCatalog))
const selectedAgentId = ref(agentRecords.value[0].id)
const skillRecords = ref(structuredClone(skillCatalog).map((item) => ({ ...item, version: item.version ?? 'v1.0', calls: item.calls ?? '0 次', adoption: item.adoption ?? '--', consistency: item.consistency ?? '96.5%' })))
const selectedSkillId = ref(skillRecords.value[0].id)
const agentManagement = reactive({
  active: false,
  agentId: null,
  capabilityType: 'agent',
  action: '',
  stage: 'idle',
  input: '',
  messages: [],
  primaryModel: '通义千问 3.5',
  backupModel: 'DeepSeek V3',
  humanConfirm: true,
  promotionStep: 0,
  createTitle: '',
  createSpec: '',
  createAssets: [],
})
const projectDialogOpen = ref(false)
const conversationDialogOpen = ref(false)
const newProjectName = ref('')
const newConversationTitle = ref('')
const commandInput = ref('')
const projectCommandInput = ref('')
const projectCommandMessages = reactive({})
const commandMessages = ref([
  { id: 'command-1', role: 'assistant', text: '我是综合指挥中心。你可以直接告诉我需要统筹、核对、催办或进入哪个 Project，我会按当前账号权限组织后续操作。', source: '账号级范围 · 全部 Project 摘要' },
  { id: 'command-2', role: 'assistant', text: '当前有 2 项风险预警、4 项待处理事项。需要我先汇总风险、催办工作汇报，还是进入某个 Project？', source: '实时待办汇总' },
])

const commandDispatches = ref([
  { id: 'dispatch-1', title: '绿城续约方案完成负责人确认', projectId: 'project-customer', conversationId: 'customer-renewal', owner: '客户经营组', due: '今天 17:00', status: '待确认', kind: '人工', tone: 'warning' },
  { id: 'dispatch-2', title: '原料价格二级预警处置', projectId: 'project-risk', conversationId: 'risk-price', owner: '风险监控', due: '12 分钟前', status: '待跟进', kind: '人工', tone: 'danger' },
  { id: 'dispatch-3', title: '7 月经营分析结果归档', projectId: 'project-analysis', conversationId: 'analysis-monthly', owner: '经营分析', due: '已完成', status: '已完成', kind: '自动', tone: 'success' },
  { id: 'dispatch-4', title: '本周工作汇报补充与提交', projectId: 'project-report', conversationId: 'report-current', owner: '我的工作汇报', due: '今天 18:00', status: '进行中', kind: '人工', tone: 'normal' },
  { id: 'dispatch-5', title: '队伍成员活跃状态同步', projectId: 'project-team', conversationId: 'team-overview', owner: '我的队伍', due: '自动运行', status: '运行中', kind: '自动', tone: 'success' },
])

const commandAlerts = ref([
  { id: 'alert-1', title: '原料价格触发二级预警', projectId: 'project-risk', conversationId: 'risk-price', detail: '价格连续 3 个周期上涨，需负责人确认处置策略。', age: '12 分钟前', severity: '高', tone: 'danger' },
  { id: 'alert-2', title: '绿城续约等待负责人拍板', projectId: 'project-customer', conversationId: 'customer-renewal', detail: '报价草案已生成，合同条件尚未完成确认。', age: '20 分钟前', severity: '中', tone: 'warning' },
  { id: 'alert-3', title: '本周工作汇报还有 2 项待补充', projectId: 'project-report', conversationId: 'report-current', detail: '补齐进展与下周计划后可提交审批。', age: '今天', severity: '中', tone: 'warning' },
])

const accountWorkspaces = new Map()
const roleFeaturePermissions = {
  '华南大区负责人': ['resource.agent.view', 'resource.skill.view', 'knowledge.personal.view', 'file.view'],
  '业务员': ['resource.agent.view', 'resource.skill.view', 'knowledge.personal.view', 'file.view'],
  '采购员': ['resource.skill.view', 'knowledge.personal.view', 'file.view'],
  '财务人员': ['resource.skill.view', 'knowledge.personal.view', 'file.view'],
  '项目成员': ['resource.agent.view', 'resource.skill.view', 'knowledge.personal.view', 'file.view'],
  '知识库管理员': ['knowledge.personal.view'],
}

const commandProjectRollup = computed(() => workspaceProjects.value.map((project, index) => ({
  ...project,
  active: project.conversations.filter((conversation) => conversation.badge || getContextUsage(conversation) >= 75).length,
  total: project.conversations.length,
  progress: Math.max(24, Math.min(96, 92 - index * 12)),
})))

const commandPendingCount = computed(() => commandDispatches.value.filter((item) => !['已完成', '运行中'].includes(item.status)).length)

const contextProfiles = {
  'report-current': 72,
  'report-history': 41,
  'report-team-review': 64,
  'team-overview': 58,
  'team-collaboration': 33,
  'customer-expert': 68,
  'customer-renewal': 88,
  'customer-visit': 46,
  'analysis-monthly': 79,
  'analysis-forecast': 55,
  'risk-price': 92,
  'risk-payment': 61,
}

const SESSION_STORAGE_KEY = 'hanhe.workbench.session'
const defaultPermissions = ['report.read.own', 'report.write.own', 'resource.agent.view', 'resource.skill.view', 'knowledge.personal.view', 'file.view']

const currentAccount = computed(() => accountRecords.value.find((item) => item.id === currentAccountId.value) ?? { id: '', name: '', role: '', department: '', avatar: '用', permissions: [] })
const currentProject = computed(() => workspaceProjects.value.find((item) => item.id === currentProjectId.value))
const hasPermission = (permission) => !permission || (currentAccount.value.permissions ?? []).includes(permission)
const hasFeatureAccess = (permission) => hasPermission(permission) || (roleFeaturePermissions[currentAccount.value.role] ?? []).includes(permission)
const filteredWorkspaceProjects = computed(() => {
  const keyword = projectSearch.value.trim().toLowerCase()
  if (!keyword) return workspaceProjects.value
  return workspaceProjects.value.filter((project) => [project.name, project.description, ...project.conversations.map((conversation) => conversation.title)].join(' ').toLowerCase().includes(keyword))
})
const fixedWorkspaceProjects = computed(() => filteredWorkspaceProjects.value.filter((project) => project.fixed))
const customWorkspaceProjects = computed(() => filteredWorkspaceProjects.value.filter((project) => !project.fixed))
const visibleConversations = computed(() => currentProject.value?.conversations.filter((item) => hasPermission(item.permission)) ?? [])
const groupedVisibleConversations = computed(() => {
  const groups = new Map()
  visibleConversations.value
    .filter((conversation) => !conversation.deleted)
    .sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)))
    .forEach((conversation) => {
      const group = conversationTimeGroup(conversation)
      if (!groups.has(group)) groups.set(group, [])
      groups.get(group).push(conversation)
    })
  return [...groups.entries()].map(([label, conversations]) => ({ label, conversations }))
})
const currentConversation = computed(() => visibleConversations.value.find((item) => item.id === currentConversationId.value))
const selectedAgent = computed(() => agentRecords.value.find((item) => item.id === selectedAgentId.value))
const managedCapability = computed(() => (agentManagement.capabilityType === 'skill' ? skillRecords.value : agentRecords.value).find((item) => item.id === agentManagement.agentId))
const visibleNotifications = computed(() => notificationRecords.value.filter((item) => hasPermission(item.permission)))
const notificationUnreadCount = computed(() => visibleNotifications.value.filter((item) => !notificationReadIds.value.includes(item.id)).length)
const currentMessages = computed(() => {
  if (!currentConversation.value) return []
  return [...currentConversation.value.messages, ...(sessionMessages[currentConversation.value.id] ?? [])]
})
const isProjectCenter = computed(() => !accountCenterActive.value && !currentConversation.value)
const currentContextUsage = computed(() => currentConversation.value ? getContextUsage(currentConversation.value) : 0)
const canReadTeamReports = computed(() => hasPermission('report.read.team'))
const canReadTeam = computed(() => hasPermission('team.read'))
const canManageGroupCapabilities = computed(() => hasPermission('resource.group.manage'))
const canViewGroupKnowledge = computed(() => hasPermission('knowledge.group.view'))
const canSupplementGroupKnowledge = computed(() => hasPermission('knowledge.group.supplement'))
const canGrantGroupKnowledge = computed(() => hasPermission('knowledge.group.grant'))
const canViewAgents = computed(() => hasFeatureAccess('resource.agent.view') || canManageGroupCapabilities.value)
const canViewSkills = computed(() => hasFeatureAccess('resource.skill.view') || canManageGroupCapabilities.value)
const canViewKnowledge = computed(() => hasFeatureAccess('knowledge.personal.view') || canViewGroupKnowledge.value || canGrantGroupKnowledge.value)
const canViewFiles = computed(() => hasFeatureAccess('file.view'))
const visibleRightTabs = computed(() => [
  { id: 'session', label: '会话数据', icon: CircleDotDashed, visible: true },
  { id: 'agent', label: 'Agent', icon: Cpu, visible: canViewAgents.value },
  { id: 'skill', label: 'Skill', icon: Puzzle, visible: canViewSkills.value },
  { id: 'knowledge', label: '知识库', icon: Database, visible: canViewKnowledge.value },
  { id: 'files', label: '文件', icon: FileOutput, visible: canViewFiles.value },
].filter((item) => item.visible))
const visibleGroupKnowledge = computed(() => groupKnowledgeRecords.value.filter((item) => hasPermission(item.contentPermission)))
const selectedGrantKnowledge = computed(() => groupKnowledgeRecords.value.find((item) => item.id === knowledgeGrantTargetId.value))
const knowledgeContentViewers = computed(() => accountRecords.value.filter((account) => account.permissions.includes('knowledge.group.view')))
const selectedPersonalKnowledge = computed(() => personalKnowledge.value.find((item) => item.id === selectedPersonalKnowledgeId.value))
const managedKnowledgeBase = computed(() => {
  const records = knowledgeManagement.scope === 'group' ? groupKnowledgeRecords.value : personalKnowledge.value
  return records.find((item) => item.id === knowledgeManagement.knowledgeBaseId)
})
const generatedFiles = computed(() => {
  if (!currentConversation.value) return []
  return [
    { id: 'output-1', name: `${currentConversation.value.title}_行动简报.pdf`, meta: 'AI 产出 · v1.0 · 今天 10:26', type: 'PDF' },
    { id: 'output-2', name: `${currentConversation.value.title}_执行清单.xlsx`, meta: 'AI 产出 · v1.0 · 今天 10:26', type: 'XLSX' },
  ]
})
const uploadedConversationFiles = computed(() => {
  const keyword = fileSearch.value.trim().toLowerCase()
  const files = currentConversation.value?.files ?? []
  return keyword ? files.filter((item) => item.name.toLowerCase().includes(keyword)) : files
})
const producedConversationFiles = computed(() => {
  const keyword = fileSearch.value.trim().toLowerCase()
  return keyword ? generatedFiles.value.filter((item) => item.name.toLowerCase().includes(keyword)) : generatedFiles.value
})
const projectFiles = computed(() => {
  const keyword = fileSearch.value.trim().toLowerCase()
  const knowledgeFiles = (currentProject.value?.knowledge ?? []).map((file) => ({ ...file, id: `project-${file.name}`, source: 'Project 文件' }))
  const conversationFiles = visibleConversations.value.flatMap((conversation) => (conversation.files ?? []).map((file) => ({ ...file, id: `${conversation.id}-${file.name}`, source: `来源对话 · ${conversation.title}`, conversationId: conversation.id })))
  const files = [...knowledgeFiles, ...conversationFiles]
  return keyword ? files.filter((file) => file.name.toLowerCase().includes(keyword)) : files
})
const projectFlowRecords = computed(() => visibleConversations.value.map((conversation, index) => ({
  conversationId: conversation.id,
  title: conversation.title,
  status: conversation.badge?.includes('待') || getContextUsage(conversation) >= 75 ? 'blocked' : 'done',
  kind: index % 2 ? '人工' : '自动',
  detail: conversation.badge ? `当前状态：${conversation.badge}` : '已同步上下文、文件与处理记录',
  evidence: `${conversation.files?.length ?? 0} 个会话文件 · 上下文 ${getContextUsage(conversation)}%`,
})))
const rightTabLabel = computed(() => ({ session: '会话数据', agent: 'Agent', skill: 'Skill', knowledge: '知识库', files: '文件' }[rightTab.value]))
const currentProjectCommandMessages = computed(() => projectCommandMessages[currentProjectId.value] ?? [])
const projectDispatchRecords = computed(() => visibleConversations.value.map((conversation, index) => ({
  id: `project-dispatch-${conversation.id}`,
  title: conversation.title,
  conversationId: conversation.id,
  projectId: currentProjectId.value,
  owner: currentProject.value?.name ?? '当前 Project',
  due: conversation.updated,
  kind: index % 2 ? '人工' : '自动',
  status: conversation.badge || getContextUsage(conversation) >= 75 ? conversation.badge || '待处理' : '已完成',
  tone: conversation.badge?.includes('风险') || getContextUsage(conversation) >= 90 ? 'danger' : conversation.badge || getContextUsage(conversation) >= 75 ? 'warning' : 'success',
})))
const projectAlertRecords = computed(() => projectDispatchRecords.value.filter((item) => item.tone !== 'success'))
const projectPendingCount = computed(() => projectDispatchRecords.value.filter((item) => item.status !== '已完成').length)

const visibleProjectMetrics = computed(() => {
  if (currentProject.value?.type === 'team' && !canReadTeam.value) {
    return currentProject.value.metrics.map((metric) => ({ ...metric, value: '--', tone: '' }))
  }
  return currentProject.value?.metrics ?? []
})
const contextLabel = computed(() => {
  if (knowledgeManagement.active) return `知识库对话管理 · ${knowledgeManagement.action === 'grant' ? selectedGrantKnowledge.value?.governanceCode ?? '管理责任' : managedKnowledgeBase.value?.name ?? '从当前对话新建'}`
  const label = agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'
  if (agentManagement.active && agentManagement.action === 'create' && !managedCapability.value) return `新建自创 ${label}`
  if (agentManagement.active && managedCapability.value) return `${label} 管理 · ${managedCapability.value.name}`
  if (accountCenterActive.value) return '综合指挥中心'
  if (currentConversation.value) return `${currentProject.value.name} · ${currentConversation.value.title}`
  return `${currentProject.value.name} · Project 指挥中心`
})

function getContextUsage(conversation) {
  return conversation.contextUsage ?? contextProfiles[conversation.id] ?? 24
}

function conversationTimeGroup(conversation) {
  const updated = conversation.updated ?? ''
  if (updated.includes('今天') || updated.includes('刚刚') || updated.includes('分钟') || updated.includes('小时')) return '今天'
  if (updated.includes('昨天')) return '昨天'
  return '更早'
}

function groupConversationsForProject(project) {
  const groups = new Map()
  project.conversations
    .filter((conversation) => hasPermission(conversation.permission) && !conversation.deleted)
    .sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)))
    .forEach((conversation) => {
      const label = conversationTimeGroup(conversation)
      if (!groups.has(label)) groups.set(label, [])
      groups.get(label).push(conversation)
    })
  return [...groups.entries()].map(([label, conversations]) => ({ label, conversations }))
}

function conversationUnread(conversation) {
  return conversation.unread ?? ['customer-renewal', 'risk-price', 'report-current'].includes(conversation.id)
}

function toggleConversationUnread(conversation) {
  conversation.unread = !conversationUnread(conversation)
}

function toggleConversationMenu(conversationId) {
  conversationMenuId.value = conversationMenuId.value === conversationId ? null : conversationId
}

function conversationStatusKind(conversation) {
  if (conversation.badge?.includes('风险')) return 'danger'
  if (conversation.badge || getContextUsage(conversation) >= 75) return 'pending'
  return 'done'
}

function conversationStatusLabel(conversation) {
  if (conversation.badge) return conversation.badge
  return conversationStatusKind(conversation) === 'done' ? '已完成' : '有待处理事项'
}

function pinConversation(conversation) {
  conversation.pinned = !conversation.pinned
  showToast(conversation.pinned ? '会话已置顶' : '已取消置顶')
}

function renameConversation(conversation) {
  const nextTitle = window.prompt('重命名会话', conversation.title)
  if (!nextTitle?.trim()) return
  conversation.title = nextTitle.trim()
  conversation.autoTitle = false
  showToast('会话名称已更新')
}

function deleteConversation(conversation) {
  if (!window.confirm(`确定删除会话“${conversation.title}”吗？`)) return
  const project = workspaceProjects.value.find((item) => item.id === currentProjectId.value)
  if (!project) return
  project.conversations = project.conversations.filter((item) => item.id !== conversation.id)
  if (currentConversationId.value === conversation.id) currentConversationId.value = null
  showToast('会话已删除')
}

function autoNameConversation(conversation, text) {
  if (!conversation || (!conversation.autoTitle && conversation.title !== '新对话')) return
  const compact = text.replace(/\s+/g, ' ').trim()
  if (!compact) return
  conversation.title = compact.length > 18 ? `${compact.slice(0, 18)}…` : compact
  conversation.autoTitle = false
}

function hasConversationHistory(conversation) {
  return conversation.hasHistory !== false && (conversation.messages?.length ?? 0) > 0
}

function contextLevel(conversation) {
  const usage = getContextUsage(conversation)
  if (usage >= 90) return 'critical'
  if (usage >= 75) return 'warning'
  return 'normal'
}

function contextHint(conversation) {
  const usage = getContextUsage(conversation)
  if (usage >= 90) return `上下文已占 ${usage}%，即将达到存储上限`
  if (usage >= 75) return `上下文已占 ${usage}%，建议尽快沉淀并新建对话`
  return `上下文已占 ${usage}%`
}

function notificationKind(item) {
  if (item.tone === 'danger' || item.title.includes('预警')) return '预警'
  if (item.title.includes('汇报') || item.title.includes('待补充')) return '待办'
  if (item.title.includes('续约') || item.title.includes('跟进')) return '跟进'
  return '通知'
}

function notificationIsUnread(item) {
  return !notificationReadIds.value.includes(item.id)
}

function showToast(message) {
  toast.value = message
  window.setTimeout(() => {
    if (toast.value === message) toast.value = ''
  }, 2200)
}

function switchAuthMode(mode) {
  authState.mode = mode
  authState.error = ''
}

function createInitialWorkspace() {
  return {
    projects: structuredClone(projectSeed)
      .filter((project) => project.fixed)
      .map((project) => ({ ...project, conversations: [], knowledge: [] })),
    notifications: [],
    agents: [],
    skills: [],
    personalKnowledge: [],
    groupKnowledge: [],
    disabledResourceIds: [],
  }
}

function createDemoWorkspace() {
  return {
    projects: structuredClone(projectSeed),
    notifications: structuredClone(notifications),
    agents: structuredClone(agentCatalog),
    skills: structuredClone(skillCatalog).map((item) => ({ ...item, version: item.version ?? 'v1.0', calls: item.calls ?? '0 次', adoption: item.adoption ?? '--', consistency: item.consistency ?? '96.5%' })),
    personalKnowledge: structuredClone(personalKnowledgeBases),
    groupKnowledge: structuredClone(groupKnowledgeBases),
    disabledResourceIds: [],
  }
}

function normalizeAccount(account) {
  const name = account.display_name || account.name || account.login_name || account.account_id || '用户'
  const role = account.role || '项目成员'
  return {
    id: account.account_id || account.id,
    loginName: account.login_name || account.loginName || '',
    name,
    role,
    department: account.department || '',
    avatar: name.slice(0, 1),
    permissions: [...new Set([...defaultPermissions, ...(roleFeaturePermissions[role] ?? [])])],
  }
}

function rememberSession(account, sessionId) {
  if (!sessionId || !account?.id) return
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ sessionId, accountId: account.id }))
}

function forgetSession() {
  window.localStorage.removeItem(SESSION_STORAGE_KEY)
}

function upsertAccount(account) {
  const normalized = normalizeAccount(account)
  const index = accountRecords.value.findIndex((item) => item.id === normalized.id)
  if (index >= 0) accountRecords.value[index] = { ...accountRecords.value[index], ...normalized }
  else accountRecords.value.push(normalized)
  return normalized
}

function normalizeProject(record) {
  return {
    ...record,
    id: record.project_id || record.id || record.record_id,
    storageProjectId: record.storage_project_id || record.storageProjectId || record.project_id || record.id || record.record_id,
    name: record.name || '未命名 Project',
    short: record.short || (record.name || '项目').slice(0, 6),
    type: record.type || 'custom',
    fixed: Boolean(record.fixed),
    description: record.description || '由工作台创建的 Project',
    status: record.status || '已创建',
    metrics: record.metrics || [],
    knowledge: record.knowledge || [],
    conversations: [],
  }
}

function fixedProjectStorageId(account, project) {
  return `${account.id}-${project.id}`.replace(/[^a-zA-Z0-9_-]/g, '-')
}

function projectStorageId(project) {
  return project?.storageProjectId || project?.storage_project_id || project?.project_id || project?.id
}

function createFixedProject(account, seed) {
  return normalizeProject({
    ...structuredClone(seed),
    project_id: seed.id,
    storage_project_id: fixedProjectStorageId(account, seed),
    owner_account_id: account.id,
    frontend_fixed: true,
  })
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0)
  if (!value) return '已入库'
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 100 * 1024 ? 1 : 0)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function formatFileType(contentType, name = '') {
  const lowerName = String(name || '').toLowerCase()
  const type = String(contentType || '').toLowerCase()
  if (type.includes('spreadsheet') || lowerName.endsWith('.xlsx') || lowerName.endsWith('.xls')) return 'Excel 文件'
  if (type.includes('wordprocessingml') || lowerName.endsWith('.docx') || lowerName.endsWith('.doc')) return 'Word 文档'
  if (type.includes('presentationml') || lowerName.endsWith('.pptx') || lowerName.endsWith('.ppt')) return 'PPT 文件'
  if (type.includes('pdf') || lowerName.endsWith('.pdf')) return 'PDF 文件'
  if (type.startsWith('image/') || ['.png', '.jpg', '.jpeg', '.gif', '.webp'].some((suffix) => lowerName.endsWith(suffix))) return '图片文件'
  if (type.startsWith('audio/') || ['.mp3', '.wav', '.webm', '.m4a'].some((suffix) => lowerName.endsWith(suffix))) return '音频文件'
  if (type.includes('text') || lowerName.endsWith('.txt') || lowerName.endsWith('.md')) return '文本文件'
  return '文件'
}

function formatStorageTime(value) {
  if (!value) return '已入库'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return `入库 ${date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}`
}

function formatFileMeta(file) {
  return `${formatFileType(file.content_type, file.original_name || file.name || file.original_filename)} · ${formatStorageTime(file.uploaded_at || file.created_at)} · ${formatFileSize(file.size_bytes)}`
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function extractUploadedDocuments(conversation) {
  return (conversation?.files || [])
    .map((file) => file.platform_ref || file.platformRef)
    .filter(Boolean)
}

async function waitForTaskResult(taskId) {
  let latest = null
  for (let index = 0; index < 8; index += 1) {
    latest = await platformApi.getTask(taskId)
    if (['waiting_human', 'succeeded', 'failed'].includes(latest.state)) return latest
    await sleep(650)
  }
  return latest
}

function formatTaskResponse(task, uploadedDocumentCount = 0) {
  if (!task) return '请求已提交，正在等待平台返回任务状态。'
  if (task.error) return `处理失败：${task.error.message || task.error.code || '平台任务执行失败'}`
  const result = task.result_ref || {}
  const data = result.data || result
  const tasks = Array.isArray(data.tasks) ? data.tasks : []
  const firstTask = tasks[0]
  if (task.state === 'waiting_human' && firstTask) {
    const confidence = firstTask.confidence ? `，置信度 ${Math.round(Number(firstTask.confidence) * 100)}%` : ''
    const fileText = uploadedDocumentCount ? `，已携带 ${uploadedDocumentCount} 个上传文件引用` : '，当前未携带上传文件引用'
    return `已完成意图识别，等待确认执行。识别任务：${firstTask.description || '未命名任务'}；能力：${firstTask.capability_code || '未指定'}${confidence}${fileText}。`
  }
  if (firstTask) {
    return `已完成任务识别：${firstTask.description || '未命名任务'}；能力：${firstTask.capability_code || '未指定'}。`
  }
  if (task.state === 'succeeded') return '平台任务已执行完成，结果已写入当前对话链路。'
  if (task.state === 'failed') return '平台任务执行失败，请查看接口调用与任务记录。'
  return `平台任务状态：${task.state || '处理中'}。`
}

function buildIntentCard(task, uploadedDocuments = []) {
  const result = task?.result_ref || {}
  const data = result.data || result
  const items = Array.isArray(data.tasks) ? data.tasks : []
  const intent = items[0]
  const confirmationId = task?.confirmation_ref?.id
  if (!intent || !confirmationId) return null
  const confidence = intent.confidence ? `${Math.round(Number(intent.confidence) * 100)}%` : '未返回'
  const parameters = intent.parameters || {}
  return {
    title: intent.description || '未命名任务',
    label: '意图确认',
    confirmationId,
    taskId: task.task_id,
    uploadedDocuments,
    status: 'pending',
    items: [
      `执行能力：${intent.capability_code || '未指定'}`,
      `识别置信度：${confidence}`,
      `关联文件：${uploadedDocuments.length ? `${uploadedDocuments.length} 个上传文件` : '未关联上传文件'}`,
      ...(parameters.missing_inputs?.length ? [`待补充信息：${parameters.missing_inputs.join('、')}`] : []),
    ],
  }
}

async function ensureProjectRegistered(project = currentProject.value) {
  if (!project || !currentAccount.value.id) return projectStorageId(project)
  const storageId = projectStorageId(project)
  if (!project.fixed && storageId === project.id) return storageId
  if (project.backendRegistered) return storageId
  const receipt = workspaceApplicationApi.acceptCommand({
    operation: 'create',
    accountId: currentAccount.value.id,
    projectId: storageId,
    payload: {
      project_id: storageId,
      name: project.name,
      short: project.short,
      type: project.type,
      description: project.description,
      owner_account_id: currentAccount.value.id,
      frontend_project_id: project.id,
      frontend_fixed: Boolean(project.fixed),
      knowledge: project.knowledge || [],
      metrics: project.metrics || [],
    },
  })
  await receipt.requestPromise
  project.backendRegistered = true
  return storageId
}

function normalizeConversation(record, messageItems = [], fileItems = []) {
  const id = record.conversation_id || record.id || record.record_id
  return {
    ...record,
    id,
    title: record.title || '新对话',
    updated: record.updated || record.updated_at || '刚刚',
    badge: record.badge || '',
    autoTitle: !record.title || record.title === '新对话',
    unread: false,
    hasHistory: record.has_history ?? messageItems.length > 0,
    contextUsage: record.context_usage ?? record.contextUsage ?? 0,
    messages: messageItems
      .filter((message) => String(message.conversation_id) === String(id))
      .sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')))
      .map((message) => ({
        id: message.message_id || message.record_id || `${id}-${Math.random()}`,
        role: message.role || 'assistant',
        text: typeof message.content === 'string' ? message.content : JSON.stringify(message.content ?? ''),
        source: message.task_id ? `任务 ${message.task_id}` : message.trace_id ? `链路 ${message.trace_id}` : undefined,
      })),
    files: fileItems
      .filter((file) => String(file.conversation_id) === String(id))
      .map((file) => ({
        id: file.file_id || file.object_id || file.record_id || file.original_name,
        name: file.original_name || file.name || file.original_filename,
        meta: formatFileMeta(file),
        platform_ref: file.platform_ref,
        platformRef: file.platform_ref,
      })),
  }
}

async function loadAccountWorkspace(account) {
  const [projectResult, conversationResult, messageResult, uploadResult] = await Promise.all([
    platformApi.queryRecords('projects'),
    platformApi.queryRecords('conversations'),
    platformApi.queryRecords('conversation_messages'),
    platformApi.queryRecords('uploaded_files'),
  ])
  const fixedProjects = projectSeed.filter((project) => project.fixed).map((project) => createFixedProject(account, project))
  const fixedStorageIds = new Set(fixedProjects.map((project) => String(projectStorageId(project))))
  const fixedUiIds = new Set(fixedProjects.map((project) => String(project.id)))
  const ownedCustomProjects = (projectResult.items || [])
    .filter((project) => String(project.owner_account_id || '') === String(account.id))
    .filter((project) => !fixedStorageIds.has(String(project.project_id || project.record_id || project.id)))
    .filter((project) => !fixedUiIds.has(String(project.project_id || project.record_id || project.id)))
    .map(normalizeProject)
  const ownedProjects = [...fixedProjects, ...ownedCustomProjects]
  const projectStorageToUiId = new Map(ownedProjects.map((project) => [String(projectStorageId(project)), project.id]))
  const ownedProjectIds = new Set(projectStorageToUiId.keys())
  const ownedConversations = (conversationResult.items || [])
    .filter((conversation) => String(conversation.owner_account_id || '') === String(account.id) && ownedProjectIds.has(String(conversation.project_id)))
  const ownedMessages = (messageResult.items || []).filter((message) => String(message.owner_account_id || '') === String(account.id))
  const ownedUploads = (uploadResult.items || []).filter((file) => String(file.owner_account_id || '') === String(account.id))
  ownedProjects.forEach((project) => {
    const seededConversations = project.fixed ? structuredClone(project.conversations || []) : []
    const persistedConversations = ownedConversations
      .filter((conversation) => String(conversation.project_id) === String(projectStorageId(project)))
      .map((conversation) => ({ ...normalizeConversation(conversation, ownedMessages, ownedUploads), project_id: project.id, storageProjectId: conversation.project_id }))
    const seededIds = new Set(seededConversations.map((conversation) => String(conversation.id)))
    project.conversations = [
      ...seededConversations,
      ...persistedConversations.filter((conversation) => !seededIds.has(String(conversation.id))),
    ]
    project.metrics = [
      { label: '对话', value: String(project.conversations.length) },
      { label: '进行中任务', value: String(project.conversations.filter((item) => item.badge).length) },
      { label: '知识库文件', value: String(project.knowledge?.length ?? 0) },
    ]
  })
  workspaceProjects.value = ownedProjects
  notificationRecords.value = []
  agentRecords.value = structuredClone(agentCatalog)
  skillRecords.value = structuredClone(skillCatalog).map((item) => ({ ...item, version: item.version ?? 'v1.0', calls: item.calls ?? '0 次', adoption: item.adoption ?? '--', consistency: item.consistency ?? '96.5%' }))
  personalKnowledge.value = []
  groupKnowledgeRecords.value = structuredClone(groupKnowledgeBases)
  disabledResourceIds.value = []
  selectedAgentId.value = agentRecords.value[0]?.id ?? null
  selectedSkillId.value = skillRecords.value[0]?.id ?? null
  selectedPersonalKnowledgeId.value = personalKnowledge.value[0]?.id ?? null
  knowledgeGrantTargetId.value = groupKnowledgeRecords.value[0]?.id ?? null
  notificationReadIds.value = []
  expandedProjectIds.value = new Set(ownedProjects.slice(0, 1).map((project) => project.id))
}

async function enterWorkbench(account, operation, payload = undefined, sessionId = undefined) {
  currentAccountId.value = account.id
  await loadAccountWorkspace(account)
  accountCenterActive.value = false
  accountMenuOpen.value = false
  agentManagement.active = false
  knowledgeManagement.active = false
  currentProjectId.value = workspaceProjects.value[0]?.id ?? null
  currentConversationId.value = workspaceProjects.value[0]?.conversations[0]?.id ?? null
  accountCenterActive.value = !currentProjectId.value
  rightTab.value = 'session'
  authState.loggedIn = true
  authState.password = ''
  if (sessionId) rememberSession(account, sessionId)
}

function submitLoginLegacy() {
  const identifier = authState.loginId.trim()
  const account = accountRecords.value.find((item) => item.id === identifier || item.name === identifier)
  if (!account) {
    authState.error = '未找到该账号，请检查账号信息或联系管理员。'
    return
  }
  if (authState.password.length < 6 || authState.password !== account.demoPassword) {
    authState.error = '账号或密码不正确。'
    return
  }
  enterWorkbench(account, AuthOperations.login, { identifier, password: authState.password })
}

function submitRegistrationLegacy() {
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
  const account = {
    id: `account-local-${Date.now().toString(36)}`,
    name,
    role: authState.role,
    department,
    avatar: name.slice(0, 1),
    permissions: ['report.read.own', 'report.write.own', ...(roleFeaturePermissions[authState.role] ?? [])],
    demoPassword: authState.password,
    initialWorkspace: true,
  }
  accountRecords.value.push(account)
  authState.confirmPassword = ''
  enterWorkbench(account, AuthOperations.register, {
    account: { name, department, role: authState.role },
    password: authState.password,
  })
}

function logoutLegacy() {
  if (!currentAccount.value) return
  authApplicationApi.acceptCommand({ operation: AuthOperations.logout, accountId: currentAccount.value.id })
  authState.loggedIn = false
  authState.mode = 'login'
  authState.loginId = currentAccount.value.id
  authState.password = ''
  authState.error = ''
  accountMenuOpen.value = false
}

function accountError(error) {
  const message = error?.message || error?.details?.error?.message || error?.details?.message || error?.code || '请求失败'
  if (message.includes('login_name already exists')) return '该登录名已被注册，请使用其他登录名。'
  if (message.includes('display_name already exists')) return '该姓名已被注册，请使用其他姓名。'
  if (message.includes('account not found')) return '未找到该账号，请检查登录名、账号 ID 或姓名。'
  if (message.includes('invalid account credentials')) return '账号或密码不正确。'
  if (message.includes('multiple accounts')) return '该姓名对应多个账号，请改用登录名或账户 ID。'
  return message
}

async function submitLogin() {
  const identifier = authState.loginId.trim()
  if (!identifier || !authState.password) {
    authState.error = '请输入登录名、账号 ID 或姓名，并填写密码。'
    return
  }
  authState.loading = true
  authState.error = ''
  try {
    const receipt = authApplicationApi.acceptCommand({
      operation: AuthOperations.login,
      accountId: identifier,
      payload: { identifier, password: authState.password },
    })
    const result = await receipt.requestPromise
    const capability = result.data?.capability_result || {}
    const account = upsertAccount(capability.account || {})
    await enterWorkbench(account, AuthOperations.login, undefined, capability.session_id)
  } catch (error) {
    authState.error = accountError(error)
  } finally {
    authState.loading = false
  }
}

async function submitRegistration() {
  const loginName = authState.loginName.trim()
  const name = authState.name.trim()
  const department = authState.department.trim()
  if (!loginName || !name || !department) {
    authState.error = '请填写登录名、姓名和所属部门。'
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
  authState.loading = true
  authState.error = ''
  try {
    const localAccountId = `account-local-${Date.now().toString(36)}`
    const receipt = authApplicationApi.acceptCommand({
      operation: AuthOperations.register,
      accountId: localAccountId,
      payload: {
        account: {
          account_id: localAccountId,
          login_name: loginName,
          display_name: name,
          name,
          department,
          role: authState.role,
        },
        password: authState.password,
      },
    })
    const result = await receipt.requestPromise
    const capability = result.data?.capability_result || {}
    const account = upsertAccount({
      ...capability,
      account_id: capability.account_id || localAccountId,
      login_name: loginName,
      display_name: name,
      department,
      role: authState.role,
    })
    authState.confirmPassword = ''
    await enterWorkbench(account, AuthOperations.register, undefined, capability.session_id)
  } catch (error) {
    authState.error = accountError(error)
  } finally {
    authState.loading = false
  }
}

function logout() {
  const stored = JSON.parse(window.localStorage.getItem(SESSION_STORAGE_KEY) || '{}')
  if (stored.sessionId) {
    authApplicationApi.acceptCommand({ operation: AuthOperations.logout, accountId: currentAccount.value.id, payload: { session_id: stored.sessionId } })
  }
  forgetSession()
  currentAccountId.value = null
  currentProjectId.value = null
  currentConversationId.value = null
  authState.loggedIn = false
  authState.mode = 'login'
  authState.loginId = ''
  authState.password = ''
  authState.error = ''
  accountMenuOpen.value = false
}

async function restoreSession() {
  const stored = JSON.parse(window.localStorage.getItem(SESSION_STORAGE_KEY) || '{}')
  if (!stored.sessionId) {
    authState.restoring = false
    return
  }
  try {
    const receipt = authApplicationApi.acceptCommand({
      operation: AuthOperations.resume,
      accountId: stored.accountId,
      payload: { session_id: stored.sessionId },
    })
    const result = await receipt.requestPromise
    const capability = result.data?.capability_result || {}
    const account = upsertAccount(capability.account || {})
    await enterWorkbench(account, AuthOperations.resume, undefined, capability.session_id || stored.sessionId)
  } catch {
    forgetSession()
  } finally {
    authState.restoring = false
  }
}

function selectAccount(accountId) {
  currentAccountId.value = accountId
  loadAccountWorkspace(currentAccount.value)
  accountMenuOpen.value = false
  accountCenterActive.value = false
  agentManagement.active = false
  knowledgeManagement.active = false
  currentProjectId.value = 'project-report'
  currentConversationId.value = null
  rightTab.value = 'knowledge'
  showToast(`已切换账号：${currentAccount.value.name}`)
}

function selectProject(projectId) {
  currentProjectId.value = projectId
  expandedProjectIds.value = new Set([...expandedProjectIds.value, projectId])
  currentConversationId.value = null
  accountCenterActive.value = false
  agentManagement.active = false
  knowledgeManagement.active = false
  projectCommandInput.value = ''
  rightTab.value = 'session'
}

function toggleProject(projectId) {
  const isExpanded = expandedProjectIds.value.has(projectId)
  if (currentProjectId.value !== projectId || accountCenterActive.value) {
    selectProject(projectId)
    return
  }
  const next = new Set(expandedProjectIds.value)
  if (isExpanded) next.delete(projectId)
  else next.add(projectId)
  expandedProjectIds.value = next
}

function selectConversation(projectId, conversationId) {
  currentProjectId.value = projectId
  expandedProjectIds.value = new Set([...expandedProjectIds.value, projectId])
  currentConversationId.value = conversationId
  conversationMenuId.value = null
  const project = workspaceProjects.value.find((item) => item.id === projectId)
  const conversation = project?.conversations.find((item) => item.id === conversationId)
  if (conversation) conversation.unread = false
  accountCenterActive.value = false
  agentManagement.active = false
  knowledgeManagement.active = false
  rightTab.value = 'session'
}

function selectAccountCenter() {
  accountCenterActive.value = true
  agentManagement.active = false
  knowledgeManagement.active = false
  currentConversationId.value = null
  rightTab.value = 'session'
}

function openNotification(item) {
  if (!notificationReadIds.value.includes(item.id)) notificationReadIds.value.push(item.id)
  selectConversation(item.projectId, item.conversationId)
  showToast('已定位到对应 Project 和对话')
}

function appendMessage(conversationId, message) {
  if (!sessionMessages[conversationId]) sessionMessages[conversationId] = []
  sessionMessages[conversationId].push(message)
}

function updateSessionMessage(conversationId, messageId, patch) {
  const message = sessionMessages[conversationId]?.find((item) => item.id === messageId)
  if (message) Object.assign(message, patch)
  return message
}

function sendMessageLegacy() {
  const text = inputText.value.trim()
  if (!text || !currentConversation.value) return
  const conversationId = currentConversation.value.id
  appendMessage(conversationId, { id: `${Date.now()}-user`, role: 'user', text })
  autoNameConversation(currentConversation.value, text)
  currentConversation.value.unread = false
  currentConversation.value.contextUsage = Math.min(100, getContextUsage(currentConversation.value) + 4)
  currentConversation.value.hasHistory = true
  inputText.value = ''
  window.setTimeout(() => {
    appendMessage(conversationId, {
      id: `${Date.now()}-assistant`,
      role: 'assistant',
      text: '请求已受理。我会依据当前账号权限和本 Project 资料继续处理。',
      source: '受理回执 · L4-260721-1042',
      receipt: true,
    })
  }, 260)
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || !currentConversation.value || !currentProject.value) return
  const conversationId = currentConversation.value.id
  appendMessage(conversationId, { id: `${Date.now()}-user`, role: 'user', text })
  autoNameConversation(currentConversation.value, text)
  currentConversation.value.unread = false
  currentConversation.value.contextUsage = Math.min(100, getContextUsage(currentConversation.value) + 4)
  currentConversation.value.hasHistory = true
  inputText.value = ''
  try {
    const backendProjectId = await ensureProjectRegistered(currentProject.value)
    const uploadedDocuments = extractUploadedDocuments(currentConversation.value)
    const pendingMessage = {
      id: `${Date.now()}-assistant`,
      role: 'assistant',
      text: '意图分析中，稍后会在这里出现确认卡。',
      source: 'L4 应用网关',
      receipt: true,
      task: {
        title: '正在分析意图',
        label: '处理中',
        status: 'running',
        items: [
          '平台正在识别任务能力与参数',
          uploadedDocuments.length ? `已携带 ${uploadedDocuments.length} 个上传文件引用` : '当前没有上传文件引用',
        ],
      },
    }
    appendMessage(conversationId, pendingMessage)
    const envelope = createInstructionEnvelope({
      utterance: text,
      actor: { user_id: currentAccount.value.id, userId: currentAccount.value.id, authenticated: true },
      projectId: backendProjectId,
      projectName: currentProject.value.name,
      conversationId,
      conversationTitle: currentConversation.value.title,
      uploadedDocuments,
    })
    const result = await platformApi.submitInstruction(envelope)
    updateSessionMessage(conversationId, pendingMessage.id, {
      source: `L4/L2 链路 · ${result.trace_id || envelope.trace_id}${result.task_id ? ` · ${result.task_id}` : ''}`,
    })
    if (result.task_id) {
      void waitForTaskResult(result.task_id).then((task) => {
        const currentMessage = updateSessionMessage(conversationId, pendingMessage.id, {
          text: formatTaskResponse(task, uploadedDocuments.length),
          source: `L4/L2 链路 · ${result.trace_id || envelope.trace_id} · ${result.task_id}`,
        })
        if (currentMessage) {
          currentMessage.task = buildIntentCard(task, uploadedDocuments) || currentMessage.task
        }
      }).catch((error) => {
        updateSessionMessage(conversationId, pendingMessage.id, {
          text: accountError(error),
          task: {
            title: '意图分析失败',
            label: '失败',
            status: 'failed',
            items: ['请查看后端任务与接口调用记录'],
          },
        })
      })
    }
  } catch (error) {
    appendMessage(conversationId, {
      id: `${Date.now()}-assistant-error`,
      role: 'assistant',
      text: accountError(error),
      source: '平台提交失败',
    })
  }
}

function openAttachmentPicker(kind) {
  if (!currentConversation.value) {
    showToast('请先进入一个对话后再添加素材')
    return
  }
  const input = kind === 'image' ? imageInput.value : kind === 'camera' ? cameraInput.value : fileInput.value
  input?.click()
}

function attachConversationFilesLegacy(event, source) {
  const files = [...(event.target.files ?? [])]
  if (!files.length || !currentConversation.value) return
  const conversation = currentConversation.value
  if (!conversation.files) conversation.files = []
  files.forEach((file) => {
    conversation.files.unshift({
      name: file.name,
      meta: `${source} · 刚刚添加 · ${(file.size / 1024 / 1024).toFixed(1)} MB`,
    })
  })
  event.target.value = ''
  showToast(`已添加 ${files.length} 个${source}`)
}

async function attachConversationFiles(event, source) {
  const files = [...(event.target.files ?? [])]
  if (!files.length || !currentConversation.value || !currentProject.value) return
  try {
    const backendProjectId = await ensureProjectRegistered(currentProject.value)
    const result = await platformApi.uploadDocuments(files, {
      actor: { user_id: currentAccount.value.id, userId: currentAccount.value.id, authenticated: true },
      projectId: backendProjectId,
      conversationId: currentConversation.value.id,
      source,
    })
    if (!currentConversation.value.files) currentConversation.value.files = []
    ;(result.items || []).forEach((file) => {
      currentConversation.value.files.unshift({
        id: file.file_id || file.object_id || file.stored_name,
        name: file.original_name || file.name,
        meta: formatFileMeta(file),
        platform_ref: file.platform_ref,
        platformRef: file.platform_ref,
      })
    })
    showToast(`已上传 ${files.length} 个${source}并写入数据模块`)
  } catch (error) {
    showToast(accountError(error))
  } finally {
    event.target.value = ''
  }
}

function toggleVoiceRecording() {
  if (!currentConversation.value) {
    showToast('请先进入一个对话后再录音')
    return
  }
  voiceRecording.value = !voiceRecording.value
  if (!voiceRecording.value) {
    if (!currentConversation.value.files) currentConversation.value.files = []
    currentConversation.value.files.unshift({ name: `语音消息_${Date.now()}.webm`, meta: '语音录音 · 刚刚添加' })
  }
  showToast(voiceRecording.value ? '录音已开始，再次点击结束录音' : '语音已保存到当前对话')
}

function sendProjectCommandMessage() {
  const text = projectCommandInput.value.trim()
  if (!text || !currentProject.value) return
  const projectId = currentProject.value.id
  if (!projectCommandMessages[projectId]) projectCommandMessages[projectId] = []
  projectCommandMessages[projectId].push({ id: `${Date.now()}-project-user`, role: 'user', text })
  projectCommandInput.value = ''
  const target = projectAlertRecords.value[0] ?? projectDispatchRecords.value[0]
  const responseText = text.includes('预警')
    ? `已汇总“${currentProject.value.name}”内 ${projectAlertRecords.value.length} 项待跟进事项，并保留每项来源会话与核对依据。`
    : text.includes('催办') || text.includes('任务')
      ? `已在“${currentProject.value.name}”内整理 ${projectPendingCount.value} 项任务，下一步可定位来源会话或发起人工催办。`
      : `已受理当前 Project 指令。我会仅使用本项目会话、任务和知识库资料执行统筹，并记录处理回执。`
  window.setTimeout(() => {
    projectCommandMessages[projectId].push({
      id: `${Date.now()}-project-ai`,
      role: 'assistant',
      text: responseText,
      source: `Project 指挥中心 · ${currentProject.value.name}`,
      action: target ? { projectId, conversationId: target.conversationId, label: '查看来源会话' } : undefined,
    })
  }, 220)
}

function openProjectDialog() {
  newProjectName.value = ''
  projectDialogOpen.value = true
}

function createProjectLegacy() {
  const name = newProjectName.value.trim()
  if (!name) return
  const id = `project-${Date.now()}`
  workspaceProjects.value.push({
    id,
    name,
    short: name.length > 6 ? name.slice(0, 6) : name,
    type: 'custom',
    fixed: false,
    description: '新建 Project，等待补充业务范围与资料',
    status: '刚刚创建',
    metrics: [
      { label: '对话', value: '0' },
      { label: '进行中任务', value: '0' },
      { label: '知识库文件', value: '0' },
    ],
    knowledge: [],
    conversations: [],
  })
  projectDialogOpen.value = false
  selectProject(id)
  showToast(`已创建 Project：${name}`)
}

function openConversationDialog() {
  createConversation()
}

function createConversationLegacy() {
  const title = newConversationTitle.value.trim() || '新对话'
  if (!currentProject.value) return
  const id = `conversation-${Date.now()}`
  currentProject.value.conversations.unshift({
    id,
    title,
    updated: '刚刚',
    badge: '新对话',
    autoTitle: true,
    unread: false,
    hasHistory: false,
    contextUsage: 0,
    messages: [{ id: `${id}-welcome`, role: 'assistant', text: `已在“${currentProject.value.name}”创建新对话。告诉我目标、范围和交付物即可开始。`, source: '新对话 · 尚未携带历史上下文' }],
    files: [],
  })
  newConversationTitle.value = ''
  conversationDialogOpen.value = false
  selectConversation(currentProject.value.id, id)
  showToast(`已创建对话：${title}`)
}

async function createProject() {
  const name = newProjectName.value.trim()
  if (!name || !currentAccount.value.id) return
  const id = `project-${Date.now()}`
  try {
    const receipt = workspaceApplicationApi.acceptCommand({
      operation: 'create',
      accountId: currentAccount.value.id,
      projectId: id,
      payload: {
        project_id: id,
        name,
        short: name.length > 6 ? name.slice(0, 6) : name,
        type: 'custom',
        description: '由工作台创建的 Project',
        owner_account_id: currentAccount.value.id,
        knowledge: [],
        metrics: [],
      },
    })
    const result = await receipt.requestPromise
    const project = {
      ...normalizeProject(result.data?.project || { project_id: id, name, owner_account_id: currentAccount.value.id }),
      storageProjectId: id,
      backendRegistered: true,
    }
    workspaceProjects.value.unshift(project)
    projectDialogOpen.value = false
    newProjectName.value = ''
    selectProject(project.id)
    showToast(`已创建 Project：${name}`)
  } catch (error) {
    showToast(accountError(error))
  }
}

async function createConversation() {
  const title = newConversationTitle.value.trim() || '新对话'
  if (!currentProject.value || !currentAccount.value.id) return
  const id = `conversation-${Date.now()}`
  try {
    const backendProjectId = await ensureProjectRegistered(currentProject.value)
    const receipt = workspaceApplicationApi.acceptCommand({
      operation: 'create_conversation',
      accountId: currentAccount.value.id,
      projectId: backendProjectId,
      conversationId: id,
      payload: {
        conversation_id: id,
        title,
        project_id: backendProjectId,
        project_name: currentProject.value.name,
        owner_account_id: currentAccount.value.id,
      },
    })
    const result = await receipt.requestPromise
    const conversation = normalizeConversation(result.data?.conversation || {
      conversation_id: id,
      title,
      project_id: backendProjectId,
      owner_account_id: currentAccount.value.id,
    })
    conversation.project_id = currentProject.value.id
    conversation.storageProjectId = backendProjectId
    conversation.messages = [{
      id: `${id}-welcome`,
      role: 'assistant',
      text: `已在“${currentProject.value.name}”创建新对话。`,
      source: `L4 应用网关 · ${result.trace_id || receipt.traceId}`,
    }]
    currentProject.value.conversations.unshift(conversation)
    newConversationTitle.value = ''
    conversationDialogOpen.value = false
    selectConversation(currentProject.value.id, id)
    showToast(`已创建对话：${title}`)
  } catch (error) {
    showToast(accountError(error))
  }
}

function startFreshConversationFromContext() {
  if (!currentConversation.value) return
  const title = `${currentConversation.value.title} · 续`
  const id = `conversation-${Date.now()}`
  currentProject.value.conversations.unshift({
    id,
    title,
    updated: '刚刚',
    badge: '续接',
    hasHistory: false,
    contextUsage: 0,
    messages: [{ id: `${id}-summary`, role: 'assistant', text: `已新建续接对话，并带入上一对话的结构化摘要。原始上下文不会继续累积。`, source: `由 ${currentConversation.value.title} 沉淀续接` }],
    files: [],
  })
  selectConversation(currentProject.value.id, id)
  showToast('已沉淀上下文并创建续接对话')
}

function openCommandRecord(record) {
  selectConversation(record.projectId, record.conversationId)
  showToast(`已定位到 ${record.title}`)
}

function dispatchCommandTask(task) {
  if (task.status === '已完成') {
    openCommandRecord(task)
    return
  }
  task.status = task.kind === '自动' ? '运行中' : '已催办'
  const project = workspaceProjects.value.find((item) => item.id === task.projectId)
  commandMessages.value.push({
    id: `${Date.now()}-dispatch`,
    role: 'assistant',
    text: `${task.title}已进入${task.kind === '自动' ? '系统执行队列' : '人工跟进队列'}，来源 Project：${project?.name ?? task.owner}。`,
    source: '综合指挥中心 · 调度回执',
    action: { projectId: task.projectId, label: '查看来源对话' },
  })
  showToast(`${task.kind === '自动' ? '任务已开始执行' : '已向负责人发出催办'}：${task.title}`)
}

function dispatchAlert(alert) {
  openCommandRecord(alert)
}

function sendCommandMessage() {
  const text = commandInput.value.trim()
  if (!text) return
  commandMessages.value.push({ id: `${Date.now()}-command-user`, role: 'user', text })
  commandInput.value = ''
  const response = text.includes('风险')
    ? { text: '已汇总风险监控 Project：2 项预警，其中“原料价格上行预警”等待负责人确认。我已把完整核对依据和处理建议带入结果。', action: { projectId: 'project-risk', label: '进入风险监控' } }
    : text.includes('汇报')
      ? { text: canReadTeamReports.value ? '已汇总团队工作汇报：4 人已提交，1 人待补充。我可以继续催办、生成汇总或进入某位成员的汇报对话。' : '已定位到你的工作汇报 Project。你可以继续补充本周进展，或让我生成提交前检查清单。', action: { projectId: 'project-report', label: '进入工作汇报' } }
      : { text: '已受理你的账号级指令。我会在当前权限范围内关联相关 Project、对话和待办，并通过追踪编号持续反馈。', action: { projectId: 'project-customer', label: '进入重点客户经营' } }
  window.setTimeout(() => {
    commandMessages.value.push({ id: `${Date.now()}-command-ai`, role: 'assistant', text: response.text, source: '综合指挥中心 · 受理回执 L4-260721-CC01', action: response.action })
  }, 220)
}

function confirmIntentLegacy() {
  if (!currentConversation.value) return
  appendMessage(currentConversation.value.id, {
    id: `${Date.now()}-confirm`,
    role: 'assistant',
    text: '已收到确定性指令“确认并执行”。任务已进入执行队列，可离开当前对话继续工作。',
    source: '追踪编号 L4-260721-1042 · 预计 8 分钟',
    receipt: true,
  })
  showToast('任务已确认并开始执行')
}

async function confirmIntent(message) {
  if (!currentConversation.value || !currentProject.value || !message?.task || message.task.status === 'running') return
  const task = message.task
  task.status = 'running'
  try {
    const backendProjectId = await ensureProjectRegistered(currentProject.value)
    const result = await platformApi.confirmIntent(task.confirmationId, {
      decision: 'confirm',
      actor: { tenant_id: platformApi.tenantId, user_id: currentAccount.value.id, authenticated: true },
      project_id: backendProjectId,
      conversation_id: currentConversation.value.id,
      uploaded_documents: task.uploadedDocuments || [],
    })
    task.status = 'confirmed'
    appendMessage(currentConversation.value.id, {
      id: `${Date.now()}-confirm`,
      role: 'assistant',
      text: result.status === 'succeeded' ? '已确认执行，工作流处理结果已写入当前对话链路。' : '已确认执行，平台正在继续处理。',
      source: `确认执行 · ${result.task_id || task.taskId}`,
      receipt: true,
    })
    showToast('任务已确认并开始执行')
  } catch (error) {
    task.status = 'pending'
    appendMessage(currentConversation.value.id, {
      id: `${Date.now()}-confirm-error`,
      role: 'assistant',
      text: accountError(error),
      source: '确认执行失败',
      receipt: true,
    })
  }
}

function canOperateResource(item) {
  return item.scope === 'personal' || canManageGroupCapabilities.value
}

function isResourceDisabled(item) {
  return disabledResourceIds.value.includes(item.id)
}

function selectAgent(item) {
  selectedAgentId.value = item.id
}

function selectSkill(item) {
  selectedSkillId.value = item.id
}

function createCapabilityCommand(operation, capabilityId = null, payload = {}) {
  return agentManagementApplicationApi.acceptCommand({
    operation,
    accountId: currentAccount.value.id,
    capabilityId,
    capabilityType: agentManagement.capabilityType,
    conversationId: currentConversation.value?.id ?? null,
    payload,
  })
}

function openAgentCreation() {
  openCapabilityCreation('agent')
}

function openSkillCreation() {
  openCapabilityCreation('skill')
}

function openCapabilityCreation(type) {
  agentManagement.active = true
  agentManagement.agentId = null
  agentManagement.capabilityType = type
  agentManagement.action = 'create'
  agentManagement.stage = 'create-request'
  agentManagement.input = ''
  agentManagement.createTitle = ''
  agentManagement.createSpec = ''
  agentManagement.createAssets = []
  agentManagement.primaryModel = '通义千问 3.5'
  agentManagement.backupModel = 'DeepSeek V3'
  agentManagement.humanConfirm = true
  rightTab.value = type
  const label = type === 'skill' ? 'Skill' : 'Agent'
  agentManagement.messages = [{
    id: `${Date.now()}-agent-create`,
    role: 'assistant',
    text: type === 'skill' ? '请用自然语言说明这个 Skill 的输入材料、处理规则和期望输出。我会装配可用工具、知识范围和执行策略，并通过样本与多模型校验后再保存。' : '请用自然语言告诉我你要解决什么业务问题、希望得到什么结果，以及哪些动作需要人工确认。我会从你已开通的个人与大区公共资产中装配技能、知识库、工具和执行规则，不重复加载已有资产。',
    source: `自创 ${label} · 免审批 · 创建人个人可用`,
  }]
}

function beginAgentCreationValidation() {
  if (agentManagement.stage !== 'create-assembly') return
  agentManagement.stage = 'create-validation'
  const receipt = createCapabilityCommand(AgentManagementOperations.create, null, {
    phase: 'multi_model_validation',
    title: agentManagement.createTitle,
  })
  appendAgentMessage({
    role: 'assistant',
    text: `已完成候选 ${agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'} 装配，现已由通义千问、DeepSeek、豆包并行校验输出逻辑与文案口径。请选择主力与备用模型，确认后即可存入个人台账。`,
    source: `跨模型一致性测试 · ${receipt.traceId}`,
  })
}

function refineNewAgentRules() {
  agentManagement.stage = 'create-request'
  agentManagement.input = agentManagement.createSpec
  appendAgentMessage({
    role: 'assistant',
    text: '已回到规则调整。请直接补充目标、阈值或人工确认要求，系统会重新装配并执行跨模型校验。',
    source: `自创 ${agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'} · 规则重调`,
  })
}

function openAgentManagement(item, action) {
  openCapabilityManagement(item, action, 'agent')
}

function openSkillManagement(item, action) {
  openCapabilityManagement(item, action, 'skill')
}

function openCapabilityManagement(item, action, type) {
  if (!canOperateResource(item)) {
    showToast(`当前账号可以使用该集团 ${type === 'skill' ? 'Skill' : 'Agent'}，但没有管理权限`)
    return
  }
  if ((action === 'promote' || action === 'publish') && item.scope === 'group') {
    showToast(`该 ${type === 'skill' ? 'Skill' : 'Agent'} 已是组织公共资产，无需再次发布`)
    return
  }
  if (type === 'skill') selectSkill(item)
  else selectAgent(item)
  agentManagement.active = true
  agentManagement.agentId = item.id
  agentManagement.capabilityType = type
  agentManagement.action = action
  agentManagement.stage = action === 'fineTune' ? 'fine-request' : action === 'upgrade' ? 'upgrade-request' : action === 'promote' || action === 'publish' ? 'promotion-intent' : action === 'disable' ? 'disable-confirm' : 'restore-request'
  agentManagement.input = ''
  agentManagement.promotionStep = 0
  rightTab.value = type
  const opening = {
    fineTune: '请用自然语言说明你希望调整的判断逻辑、权重或输出方式。我会在个人副本上生成多案例调前/调后预览，公共标准版不会被修改。',
    upgrade: '请说明要新增或优化的能力，以及哪些动作需要人工确认。我会装配新能力并进行多模型一致性校验，再由你选择主力和备用模型。',
    promote: '推荐升层只针对成熟的个人 Agent。系统将按养护人发起、经验推广官客观校验、系统归档三个阶段处理，不做主观打分。',
    publish: '发布升档会先校验个人 Skill 的样本效果、调用数据和输出一致性。通过后将其归档为组织可复用版本，原创建人保留养护责任。',
    disable: '停用会让该 Agent 在全部场景不可调用，但历史版本、调用记录和复用数据完整保留。确认停用后，任意对话中输入“恢复”即可还原。',
    restore: '该 Agent 当前已停用。请用自然语言确认“恢复”，我会还原到停用前的可调用版本。',
  }
  const label = type === 'skill' ? 'Skill' : 'Agent'
  agentManagement.messages = [{ id: `${Date.now()}-capability-open`, role: 'assistant', text: opening[action], source: `${label} 台账 · ${item.version} · ${item.scope === 'group' ? '集团共用' : '个人自建'}` }]
}

function closeAgentManagement() {
  agentManagement.active = false
  agentManagement.stage = 'idle'
  agentManagement.input = ''
  rightTab.value = agentManagement.capabilityType
}

function appendAgentMessage(message) {
  agentManagement.messages.push({ id: `${Date.now()}-${agentManagement.messages.length}`, ...message })
}

function sendAgentManagementMessage() {
  const text = agentManagement.input.trim()
  const agent = managedCapability.value
  if (!text) return
  appendAgentMessage({ role: 'user', text })
  agentManagement.input = ''
  if (agentManagement.action === 'create' && agentManagement.stage === 'create-request') {
    agentManagement.createSpec = text
    const isSkill = agentManagement.capabilityType === 'skill'
    agentManagement.createTitle = isSkill
      ? text.includes('拜访') ? '客户拜访复盘自创 Skill' : text.includes('汇报') ? '工作汇报自创 Skill' : '业务处理自创 Skill'
      : text.includes('客户') ? '客户经营自创 Agent' : text.includes('采购') ? '采购协同自创 Agent' : text.includes('汇报') ? '工作汇报自创 Agent' : '业务协同自创 Agent'
    agentManagement.createAssets = isSkill ? [
      { label: '输入规范', value: '业务材料、指令上下文', detail: '只接受当前权限范围内的输入资料' },
      { label: '输出约束', value: '标准结论、待办与引用依据', detail: '输出结构可被 Agent 与业务流程复用' },
      { label: '配套工具', value: '模板生成、规则校验', detail: '复用当前账号已开通的工具能力' },
      { label: '执行策略', value: agentManagement.humanConfirm ? '生成后人工确认' : '按规则自动交付', detail: '可在测试前继续调整' },
    ] : [
      { label: '装配技能', value: '经营分析、客户画像', detail: '复用当前账号已开通的业务分析能力' },
      { label: '挂载知识库', value: '片区经营、客户数据资料', detail: '只绑定当前权限可见的资料，不与个人库混用' },
      { label: '配套工具', value: '经营看板、阈值提醒', detail: '用于查看结果和触发可视化预警' },
      { label: '执行策略', value: agentManagement.humanConfirm ? '自动运算，发送通报前人工确认' : '按规则自动执行', detail: '可在测试前继续调整' },
    ]
    agentManagement.stage = 'create-assembly'
    const receipt = createCapabilityCommand(AgentManagementOperations.create, null, { phase: 'asset_assembly', text })
    appendAgentMessage({
      role: 'assistant',
      text: `已根据你的描述生成“${agentManagement.createTitle}”候选方案，并完成去重装配。请核对下方资产清单后启动跨模型一致性测试。`,
      source: `资产装配回执 · ${receipt.traceId}`,
    })
    return
  }
  if (!agent) return
  if (agent.status === '已停用' && text.includes('恢复')) {
    agent.status = '运行中'
    disabledResourceIds.value = disabledResourceIds.value.filter((id) => id !== agent.id)
    agentManagement.stage = 'complete'
    const receipt = createCapabilityCommand(AgentManagementOperations.restore, agent.id)
    appendAgentMessage({ role: 'assistant', text: `已恢复 ${agent.name}，版本 ${agent.version} 已回到可调用状态。历史版本和停用期间数据均保持完整。`, source: `恢复回执 · ${receipt.traceId}` })
    return
  }
  if (agentManagement.action === 'fineTune' && agentManagement.stage === 'fine-request') {
    agentManagement.stage = 'fine-preview'
    appendAgentMessage({ role: 'assistant', text: '已根据你的描述生成个人专属调整方案，并使用三组真实业务样本完成调前/调后预览。请核对差异后确认保存。', source: '参数调整预览 · 仅个人副本' })
    return
  }
  if (agentManagement.action === 'upgrade' && agentManagement.stage === 'upgrade-request') {
    agentManagement.stage = 'upgrade-validation'
    appendAgentMessage({ role: 'assistant', text: '新能力已装配到候选版本。三套模型已并行完成一致性校验，输出口径和结果差异已整理在下方，你可以选择主力与备用模型后保存。', source: '多模型一致性校验 · 候选版本' })
    return
  }
  if (['promote', 'publish'].includes(agentManagement.action)) {
    const isSkillPublish = agentManagement.action === 'publish'
    appendAgentMessage({ role: 'assistant', text: isSkillPublish ? '已收到发布升档指令。请查看下方流程和客观数据，确认后提交发布申请。' : '已收到升层指令。请查看下方三层流程和客观数据，确认后提交升层申请。', source: `${isSkillPublish ? '发布升档' : '升层'}预检 · 调用次数、采纳率、多模型一致性` })
    return
  }
  if (agentManagement.action === 'disable') {
    appendAgentMessage({ role: 'assistant', text: '如确认停用，请点击下方“确认停用”；也可以继续补充停用范围或输入“取消”。', source: '停用确认 · 可恢复' })
    return
  }
  const label = agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'
  appendAgentMessage({ role: 'assistant', text: `已记录你的管理指令。我会在当前 ${label} 的版本、权限和调用范围内继续执行，并保留完整操作记录。`, source: `${label} 管理对话 · 留痕` })
}

function confirmAgentManagement() {
  const agent = managedCapability.value
  if (agentManagement.action === 'create' && agentManagement.stage === 'create-validation') {
    const isSkill = agentManagement.capabilityType === 'skill'
    const createdAgent = {
      id: `${isSkill ? 'skill' : 'agent'}-personal-${Date.now()}`,
      scope: 'personal',
      name: agentManagement.createTitle || '自创个人 Agent',
      level: isSkill ? '自创·个人 Skill' : '自创·个人版',
      version: 'v1.0',
      status: '运行中',
      calls: '0 次',
      adoption: '--',
      consistency: '97.2%',
      detail: `由 ${currentAccount.value.name} 自然语言创建：${agentManagement.createSpec}`,
      recommendation: '等待个人使用数据积累',
    }
    if (isSkill) {
      skillRecords.value.push(createdAgent)
      selectedSkillId.value = createdAgent.id
    } else {
      agentRecords.value.push(createdAgent)
      selectedAgentId.value = createdAgent.id
    }
    agentManagement.agentId = createdAgent.id
    const receipt = createCapabilityCommand(AgentManagementOperations.create, createdAgent.id, {
      phase: 'ledger_saved',
      assets: agentManagement.createAssets,
      primaryModel: agentManagement.primaryModel,
      backupModel: agentManagement.backupModel,
      humanConfirm: agentManagement.humanConfirm,
    })
    appendAgentMessage({
      role: 'assistant',
      text: `已确认存入台账：“${createdAgent.name} · ${createdAgent.level} v1.0”。你是该能力的养护人；它仅供本人调用，不影响任何集团标准版。后续需要开放组织复用时，再发起“${isSkill ? '发布升档' : '推荐升层'}”。`,
      source: `个人${isSkill ? ' Skill' : ' Agent'}入账 · ${receipt.traceId}`,
    })
    agentManagement.stage = 'complete'
    return
  }
  if (!agent) return
  if (agentManagement.stage === 'fine-preview') {
    if (agent.scope === 'group') {
      const variant = {
        ...agent,
        id: `agent-variant-${Date.now()}`,
        scope: 'personal',
        name: `${agent.name} · ${currentAccount.value.name}变种`,
        level: '个人变种',
        version: 'v1.0',
        status: '运行中',
        calls: '0 次',
        recommendation: '等待个人使用数据积累',
      }
      if (agentManagement.capabilityType === 'skill') {
        skillRecords.value.push(variant)
        selectedSkillId.value = variant.id
      } else {
        agentRecords.value.push(variant)
        selectedAgentId.value = variant.id
      }
      agentManagement.agentId = variant.id
      appendAgentMessage({ role: 'assistant', text: `已保存为“${variant.name}”。该变种仅对你可见和调用，集团共享池中的 ${agent.name} 保持原样。`, source: '个人变种新版本 · 可独立回滚' })
    } else {
      agent.version = bumpVersion(agent.version)
      appendAgentMessage({ role: 'assistant', text: `已保存 ${agent.name} 的个人微调版本 ${agent.version}。旧版本已留存，可随时回退。`, source: '个人版本历史 · 可回滚' })
    }
    agentManagement.stage = 'complete'
    return
  }
  if (agentManagement.stage === 'upgrade-validation') {
    agent.version = bumpVersion(agent.version)
    appendAgentMessage({ role: 'assistant', text: `已保存升级版本 ${agent.version}。主力模型为 ${agentManagement.primaryModel}，备用模型为 ${agentManagement.backupModel}${agentManagement.humanConfirm ? '，关键动作将先请求人工确认。' : '，将按规则自动执行。'}`, source: '升级版本已归档 · 旧版可回滚' })
    agentManagement.stage = 'complete'
    return
  }
  if (agentManagement.stage === 'disable-confirm') {
    agent.status = '已停用'
    if (!disabledResourceIds.value.includes(agent.id)) disabledResourceIds.value.push(agent.id)
    appendAgentMessage({ role: 'assistant', text: `已停用 ${agent.name}。所有场景已停止调用，但 ${agent.version} 及历史版本、调用记录、复用数据均已完整保留。`, source: '停用回执 · 输入“恢复”可一键还原' })
    agentManagement.stage = 'disabled'
  }
}

function advancePromotionFlow() {
  const agent = managedCapability.value
  if (!agent) return
  if (agentManagement.promotionStep === 0) {
    agentManagement.promotionStep = 1
    appendAgentMessage({ role: 'assistant', text: '养护人升层申请已发起，经验推广官正在校验全大区调用次数、方案采纳率和多模型一致性。', source: '升层流程 1/3 · 申请已留痕' })
    return
  }
  if (agentManagement.promotionStep === 1) {
    agentManagement.promotionStep = 2
    agent.scope = 'group'
    const isSkill = agentManagement.capabilityType === 'skill'
    agent.level = isSkill ? '大区 S3' : '大区 L3'
    agent.status = isSkill ? '已发布' : '已升层'
    appendAgentMessage({ role: 'assistant', text: `客观数据校验通过，系统已完成归档。${agent.name} 现在作为大区公共资产开放复用，原操作人仍保留养护人身份。`, source: `${isSkill ? '发布升档' : '升层'}流程 3/3 · 即时生效` })
    agentManagement.stage = 'complete'
  }
}

function bumpVersion(version = 'v1.0') {
  const match = /v(\d+)\.(\d+)/.exec(version)
  if (!match) return 'v1.1'
  return `v${match[1]}.${Number(match[2]) + 1}`
}

function operateResource(action, item) {
  if (!canOperateResource(item)) {
    showToast('当前账号仅可使用集团能力，无维护权限')
    return
  }
  if (action === '停用') {
    if (!isResourceDisabled(item)) disabledResourceIds.value.push(item.id)
    showToast(`${item.name} 已停用，可在维护记录中恢复`)
    return
  }
  const label = action === '发起升级' ? '已发起升级评审' : action === '发布升档' ? '已提交发布升档' : '已进入微调工作台'
  showToast(`${item.name} ${label}`)
}

function createKnowledgeFromConversation() {
  if (!currentConversation.value) {
    showToast('请先进入一个对话后再沉淀个人知识库')
    return
  }
  openKnowledgeManagement('create', null, 'personal')
}

function operatePersonalKnowledge(action, item) {
  openKnowledgeManagement(action, item, 'personal')
}

function operateGroupKnowledge(action, item) {
  if (!item || !hasPermission(item.contentPermission)) {
    showToast('补资料和维护均要求该知识库的内容查看权限')
    return
  }
  if (action === 'supplement' && !canSupplementGroupKnowledge.value) {
    showToast('当前账号可查看并维护该知识库，但没有补资料权限')
    return
  }
  openKnowledgeManagement(action, item, 'group')
}

function openKnowledgeGrantDialog(item = null) {
  if (!canGrantGroupKnowledge.value) {
    showToast('当前账号没有知识库管理责任配权权限')
    return
  }
  knowledgeGrantTargetId.value = item?.id ?? groupKnowledgeRecords.value[0]?.id ?? null
  const currentSteward = selectedGrantKnowledge.value?.stewardIds?.[0]
  knowledgeGrantAssigneeId.value = knowledgeContentViewers.value.some((account) => account.id === currentSteward)
    ? currentSteward
    : knowledgeContentViewers.value[0]?.id ?? ''
  openKnowledgeManagement('grant', selectedGrantKnowledge.value, 'group')
}

function openKnowledgeManagement(action, item, scope) {
  if (!currentConversation.value) {
    showToast('请先进入一个对话后再执行知识库操作')
    return
  }
  knowledgeManagement.active = true
  knowledgeManagement.action = action
  knowledgeManagement.scope = scope
  knowledgeManagement.knowledgeBaseId = item?.id ?? null
  knowledgeManagement.input = ''
  knowledgeManagement.stage = 'request'
  rightTab.value = 'knowledge'
  const label = action === 'create' ? '请描述希望从当前对话沉淀哪些经验、规则或资料。' : action === 'supplement' ? '请说明要补充哪些材料及其适用范围。' : action === 'maintain' ? '请说明本次要维护的内容、版本或失效项。' : '请核对管理对象编号和待指定的维护责任人；本操作不会展示或授予库内业务内容。'
  knowledgeManagement.messages = [{ id: `${Date.now()}-knowledge-open`, role: 'assistant', text: label, source: `${action === 'grant' ? `治理编号 · ${item?.governanceCode} · ` : ''}当前对话 · ${currentConversation.value.title}` }]
}

function closeKnowledgeManagement() {
  knowledgeManagement.active = false
  knowledgeManagement.stage = 'idle'
  knowledgeManagement.input = ''
  rightTab.value = 'knowledge'
}

function sendKnowledgeManagementMessage() {
  const text = knowledgeManagement.input.trim()
  if (!text) return
  knowledgeManagement.messages.push({ id: `${Date.now()}-knowledge-user`, role: 'user', text })
  knowledgeManagement.input = ''
  knowledgeManagement.stage = 'confirm'
  const actionText = knowledgeManagement.action === 'create' ? '已生成个人知识库沉淀方案，请确认新建。' : knowledgeManagement.action === 'supplement' ? '已记录补材料范围，请确认写入。' : knowledgeManagement.action === 'maintain' ? '已生成维护变更单，请确认提交。' : '已记录责任分配说明，请确认登记。'
  knowledgeManagement.messages.push({ id: `${Date.now()}-knowledge-confirm`, role: 'assistant', text: actionText, source: '对话式确认 · 全程留痕' })
}

async function confirmKnowledgeManagement() {
  const action = knowledgeManagement.action
  let knowledgeBase = managedKnowledgeBase.value
  if (action === 'create') {
    const name = `${currentConversation.value.title}沉淀库`
    knowledgeBase = personalKnowledge.value.find((item) => item.name === name)
    if (!knowledgeBase) {
      knowledgeBase = { id: `pkb-${Date.now()}`, name, meta: '个人知识库 · 由当前对话新建', updated: '刚刚' }
      personalKnowledge.value.unshift(knowledgeBase)
      selectedPersonalKnowledgeId.value = knowledgeBase.id
    }
  }
  if (!knowledgeBase) return
  const assignee = accountRecords.value.find((account) => account.id === knowledgeGrantAssigneeId.value)
  if (action === 'grant' && (!assignee || !assignee.permissions.includes(knowledgeBase.contentPermission))) {
    showToast('配权不能授予内容查看权；只能从已有查看权人员中指定维护责任人')
    return
  }
  if (action === 'grant' && !knowledgeBase.stewardIds.includes(assignee.id)) knowledgeBase.stewardIds.push(assignee.id)
  const operation = action === 'create' ? KnowledgeGovernanceOperations.createFromConversation : action === 'grant' ? KnowledgeGovernanceOperations.assignSteward : action === 'supplement' ? KnowledgeGovernanceOperations.supplement : KnowledgeGovernanceOperations.maintain
  const backendProjectId = await ensureProjectRegistered(currentProject.value)
  const receipt = knowledgeGovernanceApplicationApi.acceptCommand({
    operation,
    accountId: currentAccount.value.id,
    actor: { tenant_id: platformApi.tenantId, user_id: currentAccount.value.id, authenticated: true },
    knowledgeBaseId: knowledgeBase.id,
    projectId: backendProjectId,
    conversationId: currentConversation.value?.id ?? null,
    payload: action === 'grant'
      ? { project_id: backendProjectId, conversation_id: currentConversation.value?.id ?? null, assigneeId: assignee.id, governanceOnly: true, contentAccessGranted: false, prerequisite: knowledgeBase.contentPermission, request: knowledgeManagement.messages.findLast((message) => message.role === 'user')?.text }
      : { project_id: backendProjectId, conversation_id: currentConversation.value?.id ?? null, scope: knowledgeManagement.scope, request: knowledgeManagement.messages.findLast((message) => message.role === 'user')?.text, contentPermissionVerified: action !== 'create', automaticMaintenanceDuty: action !== 'create' },
  })
  try {
    await receipt.requestPromise
  } catch (error) {
    showToast(accountError(error))
    return
  }
  if (action === 'grant') knowledgeGovernanceAudit.value.unshift({ id: receipt.traceId, code: knowledgeBase.governanceCode, assignee: assignee.name, at: '刚刚' })
  knowledgeManagement.messages.push({ id: `${Date.now()}-knowledge-done`, role: 'assistant', text: action === 'create' ? `已从当前对话新建“${knowledgeBase.name}”。` : action === 'grant' ? `已登记 ${assignee.name} 的维护责任；内容查看权未发生变化。` : `已提交 ${knowledgeBase.name} 的${action === 'supplement' ? '补材料' : '维护'}操作。`, source: `受理回执 · ${receipt.traceId}` })
  knowledgeManagement.stage = 'complete'
}

function downloadOutputFileLegacy(file) {
  const content = `${file.name}\n生成于 AI 工作台\n追踪编号：L4-260721-1042\n`
  const url = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${file.name}.txt`
  link.click()
  URL.revokeObjectURL(url)
  showToast(`已下载 ${file.name}`)
}

async function downloadOutputFile(file) {
  if (!currentProject.value || !currentConversation.value || !currentAccount.value.id) return
  try {
    const backendProjectId = await ensureProjectRegistered(currentProject.value)
    const content = `${file.name}\n生成来源：AI 工作台\n账户：${currentAccount.value.id}\nProject：${currentProject.value.id}\n对话：${currentConversation.value.id}\n`
    const result = await platformApi.createGeneratedFile({
      account_id: currentAccount.value.id,
      project_id: backendProjectId,
      conversation_id: currentConversation.value.id,
      original_name: `${file.name}.txt`,
      content,
      content_type: 'text/plain;charset=utf-8',
    })
    const downloadUrl = result.data?.download_url
    if (downloadUrl) {
      const baseUrl = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? '').replace(/\/$/, '')
      const link = document.createElement('a')
      link.href = `${baseUrl}${downloadUrl}`
      link.download = `${file.name}.txt`
      link.click()
    }
    showToast(`已生成后端文件资产：${file.name}`)
  } catch (error) {
    showToast(accountError(error))
  }
}

function citeOutputFile(file) {
  inputText.value = `请引用《${file.name}》并继续修改。`
  showToast('产出文件已引用回当前对话')
}

function citeProjectFile(file) {
  if (!currentConversation.value) return
  inputText.value = `请引用 Project 文件《${file.name}》并结合当前对话继续处理。`
  showToast('Project 文件已引用到当前对话')
}

function projectIcon(type) {
  if (type === 'report') return ClipboardList
  if (type === 'team') return Users
  return FolderKanban
}

onMounted(() => {
  restoreSession()
})
</script>

<template>
  <div v-if="authState.restoring" class="auth-shell"></div>
  <div v-else-if="!authState.loggedIn" class="auth-shell">
    <section class="auth-panel">
      <div class="auth-brand"><span class="auth-mark"><Sparkles :size="18" /></span><div><strong>AI 工作台</strong></div></div>
        <div class="auth-copy"><span class="eyebrow">WORKBENCH</span><h1>{{ authState.mode === 'login' ? '进入你的工作台' : '创建一个工作账号' }}</h1></div>
      <div class="auth-tabs"><button :class="{ active: authState.mode === 'login' }" @click="switchAuthMode('login')"><LogIn :size="14" />登录</button><button :class="{ active: authState.mode === 'register' }" @click="switchAuthMode('register')"><Plus :size="14" />创建账号</button></div>
      <form v-if="authState.mode === 'login'" class="auth-form" @submit.prevent="submitLogin">
        <label><span>登录名、账号 ID 或姓名</span><div class="auth-input"><UserRound :size="15" /><input v-model="authState.loginId" autocomplete="username" placeholder="请输入登录标识" /></div></label>
        <label><span>密码</span><div class="auth-input"><KeyRound :size="15" /><input v-model="authState.password" autocomplete="current-password" type="password" placeholder="请输入密码" /></div></label>
        <p v-if="authState.error" class="auth-error"><CircleAlert :size="14" />{{ authState.error }}</p>
        <button class="auth-submit" type="submit" :disabled="authState.loading">{{ authState.loading ? '正在登录...' : '进入工作台' }}<ChevronRight :size="16" /></button>
      </form>
      <form v-else class="auth-form" @submit.prevent="submitRegistration">
        <label><span>登录名</span><div class="auth-input"><UserRound :size="15" /><input v-model="authState.loginName" autocomplete="username" placeholder="唯一登录名" /></div></label>
        <div class="auth-form-grid"><label><span>姓名</span><div class="auth-input"><UserRound :size="15" /><input v-model="authState.name" autocomplete="name" placeholder="例如：陈晓" /></div></label><label><span>所属部门</span><div class="auth-input"><Building2 :size="15" /><input v-model="authState.department" placeholder="例如：华南大区业务部" /></div></label></div>
        <label><span>岗位</span><div class="auth-input"><ClipboardList :size="15" /><select v-model="authState.role"><option>业务员</option><option>采购员</option><option>财务人员</option><option>项目成员</option></select></div></label>
        <div class="auth-form-grid"><label><span>设置密码</span><div class="auth-input"><KeyRound :size="15" /><input v-model="authState.password" autocomplete="new-password" type="password" placeholder="至少 6 位" /></div></label><label><span>确认密码</span><div class="auth-input"><KeyRound :size="15" /><input v-model="authState.confirmPassword" autocomplete="new-password" type="password" placeholder="再次输入密码" /></div></label></div>
        <p v-if="authState.error" class="auth-error"><CircleAlert :size="14" />{{ authState.error }}</p>
        <button class="auth-submit" type="submit" :disabled="authState.loading">{{ authState.loading ? '正在创建...' : '创建并进入工作台' }}<ChevronRight :size="16" /></button>
      </form>
      <div class="auth-security"><ShieldCheck :size="14" /><span>已预留统一身份认证接口，权限由账号 ID 返回。</span></div>
    </section>
  </div>
  <div v-else class="page-shell" @click.self="accountMenuOpen = false">
    <div class="workbench">
      <header class="topbar">
        <div class="brand"><Sparkles :size="17" /><strong>AI 工作台</strong></div>
        <div class="context-pill"><Command :size="13" />{{ contextLabel }}</div>
        <button class="search-trigger" title="全局搜索" @click="showToast('全局搜索接口已预留')"><Search :size="14" /><span>搜索 Project、对话和文件</span><kbd>Ctrl K</kbd></button>
        <div class="top-spacer"></div>
        <button class="icon-button" title="消息通知" @click="showToast(`当前有 ${notificationUnreadCount} 条未读消息`)" ><Bell :size="17" /><i v-if="notificationUnreadCount"></i></button>
        <div class="account-switch">
          <button class="account-trigger" @click.stop="accountMenuOpen = !accountMenuOpen">
            <span class="avatar">{{ currentAccount.avatar }}</span>
            <span><strong>{{ currentAccount.name }}</strong><small>{{ currentAccount.role }}</small></span>
            <ChevronDown :size="14" />
          </button>
          <div v-if="accountMenuOpen" class="account-menu">
            <div class="menu-note"><ShieldCheck :size="14" /><span>权限由登录账号返回。</span></div>
            <button v-for="account in accountRecords" :key="account.id" :class="{ active: account.id === currentAccountId }" @click="selectAccount(account.id)">
              <span class="avatar small">{{ account.avatar }}</span>
              <span><strong>{{ account.name }}</strong><small>{{ account.role }} · {{ account.id }}</small></span>
              <Check v-if="account.id === currentAccountId" :size="15" />
            </button>
            <button class="account-logout" @click="logout"><LogOut :size="15" /><span><strong>退出当前账号</strong><small>返回登录页面</small></span></button>
          </div>
        </div>
      </header>

      <div class="columns">
        <aside class="left-column">
          <section class="notice-panel">
            <div class="section-title"><span><Bell :size="14" />提醒</span><b>{{ notificationUnreadCount }}</b></div>
            <button v-for="item in visibleNotifications" :key="item.id" class="notice-row" @click="openNotification(item)">
              <i :class="[item.tone, { unread: notificationIsUnread(item) }]"></i>
              <span><strong>{{ item.title }}</strong><small>{{ notificationKind(item) }} · {{ item.meta }}</small></span>
              <em class="notice-kind">{{ notificationKind(item) }}</em>
              <ChevronRight :size="12" />
            </button>
            <p v-if="visibleNotifications.length" class="notice-note">点击任意提醒，直接进入对应业务对话处理。</p>
          </section>

          <section class="projects-panel">
            <div class="section-title projects-title"><span>我的 PROJECT <em>{{ fixedWorkspaceProjects.length }} 固定 · {{ customWorkspaceProjects.length }} 自建</em></span><button title="新建 Project" @click="openProjectDialog"><Plus :size="13" />新建</button></div>
            <label class="rail-project-search"><Search :size="13" /><input v-model="projectSearch" placeholder="搜 Project / 对话名……" /></label>
            <div v-for="project in filteredWorkspaceProjects" :key="project.id" class="project-node" :class="{ open: expandedProjectIds.has(project.id) && !accountCenterActive, fixed: project.fixed }">
              <button class="project-row" @click="toggleProject(project.id)">
                <component :is="projectIcon(project.type)" :size="15" />
                <span><strong>{{ project.name }}</strong><small>{{ project.description }}</small></span>
                <em v-if="project.fixed">固定</em>
                <ChevronRight :size="13" class="arrow" />
              </button>
              <div v-if="expandedProjectIds.has(project.id) && !accountCenterActive" class="project-children">
                <button :class="{ active: isProjectCenter }" @click="selectProject(project.id)">
                  <LayoutDashboard :size="13" /><span>Project 专属指挥中心</span>
                </button>
                <div class="child-label">对话列表</div>
                <template v-for="group in groupConversationsForProject(project)" :key="group.label">
                  <div class="conversation-time-group">{{ group.label }}</div>
                  <div v-for="conversation in group.conversations" :key="conversation.id" class="conversation-list-item" :class="{ unread: conversationUnread(conversation), pinned: conversation.pinned }">
                    <button class="conversation-nav-row" :class="{ active: currentConversationId === conversation.id }" @click="selectConversation(project.id, conversation.id)"><MessageSquare :size="12" /><span>{{ conversation.title }}</span><i v-if="conversationUnread(conversation)" class="unread-dot"></i><span class="conversation-status-icon" :class="conversationStatusKind(conversation)" :title="conversationStatusLabel(conversation)"><CheckCircle2 v-if="conversationStatusKind(conversation) === 'done'" :size="12" /><Clock3 v-else-if="conversationStatusKind(conversation) === 'pending'" :size="12" /><CircleAlert v-else :size="12" /></span></button>
                    <div class="conversation-more"><button class="conversation-more-trigger" title="更多操作" @click.stop="toggleConversationMenu(conversation.id)"><MoreHorizontal :size="14" /></button><div v-if="conversationMenuId === conversation.id" class="conversation-more-menu" @click.stop><button @click="pinConversation(conversation); conversationMenuId = null"><Pin :size="13" />{{ conversation.pinned ? '取消置顶' : '置顶会话' }}</button><button @click="toggleConversationUnread(conversation); conversationMenuId = null"><CircleDotDashed :size="13" />{{ conversationUnread(conversation) ? '标记已读' : '标记未读' }}</button><button @click="renameConversation(conversation); conversationMenuId = null"><MoreHorizontal :size="13" />重命名</button><button class="danger" @click="deleteConversation(conversation); conversationMenuId = null"><X :size="13" />删除会话</button></div></div>
                  </div>
                </template>
                <button class="new-conversation" @click="selectProject(project.id); openConversationDialog()"><Plus :size="12" />新建对话</button>
              </div>
            </div>
            <div v-if="!filteredWorkspaceProjects.length" class="project-empty-state"><FolderKanban :size="18" /><span>未找到匹配的 Project</span></div>
          </section>

          <section class="account-center-entry">
            <button :class="{ active: accountCenterActive }" @click="selectAccountCenter">
              <Command :size="16" />
              <span><strong>综合指挥中心</strong><small>统管账号下全部 Projects</small></span>
              <ChevronRight :size="13" />
            </button>
          </section>
        </aside>

        <main class="center-column">
          <header class="center-header">
            <div>
              <span class="eyebrow">{{ knowledgeManagement.active ? 'KNOWLEDGE MANAGEMENT CONVERSATION' : agentManagement.active ? 'AGENT MANAGEMENT CONVERSATION' : accountCenterActive ? 'ACCOUNT COMMAND CENTER' : currentProject.name }}</span>
              <h1>{{ knowledgeManagement.active ? (knowledgeManagement.action === 'grant' ? `知识库治理 · ${selectedGrantKnowledge?.governanceCode ?? '管理责任配权'}` : knowledgeManagement.action === 'create' ? '从当前对话新建知识库' : `知识库${knowledgeManagement.action === 'supplement' ? '补材料' : '维护'} · ${managedKnowledgeBase?.name ?? ''}`) : agentManagement.active ? (managedCapability ? `${agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'} 管理 · ${managedCapability.name}` : `新建自创 ${agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'}`) : accountCenterActive ? '综合指挥中心' : currentConversation ? currentConversation.title : 'Project 专属指挥中心' }}</h1>
            </div>
            <div class="header-actions">
              <span class="scope-chip"><ShieldCheck :size="13" />{{ currentAccount.role }}权限</span>
              <button v-if="knowledgeManagement.active" class="icon-button plain" title="返回当前对话" @click="closeKnowledgeManagement"><X :size="16" /></button>
              <button v-else-if="agentManagement.active" class="icon-button plain" title="返回当前对话" @click="closeAgentManagement"><X :size="16" /></button>
              <button class="icon-button plain" title="更多操作"><MoreHorizontal :size="17" /></button>
            </div>
          </header>

          <template v-if="knowledgeManagement.active">
            <div class="center-scroll agent-chat-stream knowledge-chat-stream">
              <div class="assistant-intro agent-management-intro">
                <span class="ai-avatar"><Database :size="18" /></span>
                <div>
                  <strong>{{ knowledgeManagement.action === 'grant' ? `管理责任配权 · ${selectedGrantKnowledge?.governanceCode ?? ''}` : knowledgeManagement.action === 'create' ? '从当前对话沉淀个人知识库' : managedKnowledgeBase?.name }}</strong>
                  <p>{{ knowledgeManagement.action === 'grant' ? '仅登记维护责任；管理权和内容查看权严格隔离。' : knowledgeManagement.action === 'create' ? '根据当前对话沉淀经验、规则或资料，个人知识库与集团库保持独立。' : '请用自然语言说明本次变更，系统会在确认后写入治理留痕。' }}</p>
                </div>
              </div>
              <div v-for="message in knowledgeManagement.messages" :key="message.id" class="message agent-management-message" :class="message.role">
                <span v-if="message.role === 'assistant'" class="message-avatar"><Database :size="16" /></span>
                <div class="bubble"><p>{{ message.text }}</p><small v-if="message.source"><Activity :size="11" />{{ message.source }}</small></div>
                <span v-if="message.role === 'user'" class="message-avatar user">{{ currentAccount.avatar }}</span>
              </div>
              <section v-if="knowledgeManagement.stage === 'confirm'" class="agent-operation-card creation-card knowledge-operation-card">
                <div class="operation-heading"><span><ShieldCheck :size="15" />{{ knowledgeManagement.action === 'grant' ? '管理责任配权确认' : knowledgeManagement.action === 'create' ? '知识库沉淀确认' : `知识库${knowledgeManagement.action === 'supplement' ? '补材料' : '维护'}确认` }}</span><em>对话留痕</em></div>
                <template v-if="knowledgeManagement.action === 'grant'">
                  <label class="knowledge-management-select"><span>管理对象编号</span><select v-model="knowledgeGrantTargetId"><option v-for="item in groupKnowledgeRecords" :key="item.id" :value="item.id">{{ item.governanceCode }}</option></select></label>
                  <label class="knowledge-management-select"><span>指定维护责任人</span><select v-model="knowledgeGrantAssigneeId"><option v-for="account in knowledgeContentViewers" :key="account.id" :value="account.id">{{ account.name }} · 已具备内容查看权</option></select></label>
                  <div class="governance-rule"><LockKeyhole :size="14" /><span><strong>内容访问独立校验</strong><small>只登记维护责任，不展示或授予库内业务内容；候选人需已有内容查看权。</small></span></div>
                </template>
                <div v-else class="creation-name"><strong>{{ managedKnowledgeBase?.name ?? `${currentConversation?.title ?? '当前对话'}沉淀库` }}</strong><small>{{ knowledgeManagement.scope === 'group' ? '集团知识库：内容查看权已绑定日常维护责任' : '个人知识库：仅归当前账号管理' }} · 当前对话：{{ currentConversation?.title }}</small></div>
                <div class="operation-actions"><button @click="closeKnowledgeManagement">取消</button><button class="primary" @click="confirmKnowledgeManagement">{{ knowledgeManagement.action === 'grant' ? '确认登记责任' : knowledgeManagement.action === 'create' ? '确认新建知识库' : '确认提交' }}</button></div>
              </section>
            </div>
            <footer class="composer agent-management-composer knowledge-management-composer"><div class="composer-tools"><span><Database :size="12" />{{ knowledgeManagement.action === 'create' ? '描述要从当前对话沉淀的知识与规则' : knowledgeManagement.action === 'supplement' ? '描述要补充的资料及适用范围' : knowledgeManagement.action === 'maintain' ? '描述维护内容、版本或失效项' : '说明责任分配原因；不输入或展示业务内容' }}</span><span><History :size="12" />操作全程留痕</span></div><div class="composer-input"><textarea v-model="knowledgeManagement.input" rows="2" placeholder="用自然语言说明本次知识库操作…" @keydown.ctrl.enter.prevent="sendKnowledgeManagementMessage"></textarea><button class="send-button" title="发送知识库管理指令" :disabled="!knowledgeManagement.input.trim()" @click="sendKnowledgeManagementMessage"><Send :size="17" /></button></div></footer>
          </template>

          <template v-else-if="agentManagement.active">
            <div class="center-scroll agent-chat-stream">
              <div v-if="managedCapability" class="assistant-intro agent-management-intro"><span class="ai-avatar"><component :is="agentManagement.capabilityType === 'skill' ? Puzzle : Bot" :size="18" /></span><div><strong>{{ managedCapability.name }}</strong><p>{{ managedCapability.scope === 'group' ? '集团共享标准版' : '个人自建 / 个人变种' }} · {{ managedCapability.version }} · {{ managedCapability.status }}</p></div></div>
              <div v-else class="assistant-intro agent-management-intro creation-intro"><span class="ai-avatar"><Sparkles :size="18" /></span><div><strong>从自然语言创建个人 {{ agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent' }}</strong><p>零代码、免审批；候选资产、测试结果和保存确认都在当前对话完成。</p></div></div>
              <div v-if="managedCapability" class="agent-ledger-strip"><span><b>{{ managedCapability.calls }}</b><small>累计调用</small></span><span><b>{{ managedCapability.adoption }}</b><small>方案采纳率</small></span><span><b>{{ managedCapability.consistency }}</b><small>多模型一致性</small></span><span><b>{{ managedCapability.version }}</b><small>当前版本</small></span></div>
              <div v-for="message in agentManagement.messages" :key="message.id" class="message agent-management-message" :class="message.role">
                <span v-if="message.role === 'assistant'" class="message-avatar"><Bot :size="16" /></span>
                <div class="bubble"><p>{{ message.text }}</p><small v-if="message.source"><Activity :size="11" />{{ message.source }}</small></div>
                <span v-if="message.role === 'user'" class="message-avatar user">{{ currentAccount.avatar }}</span>
              </div>

              <section v-if="agentManagement.stage === 'create-assembly'" class="agent-operation-card creation-card">
                <div class="operation-heading"><span><Sparkles :size="15" />候选资产装配</span><em>去重匹配</em></div>
                <div class="creation-name"><strong>{{ agentManagement.createTitle }}</strong><small>创建人：{{ currentAccount.name }} · 仅个人可用 · 无需审批</small></div>
                <div class="assembly-list"><div v-for="asset in agentManagement.createAssets" :key="asset.label"><span>{{ asset.label }}</span><strong>{{ asset.value }}</strong><small>{{ asset.detail }}</small></div></div>
                <label class="human-confirm"><input v-model="agentManagement.humanConfirm" type="checkbox" /><span><strong>发送通报前必须人工确认</strong><small>关闭后将按已声明的执行规则自动处理；可在测试前再次调整。</small></span></label>
                <div class="operation-actions"><button @click="refineNewAgentRules">再调调规则</button><button class="primary" @click="beginAgentCreationValidation">开始跨模型测试</button></div>
              </section>

              <section v-if="agentManagement.stage === 'create-validation'" class="agent-operation-card creation-card">
                <div class="operation-heading"><span><CheckCircle2 :size="15" />跨模型一致性测试</span><em>候选 v1.0</em></div>
                <div class="model-check"><button :class="{ active: agentManagement.primaryModel === '通义千问 3.5' }" @click="agentManagement.primaryModel = '通义千问 3.5'"><span><strong>通义千问 3.5</strong><small>一致性 97.2% · 推荐主力</small></span><CheckCircle2 :size="15" /></button><button :class="{ active: agentManagement.backupModel === 'DeepSeek V3' }" @click="agentManagement.backupModel = 'DeepSeek V3'"><span><strong>DeepSeek V3</strong><small>一致性 96.8% · 推荐备用</small></span><CheckCircle2 :size="15" /></button><button><span><strong>豆包</strong><small>一致性 96.5% · 文案口径已核对</small></span><CheckCircle2 :size="15" /></button></div>
                <label class="human-confirm"><input v-model="agentManagement.humanConfirm" type="checkbox" /><span><strong>关键通报先人工确认</strong><small>模型选择与执行策略将随候选版本一并留痕。</small></span></label>
                <div class="operation-actions"><button @click="refineNewAgentRules">再调调规则</button><button class="primary" @click="confirmAgentManagement">确认存入台账</button></div>
              </section>

              <section v-if="agentManagement.stage === 'fine-preview'" class="agent-operation-card fine-preview-card">
                <div class="operation-heading"><span><Wrench :size="15" />个人微调预览</span><em>不影响公共标准版</em></div>
                <div class="preview-grid"><div><span>调前</span><strong>客户风险权重 35%</strong><small>案例命中率 78%</small></div><div class="after"><span>调后</span><strong>客户风险权重 48%</strong><small>案例命中率 89%</small></div></div>
                <div class="case-preview"><span><CheckCircle2 :size="13" />真实案例 A：高风险客户提前 3 天识别</span><span><CheckCircle2 :size="13" />真实案例 B：低优先级误报减少 21%</span><span><CheckCircle2 :size="13" />真实案例 C：建议口径与人工判断一致</span></div>
                <div class="operation-actions"><button @click="agentManagement.stage = 'fine-request'">继续调整</button><button class="primary" @click="confirmAgentManagement">确认保存个人变种</button></div>
              </section>

              <section v-if="agentManagement.stage === 'upgrade-validation'" class="agent-operation-card upgrade-card">
                <div class="operation-heading"><span><Settings2 :size="15" />多模型一致性校验</span><em>候选 {{ bumpVersion(managedCapability.version) }}</em></div>
                <div class="model-check"><button :class="{ active: agentManagement.primaryModel === '通义千问 3.5' }" @click="agentManagement.primaryModel = '通义千问 3.5'"><span><strong>通义千问 3.5</strong><small>一致性 97.3% · 推荐主力</small></span><CheckCircle2 :size="15" /></button><button :class="{ active: agentManagement.backupModel === 'DeepSeek V3' }" @click="agentManagement.backupModel = 'DeepSeek V3'"><span><strong>DeepSeek V3</strong><small>一致性 96.9% · 推荐备用</small></span><CheckCircle2 :size="15" /></button><button><span><strong>GPT-5</strong><small>一致性 96.7% · 结果可复核</small></span><CheckCircle2 :size="15" /></button></div>
                <label class="human-confirm"><input v-model="agentManagement.humanConfirm" type="checkbox" /><span><strong>关键动作先人工确认</strong><small>启用后，预警通报和外部执行将在发送前挂起确认。</small></span></label>
                <div class="operation-actions"><button @click="agentManagement.stage = 'upgrade-request'">继续补充能力</button><button class="primary" @click="confirmAgentManagement">确认保存升级版本</button></div>
              </section>

              <section v-if="['promote', 'publish'].includes(agentManagement.action) && agentManagement.stage !== 'complete'" class="agent-operation-card promotion-card">
                <div class="operation-heading"><span><ArrowUpCircle :size="15" />{{ agentManagement.action === 'publish' ? '发布升档' : '推荐升层' }}</span><em>仅客观数据</em></div>
                <div class="promotion-steps"><div :class="{ done: agentManagement.promotionStep >= 1, active: agentManagement.promotionStep === 0 }"><i>1</i><span><strong>养护人发起申请</strong><small>当前账号：{{ currentAccount.name }}</small></span></div><div :class="{ done: agentManagement.promotionStep >= 2, active: agentManagement.promotionStep === 1 }"><i>2</i><span><strong>经验推广官校验</strong><small>调用 {{ managedCapability.calls }} · 采纳 {{ managedCapability.adoption }} · 一致性 {{ managedCapability.consistency }}</small></span></div><div :class="{ active: agentManagement.promotionStep === 2 }"><i>3</i><span><strong>系统归档为公共资产</strong><small>开放大区复用，原操作人保留养护人身份</small></span></div></div>
                <div class="operation-actions"><button class="primary" @click="advancePromotionFlow">{{ agentManagement.promotionStep === 0 ? `提交${agentManagement.action === 'publish' ? '发布' : '升层'}申请` : '完成客观校验并归档' }}</button></div>
              </section>

              <section v-if="agentManagement.stage === 'disable-confirm'" class="agent-operation-card disable-card">
                <div class="operation-heading"><span><Power :size="15" />确认停用</span><em>可恢复，不删除</em></div>
                <p>停用后全部场景都不可调用，但历史版本、使用数据和复用记录完整保留。已发布或被复用的 Agent 只能停用，不能直接删除。</p>
                <div class="operation-actions"><button @click="closeAgentManagement">取消停用</button><button class="danger" @click="confirmAgentManagement">确认停用</button></div>
              </section>
            </div>
            <footer class="composer agent-management-composer"><div class="composer-tools"><span><Bot :size="12" />{{ agentManagement.action === 'create' ? `描述要创建的 ${agentManagement.capabilityType === 'skill' ? 'Skill 输入、规则与输出' : 'Agent、目标效果与执行规则'}` : agentManagement.action === 'fineTune' ? '描述微调需求' : agentManagement.action === 'upgrade' ? '描述新增能力与规则' : ['promote', 'publish'].includes(agentManagement.action) ? `补充${agentManagement.action === 'publish' ? '发布升档' : '升层'}说明或直接提交` : '输入确认、取消或恢复指令' }}</span><span><History :size="12" />版本全程留痕</span></div><div class="composer-input"><textarea v-model="agentManagement.input" rows="2" placeholder="用自然语言描述你的管理需求…" @keydown.ctrl.enter.prevent="sendAgentManagementMessage"></textarea><button class="send-button" :title="`发送 ${agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'} 管理指令`" :disabled="!agentManagement.input.trim()" @click="sendAgentManagementMessage"><Send :size="17" /></button></div></footer>
          </template>

          <template v-else-if="accountCenterActive">
            <div class="center-scroll command-chat-stream">
              <div class="assistant-intro command-intro"><span class="ai-avatar"><Command :size="18" /></span><div><strong>{{ currentAccount.name }}的综合指挥中心</strong><p>用自然语言下发账号级指令；系统在当前权限范围内统筹 Project、待办与风险，并全程留痕。</p></div></div>
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
                    <button v-for="project in commandProjectRollup" :key="project.id" class="command-project-row" @click="selectProject(project.id)">
                      <span class="command-project-main"><component :is="projectIcon(project.type)" :size="15" /><span><strong>{{ project.name }}</strong><small>{{ project.total }} 个会话 · {{ project.active }} 个需关注</small></span></span>
                      <span class="command-progress"><i><b :style="{ width: `${project.progress}%` }"></b></i><em>{{ project.progress }}%</em></span>
                      <ChevronRight :size="14" />
                    </button>
                  </div>
                </article>
                <article class="command-panel command-alert-panel">
                  <div class="content-heading"><span><CircleAlert :size="15" />预警归集</span><small>{{ commandAlerts.length }} 条待跟进</small></div>
                  <button v-for="alert in commandAlerts" :key="alert.id" class="command-alert-row" :class="alert.tone" @click="dispatchAlert(alert)">
                    <span class="alert-mark"><CircleAlert :size="14" /></span><span><strong>{{ alert.title }}</strong><small>{{ alert.detail }}</small><em>{{ alert.age }} · {{ alert.severity }}级</em></span><ChevronRight :size="14" />
                  </button>
                </article>
              </section>
              <section class="command-panel command-queue-panel">
                <div class="content-heading"><span><ListTodo :size="15" />统一任务队列</span><small>{{ commandPendingCount }} 项待调度 · 人工 / 自动全程留痕</small></div>
                <div class="command-queue-head"><span>事项</span><span>来源与负责人</span><span>到期 / 状态</span><span>动作</span></div>
                <div v-for="task in commandDispatches" :key="task.id" class="command-queue-row" :class="task.tone">
                  <button class="queue-title" @click="openCommandRecord(task)"><strong>{{ task.title }}</strong><small>{{ task.kind }}环节 · {{ task.projectId === 'project-team' ? '我的队伍' : workspaceProjects.find((project) => project.id === task.projectId)?.name }}</small></button>
                  <span class="queue-owner">{{ task.owner }}</span>
                  <span class="queue-status"><small>{{ task.due }}</small><em>{{ task.status }}</em></span>
                  <button class="queue-action" @click="dispatchCommandTask(task)">{{ task.status === '已完成' ? '查看' : task.kind === '自动' ? '执行' : '催办' }}</button>
                </div>
              </section>
              <div v-for="message in commandMessages" :key="message.id" class="message command-message" :class="message.role">
                <span v-if="message.role === 'assistant'" class="message-avatar"><Command :size="16" /></span>
                <div class="bubble"><p>{{ message.text }}</p><button v-if="message.action" class="command-action" @click="selectProject(message.action.projectId)"><FolderKanban :size="13" />{{ message.action.label }}</button><small v-if="message.source"><Activity :size="11" />{{ message.source }}</small></div>
                <span v-if="message.role === 'user'" class="message-avatar user">{{ currentAccount.avatar }}</span>
              </div>
              <section class="overview-section command-overview"><div class="content-heading"><span><FolderKanban :size="15" />Project 运行概览</span><small>点击进入专属指挥中心</small></div><button v-for="project in workspaceProjects" :key="project.id" class="overview-project" @click="selectProject(project.id)"><component :is="projectIcon(project.type)" :size="17" /><span><strong>{{ project.name }}</strong><small>{{ project.description }}</small></span><em>{{ project.status }}</em><ChevronRight :size="14" /></button></section>
            </div>
            <footer class="composer command-composer"><div class="composer-tools"><span><Command :size="12" />账号级自然语言指令</span><span><ShieldCheck :size="12" />{{ currentAccount.role }}权限范围</span></div><div class="composer-input"><textarea v-model="commandInput" rows="2" placeholder="例如：汇总今天需要我处理的风险，并催办未提交的工作汇报" @keydown.ctrl.enter.prevent="sendCommandMessage"></textarea><button class="send-button" title="发送指令" :disabled="!commandInput.trim()" @click="sendCommandMessage"><Send :size="17" /></button></div></footer>
          </template>

          <template v-else-if="isProjectCenter">
          <div class="center-scroll command-view">
            <div class="assistant-intro project-intro">
              <span class="ai-avatar"><LayoutDashboard :size="18" /></span>
              <div><strong>{{ currentProject.name }} · 专属指挥中心</strong><p>{{ currentProject.description }}。本中心只统筹当前 Project 内的对话、任务和资料。</p></div>
            </div>
            <div class="metric-grid">
              <div v-for="metric in visibleProjectMetrics" :key="metric.label" :class="metric.tone"><span>{{ metric.label }}</span><b>{{ metric.value }}</b><small>{{ currentProject.type === 'team' && !canReadTeam ? '需要队伍管理权限' : '当前 Project' }}</small></div>
            </div>

            <div class="command-control-strip project-control-strip">
              <span><LayoutDashboard :size="14" />项目全局视图</span>
              <span class="live-indicator"><i></i>本 Project 实时同步</span>
              <small>仅汇总当前 Project 的 {{ visibleConversations.length }} 个会话、{{ projectPendingCount }} 项待处理事项与 {{ projectAlertRecords.length }} 条预警</small>
            </div>
            <section class="command-dashboard-grid project-dashboard-grid">
              <article class="command-panel command-portfolio-panel">
                <div class="content-heading"><span><MessageSquare :size="15" />本项目对话汇总</span><small>{{ visibleConversations.length }} 个会话</small></div>
                <button v-for="conversation in visibleConversations" :key="conversation.id" class="command-project-row" @click="selectConversation(currentProject.id, conversation.id)">
                  <span class="command-project-main"><MessageSquare :size="15" /><span><strong>{{ conversation.title }}</strong><small>{{ conversation.updated }} · {{ conversation.files?.length ?? 0 }} 个文件</small></span></span>
                  <em v-if="conversation.badge">{{ conversation.badge }}</em><ChevronRight :size="14" />
                </button>
                <p v-if="!visibleConversations.length" class="empty-search">当前 Project 还没有可访问的对话</p>
              </article>
              <article class="command-panel command-alert-panel">
                <div class="content-heading"><span><CircleAlert :size="15" />项目预警归集</span><small>{{ projectAlertRecords.length }} 条</small></div>
                <button v-for="alert in projectAlertRecords" :key="alert.id" class="command-alert-row" :class="alert.tone" @click="selectConversation(currentProject.id, alert.conversationId)">
                  <span class="alert-mark"><CircleAlert :size="14" /></span><span><strong>{{ alert.title }}</strong><small>{{ alert.owner }} · {{ alert.due }}</small><em>{{ alert.status }}</em></span><ChevronRight :size="14" />
                </button>
                <p v-if="!projectAlertRecords.length" class="empty-search">当前 Project 暂无待跟进预警</p>
              </article>
            </section>
            <section class="command-panel command-queue-panel project-queue-panel">
              <div class="content-heading"><span><ListTodo :size="15" />项目任务与待办</span><small>{{ projectPendingCount }} 项待调度 · 仅限当前 Project</small></div>
              <div class="command-queue-head"><span>事项</span><span>处理方式</span><span>更新时间 / 状态</span><span>动作</span></div>
              <div v-for="task in projectDispatchRecords" :key="task.id" class="command-queue-row" :class="task.tone">
                <button class="queue-title" @click="selectConversation(currentProject.id, task.conversationId)"><strong>{{ task.title }}</strong><small>{{ task.owner }}</small></button>
                <span class="queue-owner">{{ task.kind }}环节</span><span class="queue-status"><small>{{ task.due }}</small><em>{{ task.status }}</em></span><button class="queue-action" @click="selectConversation(currentProject.id, task.conversationId)">定位</button>
              </div>
              <p v-if="!projectDispatchRecords.length" class="empty-search">当前 Project 暂无任务记录</p>
            </section>
            <div v-for="message in currentProjectCommandMessages" :key="message.id" class="message command-message project-command-message" :class="message.role">
              <span v-if="message.role === 'assistant'" class="message-avatar"><Command :size="16" /></span><div class="bubble"><p>{{ message.text }}</p><button v-if="message.action" class="command-action" @click="selectConversation(message.action.projectId, message.action.conversationId)"><FolderKanban :size="13" />{{ message.action.label }}</button><small v-if="message.source"><Activity :size="11" />{{ message.source }}</small></div><span v-if="message.role === 'user'" class="message-avatar user">{{ currentAccount.avatar }}</span>
            </div>

            <section v-if="currentProject.type === 'report'" class="domain-section">
              <div class="content-heading"><span><ClipboardList :size="15" />{{ canReadTeamReports ? '汇报管理' : '我的本周汇报' }}</span><small>权限来自 {{ currentAccount.id }}</small></div>
              <template v-if="canReadTeamReports">
                <button v-for="member in teamMembers" :key="member.id" class="member-row" @click="selectConversation('project-report', 'report-team-review')">
                  <span class="member-avatar">{{ member.name.slice(0, 1) }}</span><span><strong>{{ member.name }}</strong><small>{{ member.role }} · {{ member.activity }}</small></span><em :class="{ pending: member.report === '待提交' }">{{ member.report }}</em><ChevronRight :size="14" />
                </button>
              </template>
              <div v-else class="personal-report">
                <div><span>本周完成</span><strong>客户拜访 4 次，推进重点事项 3 项</strong></div>
                <div><span>下周计划</span><strong>完成续约方案并推进客户确认</strong></div>
                <div><span>需要协助</span><strong>绿城续约价格需要负责人拍板</strong></div>
                <button @click="selectConversation('project-report', 'report-current')">继续完善汇报</button>
              </div>
            </section>

            <section v-else-if="currentProject.type === 'team'" class="domain-section">
              <div class="content-heading"><span><Users :size="15" />队伍状态</span><small>账号权限实时判定</small></div>
              <template v-if="canReadTeam">
                <div class="team-table-head"><span>成员</span><span>状态</span><span>工作负载</span><span>汇报</span></div>
                <div v-for="member in teamMembers" :key="member.id" class="team-table-row">
                  <span><i class="status-dot" :class="member.status"></i><b>{{ member.name }}</b><small>{{ member.role }}</small></span><span>{{ member.status }}</span><span><i class="load-track"><b :style="{ width: `${member.load}%` }"></b></i>{{ member.load }}%</span><span :class="{ pending: member.report === '待提交' }">{{ member.report }}</span>
                </div>
              </template>
              <div v-else class="permission-empty"><span><Users :size="24" /></span><strong>当前账号没有队伍管理权限</strong><p>“我的队伍”Project 仍然保留。正式系统会根据账号 ID 返回可管理成员范围。</p></div>
            </section>

            <section v-else class="domain-section">
              <div class="content-heading"><span><ListTodo :size="15" />当前对话与任务</span><small>{{ visibleConversations.length }} 个对话</small></div>
              <button v-for="conversation in visibleConversations" :key="conversation.id" class="conversation-summary" @click="selectConversation(currentProject.id, conversation.id)">
                <MessageSquare :size="15" /><span><strong>{{ conversation.title }}</strong><small>{{ conversation.updated }} · 文件已同步</small></span><em v-if="conversation.badge">{{ conversation.badge }}</em><ChevronRight :size="14" />
              </button>
            </section>
          </div>
          <footer class="composer command-composer project-command-composer">
            <div class="composer-tools"><span><Command :size="12" />Project 级统筹指令</span><span><ShieldCheck :size="12" />仅限 {{ currentProject.name }} 权限范围</span></div>
            <div class="composer-input"><textarea v-model="projectCommandInput" rows="2" placeholder="例如：汇总本 Project 待处理事项并催办负责人" @keydown.ctrl.enter.prevent="sendProjectCommandMessage"></textarea><button class="send-button" title="发送项目指令" :disabled="!projectCommandInput.trim()" @click="sendProjectCommandMessage"><Send :size="17" /></button></div>
          </footer>
          </template>

          <template v-else>
            <div class="center-scroll chat-stream">
              <div v-for="message in currentMessages" :key="message.id" class="message" :class="message.role">
                <span v-if="message.role === 'assistant'" class="message-avatar"><Bot :size="17" /></span>
                <div class="bubble" :class="{ receipt: message.receipt }">
                  <p>{{ message.text }}</p>
                  <div v-if="message.task" class="intent-card">
                    <div><span><Sparkles :size="14" />{{ message.task.title }}</span><em>{{ message.task.label || '意图确认' }}</em></div>
                    <ul><li v-for="item in message.task.items" :key="item"><CheckCircle2 :size="13" />{{ item }}</li></ul>
                    <div class="intent-actions"><button :disabled="message.task.status !== 'pending'" @click="showToast('调整范围入口已预留')">调整范围</button><button class="primary" :disabled="message.task.status !== 'pending'" @click="confirmIntent(message)">{{ message.task.status === 'running' ? '执行中...' : message.task.status === 'confirmed' ? '已确认' : '确认并执行' }}</button></div>
                  </div>
                  <small v-if="message.source"><Activity :size="11" />{{ message.source }}</small>
                </div>
                <span v-if="message.role === 'user'" class="message-avatar user">{{ currentAccount.avatar }}</span>
              </div>
            </div>
            <footer class="composer">
              <div v-if="currentConversation && currentContextUsage >= 75" class="context-alert" :class="contextLevel(currentConversation)"><CircleAlert :size="14" /><span><strong>上下文已占 {{ currentContextUsage }}%</strong><small>{{ currentContextUsage >= 90 ? '即将触达存储上限，请立即沉淀并续接对话。' : '接近存储上限，建议沉淀当前要点后新建续接对话。' }}</small></span><button @click="startFreshConversationFromContext">沉淀并续接</button></div>
              <div class="composer-tools composer-media-tools">
                <button title="添加文件" @click="openAttachmentPicker('file')"><Paperclip :size="14" />文件</button>
                <button title="添加图片" @click="openAttachmentPicker('image')"><ImageIcon :size="14" />图片</button>
                <button title="拍照" @click="openAttachmentPicker('camera')"><Camera :size="14" />拍照</button>
                <button title="语音输入" :class="{ recording: voiceRecording }" @click="toggleVoiceRecording"><Mic :size="14" />{{ voiceRecording ? '结束录音' : '语音' }}</button>
                <input ref="fileInput" class="visually-hidden-input" type="file" multiple @change="attachConversationFiles($event, '文件')" />
                <input ref="imageInput" class="visually-hidden-input" type="file" accept="image/*" multiple @change="attachConversationFiles($event, '图片')" />
                <input ref="cameraInput" class="visually-hidden-input" type="file" accept="image/*" capture="environment" @change="attachConversationFiles($event, '照片')" />
                <span><ShieldCheck :size="12" />按 {{ currentAccount.role }}权限发送</span>
              </div>
              <div class="composer-input">
                <textarea v-model="inputText" rows="2" placeholder="向 AI 提出需求，Enter 换行，点击发送提交..." @keydown.ctrl.enter.prevent="sendMessage"></textarea>
                <button class="send-button" title="发送" :disabled="!inputText.trim()" @click="sendMessage"><Send :size="17" /></button>
              </div>
            </footer>
          </template>
        </main>

        <aside class="right-column">
          <div class="right-main">
            <header class="right-header">
              <div><span>{{ rightTabLabel }}</span><strong>{{ currentConversation ? currentConversation.title : accountCenterActive ? '账号范围' : currentProject.name }}</strong></div>
              <span v-if="currentConversation" class="sync-state"><i></i>随对话同步</span>
            </header>

            <div class="right-scroll">
              <template v-if="rightTab === 'session'">
                <template v-if="currentConversation">
                  <div class="session-state"><span><Activity :size="14" />执行中</span><em>62%</em><small>当前卡点：负责人确认</small></div>
                  <div class="context-storage-state" :class="contextLevel(currentConversation)"><CircleDotDashed :size="14" /><span><strong>上下文占用 {{ currentContextUsage }}%</strong><small>{{ contextHint(currentConversation) }}</small></span><b>{{ currentContextUsage }}%</b></div>
                  <section class="session-section">
                    <div class="resource-heading"><span><History :size="14" />业务链路</span><em>5 个节点</em></div>
                    <div class="session-timeline">
                      <article v-for="node in sessionTimeline" :key="node.title" class="timeline-node" :class="[node.status, node.kind === '人工' ? 'manual' : 'automatic']">
                        <div class="timeline-mark"><i></i><span>{{ node.time }}</span></div>
                        <div class="timeline-content"><div><strong>{{ node.title }}</strong><em>{{ node.kind }}</em></div><p>{{ node.detail }}</p><small><FileText :size="11" />核对依据：{{ node.evidence }}</small></div>
                      </article>
                    </div>
                  </section>
                  <section class="session-section asset-section">
                    <div class="resource-heading"><span><Database :size="14" />已沉淀业务资产</span><em>可追溯</em></div>
                    <div class="asset-tags"><span>客户画像</span><span>专家经验</span><span>采购单据</span><span>业务规则</span><span>流程模板</span></div>
                    <p>标准作业流程、客户资料和操作证据都绑定追踪编号；重复校验与流转由系统自动承担。</p>
                  </section>
                </template>
                <template v-else-if="accountCenterActive">
                  <div class="session-state account-session-state"><span><Activity :size="14" />全局流程同步</span><em>{{ commandPendingCount }}</em><small>待调度事项 · 账号级跨 Project 视图</small></div>
                  <section class="session-section">
                    <div class="resource-heading"><span><History :size="14" />全局处理留痕</span><em>{{ commandDispatches.length }} 条</em></div>
                    <div class="session-timeline command-timeline">
                      <button v-for="task in commandDispatches.slice(0, 4)" :key="task.id" class="timeline-node project-flow-node" :class="[task.status === '已完成' ? 'done' : 'blocked', task.kind === '人工' ? 'manual' : 'automatic']" @click="openCommandRecord(task)">
                        <div class="timeline-mark"><i></i><span>{{ task.kind }}</span></div>
                        <div class="timeline-content"><div><strong>{{ task.title }}</strong><em>{{ task.status }}</em></div><p>{{ task.owner }} · {{ task.due }}</p><small><FileText :size="11" />来源：{{ workspaceProjects.find((project) => project.id === task.projectId)?.name ?? 'Project' }}</small></div>
                      </button>
                    </div>
                  </section>
                  <section class="session-section asset-section"><div class="resource-heading"><span><CircleAlert :size="14" />待跟进预警</span><em>{{ commandAlerts.length }} 条</em></div><div class="asset-tags command-alert-tags"><button v-for="alert in commandAlerts" :key="alert.id" @click="dispatchAlert(alert)">{{ alert.severity }} · {{ alert.title }}</button></div></section>
                </template>
                <template v-else-if="isProjectCenter">
                  <div class="session-state"><span><Activity :size="14" />{{ projectFlowRecords.filter((item) => item.status === 'blocked').length ? '存在待处理卡点' : '流程正常' }}</span><em>{{ projectFlowRecords.length }}</em><small>按对话聚合的全链路数据</small></div>
                  <section class="session-section"><div class="resource-heading"><span><History :size="14" />Project 处理链路</span><em>{{ projectFlowRecords.length }} 条</em></div><div class="session-timeline"><button v-for="node in projectFlowRecords" :key="node.conversationId" class="timeline-node project-flow-node" :class="[node.status, node.kind === '人工' ? 'manual' : 'automatic']" @click="selectConversation(currentProject.id, node.conversationId)"><div class="timeline-mark"><i></i><span>可下钻</span></div><div class="timeline-content"><div><strong>{{ node.title }}</strong><em>{{ node.kind }}</em></div><p>{{ node.detail }}</p><small><FileText :size="11" />{{ node.evidence }}</small></div></button></div></section>
                </template>
                <div v-else class="right-empty"><CircleDotDashed :size="25" /><strong>选择一个 Project 查看流程数据</strong><p>综合指挥中心不混合不同 Project 的流程记录。</p></div>
              </template>

              <template v-else-if="rightTab === 'agent'">
                <section class="capability-section">
                  <div class="capability-heading"><span><Building2 :size="14" />集团共用</span><em>{{ agentRecords.filter((item) => item.scope === 'group').length }}</em></div>
                  <article v-for="item in agentRecords.filter((item) => item.scope === 'group')" :key="item.id" class="capability-card agent-ledger-card" :class="{ disabled: isResourceDisabled(item), selected: selectedAgentId === item.id }" @click="selectAgent(item)">
                    <div class="capability-title"><span class="capability-icon agent"><Bot :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.level }} · {{ item.version }} · {{ isResourceDisabled(item) ? '已停用' : item.status }}</small></span><em>集团</em></div>
                    <p>{{ item.detail }}</p><div class="ledger-meta"><span>调用 {{ item.calls }}</span><span>采纳 {{ item.adoption }}</span><span>一致性 {{ item.consistency }}</span></div><div class="recommendation"><ArrowUpCircle :size="13" />{{ item.recommendation }}</div>
                    <div class="capability-actions agent-actions"><button :disabled="!canOperateResource(item) || isResourceDisabled(item)" @click.stop="openAgentManagement(item, 'fineTune')"><Wrench :size="12" />微调</button><button :disabled="!canOperateResource(item) || isResourceDisabled(item)" @click.stop="openAgentManagement(item, 'upgrade')"><Settings2 :size="12" />发起升级</button><button title="集团资产无需再次升层" :disabled="true" @click.stop><ArrowUpCircle :size="12" />推荐升层</button><button class="danger-action" :disabled="!canOperateResource(item) || isResourceDisabled(item)" @click.stop="openAgentManagement(item, 'disable')"><Power :size="12" />停用</button></div>
                  </article>
                </section>
                <section class="capability-section">
                  <div class="capability-heading"><span><UserRound :size="14" />个人自建</span><button class="new-agent-button" title="新建 Agent" @click="openAgentCreation"><Plus :size="13" />新建 Agent</button></div>
                  <article v-for="item in agentRecords.filter((item) => item.scope === 'personal')" :key="item.id" class="capability-card agent-ledger-card" :class="{ disabled: isResourceDisabled(item), selected: selectedAgentId === item.id }" @click="selectAgent(item)">
                    <div class="capability-title"><span class="capability-icon agent"><Bot :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.level }} · {{ item.version }} · {{ isResourceDisabled(item) ? '已停用' : item.status }}</small></span><em>个人</em></div>
                    <p>{{ item.detail }}</p><div class="ledger-meta"><span>调用 {{ item.calls }}</span><span>采纳 {{ item.adoption }}</span><span>一致性 {{ item.consistency }}</span></div><div class="recommendation"><ArrowUpCircle :size="13" />{{ item.recommendation }}</div>
                    <div class="capability-actions agent-actions"><button :disabled="isResourceDisabled(item)" @click.stop="openAgentManagement(item, 'fineTune')"><Wrench :size="12" />微调</button><button :disabled="isResourceDisabled(item)" @click.stop="openAgentManagement(item, 'upgrade')"><Settings2 :size="12" />发起升级</button><button :disabled="isResourceDisabled(item)" @click.stop="openAgentManagement(item, 'promote')"><ArrowUpCircle :size="12" />推荐升层</button><button class="danger-action" :disabled="isResourceDisabled(item)" @click.stop="openAgentManagement(item, 'disable')"><Power :size="12" />停用</button></div>
                  </article>
                </section>
              </template>

              <template v-else-if="rightTab === 'skill'">
                <section class="capability-section">
                  <div class="capability-heading"><span><Building2 :size="14" />集团共用</span><em>{{ skillRecords.filter((item) => item.scope === 'group').length }}</em></div>
                  <article v-for="item in skillRecords.filter((item) => item.scope === 'group')" :key="item.id" class="capability-card agent-ledger-card" :class="{ disabled: isResourceDisabled(item), selected: selectedSkillId === item.id }" @click="selectSkill(item)">
                    <div class="capability-title"><span class="capability-icon skill"><Puzzle :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.level }} · {{ item.version }} · {{ isResourceDisabled(item) ? '已停用' : item.status }}</small></span><em>集团</em></div>
                    <p>{{ item.detail }}</p><div class="ledger-meta"><span>调用 {{ item.calls }}</span><span>采纳 {{ item.adoption }}</span><span>一致性 {{ item.consistency }}</span></div><div class="recommendation"><ArrowUpCircle :size="13" />{{ item.recommendation }}</div>
                    <div class="capability-actions agent-actions"><button :disabled="!canOperateResource(item) || isResourceDisabled(item)" @click.stop="openSkillManagement(item, 'fineTune')"><Wrench :size="12" />微调</button><button title="集团 Skill 无需再次发布" disabled><ArrowUpCircle :size="12" />发布升档</button><button class="danger-action" :disabled="!canOperateResource(item) || isResourceDisabled(item)" @click.stop="openSkillManagement(item, 'disable')"><Power :size="12" />停用</button></div>
                  </article>
                </section>
                <section class="capability-section">
                  <div class="capability-heading"><span><UserRound :size="14" />个人自建</span><button class="new-agent-button" title="新建 Skill" @click="openSkillCreation"><Plus :size="13" />新建 Skill</button></div>
                  <article v-for="item in skillRecords.filter((item) => item.scope === 'personal')" :key="item.id" class="capability-card agent-ledger-card" :class="{ disabled: isResourceDisabled(item), selected: selectedSkillId === item.id }" @click="selectSkill(item)">
                    <div class="capability-title"><span class="capability-icon skill"><Puzzle :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.level }} · {{ item.version }} · {{ isResourceDisabled(item) ? '已停用' : item.status }}</small></span><em>个人</em></div>
                    <p>{{ item.detail }}</p><div class="ledger-meta"><span>调用 {{ item.calls }}</span><span>采纳 {{ item.adoption }}</span><span>一致性 {{ item.consistency }}</span></div><div class="recommendation"><ArrowUpCircle :size="13" />{{ item.recommendation }}</div>
                    <div class="capability-actions agent-actions"><button :disabled="isResourceDisabled(item)" @click.stop="openSkillManagement(item, 'fineTune')"><Wrench :size="12" />微调</button><button :disabled="isResourceDisabled(item)" @click.stop="openSkillManagement(item, 'publish')"><ArrowUpCircle :size="12" />发布升档</button><button class="danger-action" :disabled="isResourceDisabled(item)" @click.stop="openSkillManagement(item, 'disable')"><Power :size="12" />停用</button></div>
                  </article>
                </section>
              </template>

              <template v-else-if="rightTab === 'knowledge'">
                <template v-if="isProjectCenter">
                  <section class="resource-section project-knowledge-scope">
                    <div class="resource-heading"><span><BookOpen :size="14" />当前 Project 知识库</span><em>{{ currentProject.knowledge.length }}</em></div>
                    <article v-for="file in currentProject.knowledge" :key="file.name" class="file-row static"><span class="file-icon group"><Database :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.meta }} · 仅限当前 Project</small></span></article>
                    <p v-if="!currentProject.knowledge.length" class="empty-search">当前 Project 尚未上传知识库文件</p>
                  </section>
                  <div class="separation-note project-note"><LockKeyhole :size="13" />项目级指挥中心仅可访问当前 Project 知识库与项目会话数据</div>
                </template>
                <template v-else>
                <div class="knowledge-switch"><button :class="{ active: knowledgeScope === 'personal' }" @click="knowledgeScope = 'personal'"><UserRound :size="13" />个人知识库</button><button :class="{ active: knowledgeScope === 'group' }" @click="knowledgeScope = 'group'"><Building2 :size="13" />集团知识库</button></div>
                <template v-if="knowledgeScope === 'personal'">
                  <section class="resource-section">
                    <div class="resource-heading"><span><BookOpen :size="14" />我的知识库</span><em>{{ personalKnowledge.length }}</em></div>
                    <article v-for="item in personalKnowledge" :key="item.id" class="group-knowledge-card" :class="{ selected: selectedPersonalKnowledgeId === item.id }" @click="selectedPersonalKnowledgeId = item.id"><div><span class="file-icon"><BookOpen :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.meta }} · {{ item.updated }}</small></span></div><div class="group-knowledge-actions"><button @click.stop="operatePersonalKnowledge('supplement', item)"><Upload :size="12" />补材料</button><button @click.stop="operatePersonalKnowledge('maintain', item)"><Settings2 :size="12" />维护</button></div></article>
                  </section>
                  <button class="upload-button" :disabled="!currentConversation" @click="createKnowledgeFromConversation"><Sparkles :size="14" />根据当前对话新建</button>
                  <div class="separation-note"><ShieldCheck :size="13" />只归属于账号 {{ currentAccount.id }}；新建、补材料和维护均留存对话追踪编号，不与集团库或 Project 库混用</div>
                </template>
                <template v-else>
                  <template v-if="canViewGroupKnowledge">
                    <section class="resource-section">
                      <div class="resource-heading"><span><Building2 :size="14" />有权查看的集团知识库</span><em>{{ visibleGroupKnowledge.length }}</em></div>
                      <article v-for="item in visibleGroupKnowledge" :key="item.id" class="group-knowledge-card"><div><span class="file-icon group"><Database :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.meta }} · 责任部门：{{ item.owner }}</small></span></div><div class="knowledge-duty"><ShieldCheck :size="12" />内容查看权已绑定日常维护责任</div><div class="group-knowledge-actions"><button v-if="canSupplementGroupKnowledge" @click="operateGroupKnowledge('supplement', item)"><Upload :size="12" />补资料</button><button @click="operateGroupKnowledge('maintain', item)"><Settings2 :size="12" />维护</button></div></article>
                    </section>
                    <section v-if="canGrantGroupKnowledge" class="grant-card"><div><ShieldPlus :size="16" /><span><strong>配权：指定维护责任人</strong><small>仅在已有内容查看权的人中分配责任，不新增或返回任何库内业务内容。</small></span></div><button @click="openKnowledgeGrantDialog()">配置管理责任</button></section>
                    <div class="separation-note project-note"><LockKeyhole :size="13" />配权 ≠ 看权；内容查看权决定页面可见，并自动承担日常维护责任。</div>
                  </template>
                   <template v-else-if="canGrantGroupKnowledge">
                     <section class="grant-card governance-card"><div><ShieldPlus :size="16" /><span><strong>可执行：管理责任配权</strong><small>配权不会赋予内容查看权，也不能绕过内容访问校验。</small></span></div><button @click="openKnowledgeGrantDialog()">进入配权工作台</button></section>
                    <section v-if="knowledgeGovernanceAudit.length" class="resource-section governance-audit"><div class="resource-heading"><span><History :size="14" />本次治理留痕</span><em>{{ knowledgeGovernanceAudit.length }}</em></div><div v-for="record in knowledgeGovernanceAudit" :key="record.id" class="file-row static"><span class="file-icon group"><ShieldCheck :size="15" /></span><span><strong>{{ record.code }} · 责任已登记</strong><small>{{ record.assignee }} · {{ record.at }} · {{ record.id }}</small></span></div></section>
                  </template>
                  <div v-else class="right-empty"><LockKeyhole :size="25" /><strong>当前账号没有集团知识库内容查看权限</strong><p>集团知识库不会因可见其他资源或拥有配权职责而展示内容；权限由账号 ID 和职责范围返回。</p></div>
                </template>
                </template>
              </template>

              <template v-else>
                <template v-if="currentConversation">
                   <label class="file-search"><Search :size="14" /><input v-model="fileSearch" placeholder="搜索当前对话文件名称" /></label>
                  <section class="resource-section"><div class="resource-heading"><span><Paperclip :size="14" />我上传的文件</span><em>{{ uploadedConversationFiles.length }}</em></div><div v-if="uploadedConversationFiles.length" class="file-list"><div v-for="file in uploadedConversationFiles" :key="file.name" class="file-row static"><span class="file-icon"><FileText :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.meta }}</small></span></div></div><p v-else class="empty-search">未找到匹配的上传文件</p></section>
                  <section class="resource-section"><div class="resource-heading"><span><FileOutput :size="14" />本对话产出的文件</span><em>{{ producedConversationFiles.length }}</em></div><article v-for="file in producedConversationFiles" :key="file.id" class="output-file"><div class="file-row static"><span class="file-icon output"><FileOutput :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.meta }}</small></span></div><div><button @click="downloadOutputFile(file)"><Download :size="12" />下载</button><button @click="citeOutputFile(file)"><MessageSquare :size="12" />引用进对话</button></div></article><p v-if="!producedConversationFiles.length" class="empty-search">未找到匹配的产出文件</p></section>
                  <section class="resource-section"><div class="resource-heading"><span><FolderKanban :size="14" />可引用的 Project 文件</span><em>{{ currentProject.knowledge.length }}</em></div><article v-for="file in currentProject.knowledge" :key="file.name" class="output-file"><div class="file-row static"><span class="file-icon group"><FileText :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.meta }} · 当前 Project 共享资料</small></span></div><div><button @click="citeProjectFile(file)"><MessageSquare :size="12" />引用进对话</button></div></article></section>
                </template>
                <template v-else-if="isProjectCenter">
                  <label class="file-search"><Search :size="14" /><input v-model="fileSearch" placeholder="搜索当前 Project 的文件名称" /></label>
                  <section class="resource-section"><div class="resource-heading"><span><FolderKanban :size="14" />Project 与会话文件</span><em>{{ projectFiles.length }}</em></div><button v-for="file in projectFiles" :key="file.id" class="file-row project-file" @click="file.conversationId ? selectConversation(currentProject.id, file.conversationId) : showToast('这是当前 Project 的共享文件，进入对话后可引用')"><span class="file-icon" :class="{ group: !file.conversationId }"><FileText :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.source }} · {{ file.meta }}</small></span><ChevronRight :size="12" /></button><p v-if="!projectFiles.length" class="empty-search">未找到匹配的 Project 文件</p></section>
                </template>
                <div v-else class="right-empty"><FileOutput :size="25" /><strong>选择一个 Project 查看文件</strong><p>文件按 Project 与对话两个范围分层；进入对话后可上传、下载和引用。</p></div>
              </template>
            </div>
          </div>

          <nav class="right-tabrail" aria-label="右栏功能">
            <button v-for="tab in visibleRightTabs" :key="tab.id" :title="tab.label" :class="{ active: rightTab === tab.id }" @click="rightTab = tab.id"><component :is="tab.icon" :size="17" /><span>{{ tab.label }}</span></button>
          </nav>
        </aside>
      </div>
    </div>
    <div v-if="projectDialogOpen" class="dialog-backdrop" @click.self="projectDialogOpen = false">
      <form class="creation-dialog" @submit.prevent="createProject">
        <div class="dialog-icon"><FolderKanban :size="19" /></div>
        <div><span>新建 Project</span><h2>建立一个独立业务空间</h2><p>创建后将自动拥有 Project 专属指挥中心、对话列表和独立知识库。</p></div>
        <label>Project 名称<input v-model="newProjectName" autofocus maxlength="24" placeholder="例如：重点客户续约推进" /></label>
        <div class="dialog-actions"><button type="button" @click="projectDialogOpen = false">取消</button><button class="primary" type="submit" :disabled="!newProjectName.trim()">创建 Project</button></div>
      </form>
    </div>
    <div v-if="conversationDialogOpen" class="dialog-backdrop" @click.self="conversationDialogOpen = false">
      <form class="creation-dialog" @submit.prevent="createConversation">
        <div class="dialog-icon conversation"><MessageSquare :size="19" /></div>
        <div><span>新建对话</span><h2>{{ currentProject.name }}</h2><p>新对话从零开始，不携带历史上下文；后续消息会按本 Project 的权限和资料范围处理。</p></div>
        <label>对话主题<input v-model="newConversationTitle" autofocus maxlength="32" placeholder="例如：绿城续约下一步方案" /></label>
        <div class="dialog-actions"><button type="button" @click="conversationDialogOpen = false">取消</button><button class="primary" type="submit" :disabled="!newConversationTitle.trim()">创建对话</button></div>
      </form>
    </div>
    <transition name="toast"><div v-if="toast" class="toast"><CheckCircle2 :size="16" />{{ toast }}</div></transition>
  </div>
</template>
