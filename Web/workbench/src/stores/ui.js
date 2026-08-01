import { ref } from 'vue'

export function useWorkbenchUiStore() {
  const currentAccountId = ref(null)
  const currentProjectId = ref('project-customer')
  const currentConversationId = ref('customer-expert')
  const conversationMenuId = ref(null)
  const expandedProjectIds = ref(new Set())
  const accountCenterActive = ref(false)
  const accountMenuOpen = ref(false)
  const rightTab = ref('session')
  const inputText = ref('')
  const messageActionMenuId = ref(null)
  const editingMessageId = ref(null)
  const deleteMessageDialogOpen = ref(false)
  const forwardMessageDialogOpen = ref(false)
  const messagePendingAction = ref(null)
  const chatStreamRef = ref(null)
  const fileInput = ref(null)
  const imageInput = ref(null)
  const cameraInput = ref(null)
  const voiceRecording = ref(false)
  const knowledgeScope = ref('personal')
  const projectSearch = ref('')
  const projectDialogOpen = ref(false)
  const conversationDialogOpen = ref(false)
  const newProjectName = ref('')
  const newConversationTitle = ref('')
  const commandInput = ref('')
  const projectCommandInput = ref('')

  return {
    currentAccountId,
    currentProjectId,
    currentConversationId,
    conversationMenuId,
    expandedProjectIds,
    accountCenterActive,
    accountMenuOpen,
    rightTab,
    inputText,
    messageActionMenuId,
    editingMessageId,
    deleteMessageDialogOpen,
    forwardMessageDialogOpen,
    messagePendingAction,
    chatStreamRef,
    fileInput,
    imageInput,
    cameraInput,
    voiceRecording,
    knowledgeScope,
    projectSearch,
    projectDialogOpen,
    conversationDialogOpen,
    newProjectName,
    newConversationTitle,
    commandInput,
    projectCommandInput,
  }
}
