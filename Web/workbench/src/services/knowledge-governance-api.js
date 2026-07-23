export const KnowledgeGovernanceOperations = Object.freeze({
  createFromConversation: 'create_from_conversation',
  supplement: 'supplement',
  maintain: 'maintain',
  assignSteward: 'assign_steward',
})

const platformBaseUrl = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? '').replace(/\/$/, '')

function traceId() {
  return `L4-KB-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

async function parseJson(response) {
  const text = await response.text()
  if (!text) return {}
  try {
    return JSON.parse(text)
  } catch {
    return { raw: text }
  }
}

async function postKnowledgeCommand(command) {
  const response = await fetch(`${platformBaseUrl}/api/application/knowledge-governance/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      trace_id: command.trace_id ?? traceId(),
      request_id: command.request_id ?? crypto.randomUUID(),
      actor: command.actor ?? {
        tenant_id: 'web-workbench',
        user_id: command.accountId,
        authenticated: true,
      },
      ...command,
    }),
  })
  const body = await parseJson(response)
  if (!response.ok || body.status === 'failed') {
    throw body.error ?? { code: 'KNOWLEDGE_COMMAND_FAILED', details: body }
  }
  return body
}

export const knowledgeGovernanceApplicationApi = {
  endpoint: '/api/application/knowledge-governance/commands',

  acceptCommand(command) {
    const trace = command.trace_id ?? traceId()
    return {
      accepted: true,
      traceId: trace,
      requestPromise: postKnowledgeCommand({ ...command, trace_id: trace }),
    }
  },
}
