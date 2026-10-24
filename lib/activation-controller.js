/**
 * Generic activation controller: wakes the bound DSH session for one pending
 * activation, waits for the turn to finish, and checks that the gateway marked
 * the activation as acted.
 *
 * It knows nothing about Gomoku (or any other game). The game's display,
 * instructions and action example all arrive inside the activation.
 */

export class ActivationController {
  #client
  #log
  #toUserMessage
  #buildMessage
  #buildCorrection
  #buildResult
  #maxRetries

  binding = null
  inFlight = false
  processed = new Map()

  constructor({
    client,
    log = console,
    toUserMessage = (text) => ({ content: [{ type: 'text', text }] }),
    buildMessage,
    buildCorrection,
    buildResult,
    maxRetries = 1,
  }) {
    this.#client = client
    this.#log = log
    this.#toUserMessage = toUserMessage
    this.#buildMessage = buildMessage
    this.#buildCorrection = buildCorrection
    this.#buildResult = buildResult ?? ((activation) => `对局结束：${activation.matchId}`)
    this.#maxRetries = Math.max(0, Math.min(2, Number(maxRetries) || 0))
  }

  bind(agent, matchId = null) {
    if (!agent?.session?.id) throw new Error('绑定失败：没有可用的会话')
    this.binding = { agent, sessionId: String(agent.session.id), matchId: matchId ?? null }
    this.inFlight = false
    this.processed.clear()
  }

  unbind() {
    this.binding = null
    this.inFlight = false
  }

  async observe(activations) {
    if (!this.binding || this.inFlight) return
    const activation = (activations || []).find((row) => this.#eligible(row))
    if (!activation) return

    this.inFlight = true
    try {
      // Result notices are review requests, not turns: wake the agent, then
      // acknowledge them so the gateway can close the notification.
      if (activation.kind === 'result') {
        await this.#deliver(this.#buildResult(activation))
        try {
          await this.#client.ack(activation.id)
          this.processed.set(activation.id, 'acked')
        } catch (error) {
          this.processed.set(activation.id, 'ack-error')
          this.#log.warn?.(`[turn-game] ack ${activation.id} failed: ${error?.message ?? error}`)
        }
        return
      }
      await this.#deliver(this.#buildMessage(activation))
      let current = await this.#client.activation(activation.id)
      if (current?.status === 'pending') {
        await this.#deliver(this.#buildCorrection(activation))
        current = await this.#client.activation(activation.id)
      }
      this.processed.set(activation.id, current?.status ?? 'unknown')
      if (current?.status !== 'acted') {
        this.#log.warn?.(`[turn-game] activation ${activation.id} ended as ${current?.status ?? 'unknown'}`)
      }
    } catch (error) {
      this.processed.set(activation.id, 'error')
      this.#log.warn?.(`[turn-game] activation ${activation.id} failed: ${error?.message ?? error}`)
    } finally {
      this.inFlight = false
    }
  }

  #eligible(activation) {
    if (!activation || activation.status !== 'pending') return false
    if (this.processed.has(activation.id)) return false
    if (this.binding.matchId !== null && activation.matchId !== this.binding.matchId) return false
    return true
  }

  async #deliver(text) {
    const binding = this.binding
    if (!binding) return
    binding.agent.followup(this.#toUserMessage(text))
    await binding.agent.whenIdle?.()
  }
}
