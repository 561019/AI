import { ref } from 'vue'

export function useToast() {
  const toast = ref('')
  let timerId = null

  function showToast(message, duration = 2200) {
    toast.value = message
    window.clearTimeout(timerId)
    timerId = window.setTimeout(() => {
      if (toast.value === message) toast.value = ''
    }, duration)
  }

  return { toast, showToast }
}
