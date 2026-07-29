<script setup>
import {
  Activity, ArrowUpCircle, BookOpen, Bot, Building2, CircleDotDashed,
  Cpu, Database, FileOutput, FileText, FolderKanban, History, LockKeyhole,
  MessageSquare, Paperclip, Plus, Puzzle, Search, Settings2, ShieldCheck,
  ShieldPlus, Sparkles, Upload, UserRound, ChevronRight, Download
} from '@lucide/vue'
import { sessionTimeline } from '@/utils/demo-data'

const props = defineProps({
  rightTab: { type: String, default: 'session' },
  currentProject: { type: Object, default: null },
  currentConversation: { type: Object, default: null },
  accountCenterActive: { type: Boolean, default: false },
  isProjectCenter: { type: Boolean, default: false },
  projectFlowRecords: { type: Array, default: () => [] },
  fileSearch: { type: String, default: '' },
  uploadedConversationFiles: { type: Array, default: () => [] },
  producedConversationFiles: { type: Array, default: () => [] },
  projectFiles: { type: Array, default: () => [] },
  generatedFiles: { type: Array, default: () => [] },
  rightTabLabel: { type: String, default: '' },
  agentRecords: { type: Array, default: () => [] },
  skillRecords: { type: Array, default: () => [] },
  selectedAgentId: { type: String, default: null },
  selectedSkillId: { type: String, default: null },
  disabledResourceIds: { type: Array, default: () => [] },
  knowledgeScope: { type: String, default: 'personal' },
  personalKnowledge: { type: Array, default: () => [] },
  groupKnowledgeRecords: { type: Array, default: () => [] },
  selectedPersonalKnowledgeId: { type: String, default: null },
  knowledgeGovernanceAudit: { type: Array, default: () => [] },
  hasPermission: { type: Function, required: true },
  currentAccountId: { type: String, default: null },
})

const emit = defineEmits([
  'update:rightTab', 'update:fileSearch', 'update:knowledgeScope',
  'update:selectedPersonalKnowledgeId',
  'selectConversation', 'selectProject',
  'openAgentCreation', 'openSkillCreation',
  'openAgentManagement', 'openSkillManagement',
  'selectSkill', 'selectAgent',
  'operatePersonalKnowledge', 'operateGroupKnowledge',
  'createKnowledgeFromConversation', 'openKnowledgeGrantDialog',
])

const canViewGroupKnowledge = props.hasPermission('knowledge.group.view')
const canSupplementGroupKnowledge = props.hasPermission('knowledge.group.supplement')
const canGrantGroupKnowledge = props.hasPermission('knowledge.group.grant')
const canManageGroupCapabilities = props.hasPermission('resource.group.manage')
const visibleGroupKnowledge = props.groupKnowledgeRecords.filter((item) => props.hasPermission(item.contentPermission))
const knowledgeContentViewers = [] // would come from auth store

function isResourceDisabled(item) {
  return props.disabledResourceIds.includes(item.id)
}

function canOperateResource(item) {
  return item.scope === 'personal' || canManageGroupCapabilities
}

