import { uniqueId } from './id'

const platformBaseUrl = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? '').replace(/\/$/, '')
const tenantId = import.meta.env.VITE_PLATFORM_TENANT_ID ?? 'web-workbench'

function newId(prefix) {
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

async function request(path, options = {}) {
  const response = await fetch(`${platformBaseUrl}${path}`, options)
  const body = await parseJson(response)
  if (!response.ok || body.status === 'failed') {
    throw body.error ?? { code: 'PLATFORM_REQUEST_FAILED', details: body }
  }
  return body
}

export function createInstructionEnvelope({
  utterance,
  actor,
  projectId,
  projectName,
  conversationId,
  conversationTitle,
  uploadedDocuments = [],
}) {
  const trace = newId('trace')
  const request = uniqueId('request')
  const message = uniqueId('message')
  return {
    protocol_version: '1.0',
    message_id: message,
    request_id: request,
    trace_id: trace,
    parent_request_id: null,
    source: { layer: 'business_application', module: 'web-workbench' },
    target: { layer: 'business_engine', module: 'engine-gateway', capability: 'intent.analyze' },
    actor: {
      tenant_id: tenantId,
      tenantId,
      authenticated: true,
      ...actor,
    },
    context: {
      project_id: projectId,
      project_name: projectName,
      conversation_id: conversationId,
      conversation_title: conversationTitle,
      locale: 'zh-CN',
    },
    request_type: 'execute',
    action: 'intent.analyze',
    payload: { utterance, uploaded_documents: uploadedDocuments },
    expected_response: { mode: 'async' },
    idempotency_key: `web-${request}`,
  }
}

export const platformApi = {
  tenantId,

  async queryRecords(dataset, { filters = {}, limit = 500 } = {}) {
    const params = new URLSearchParams({ dataset, tenant_id: tenantId, limit: String(limit) })
    if (Object.keys(filters).length) params.set('filters', JSON.stringify(filters))
    if (dataset === 'conversation_messages') params.set('compact', 'true')
    const result = await request(`/api/v1/data/records?${params.toString()}`)
    const items = result.items ?? []
    const filtered = Object.keys(filters).length
      ? items.filter((item) => Object.entries(filters).every(([key, value]) => String(item?.[key] ?? '') === String(value)))
      : items
    return { ...result, items: filtered, count: filtered.length }
  },

  submitInstruction(envelope) {
    return request('/api/v1/application/instructions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(envelope),
    })
  },

  getTask(taskId) {
    return request(`/api/v1/tasks/${encodeURIComponent(taskId)}`)
  },

  confirmIntent(confirmationId, payload) {
    return request(`/api/v1/confirmations/${encodeURIComponent(confirmationId)}/decisions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },

  async uploadDocuments(files, { actor, projectId, conversationId, source = 'file' }) {
    const trace = newId('upload')
    const form = new FormData()
    form.append('tenant_id', tenantId)
    form.append('account_id', actor?.userId ?? actor?.user_id ?? '')
    form.append('authenticated', 'true')
    form.append('project_id', projectId)
    form.append('conversation_id', conversationId)
    form.append('scenario_id', conversationId)
    form.append('trace_id', trace)
    form.append('source_module', 'web-workbench')
    form.append('source', source)
    ;[...files].forEach((file) => form.append('files', file, file.name))
    return request('/api/v1/uploads', { method: 'POST', body: form })
  },

  createGeneratedFile(payload) {
    return request('/api/v1/generated-files', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tenant_id: tenantId,
        ...payload,
      }),
    })
  },
}
