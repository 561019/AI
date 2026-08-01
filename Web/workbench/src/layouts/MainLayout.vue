<script setup>
const emit = defineEmits(['background-click'])
</script>

<template>
  <div class="page-shell" @click.self="emit('background-click')">
    <div class="workbench">
      <slot name="topbar" />
      <div class="columns">
        <slot name="sidebar" />
        <slot name="main" />
        <slot name="right" />
      </div>
    </div>
    <slot name="overlays" />
  </div>
</template>
