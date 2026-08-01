<script setup>
import { useId } from 'vue'
import { Camera, Image as ImageIcon, Mic, Paperclip, Pause, Send, X } from '@lucide/vue'

defineProps({
  inputText: { type: String, default: '' },
  editingMessageId: { type: String, default: null },
  voiceRecording: { type: Boolean, default: false },
  isGenerating: { type: Boolean, default: false },
  fileInput: { type: Object, default: null },
  imageInput: { type: Object, default: null },
  cameraInput: { type: Object, default: null },
})

const emit = defineEmits([
  'update:inputText',
  'send',
  'pause',
  'cancel-edit',
  'open-picker',
  'toggle-voice',
  'attach',
])

const inputIdBase = useId()
const fileInputId = `${inputIdBase}-file`
const imageInputId = `${inputIdBase}-image`
const cameraInputId = `${inputIdBase}-camera`
</script>

<template>
  <footer class="composer">
    <div class="composer-tools composer-media-tools">
      <span class="composer-upload-trigger" title="添加文件">
        <Paperclip :size="14" />文件
        <input :id="fileInputId" class="composer-upload-native" type="file" multiple @change="emit('attach', $event, '文件')" />
      </span>
      <span class="composer-upload-trigger" title="添加图片">
        <ImageIcon :size="14" />图片
        <input :id="imageInputId" class="composer-upload-native" type="file" accept="image/*" multiple @change="emit('attach', $event, '图片')" />
      </span>
      <span class="composer-upload-trigger" title="拍照">
        <Camera :size="14" />拍照
        <input :id="cameraInputId" class="composer-upload-native" type="file" accept="image/*" capture="environment" @change="emit('attach', $event, '照片')" />
      </span>
      <button title="语音输入" :class="{ recording: voiceRecording }" @click="emit('toggle-voice')">
        <Mic :size="14" />{{ voiceRecording ? '结束录音' : '语音' }}
      </button>
    </div>
    <div class="composer-input">
      <textarea
        :value="inputText"
        rows="2"
        :placeholder="editingMessageId ? '正在编辑消息，Enter 保存，Esc 取消' : '向 AI 提出需求，Enter 发送，Shift+Enter 换行...'"
        @input="emit('update:inputText', $event.target.value)"
        @keydown.enter.exact.prevent="emit('send')"
        @keydown.esc.prevent="emit('cancel-edit')"
      />
      <button v-if="editingMessageId" class="cancel-edit-button" title="取消编辑" @click="emit('cancel-edit')">
        <X :size="16" />
      </button>
      <button v-if="isGenerating" class="send-button pause-button" title="暂停生成" @click="emit('pause')">
        <Pause :size="17" />
      </button>
      <button v-else class="send-button" title="发送" :disabled="!inputText.trim()" @click="emit('send')">
        <Send :size="17" />
      </button>
    </div>
  </footer>
</template>
