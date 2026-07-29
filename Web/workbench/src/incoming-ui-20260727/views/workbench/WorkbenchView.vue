<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useWorkspaceStore } from '@/stores/workspace'

const router = useRouter()
const workspace = useWorkspaceStore()

onMounted(() => {
  router.replace(`/project/${workspace.currentProjectId}`)
})
</script>

<template>
  <div class="center-scroll">
    <div style="padding:60px;text-align:center;color:var(--text-3)">加载中...</div>
  </div>
</template>
