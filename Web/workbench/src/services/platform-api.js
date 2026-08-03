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
  conversationContext = [],
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
    payload: {
      utterance,
      uploaded_documents: uploadedDocuments,
      // The gateway independently reloads this window from persistence. This
      // client copy keeps the current turn usable while a write is not yet queryable.
      conversation_context: Array.isArray(conversationContext)
        ? conversationContext.slice(-12).map((item) => ({
          role: String(item?.role || 'unknown'),
          content: String(item?.text || item?.content || '').slice(0, 2000),
        })).filter((item) => item.content.trim())
        : [],
    },
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

  async queryKnowledgeChunks({ knowledgeSourceId, fileId, ownerAccountId, limit = 100 } = {}) {
    const filters = {}
    if (knowledgeSourceId) filters.knowledge_source_id = knowledgeSourceId
    if (fileId) filters.file_id = fileId
    if (ownerAccountId) filters.owner_account_id = ownerAccountId
    return this.queryRecords('knowledge_chunks', { filters, limit })
  },

  reindexKnowledgeFile(fileId, { actor } = {}) {
    return request('/api/v1/uploads/reindex', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_id: fileId,
        tenant_id: tenantId,
        actor: actor ?? { tenant_id: tenantId, user_id: '', authenticated: true },
      }),
    })
  },

  submitInstruction(envelope) {
    return request('/api/v1/application/instructions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(envelope),
    })
  },

  evaluateContextCapacity({ actor, projectId, conversationId, capacityLimit = 8000 } = {}) {
    return request('/api/v1/application/context/capacity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        trace_id: newId('ctx-cap'),
        request_id: uniqueId('request'),
        tenant_id: tenantId,
        actor: {
          ...actor,
          tenant_id: tenantId,
          user_id: actor?.user_id || actor?.userId || actor?.accountId || '',
          authenticated: true,
        },
        project_id: projectId,
        conversation_id: conversationId,
        capacity_limit: capacityLimit,
      }),
    })
  },

  generateContextHandoff({ actor, projectId, conversationId } = {}) {
    return request('/api/v1/application/context/handoff', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        trace_id: newId('ctx-handoff'),
        request_id: uniqueId('request'),
        tenant_id: tenantId,
        actor: {
          ...actor,
          tenant_id: tenantId,
          user_id: actor?.user_id || actor?.userId || actor?.accountId || '',
          authenticated: true,
        },
        project_id: projectId,
        conversation_id: conversationId,
      }),
    })
  },

  queryContextHandoff({ actor, scope = 'conversation', projectId = '', conversationId = '' } = {}) {
    return request('/api/v1/application/context/handoff/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        trace_id: newId('ctx-query'),
        request_id: uniqueId('request'),
        tenant_id: tenantId,
        actor: {
          ...actor,
          tenant_id: tenantId,
          user_id: actor?.user_id || actor?.userId || actor?.accountId || '',
          authenticated: true,
        },
        scope,
        project_id: projectId,
        conversation_id: conversationId,
      }),
    })
  },

  deleteKnowledgeFile({ actor, fileId, reason = 'user_requested' } = {}) {
    return request('/api/v1/application/knowledge/files/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        trace_id: newId('kb-delete'),
        request_id: uniqueId('request'),
        tenant_id: tenantId,
        actor: {
          ...actor,
          tenant_id: tenantId,
          user_id: actor?.user_id || actor?.userId || actor?.accountId || '',
          authenticated: true,
        },
        file_id: fileId,
        reason,
      }),
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

  async uploadDocuments(files, { actor, projectId, conversationId, source = 'file', assetScope = '', knowledgeBaseId = '', knowledgeBaseName = '' }) {
    const trace = newId('upload')
    const form = new FormData()
    form.append('tenant_id', tenantId)
    form.append('account_id', actor?.userId ?? actor?.user_id ?? '')
    form.append('authenticated', 'true')
    if (projectId) form.append('project_id', projectId)
    if (conversationId) form.append('conversation_id', conversationId)
    form.append('scenario_id', conversationId || knowledgeBaseId || source || 'manual-upload')
    form.append('trace_id', trace)
    form.append('source_module', 'web-workbench')
    form.append('source', source)
    if (assetScope) form.append('asset_scope', assetScope)
    if (knowledgeBaseId) form.append('knowledge_base_id', knowledgeBaseId)
    if (knowledgeBaseName) form.append('knowledge_base_name', knowledgeBaseName)
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
