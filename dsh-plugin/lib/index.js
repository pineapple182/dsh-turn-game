/**
 * DSH adapter for the generic Turn Gateway.
 *
 * The adapter is intentionally game-agnostic: it binds the current session,
 * receives activations, and exposes generic turn-game tools. Any game that
 * implements `GET /api/turn` + `POST /api/action` works without plugin changes.
 */

import z from '@deepseek-ai/schemastery'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { GatewayClient } from './gateway-client.js'
import { createGameHost } from './host.js'

export const name = 'dsh-turn-game'
export const inject = ['tools']

export const Config = z.object({
  gatewayUrl: z.string().default('http://127.0.0.1:8766'),
  pollMs: z.number().default(400),
  enabled: z.boolean().default(true),
})

function loggerFor(ctx) {
  try {
    const logger = typeof ctx.logger === 'function' ? ctx.logger(name) : ctx.logger
    return {
      info: (message) => logger?.info?.(message),
      warn: (message) => logger?.warn?.(message),
      error: (message) => logger?.error?.(message),
    }
  } catch {
    return { info() {}, warn() {}, error() {} }
  }
}

export function apply(ctx, config) {
  if (config?.enabled === false) return

  const log = loggerFor(ctx)
  const host = createGameHost({
    client: new GatewayClient({ baseUrl: config?.gatewayUrl ?? 'http://127.0.0.1:8766' }),
    config,
    defineTool,
    createUserMessage,
    log,
    tools: ctx.tools,
    timers: {
      setInterval: (fn, ms) => globalThis.setInterval(fn, ms),
      clearInterval: (handle) => globalThis.clearInterval(handle),
      setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
    },
  })

  host.register()
  ctx.effect(() => () => host.dispose())
}
