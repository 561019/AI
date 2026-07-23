const platformBaseUrl = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? '').replace(/\/$/, '')

function traceId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
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

async function postCommand(path, command) {
  const response = await fetch(`${platformBaseUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      trace_id: command.trace_id ?? traceId('L4-WORKSPACE'),
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
    throw body.error ?? { code: 'WORKSPACE_COMMAND_FAILED', details: body }
  }
  return body
}

export const workspaceApplicationApi = {
  acceptCommand(command) {
    const path = command.operation === 'create_conversation' || command.operation === 'update_conversation' || command.operation === 'archive_conversation'
      ? '/api/application/conversation/commands'
      : '/api/application/project/commands'
    const normalized = command.operation === 'create_conversation'
      ? { ...command, operation: 'create' }
      : command.operation === 'update_conversation'
        ? { ...command, operation: 'update' }
        : command.operation === 'archive_conversation'
          ? { ...command, operation: 'archive' }
          : command
    const trace = normalized.trace_id ?? traceId('L4-WORKSPACE')
    return {
      accepted: true,
      traceId: trace,
      requestPromise: postCommand(path, { ...normalized, trace_id: trace }),
    }
  },
}
