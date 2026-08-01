<script setup>
import { ChevronRight, Download, Eye, FileOutput, FileText, FolderKanban, MessageSquare, Paperclip } from '@lucide/vue'

defineProps({
  currentConversation: { type: Object, default: null }, isProjectCenter: { type: Boolean, default: false }, currentProject: { type: Object, default: null },
  uploadedFiles: { type: Array, default: () => [] }, producedFiles: { type: Array, default: () => [] }, projectFiles: { type: Array, default: () => [] }, projectKnowledgeFiles: { type: Array, default: () => [] },
})
const emit = defineEmits(['preview', 'download', 'download-upload', 'cite-upload', 'cite-output', 'cite-project', 'select-conversation', 'show-shared-file'])
</script>

<template>
  <template v-if="currentConversation">
    <section class="resource-section"><div class="resource-heading"><span><Paperclip :size="14" />我上传的文件</span><em>{{ uploadedFiles.length }}</em></div><div v-if="uploadedFiles.length" class="file-list"><article v-for="file in uploadedFiles" :key="file.name" class="output-file"><div class="file-row static"><span class="file-icon"><FileText :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.meta }}</small></span><button class="output-download-icon" title="下载文件" @click="emit('download-upload', file)"><Download :size="15" /></button></div><div><button @click="emit('preview', file)"><Eye :size="12" />查看</button><button @click="emit('cite-upload', file)"><MessageSquare :size="12" />引用进对话</button></div></article></div><p v-else class="empty-search">未找到匹配的上传文件</p></section>
    <section class="resource-section"><div class="resource-heading"><span><FileOutput :size="14" />本对话产出的文件</span><em>{{ producedFiles.length }}</em></div><article v-for="file in producedFiles" :key="file.id" class="output-file"><div class="file-row static"><span class="file-icon output"><FileOutput :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.meta }}</small></span><button class="output-download-icon" title="下载文件" @click="emit('download', file)"><Download :size="15" /></button></div><div><button @click="emit('preview', file)"><Eye :size="12" />查看</button><button @click="emit('cite-output', file)"><MessageSquare :size="12" />引用进对话</button></div></article><p v-if="!producedFiles.length" class="empty-search">未找到匹配的产出文件</p></section>
  </template>
  <template v-else-if="isProjectCenter">
    <section class="resource-section"><div class="resource-heading"><span><FolderKanban :size="14" />Project 与会话文件</span><em>{{ projectFiles.length }}</em></div><button v-for="file in projectFiles" :key="file.id" class="file-row project-file" @click="emit('preview', file)"><span class="file-icon" :class="{ group: !file.conversationId }"><FileText :size="15" /></span><span><strong>{{ file.name }}</strong><small>{{ file.source }} · {{ file.meta }}</small></span><ChevronRight :size="12" /></button><p v-if="!projectFiles.length" class="empty-search">未找到匹配的 Project 文件</p></section>
  </template>
  <div v-else class="right-empty"><FileOutput :size="25" /><strong>选择一个 Project 查看文件</strong><p>文件按 Project 与会话分层；进入对话后可上传、下载和引用。</p></div>
</template>
