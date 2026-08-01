<script setup>
import { ArrowLeft, Download, FileOutput, FileText, FolderKanban, Table2 } from '@lucide/vue'
import { computed } from 'vue'

const props = defineProps({
  file: { type: Object, required: true },
  projectName: { type: String, default: '' },
  conversationTitle: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const extension = computed(() => props.file.type || props.file.name?.split('.').pop()?.toUpperCase() || 'FILE')
const isSpreadsheet = computed(() => ['XLSX', 'XLS', 'CSV'].includes(extension.value))
const parsedChunks = computed(() => Array.isArray(props.file.parsedChunks) ? props.file.parsedChunks : [])
const isKnowledgeFile = computed(() => Boolean(props.file.knowledgeSourceId || props.file.knowledge_source_id || props.file.knowledgeBaseId || props.file.knowledge_base_id || props.file.knowledgeBaseName || props.file.knowledge_base_name || props.file.assetScope === 'personal_knowledge' || props.file.asset_scope === 'personal_knowledge'))
const hasParsedContent = computed(() => isKnowledgeFile.value)
const sourceLabel = computed(() => isKnowledgeFile.value ? '个人知识库' : (props.file.source || '当前对话文件'))
</script>

<template>
  <div class="center-scroll file-preview-view">
    <div class="file-preview-toolbar">
      <button type="button" title="返回" @click="emit('close')"><ArrowLeft :size="16" /></button>
      <span>文件预览</span>
      <a v-if="!isKnowledgeFile && (file.download_url || file.downloadUrl)" class="file-preview-download" :href="file.download_url || file.downloadUrl" target="_blank" rel="noreferrer" download><Download :size="14" />打开原文件</a>
    </div>
    <article class="file-preview-document">
      <header>
        <span class="file-preview-icon"><Table2 v-if="isSpreadsheet" :size="22" /><FileOutput v-else-if="file.type" :size="22" /><FileText v-else :size="22" /></span>
        <div><h2>{{ file.name }}</h2><p>{{ extension }} · {{ file.meta || '当前文件' }}</p></div>
      </header>
      <dl class="file-preview-meta"><div><dt>来源</dt><dd>{{ sourceLabel }}</dd></div><div v-if="file.knowledgeBaseName || file.knowledge_base_name"><dt>知识库</dt><dd>{{ file.knowledgeBaseName || file.knowledge_base_name }}</dd></div><div v-if="isKnowledgeFile"><dt>解析状态</dt><dd>{{ file.parsedLoading ? '正在读取解析结果' : `已解析 ${file.knowledgeChunkCount ?? parsedChunks.length} 个片段` }}</dd></div><div v-if="!isKnowledgeFile && projectName"><dt>Project</dt><dd>{{ projectName }}</dd></div><div v-if="!isKnowledgeFile && conversationTitle"><dt>对话</dt><dd>{{ conversationTitle }}</dd></div></dl>

      <section v-if="hasParsedContent" class="knowledge-parsed-preview">
        <div class="preview-section-heading"><strong>知识库解析结果</strong><span>以下内容来自知识库模块保存的 knowledge_chunks</span></div>
        <p v-if="file.parsedLoading" class="preview-state">正在从数据模块读取解析结果...</p>
        <p v-else-if="file.parsedError" class="preview-state error">{{ file.parsedError }}</p>
        <p v-else-if="!parsedChunks.length" class="preview-state">知识库已登记，但暂未返回可预览的解析片段。</p>
        <article v-for="chunk in parsedChunks" v-else :key="chunk.chunk_id || chunk.record_id" class="parsed-chunk"><header><span>片段 {{ chunk.chunk_index || '-' }}</span><small>{{ chunk.original_name || file.name }}</small></header><p>{{ chunk.content || chunk.content_preview || '无文本内容' }}</p></article>
      </section>
      <section v-else class="file-preview-content"><p>这是当前工作台文件索引。点击“打开原文件”可查看实际上传文件。</p></section>
      <footer><FolderKanban :size="14" />{{ isKnowledgeFile ? '文件归属于当前账号；以下内容来自知识库模块解析索引。' : '原文件来自受权限保护的上传对象。' }}</footer>
    </article>
  </div>
</template>
