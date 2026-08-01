<script setup>
import { Camera, Command, Image as ImageIcon, Mic, Paperclip, Send, ShieldCheck } from '@lucide/vue'

defineProps({ value: { type: String, default: '' }, title: { type: String, required: true }, scope: { type: String, required: true }, placeholder: { type: String, required: true }, project: { type: Boolean, default: false }, voiceRecording: { type: Boolean, default: false } })
const emit = defineEmits(['update:value', 'send', 'open-picker', 'toggle-voice'])
</script>

<template>
  <footer class="composer command-composer" :class="{ 'project-command-composer': project }"><div class="composer-tools command-composer-tools"><div class="composer-media-tools"><button title="添加文件" @click="emit('open-picker', 'file')"><Paperclip :size="14" />文件</button><button title="添加图片" @click="emit('open-picker', 'image')"><ImageIcon :size="14" />图片</button><button title="拍照" @click="emit('open-picker', 'camera')"><Camera :size="14" />拍照</button><button title="语音输入" :class="{ recording: voiceRecording }" @click="emit('toggle-voice')"><Mic :size="14" />{{ voiceRecording ? '结束录音' : '语音' }}</button></div><div class="command-composer-scope"><span><Command :size="12" />{{ title }}</span><span><ShieldCheck :size="12" />{{ scope }}</span></div></div><div class="composer-input"><textarea :value="value" rows="2" :placeholder="placeholder" @input="emit('update:value', $event.target.value)" @keydown.enter.exact.prevent="emit('send')" /><button class="send-button" :title="title" :disabled="!value.trim()" @click="emit('send')"><Send :size="17" /></button></div></footer>
</template>
