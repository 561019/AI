<script setup>
import { Activity, Database, History, LockKeyhole, Send, ShieldCheck } from '@lucide/vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToast } from '@/composables/useToast'

const knowledge = useKnowledgeStore()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const { showToast } = useToast()

function sendMessage() {
  knowledge.sendKnowledgeManagementMessage()
}

function confirmKnowledge() {
  knowledge.confirmKnowledgeManagement(
    auth.currentAccount?.id,
    workspace.currentConversation?.title ?? ''
  )
  showToast(knowledge.knowledgeManagement.stage === 'complete' ? '操作已完成' : '确认中...')
}

const knowledgeContentViewers = auth.accountRecords.filter((account) =>
  account.permissions.includes('knowledge.group.view')
)
</script>

<template>
  <div class="center-scroll agent-chat-stream knowledge-chat-stream">
    <div class="assistant-intro agent-management-intro">
      <span class="ai-avatar"><Database :size="18" /></span>
      <div>
        <strong>{{ knowledge.knowledgeManagement.action === 'grant' ? `管理责任配权 · ${knowledge.selectedGrantKnowledge?.governanceCode ?? ''}` : knowledge.knowledgeManagement.action === 'create' ? '从当前对话沉淀个人知识库' : knowledge.managedKnowledgeBase?.name }}</strong>
        <p>{{ knowledge.knowledgeManagement.action === 'grant' ? '仅登记维护责任；管理权和内容查看权严格隔离。' : knowledge.knowledgeManagement.action === 'create' ? '根据当前对话沉淀经验、规则或资料，个人知识库与集团库保持独立。' : '请用自然语言说明本次变更，系统会在确认后写入治理留痕。' }}</p>
      </div>
    </div>
    <div v-for="message in knowledge.knowledgeManagement.messages" :key="message.id" class="message agent-management-message" :class="message.role">
      <span v-if="message.role === 'assistant'" class="message-avatar"><Database :size="16" /></span>
      <div class="bubble"><p>{{ message.text }}</p><small v-if="message.source"><Activity :size="11" />{{ message.source }}</small></div>
      <span v-if="message.role === 'user'" class="message-avatar user">{{ auth.currentAccount?.avatar }}</span>
    </div>
    <section v-if="knowledge.knowledgeManagement.stage === 'confirm'" class="agent-operation-card creation-card knowledge-operation-card">
      <div class="operation-heading"><span><ShieldCheck :size="15" />{{ knowledge.knowledgeManagement.action === 'grant' ? '管理责任配权确认' : knowledge.knowledgeManagement.action === 'create' ? '知识库沉淀确认' : `知识库${knowledge.knowledgeManagement.action === 'supplement' ? '补材料' : '维护'}确认` }}</span><em>对话留痕</em></div>
      <template v-if="knowledge.knowledgeManagement.action === 'grant'">
        <label class="knowledge-management-select"><span>管理对象编号</span><select v-model="knowledge.knowledgeGrantTargetId"><option v-for="item in knowledge.groupKnowledgeRecords" :key="item.id" :value="item.id">{{ item.governanceCode }}</option></select></label>
        <label class="knowledge-management-select"><span>指定维护责任人</span><select v-model="knowledge.knowledgeGrantAssigneeId"><option v-for="account in knowledgeContentViewers" :key="account.id" :value="account.id">{{ account.name }} · 已具备内容查看权</option></select></label>
        <div class="governance-rule"><LockKeyhole :size="14" /><span><strong>内容访问独立校验</strong><small>只登记维护责任，不展示或授予库内业务内容；候选人需已有内容查看权。</small></span></div>
      </template>
      <div v-else class="creation-name"><strong>{{ knowledge.managedKnowledgeBase?.name ?? `${workspace.currentConversation?.title ?? '当前对话'}沉淀库` }}</strong><small>{{ knowledge.knowledgeManagement.scope === 'group' ? '集团知识库：内容查看权已绑定日常维护责任' : '个人知识库：仅归当前账号管理' }} · 当前对话：{{ workspace.currentConversation?.title }}</small></div>
      <div class="operation-actions"><button @click="knowledge.closeKnowledgeManagement()">取消</button><button class="primary" @click="confirmKnowledge">{{ knowledge.knowledgeManagement.action === 'grant' ? '确认登记责任' : knowledge.knowledgeManagement.action === 'create' ? '确认新建知识库' : '确认提交' }}</button></div>
    </section>
  </div>

  <footer class="composer agent-management-composer knowledge-management-composer">
    <div class="composer-tools"><span><Database :size="12" />{{ knowledge.knowledgeManagement.action === 'create' ? '描述要从当前对话沉淀的知识与规则' : knowledge.knowledgeManagement.action === 'supplement' ? '描述要补充的资料及适用范围' : knowledge.knowledgeManagement.action === 'maintain' ? '描述维护内容、版本或失效项' : '说明责任分配原因；不输入或展示业务内容' }}</span><span><History :size="12" />操作全程留痕</span></div>
    <div class="composer-input">
      <textarea v-model="knowledge.knowledgeManagement.input" rows="2" placeholder="用自然语言说明本次知识库操作..." @keydown.enter.exact.prevent="sendMessage"></textarea>
      <button class="send-button" title="发送知识库管理指令" :disabled="!knowledge.knowledgeManagement.input.trim()" @click="sendMessage"><Send :size="17" /></button>
    </div>
  </footer>
</template>
