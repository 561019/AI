export function uniqueId(prefix = 'id') {
  const nativeCrypto = globalThis.crypto
  if (nativeCrypto?.randomUUID) {
    return nativeCrypto.randomUUID()
  }
  const randomPart = nativeCrypto?.getRandomValues
    ? Array.from(nativeCrypto.getRandomValues(new Uint32Array(2)), (value) => value.toString(36)).join('')
    : Math.random().toString(36).slice(2)
  return `${prefix}-${Date.now().toString(36)}-${randomPart}`
}
