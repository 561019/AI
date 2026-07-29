import { uniqueId } from './id'

export const AuthOperations = Object.freeze({
  login: 'login',
  register: 'register',
  resume: 'resume',
  logout: 'logout',
})

export const AccountGatewayRoutes = Object.freeze({
  command: '/api/application/account/commands',
})

const platformBaseUrl = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? '').replace(/\/$/, '')

function traceId(prefix = 'L4-ACCOUNT') {
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

async function postCommand(command) {
  const response = await fetch(`${platformBaseUrl}${AccountGatewayRoutes.command}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      trace_id: command.trace_id ?? traceId(),
      request_id: command.request_id ?? uniqueId('request'),
      ...command,
    }),
  })
  const body = await parseJson(response)
  if (!response.ok || body.status === 'failed') {
    const error = body.error ?? { code: 'ACCOUNT_REQUEST_FAILED', details: body }
    throw error
  }
  return body
}

export const accountGatewayApi = {
  createSession(payload) {
    return postCommand({ operation: AuthOperations.login, ...payload })
  },
  createAccount(payload) {
    return postCommand({ operation: AuthOperations.register, ...payload })
  },
  resumeSession(payload) {
    return postCommand({ operation: AuthOperations.resume, ...payload })
  },
  closeSession(payload) {
    return postCommand({ operation: AuthOperations.logout, ...payload })
  },
}

export const authApplicationApi = {
  endpoint: AccountGatewayRoutes.command,

  acceptCommand(command) {
    const requestPromise = (() => {
      if (command.operation === AuthOperations.login) return accountGatewayApi.createSession(command)
      if (command.operation === AuthOperations.register) return accountGatewayApi.createAccount(command)
      if (command.operation === AuthOperations.resume) return accountGatewayApi.resumeSession(command)
      if (command.operation === AuthOperations.logout) return accountGatewayApi.closeSession(command)
      throw new Error(`Unsupported auth operation: ${command.operation}`)
    })()
    return {
      accepted: true,
      traceId: command.trace_id,
      requestPromise,
    }
  },
}
