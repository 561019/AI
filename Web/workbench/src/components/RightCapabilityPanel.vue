<script setup>
import { Plus } from '@lucide/vue'

const props = defineProps({
  type: { type: String, required: true }, records: { type: Array, default: () => [] }, selectedId: { type: String, default: null },
  isDisabled: { type: Function, required: true }, canOperate: { type: Function, required: true },
})
const emit = defineEmits(['select', 'create', 'manage'])
const typeLabel = () => props.type === 'skill' ? 'Skill' : 'Agent'
const panelTitle = () => props.type === 'skill' ? '我的技能(Skills)' : '我的 Agent'
const actionSet = (item) => props.type === 'skill'
  ? (item.scope === 'group' ? ['fineTune', 'disable'] : ['fineTune', 'publish', 'disable'])
  : (item.scope === 'group' ? ['fineTune', 'upgrade', 'disable'] : ['fineTune', 'upgrade', 'promote', 'disable'])
const actionLabel = (action) => ({ fineTune: '微调', upgrade: '发起升级', promote: '推荐升层', publish: '发布升档', disable: '停用' }[action])
</script>

<template>
  <section class="capability-section capability-ledger">
    <div class="capability-heading capability-toolbar">
      <span>{{ panelTitle() }}</span>
      <button class="new-agent-button" :title="`新建 ${typeLabel()}`" @click="emit('create')"><Plus :size="13" />新建 {{ typeLabel() }}</button>
    </div>
    <div class="capability-list">
      <article v-for="item in records" :key="item.id" class="capability-card agent-ledger-card" :class="{ disabled: isDisabled(item), selected: selectedId === item.id }" @click="emit('select', item)">
        <div class="capability-title">
          <i class="capability-status-dot" :class="{ disabled: isDisabled(item) }" />
          <strong>{{ item.name }}</strong>
          <span class="capability-usage">调用 {{ item.calls }}</span>
        </div>
        <div class="capability-tags"><span>{{ item.level }}</span><span>{{ item.version }}</span></div>
        <p>{{ item.detail }}</p>
        <div class="capability-actions agent-actions">
          <button v-for="action in actionSet(item)" :key="action" :class="{ 'danger-action': action === 'disable', 'promote-action': action === 'promote' }" :disabled="isDisabled(item) || (item.scope === 'group' && !canOperate(item))" @click.stop="emit('manage', item, action)">{{ actionLabel(action) }}</button>
        </div>
      </article>
      <p v-if="!records.length" class="empty-search">未找到匹配的{{ typeLabel() }}</p>
    </div>
  </section>
</template>
