import { ref } from 'vue'

export function useToast() {
  const toast = ref('')
  let timer = null

  function showToast(message) {
    toast.value = message
    if (timer) window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      if (toast.value === message) toast.value = ''
    }, 2200)
  }

  return { toast, showToast }
}
