<script setup>
import { MessageSquare } from '@lucide/vue'

defineProps({
  open: { type: Boolean, default: false },
  projectName: { type: String, default: '' },
  title: { type: String, default: '' },
})

const emit = defineEmits(['close', 'confirm', 'update:title'])
</script>

<template>
  <div v-if="open" class="dialog-backdrop" @click.self="$emit('close')">
    <form class="creation-dialog" @submit.prevent="$emit('confirm')">
      <div class="dialog-icon conversation"><MessageSquare :size="19" /></div>
      <div><span>新建对话</span><h2>{{ projectName }}</h2><p>新对话从零开始，不携带历史上下文；后续消息会按本 Project 的权限和资料范围处理。</p></div>
      <label>对话主题<input :value="title" autofocus maxlength="32" placeholder="例如：绿城续约下一步方案" @input="$emit('update:title', $event.target.value)" /></label>
      <div class="dialog-actions"><button type="button" @click="$emit('close')">取消</button><button class="primary" type="submit" :disabled="!title.trim()">创建对话</button></div>
    </form>
  </div>
</template>
