/**
 * HTTP client for the Turn Gateway.
 *
 * Kept free of DSH imports so it can be tested with plain Node.
 */

export class GatewayError extends Error {
  constructor(message, code = 'gateway_error', status = 0) {
    super(message)
    this.name = 'GatewayError'
    this.code = code
    this.status = status
  }
}

export class GatewayClient {
  #baseUrl
  #fetch
  #timeoutMs

  constructor({ baseUrl = 'http://127.0.0.1:8766', fetchImpl = globalThis.fetch, timeoutMs = 6000 } = {}) {
    if (typeof fetchImpl !== 'function') throw new Error('fetch is not available in this runtime')
    this.#baseUrl = String(baseUrl).replace(/\/+$/, '')
    this.#fetch = fetchImpl
    this.#timeoutMs = timeoutMs
  }

  async #request(path, { method = 'GET', body } = {}) {
    let response
    try {
      response = await this.#fetch(this.#baseUrl + path, {
        method,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(this.#timeoutMs),
      })
    } catch (error) {
      throw new GatewayError(`连不上 Turn Gateway：${error?.message ?? error}`, 'offline', 0)
    }
    let payload = null
    try {
      payload = await response.json()
    } catch {
      payload = null
    }
    if (!response.ok) {
      const detail = payload?.error ?? {}
      throw new GatewayError(detail.message ?? `Turn Gateway 返回 HTTP ${response.status}`, detail.code ?? 'http_error', response.status)
    }
    return payload
  }

  async health() {
    return this.#request('/api/health')
  }

  async pending() {
    const body = await this.#request('/api/activations?status=pending')
    return Array.isArray(body?.activations) ? body.activations : []
  }

  async activation(id) {
    const body = await this.#request(`/api/activations/${encodeURIComponent(id)}`)
    return body?.activation ?? null
  }

  async action(id, action) {
    return this.#request(`/api/activations/${encodeURIComponent(id)}/action`, {
      method: 'POST',
      body: { action },
    })
  }

  async ack(id) {
    return this.#request(`/api/activations/${encodeURIComponent(id)}/ack`, {
      method: 'POST',
      body: {},
    })
  }

  async matches() {
    const body = await this.#request('/api/matches')
    return Array.isArray(body?.matches) ? body.matches : []
  }

  async matchDetail(key) {
    const body = await this.#request(`/api/matches/${encodeURIComponent(key)}`)
    return body?.match ?? null
  }
}
