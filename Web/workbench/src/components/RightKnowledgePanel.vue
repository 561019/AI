<script setup>
import { BookOpen, Building2, Database, Eye, FileText, LockKeyhole, Settings2, ShieldCheck, ShieldPlus, Sparkles, Upload, UserRound } from '@lucide/vue'

defineProps({
  isProjectCenter: { type: Boolean, default: false },
  currentProject: { type: Object, default: null },
  projectKnowledge: { type: Array, default: () => [] },
  knowledgeScope: { type: String, default: 'personal' },
  personalKnowledge: { type: Array, default: () => [] },
  groupKnowledge: { type: Array, default: () => [] },
  selectedPersonalKnowledgeId: { type: String, default: null },
  canViewGroupKnowledge: { type: Boolean, default: false },
  canSupplementGroupKnowledge: { type: Boolean, default: false },
  canGrantGroupKnowledge: { type: Boolean, default: false },
  currentAccountId: { type: String, default: '' },
})

const emit = defineEmits([
  'update:knowledgeScope',
  'update:selectedPersonalKnowledgeId',
  'operate-personal',
  'operate-group',
  'create',
  'grant',
  'preview',
])
</script>

<template>
  <div class="knowledge-panel" data-testid="knowledge-panel">
    <section v-if="isProjectCenter && projectKnowledge.length" class="resource-section project-knowledge-scope">
      <div class="resource-heading"><span><BookOpen :size="14" />当前 Project 文件</span><em>{{ projectKnowledge.length }}</em></div>
      <article v-for="file in projectKnowledge" :key="file.id || file.name" class="file-row static">
        <span class="file-icon group"><Database :size="15" /></span>
        <span><strong>{{ file.name }}</strong><small>{{ file.meta }} · 仅限当前 Project</small></span>
      </article>
    </section>

    <div class="knowledge-switch">
      <button type="button" :class="{ active: knowledgeScope === 'personal' }" @click="emit('update:knowledgeScope', 'personal')"><UserRound :size="13" />个人知识库</button>
      <button type="button" :class="{ active: knowledgeScope === 'group' }" @click="emit('update:knowledgeScope', 'group')"><Building2 :size="13" />集团知识库</button>
    </div>

    <template v-if="knowledgeScope === 'personal'">
      <section class="resource-section">
        <div class="resource-heading"><span><BookOpen :size="14" />我的知识库</span><em>{{ personalKnowledge.length }}</em></div>
        <article v-for="item in personalKnowledge" :key="item.id" class="group-knowledge-card" :class="{ selected: selectedPersonalKnowledgeId === item.id }" @click="emit('update:selectedPersonalKnowledgeId', item.id)">
          <div class="knowledge-card-heading">
            <span class="file-icon"><BookOpen :size="15" /></span>
            <span><strong>{{ item.name }}</strong><small>{{ item.meta }} · {{ item.updated }}</small></span>
          </div>
          <div v-if="item.files?.length" class="knowledge-file-list">
            <button v-for="file in item.files" :key="file.id || file.name" type="button" class="knowledge-file-row" @click.stop="emit('preview', file)">
              <FileText :size="13" />
              <span><strong>{{ file.name }}</strong><small>{{ file.meta }} · 已解析 {{ file.knowledgeChunkCount ?? 0 }} 个片段</small></span>
              <Eye :size="13" />
            </button>
          </div>
          <p v-else class="knowledge-file-empty">该知识库暂未上传文件</p>
          <div class="group-knowledge-actions">
            <button type="button" @click.stop="emit('operate-personal', 'supplement', item)"><Upload :size="12" />补资料</button>
            <button type="button" @click.stop="emit('operate-personal', 'maintain', item)"><Settings2 :size="12" />维护</button>
          </div>
        </article>
        <div v-if="!personalKnowledge.length" class="knowledge-account-empty"><BookOpen :size="18" /><strong>当前账号还没有个人知识库</strong><p>上传文件后，文件会按当前账号归入个人知识库。</p></div>
      </section>
      <button type="button" class="upload-button" @click="emit('create')"><Sparkles :size="14" />根据当前对话新建</button>
      <div class="separation-note"><ShieldCheck :size="13" />仅归属于账号 {{ currentAccountId }}；不与集团库、Project 库或对话混用。</div>
    </template>

    <template v-else-if="canViewGroupKnowledge">
      <section class="resource-section">
        <div class="resource-heading"><span><Building2 :size="14" />有权查看的集团知识库</span><em>{{ groupKnowledge.length }}</em></div>
        <article v-for="item in groupKnowledge" :key="item.id" class="group-knowledge-card">
          <div class="knowledge-card-heading"><span class="file-icon group"><Database :size="15" /></span><span><strong>{{ item.name }}</strong><small>{{ item.meta }} · 责任部门：{{ item.owner }}</small></span></div>
          <div class="group-knowledge-actions"><button v-if="canSupplementGroupKnowledge" type="button" @click="emit('operate-group', 'supplement', item)"><Upload :size="12" />补资料</button><button type="button" @click="emit('operate-group', 'maintain', item)"><Settings2 :size="12" />维护</button></div>
        </article>
        <div v-if="!groupKnowledge.length" class="knowledge-account-empty"><LockKeyhole :size="18" /><strong>当前账号没有可查看的集团知识库</strong><p>集团知识库内容由账号权限决定。</p></div>
      </section>
      <section v-if="canGrantGroupKnowledge" class="grant-card"><div><ShieldPlus :size="16" /><span><strong>配权：指定维护责任人</strong><small>不会授予内容查看权。</small></span></div><button type="button" @click="emit('grant')">配置管理责任</button></section>
    </template>

    <template v-else>
      <section v-if="canGrantGroupKnowledge" class="grant-card governance-card"><div><ShieldPlus :size="16" /><span><strong>可执行：管理责任配权</strong><small>配权不返回知识库业务内容。</small></span></div><button type="button" @click="emit('grant')">进入配权工作台</button></section>
      <div v-else class="right-empty"><LockKeyhole :size="25" /><strong>当前账号没有集团知识库查看权限</strong><p>可见性由账号权限决定。</p></div>
    </template>
  </div>
</template>