function downloadOutputFile(file) {
  const content = `${file.name}\n生成于 AI 工作台\n追踪编号：L4-260721-1042\n`
  const url = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${file.name}.txt`
  link.click()
  URL.revokeObjectURL(url)
}

function citeOutputFile(file) {
  // This emits to parent for handling
  window.dispatchEvent(new CustomEvent('cite-output-file', { detail: file }))
}

function citeProjectFile(file) {
  window.dispatchEvent(new CustomEvent('cite-project-file', { detail: file }))
}

function showToastLocal(msg) {
  window.dispatchEvent(new CustomEvent('show-toast', { detail: msg }))
}
</script>

<template>
  <aside class="right-column">
    <div class="right-main">
      <header class="right-header">
        <div><span>{{ rightTabLabel }}</span><strong>{{ currentConversation ? currentConversation.title : accountCenterActive ? '账号范围' : currentProject?.name }}</strong></div>
        <span v-if="currentConversation" class="sync-state"><i></i>随对话同步</span>
      </header>

      <div class="right-scroll">
        <!-- Session Tab -->
        <template v-if="rightTab === 'session'">
          <template v-if="currentConversation">
            <div class="right-summary session-summary"><strong>会话数据</strong><span>追踪编号 L4-260721-1042 · 全程留痕</span><p>业务全链路、自动与人工环节、停滞卡点和核对依据均在此可追溯。</p></div>
            <div class="session-state"><span><Activity :size="14" />执行中</span><em>62%</em><small>当前卡点：负责人确认</small></div>
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
          <template v-else-if="isProjectCenter">
            <div class="right-summary session-summary"><strong>Project 流程数据</strong><span>{{ currentProject?.name }} · 汇总 {{ projectFlowRecords.length }} 个对话</span><p>汇总本 Project 的自动处理、人工确认、文件依据和卡点；点击节点可下钻至来源对话。</p></div>
            <div class="session-state"><span><Activity :size="14" />{{ projectFlowRecords.filter((item) => item.status === 'blocked').length ? '存在待处理卡点' : '流程正常' }}</span><em>{{ projectFlowRecords.length }}</em><small>按对话聚合的全链路数据</small></div>
            <section class="session-section"><div class="resource-heading"><span><History :size="14" />Project 处理链路</span><em>{{ projectFlowRecords.length }} 条</em></div><div class="session-timeline"><button v-for="node in projectFlowRecords" :key="node.conversationId" class="timeline-node project-flow-node" :class="[node.status, node.kind === '人工' ? 'manual' : 'automatic']" @click="$emit('selectConversation', currentProject?.id, node.conversationId)"><div class="timeline-mark"><i></i><span>可下钻</span></div><div class="timeline-content"><div><strong>{{ node.title }}</strong><em>{{ node.kind }}</em></div><p>{{ node.detail }}</p><small><FileText :size="11" />{{ node.evidence }}</small></div></button></div></section>
          </template>
          <div v-else class="right-empty"><CircleDotDashed :size="25" /><strong>选择一个 Project 查看流程数据</strong><p>综合指挥中心不混合不同 Project 的流程记录。</p></div>
        </template>

        <!-- Agent Tab -->
        <template v-else-if="rightTab === 'agent'">
          <div class="right-summary"><strong>Agent 台账</strong><span>选中 Agent 后，所有管理操作都进入中心对话完成</span><p>右栏只展示版本、调用与复用台账；不单独打开后台页面。</p></div>
          <div class="agent-operation-overview"><strong>6 项对话式操作</strong><span>新建</span><span>微调</span><span>升级</span><span>升层</span><span>停用</span><span>恢复</span></div>
          <section class="capability-section">
            <div class="capability-heading"><span><Building2 :size="14" />集团共用</span><em>{{ agentRecords.filter((item) => item.scope === 'group').length }}</em></div>
            <article v-for="item in agentRecords.filter((item) => item.scope === 'group')" :key="item.id" class="capability-card agent-ledger-card" :class="{ disabled: isResourceDisabled(item), selected: selectedAgentId === item.id }" @click="$emit('selectAgent', item)">
              <div class="capability-title"><span class="capability-icon agent"><Bot :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.level }} · {{ item.version }} · {{ isResourceDisabled(item) ? '已停用' : item.status }}</small></span><em>集团</em></div>
              <p>{{ item.detail }}</p><div class="ledger-meta"><span>调用 {{ item.calls }}</span><span>采纳 {{ item.adoption }}</span><span>一致性 {{ item.consistency }}</span></div><div class="recommendation"><ArrowUpCircle :size="13" />{{ item.recommendation }}</div>
              <div class="capability-actions agent-actions"><button :disabled="!canOperateResource(item) || isResourceDisabled(item)" @click.stop="$emit('openAgentManagement', item, 'fineTune')"><Wrench :size="12" />微调</button><button :disabled="!canOperateResource(item) || isResourceDisabled(item)" @click.stop="$emit('openAgentManagement', item, 'upgrade')"><Settings2 :size="12" />发起升级</button><button title="集团资产无需再次升层" :disabled="true" @click.stop><ArrowUpCircle :size="12" />推荐升层</button><button :disabled="!canOperateResource(item) || isResourceDisabled(item)" @click.stop="$emit('openAgentManagement', item, 'disable')" class="danger-action"><Power :size="12" />停用</button></div>
            </article>
          </section>
          <section class="capability-section">
            <div class="capability-heading"><span><UserRound :size="14" />个人自建</span><button class="new-agent-button" title="新建 Agent" @click="$emit('openAgentCreation', 'agent')"><Plus :size="13" />新建 Agent</button></div>
            <article v-for="item in agentRecords.filter((item) => item.scope === 'personal')" :key="item.id" class="capability-card agent-ledger-card" :class="{ disabled: isResourceDisabled(item), selected: selectedAgentId === item.id }" @click="$emit('selectAgent', item)">
              <div class="capability-title"><span class="capability-icon agent"><Bot :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.level }} · {{ item.version }} · {{ isResourceDisabled(item) ? '已停用' : item.status }}</small></span><em>个人</em></div>
              <p>{{ item.detail }}</p><div class="ledger-meta"><span>调用 {{ item.calls }}</span><span>采纳 {{ item.adoption }}</span><span>一致性 {{ item.consistency }}</span></div><div class="recommendation"><ArrowUpCircle :size="13" />{{ item.recommendation }}</div>
              <div class="capability-actions agent-actions"><button :disabled="isResourceDisabled(item)" @click.stop="$emit('openAgentManagement', item, 'fineTune')"><Wrench :size="12" />微调</button><button :disabled="isResourceDisabled(item)" @click.stop="$emit('openAgentManagement', item, 'upgrade')"><Settings2 :size="12" />发起升级</button><button :disabled="isResourceDisabled(item)" @click.stop="$emit('openAgentManagement', item, 'promote')"><ArrowUpCircle :size="12" />推荐升层</button><button :disabled="isResourceDisabled(item)" @click.stop="$emit('openAgentManagement', item, 'disable')" class="danger-action"><Power :size="12" />停用</button></div>
            </article>
          </section>
        </template>

        <!-- Skill Tab -->
        <template v-else-if="rightTab === 'skill'">
          <div class="right-summary"><strong>Skill 台账</strong><span>所有创建与维护操作均在中心对话完成</span><p>Skill 支持新建、微调、发布升档、停用与恢复；版本、测试和调用记录保持可追溯。</p></div>
          <div class="agent-operation-overview"><strong>5 项对话式操作</strong><span>新建</span><span>微调</span><span>发布升档</span><span>停用</span><span>恢复</span></div>
          <section class="capability-section">
            <div class="capability-heading"><span><Building2 :size="14" />集团共用</span><em>{{ skillRecords.filter((item) => item.scope === 'group').length }}</em></div>
            <article v-for="item in skillRecords.filter((item) => item.scope === 'group')" :key="item.id" class="capability-card agent-ledger-card" :class="{ disabled: isResourceDisabled(item), selected: selectedSkillId === item.id }" @click="$emit('selectSkill', item)">
              <div class="capability-title"><span class="capability-icon skill"><Puzzle :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.level }} · {{ item.version }} · {{ isResourceDisabled(item) ? '已停用' : item.status }}</small></span><em>集团</em></div>
              <p>{{ item.detail }}</p><div class="ledger-meta"><span>调用 {{ item.calls }}</span><span>采纳 {{ item.adoption }}</span><span>一致性 {{ item.consistency }}</span></div><div class="recommendation"><ArrowUpCircle :size="13" />{{ item.recommendation }}</div>
              <div class="capability-actions agent-actions"><button :disabled="!canOperateResource(item) || isResourceDisabled(item)" @click.stop="$emit('openSkillManagement', item, 'fineTune')"><Wrench :size="12" />微调</button><button title="集团 Skill 无需再次发布" disabled><ArrowUpCircle :size="12" />发布升档</button><button :disabled="!canOperateResource(item) || isResourceDisabled(item)" @click.stop="$emit('openSkillManagement', item, 'disable')" class="danger-action"><Power :size="12" />停用</button></div>
            </article>
          </section>
          <section class="capability-section">
            <div class="capability-heading"><span><UserRound :size="14" />个人自建</span><button class="new-agent-button" title="新建 Skill" @click="$emit('openSkillCreation')"><Plus :size="13" />新建 Skill</button></div>
            <article v-for="item in skillRecords.filter((item) => item.scope === 'personal')" :key="item.id" class="capability-card agent-ledger-card" :class="{ disabled: isResourceDisabled(item), selected: selectedSkillId === item.id }" @click="$emit('selectSkill', item)">
              <div class="capability-title"><span class="capability-icon skill"><Puzzle :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.level }} · {{ item.version }} · {{ isResourceDisabled(item) ? '已停用' : item.status }}</small></span><em>个人</em></div>
              <p>{{ item.detail }}</p><div class="ledger-meta"><span>调用 {{ item.calls }}</span><span>采纳 {{ item.adoption }}</span><span>一致性 {{ item.consistency }}</span></div><div class="recommendation"><ArrowUpCircle :size="13" />{{ item.recommendation }}</div>
              <div class="capability-actions agent-actions"><button :disabled="isResourceDisabled(item)" @click.stop="$emit('openSkillManagement', item, 'fineTune')"><Wrench :size="12" />微调</button><button :disabled="isResourceDisabled(item)" @click.stop="$emit('openSkillManagement', item, 'publish')"><ArrowUpCircle :size="12" />发布升档</button><button :disabled="isResourceDisabled(item)" @click.stop="$emit('openSkillManagement', item, 'disable')" class="danger-action"><Power :size="12" />停用</button></div>
            </article>
          </section>
        </template>

        <!-- Knowledge Tab -->
        <template v-else-if="rightTab === 'knowledge'">
          <div class="right-summary project-summary"><strong>知识库</strong><span>个人与集团知识库严格分开</span><p>库内内容查看、补资料、日常维护与管理责任配权分层校验，互不越权。</p></div>
          <div class="knowledge-switch"><button :class="{ active: knowledgeScope === 'personal' }" @click="$emit('update:knowledgeScope', 'personal')"><UserRound :size="13" />个人知识库</button><button :class="{ active: knowledgeScope === 'group' }" @click="$emit('update:knowledgeScope', 'group')"><Building2 :size="13" />集团知识库</button></div>
          <template v-if="knowledgeScope === 'personal'">
            <section class="resource-section">
              <div class="resource-heading"><span><BookOpen :size="14" />我的知识库</span><em>{{ personalKnowledge.length }}</em></div>
              <article v-for="item in personalKnowledge" :key="item.id" class="group-knowledge-card" :class="{ selected: selectedPersonalKnowledgeId === item.id }" @click="$emit('update:selectedPersonalKnowledgeId', item.id)"><div><span class="file-icon"><BookOpen :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.meta }} · {{ item.updated }}</small></span></div><div class="group-knowledge-actions"><button @click.stop="$emit('operatePersonalKnowledge', 'supplement', item)"><Upload :size="12" />补材料</button><button @click.stop="$emit('operatePersonalKnowledge', 'maintain', item)"><Settings2 :size="12" />维护</button></div></article>
            </section>
            <button class="upload-button" :disabled="!currentConversation" @click="$emit('createKnowledgeFromConversation')"><Sparkles :size="14" />根据当前对话新建</button>
            <div class="separation-note"><ShieldCheck :size="13" />只归属于账号 {{ currentAccountId }}；新建、补材料和维护均留存对话追踪编号，不与集团库或 Project 库混用</div>
          </template>
          <template v-else>
            <template v-if="canViewGroupKnowledge">
              <section class="resource-section">
                <div class="resource-heading"><span><Building2 :size="14" />有权查看的集团知识库</span><em>{{ visibleGroupKnowledge.length }}</em></div>
                <article v-for="item in visibleGroupKnowledge" :key="item.id" class="group-knowledge-card"><div><span class="file-icon group"><Database :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.meta }} · 责任部门：{{ item.owner }}</small></span></div><div class="knowledge-duty"><ShieldCheck :size="12" />内容查看权已绑定日常维护责任</div><div class="group-knowledge-actions"><button v-if="canSupplementGroupKnowledge" @click="$emit('operateGroupKnowledge', 'supplement', item)"><Upload :size="12" />补资料</button><button @click="$emit('operateGroupKnowledge', 'maintain', item)"><Settings2 :size="12" />维护</button></div></article>
              </section>
              <section v-if="canGrantGroupKnowledge" class="grant-card"><div><ShieldPlus :size="16" /><span><strong>配权：指定维护责任人</strong><small>仅在已有内容查看权的人中分配责任，不新增或返回任何库内业务内容。</small></span></div><button @click="$emit('openKnowledgeGrantDialog')">配置管理责任</button></section>
              <div class="separation-note project-note"><LockKeyhole :size="13" />配权 ≠ 看权；内容查看权决定页面可见，并自动承担日常维护责任。</div>
            </template>
            <template v-else-if="canGrantGroupKnowledge">
              <div class="right-summary governance-summary"><strong>知识库管理责任配权</strong><span>治理权限，不含内容查看权</span><p>当前账号只能为已有内容查看权的人员登记维护责任。此处不展示库名、文件、检索结果或业务资料。</p></div>
              <section class="grant-card governance-card"><div><ShieldPlus :size="16" /><span><strong>可执行：管理责任配权</strong><small>配权不会赋予内容查看权，也不能绕过内容访问校验。</small></span></div><button @click="$emit('openKnowledgeGrantDialog')">进入配权工作台</button></section>
              <section v-if="knowledgeGovernanceAudit.length" class="resource-section governance-audit"><div class="resource-heading"><span><History :size="14" />本次治理留痕</span><em>{{ knowledgeGovernanceAudit.length }}</em></div><div v-for="record in knowledgeGovernanceAudit" :key="record.id" class="file-row static"><span class="file-icon group"><ShieldCheck :size="15" /></span><span><strong>{{ record.code }} · 责任已登记</strong><small>{{ record.assignee }} · {{ record.at }} · {{ record.id }}</small></span></div></section>
            </template>
            <div v-else class="right-empty"><LockKeyhole :size="25" /><strong>当前账号没有集团知识库内容查看权限</strong><p>集团知识库不会因可见其他资源或拥有配权职责而展示内容；权限由账号 ID 和职责范围返回。</p></div>
          </template>
        </template>

        <!-- Files Tab -->
        <template v-else>
          <template v-if="currentConversation">
            <div class="right-summary"><strong>文件</strong><span>仅限当前对话上传与产出</span><p>可按文件名搜索。产出文件支持下载，或引用回当前对话继续修改。</p></div>
            <label class="file-search"><Search :size="14" /><input :value="fileSearch" placeholder="搜索当前对话文件名称" @input="$emit('update:fileSearch', $event.target.value)" /></label>
            <section class="resource-section"><div class="resource-heading"><span><Paperclip :size="14" />我上传的文件</span><em>{{ uploadedConversationFiles.length }}</em></div><div v-if="uploadedConversationFiles.length" class="file-list"><div v-for="file in uploadedConversationFiles" :key="file.name" class="file-row static"><span class="file-icon"><FileText :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.meta }}</small></span></div></div><p v-else class="empty-search">未找到匹配的上传文件</p></section>
            <section class="resource-section"><div class="resource-heading"><span><FileOutput :size="14" />本对话产出的文件</span><em>{{ producedConversationFiles.length }}</em></div><article v-for="file in producedConversationFiles" :key="file.id" class="output-file"><div class="file-row static"><span class="file-icon output"><FileOutput :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.meta }}</small></span></div><div><button @click="downloadOutputFile(file)"><Download :size="12" />下载</button><button @click="citeOutputFile(file)"><MessageSquare :size="12" />引用进对话</button></div></article><p v-if="!producedConversationFiles.length" class="empty-search">未找到匹配的产出文件</p></section>
            <section class="resource-section"><div class="resource-heading"><span><FolderKanban :size="14" />可引用的 Project 文件</span><em>{{ currentProject?.knowledge?.length ?? 0 }}</em></div><article v-for="file in (currentProject?.knowledge ?? [])" :key="file.name" class="output-file"><div class="file-row static"><span class="file-icon group"><FileText :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.meta }} · 当前 Project 共享资料</small></span></div><div><button @click="citeProjectFile(file)"><MessageSquare :size="12" />引用进对话</button></div></article></section>
          </template>
          <template v-else-if="isProjectCenter">
            <div class="right-summary"><strong>Project 文件</strong><span>{{ currentProject?.name }} · 文件与来源对话汇总</span><p>Project 文件、各会话上传文件均可搜索和下钻；进入对话后才可将资料引用进当前上下文。</p></div>
            <label class="file-search"><Search :size="14" /><input :value="fileSearch" placeholder="搜索当前 Project 的文件名称" @input="$emit('update:fileSearch', $event.target.value)" /></label>
            <section class="resource-section"><div class="resource-heading"><span><FolderKanban :size="14" />Project 与会话文件</span><em>{{ projectFiles.length }}</em></div><button v-for="file in projectFiles" :key="file.id" class="file-row project-file" @click="file.conversationId ? $emit('selectConversation', currentProject?.id, file.conversationId) : showToastLocal('这是当前 Project 的共享文件，进入对话后可引用')"><span class="file-icon" :class="{ group: !file.conversationId }"><FileText :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.source }} · {{ file.meta }}</small></span><ChevronRight :size="12" /></button><p v-if="!projectFiles.length" class="empty-search">未找到匹配的 Project 文件</p></section>
          </template>
          <div v-else class="right-empty"><FileOutput :size="25" /><strong>选择一个 Project 查看文件</strong><p>文件按 Project 与对话两个范围分层；进入对话后可上传、下载和引用。</p></div>
        </template>
      </div>
    </div>

    <nav class="right-tabrail" aria-label="右栏功能">
      <button title="会话数据" :class="{ active: rightTab === 'session' }" @click="$emit('update:rightTab', 'session')"><CircleDotDashed :size="21" /><span>会话数据</span></button>
      <button title="Agent" :class="{ active: rightTab === 'agent' }" @click="$emit('update:rightTab', 'agent')"><Cpu :size="21" /><span>Agent</span></button>
      <button title="Skill" :class="{ active: rightTab === 'skill' }" @click="$emit('update:rightTab', 'skill')"><Puzzle :size="21" /><span>Skill</span></button>
      <button title="知识库" :class="{ active: rightTab === 'knowledge' }" @click="$emit('update:rightTab', 'knowledge')"><Database :size="21" /><span>知识库</span></button>
      <button title="文件" :class="{ active: rightTab === 'files' }" @click="$emit('update:rightTab', 'files')"><FileOutput :size="21" /><span>文件</span></button>
    </nav>
  </aside>
</template>
