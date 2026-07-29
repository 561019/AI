<script setup>
import { FolderKanban } from '@lucide/vue'

defineProps({
  open: { type: Boolean, default: false },
  name: { type: String, default: '' },
})

const emit = defineEmits(['close', 'confirm', 'update:name'])
</script>

<template>
  <div v-if="open" class="dialog-backdrop" @click.self="$emit('close')">
    <form class="creation-dialog" @submit.prevent="$emit('confirm')">
      <div class="dialog-icon"><FolderKanban :size="19" /></div>
      <div><span>新建 Project</span><h2>建立一个独立业务空间</h2><p>创建后将自动拥有 Project 专属指挥中心、对话列表和独立知识库。</p></div>
      <label>Project 名称<input :value="name" autofocus maxlength="24" placeholder="例如：重点客户续约推进" @input="$emit('update:name', $event.target.value)" /></label>
      <div class="dialog-actions"><button type="button" @click="$emit('close')">取消</button><button class="primary" type="submit" :disabled="!name.trim()">创建 Project</button></div>
    </form>
  </div>
</template>
