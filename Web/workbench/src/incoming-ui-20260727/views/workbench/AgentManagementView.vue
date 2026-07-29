<script setup>
import {
  Activity, ArrowUpCircle, Bot, CheckCircle2, History, Power,
  Puzzle, Send, Settings2, ShieldCheck, Sparkles, Wrench,
} from '@lucide/vue'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToast } from '@/composables/useToast'

const capabilities = useCapabilitiesStore()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const { showToast } = useToast()

function sendMessage() {
  capabilities.sendAgentManagementMessage(auth.currentAccount?.id, workspace.currentConversationId)
}

function confirmAgent() {
  capabilities.confirmAgentManagement(auth.currentAccount?.id, auth.currentAccount?.name)
  showToast(capabilities.agentManagement.stage === 'complete' ? '操作已确认' : '确认中...')
}

function advancePromotion() {
  capabilities.advancePromotionFlow()
}

function canOperateResource(item) {
  return capabilities.canOperateResource(item, auth.hasPermission('resource.group.manage'))
}
</script>

<template>
  <div class="center-scroll agent-chat-stream">
    <div v-if="capabilities.managedCapability" class="assistant-intro agent-management-intro">
      <span class="ai-avatar"><component :is="capabilities.agentManagement.capabilityType === 'skill' ? Puzzle : Bot" :size="18" /></span>
      <div><strong>{{ capabilities.managedCapability.name }}</strong><p>{{ capabilities.managedCapability.scope === 'group' ? '集团共享标准版' : '个人自建 / 个人变种' }} · {{ capabilities.managedCapability.version }} · {{ capabilities.managedCapability.status }}</p></div>
    </div>
    <div v-else class="assistant-intro agent-management-intro creation-intro">
      <span class="ai-avatar"><Sparkles :size="18" /></span>
      <div><strong>从自然语言创建个人 {{ capabilities.agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent' }}</strong><p>零代码、免审批；候选资产、测试结果和保存确认都在当前对话完成。</p></div>
    </div>

    <div v-if="capabilities.managedCapability" class="agent-ledger-strip">
      <span><b>{{ capabilities.managedCapability.calls }}</b><small>累计调用</small></span>
      <span><b>{{ capabilities.managedCapability.adoption }}</b><small>方案采纳率</small></span>
      <span><b>{{ capabilities.managedCapability.consistency }}</b><small>多模型一致性</small></span>
      <span><b>{{ capabilities.managedCapability.version }}</b><small>当前版本</small></span>
    </div>

    <div v-for="message in capabilities.agentManagement.messages" :key="message.id" class="message agent-management-message" :class="message.role">
      <span v-if="message.role === 'assistant'" class="message-avatar"><Bot :size="16" /></span>
      <div class="bubble"><p>{{ message.text }}</p><small v-if="message.source"><Activity :size="11" />{{ message.source }}</small></div>
      <span v-if="message.role === 'user'" class="message-avatar user">{{ auth.currentAccount?.avatar }}</span>
    </div>

    <!-- Create Assembly -->
    <section v-if="capabilities.agentManagement.stage === 'create-assembly'" class="agent-operation-card creation-card">
      <div class="operation-heading"><span><Sparkles :size="15" />候选资产装配</span><em>去重匹配</em></div>
      <div class="creation-name"><strong>{{ capabilities.agentManagement.createTitle }}</strong><small>创建人：{{ auth.currentAccount?.name }} · 仅个人可用 · 无需审批</small></div>
      <div class="assembly-list"><div v-for="asset in capabilities.agentManagement.createAssets" :key="asset.label"><span>{{ asset.label }}</span><strong>{{ asset.value }}</strong><small>{{ asset.detail }}</small></div></div>
      <label class="human-confirm"><input v-model="capabilities.agentManagement.humanConfirm" type="checkbox" /><span><strong>发送通报前必须人工确认</strong><small>关闭后将按已声明的执行规则自动处理；可在测试前再次调整。</small></span></label>
      <div class="operation-actions"><button @click="capabilities.refineNewAgentRules()">再调调规则</button><button class="primary" @click="capabilities.beginAgentCreationValidation(auth.currentAccount?.id, workspace.currentConversationId)">开始跨模型测试</button></div>
    </section>

    <!-- Create Validation -->
    <section v-if="capabilities.agentManagement.stage === 'create-validation'" class="agent-operation-card creation-card">
      <div class="operation-heading"><span><CheckCircle2 :size="15" />跨模型一致性测试</span><em>候选 v1.0</em></div>
      <div class="model-check">
        <button :class="{ active: capabilities.agentManagement.primaryModel === '通义千问 3.5' }" @click="capabilities.agentManagement.primaryModel = '通义千问 3.5'"><span><strong>通义千问 3.5</strong><small>一致性 97.2% · 推荐主力</small></span><CheckCircle2 :size="15" /></button>
        <button :class="{ active: capabilities.agentManagement.backupModel === 'DeepSeek V3' }" @click="capabilities.agentManagement.backupModel = 'DeepSeek V3'"><span><strong>DeepSeek V3</strong><small>一致性 96.8% · 推荐备用</small></span><CheckCircle2 :size="15" /></button>
        <button><span><strong>豆包</strong><small>一致性 96.5% · 文案口径已核对</small></span><CheckCircle2 :size="15" /></button>
      </div>
      <label class="human-confirm"><input v-model="capabilities.agentManagement.humanConfirm" type="checkbox" /><span><strong>关键通报先人工确认</strong><small>模型选择与执行策略将随候选版本一并留痕。</small></span></label>
      <div class="operation-actions"><button @click="capabilities.refineNewAgentRules()">再调调规则</button><button class="primary" @click="confirmAgent">确认存入台账</button></div>
    </section>

    <!-- Fine Tune Details -->
    <section v-if="capabilities.agentManagement.stage === 'fine-request' && capabilities.managedCapability" class="agent-operation-card fine-details-card">
      <div class="operation-heading"><span><Settings2 :size="15" />Agent 运行信息</span><em>当前版本 {{ capabilities.managedCapability.version }}</em></div>
      
      <div class="agent-info-section">
        <div class="info-block">
          <div class="info-header"><Activity :size="14" /><strong>运行逻辑</strong></div>
          <div class="info-content">
            <p>{{ capabilities.agentManagement.detailedInfo?.runningLogic?.description || capabilities.managedCapability.detail }}</p>
            <div class="logic-flow">
              <template v-if="capabilities.agentManagement.detailedInfo?.runningLogic?.steps">
                <div v-for="step in capabilities.agentManagement.detailedInfo.runningLogic.steps" :key="step.step" class="flow-step">
                  <span class="step-num">{{ step.step }}</span>
                  <span>{{ step.name }}{{ step.description ? `（${step.description}）` : '' }}</span>
                </div>
              </template>
              <template v-else>
                <div class="flow-step"><span class="step-num">1</span><span>接收业务输入（客户数据、规则、上下文）</span></div>
                <div class="flow-step"><span class="step-num">2</span><span>执行判断逻辑与权重计算</span></div>
                <div class="flow-step"><span class="step-num">3</span><span>生成结构化输出与建议</span></div>
                <div class="flow-step"><span class="step-num">4</span><span>{{ capabilities.agentManagement.humanConfirm ? '人工确认后交付' : '自动交付结果' }}</span></div>
              </template>
            </div>
          </div>
        </div>

        <div class="info-block">
          <div class="info-header"><ShieldCheck :size="14" /><strong>判断逻辑</strong></div>
          <div class="info-content">
            <div class="logic-rules">
              <template v-if="capabilities.agentManagement.detailedInfo?.judgmentLogic?.rules">
                <div v-for="rule in capabilities.agentManagement.detailedInfo.judgmentLogic.rules" :key="rule.label" class="rule-item">
                  <span class="rule-label">{{ rule.label }}</span>
                  <span class="rule-value">{{ rule.value }}</span>
                </div>
              </template>
              <template v-else>
                <div class="rule-item">
                  <span class="rule-label">风险评估规则</span>
                  <span class="rule-value">基于客户画像、历史记录、行业规则</span>
                </div>
                <div class="rule-item">
                  <span class="rule-label">优先级判定</span>
                  <span class="rule-value">金额 > 时效 > 合规要求</span>
                </div>
                <div class="rule-item">
                  <span class="rule-label">决策阈值</span>
                  <span class="rule-value">高风险 ≥ 80 分、中风险 50-79 分、低风险 < 50 分</span>
                </div>
              </template>
            </div>
          </div>
        </div>

        <div class="info-block">
          <div class="info-header"><Wrench :size="14" /><strong>权重配置</strong></div>
          <div class="info-content">
            <div class="weight-grid">
              <template v-if="capabilities.agentManagement.detailedInfo?.weights">
                <div v-for="weight in capabilities.agentManagement.detailedInfo.weights" :key="weight.label" class="weight-item">
                  <span class="weight-label">{{ weight.label }}</span>
                  <div class="weight-bar">
                    <div class="weight-fill" :style="{ width: weight.value + '%' }"></div>
                    <span class="weight-value">{{ weight.value }}{{ weight.unit }}</span>
                  </div>
                </div>
              </template>
              <template v-else>
                <div class="weight-item">
                  <span class="weight-label">客户风险权重</span>
                  <div class="weight-bar">
                    <div class="weight-fill" style="width: 35%"></div>
                    <span class="weight-value">35%</span>
                  </div>
                </div>
                <div class="weight-item">
                  <span class="weight-label">金额影响权重</span>
                  <div class="weight-bar">
                    <div class="weight-fill" style="width: 30%"></div>
                    <span class="weight-value">30%</span>
                  </div>
                </div>
                <div class="weight-item">
                  <span class="weight-label">时效性权重</span>
                  <div class="weight-bar">
                    <div class="weight-fill" style="width: 20%"></div>
                    <span class="weight-value">20%</span>
                  </div>
                </div>
                <div class="weight-item">
                  <span class="weight-label">合规要求权重</span>
                  <div class="weight-bar">
                    <div class="weight-fill" style="width: 15%"></div>
                    <span class="weight-value">15%</span>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>

        <div class="info-block">
          <div class="info-header"><Send :size="14" /><strong>输出方式</strong></div>
          <div class="info-content">
            <div class="output-format">
              <template v-if="capabilities.agentManagement.detailedInfo?.outputFormat?.formats">
                <div v-for="format in capabilities.agentManagement.detailedInfo.outputFormat.formats" :key="format.type" class="format-item">
                  <span class="format-type">{{ format.type }}</span>
                  <span class="format-desc">{{ format.description }}</span>
                </div>
              </template>
              <template v-else>
                <div class="format-item">
                  <span class="format-type">结构化结论</span>
                  <span class="format-desc">风险等级、建议行动、依据说明</span>
                </div>
                <div class="format-item">
                  <span class="format-type">待办清单</span>
                  <span class="format-desc">优先级排序、责任人、截止时间</span>
                </div>
                <div class="format-item">
                  <span class="format-type">引用依据</span>
                  <span class="format-desc">客户档案、规则版本、历史案例</span>
                </div>
                <div class="format-item">
                  <span class="format-type">交付格式</span>
                  <span class="format-desc">对话消息 + 可导出报告（PDF/Excel）</span>
                </div>
              </template>
            </div>
          </div>
        </div>

        <div class="info-block">
          <div class="info-header"><History :size="14" /><strong>执行统计</strong></div>
          <div class="info-content">
            <div class="stats-grid">
              <div class="stat-item">
                <span class="stat-value">{{ capabilities.agentManagement.detailedInfo?.executionStats?.calls || capabilities.managedCapability.calls }}</span>
                <span class="stat-label">累计调用</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{{ capabilities.agentManagement.detailedInfo?.executionStats?.adoption || capabilities.managedCapability.adoption }}</span>
                <span class="stat-label">方案采纳率</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{{ capabilities.agentManagement.detailedInfo?.executionStats?.consistency || capabilities.managedCapability.consistency }}</span>
                <span class="stat-label">多模型一致性</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{{ capabilities.agentManagement.detailedInfo?.executionStats?.version || capabilities.managedCapability.version }}</span>
                <span class="stat-label">当前版本</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Fine Preview -->
    <section v-if="capabilities.agentManagement.stage === 'fine-preview'" class="agent-operation-card fine-preview-card">
      <div class="operation-heading"><span><Wrench :size="15" />个人微调预览</span><em>不影响公共标准版</em></div>
      <div class="preview-grid"><div><span>调前</span><strong>客户风险权重 35%</strong><small>案例命中率 78%</small></div><div class="after"><span>调后</span><strong>客户风险权重 48%</strong><small>案例命中率 89%</small></div></div>
      <div class="case-preview"><span><CheckCircle2 :size="13" />真实案例 A：高风险客户提前 3 天识别</span><span><CheckCircle2 :size="13" />真实案例 B：低优先级误报减少 21%</span><span><CheckCircle2 :size="13" />真实案例 C：建议口径与人工判断一致</span></div>
      <div class="operation-actions"><button @click="capabilities.agentManagement.stage = 'fine-request'">继续调整</button><button class="primary" @click="confirmAgent">确认保存个人变种</button></div>
    </section>

    <!-- Upgrade Validation -->
    <section v-if="capabilities.agentManagement.stage === 'upgrade-validation'" class="agent-operation-card upgrade-card">
      <div class="operation-heading"><span><Settings2 :size="15" />多模型一致性校验</span><em>候选 {{ capabilities.bumpVersion(capabilities.managedCapability?.version) }}</em></div>
      <div class="model-check">
        <button :class="{ active: capabilities.agentManagement.primaryModel === '通义千问 3.5' }" @click="capabilities.agentManagement.primaryModel = '通义千问 3.5'"><span><strong>通义千问 3.5</strong><small>一致性 97.3% · 推荐主力</small></span><CheckCircle2 :size="15" /></button>
        <button :class="{ active: capabilities.agentManagement.backupModel === 'DeepSeek V3' }" @click="capabilities.agentManagement.backupModel = 'DeepSeek V3'"><span><strong>DeepSeek V3</strong><small>一致性 96.9% · 推荐备用</small></span><CheckCircle2 :size="15" /></button>
        <button><span><strong>GPT-5</strong><small>一致性 96.7% · 结果可复核</small></span><CheckCircle2 :size="15" /></button>
      </div>
      <label class="human-confirm"><input v-model="capabilities.agentManagement.humanConfirm" type="checkbox" /><span><strong>关键动作先人工确认</strong><small>启用后，预警通报和外部执行将在发送前挂起确认。</small></span></label>
      <div class="operation-actions"><button @click="capabilities.agentManagement.stage = 'upgrade-request'">继续补充能力</button><button class="primary" @click="confirmAgent">确认保存升级版本</button></div>
    </section>

    <!-- Promotion -->
    <section v-if="['promote', 'publish'].includes(capabilities.agentManagement.action) && capabilities.agentManagement.stage !== 'complete'" class="agent-operation-card promotion-card">
      <div class="operation-heading"><span><ArrowUpCircle :size="15" />{{ capabilities.agentManagement.action === 'publish' ? '发布升档' : '推荐升层' }}</span><em>仅客观数据</em></div>
      <div class="promotion-steps">
        <div :class="{ done: capabilities.agentManagement.promotionStep >= 1, active: capabilities.agentManagement.promotionStep === 0 }"><i>1</i><span><strong>养护人发起申请</strong><small>当前账号：{{ auth.currentAccount?.name }}</small></span></div>
        <div :class="{ done: capabilities.agentManagement.promotionStep >= 2, active: capabilities.agentManagement.promotionStep === 1 }"><i>2</i><span><strong>经验推广官校验</strong><small>调用 {{ capabilities.managedCapability?.calls }} · 采纳 {{ capabilities.managedCapability?.adoption }} · 一致性 {{ capabilities.managedCapability?.consistency }}</small></span></div>
        <div :class="{ active: capabilities.agentManagement.promotionStep === 2 }"><i>3</i><span><strong>系统归档为公共资产</strong><small>开放大区复用，原操作人保留养护人身份</small></span></div>
      </div>
      <div class="operation-actions"><button class="primary" @click="advancePromotion">{{ capabilities.agentManagement.promotionStep === 0 ? `提交${capabilities.agentManagement.action === 'publish' ? '发布' : '升层'}申请` : '完成客观校验并归档' }}</button></div>
    </section>

    <!-- Disable -->
    <section v-if="capabilities.agentManagement.stage === 'disable-confirm'" class="agent-operation-card disable-card">
      <div class="operation-heading"><span><Power :size="15" />确认停用</span><em>可恢复，不删除</em></div>
      <p>停用后全部场景都不可调用，但历史版本、使用数据和复用记录完整保留。已发布或被复用的 Agent 只能停用，不能直接删除。</p>
      <div class="operation-actions"><button @click="capabilities.agentManagement.stage = 'idle'">取消停用</button><button class="danger" @click="confirmAgent">确认停用</button></div>
    </section>
  </div>

  <footer class="composer agent-management-composer">
    <div class="composer-tools">
      <span><Bot :size="12" />{{ capabilities.agentManagement.action === 'create' ? `描述要创建的 ${capabilities.agentManagement.capabilityType === 'skill' ? 'Skill 输入、规则与输出' : 'Agent、目标效果与执行规则'}` : capabilities.agentManagement.action === 'fineTune' ? '描述微调需求' : capabilities.agentManagement.action === 'upgrade' ? '描述新增能力与规则' : ['promote', 'publish'].includes(capabilities.agentManagement.action) ? `补充${capabilities.agentManagement.action === 'publish' ? '发布升档' : '升层'}说明或直接提交` : '输入确认、取消或恢复指令' }}</span>
      <span><History :size="12" />版本全程留痕</span>
    </div>
    <div class="composer-input">
      <textarea v-model="capabilities.agentManagement.input" rows="2" :placeholder="`用自然语言描述你的管理需求...`" @keydown.enter.exact.prevent="sendMessage"></textarea>
      <button class="send-button" :title="`发送 ${capabilities.agentManagement.capabilityType === 'skill' ? 'Skill' : 'Agent'} 管理指令`" :disabled="!capabilities.agentManagement.input.trim()" @click="sendMessage"><Send :size="17" /></button>
    </div>
  </footer>
</template>
