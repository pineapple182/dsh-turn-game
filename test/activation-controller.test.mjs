import { test } from 'node:test'
import assert from 'node:assert/strict'

import { ActivationController } from '../lib/activation-controller.js'

function makeActivation(overrides = {}) {
  return {
    id: 'act-1',
    matchId: 'gomoku-default',
    gameId: 'gomoku',
    gameName: '五子棋',
    actor: 'white',
    turnId: '12',
    status: 'pending',
    display: 'board',
    instructions: 'place a stone',
    actionExample: { notation: 'H8' },
    state: {},
    ...overrides,
  }
}

function makeClient(status = 'pending') {
  const client = {
    currentStatus: status,
    calls: { activation: 0 },
    acks: [],
    async activation(id) {
      this.calls.activation += 1
      return makeActivation({ id, status: this.currentStatus })
    },
    async ack(id) {
      this.acks.push(id)
      return { ok: true }
    },
  }
  return client
}

function makeAgent({ onFollowup, whenIdle } = {}) {
  return {
    session: { id: 'session-1' },
    followups: [],
    followup(message) {
      this.followups.push(message)
      onFollowup?.(message, this)
    },
    whenIdle: whenIdle ?? (async () => {}),
  }
}

function makeController(client, agent, { matchId = null, maxRetries = 1 } = {}) {
  const logs = []
  const controller = new ActivationController({
    client,
    maxRetries,
    log: { warn: (line) => logs.push(line), info() {} },
    toUserMessage: (text) => ({ content: [{ type: 'text', text }] }),
    buildMessage: (activation) => `turn:${activation.id}`,
    buildCorrection: (activation) => `fix:${activation.id}`,
    buildResult: (activation) => `result:${activation.id}`,
  })
  controller.bind(agent, matchId)
  return { controller, logs }
}

test('does nothing while unbound', async () => {
  const client = makeClient()
  const agent = makeAgent()
  const controller = new ActivationController({
    client,
    log: { warn() {} },
    buildMessage: () => 'turn',
    buildCorrection: () => 'fix',
  })
  await controller.observe([makeActivation()])
  assert.equal(agent.followups.length, 0)
})

test('wakes once and records an acted activation', async () => {
  const client = makeClient()
  const agent = makeAgent({
    onFollowup: () => {
      client.currentStatus = 'acted'
    },
  })
  const { controller } = makeController(client, agent)
  await controller.observe([makeActivation()])
  assert.equal(agent.followups.length, 1)
  assert.equal(agent.followups[0].content[0].text, 'turn:act-1')
  assert.equal(controller.processed.get('act-1'), 'acted')
})

test('sends one correction when the model did not act', async () => {
  const client = makeClient('pending')
  const agent = makeAgent()
  const { controller, logs } = makeController(client, agent)
  await controller.observe([makeActivation()])
  assert.equal(agent.followups.length, 2)
  assert.equal(agent.followups[0].content[0].text, 'turn:act-1')
  assert.equal(agent.followups[1].content[0].text, 'fix:act-1')
  assert.equal(controller.processed.get('act-1'), 'pending')
  assert.equal(logs.length, 1)
})

test('does not start a second activation in flight', async () => {
  const client = makeClient()
  let release
  const idle = new Promise((resolve) => {
    release = resolve
  })
  const agent = makeAgent({
    whenIdle: () => idle,
    onFollowup: () => {
      client.currentStatus = 'acted'
    },
  })
  const { controller } = makeController(client, agent)
  const first = controller.observe([makeActivation()])
  const second = controller.observe([makeActivation()])
  await second
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(agent.followups.length, 1)
  release()
  await first
})

test('filters by matchId', async () => {
  const client = makeClient()
  const agent = makeAgent({ onFollowup: () => { client.currentStatus = 'acted' } })
  const { controller } = makeController(client, agent, { matchId: 'other-match' })
  await controller.observe([makeActivation()])
  assert.equal(agent.followups.length, 0)
})

test('does not retrigger a processed activation', async () => {
  const client = makeClient()
  const agent = makeAgent({ onFollowup: () => { client.currentStatus = 'acted' } })
  const { controller } = makeController(client, agent)
  await controller.observe([makeActivation()])
  await controller.observe([makeActivation()])
  assert.equal(agent.followups.length, 1)
})

test('recovers when the activation expired before the turn', async () => {
  const client = makeClient('expired')
  const agent = makeAgent()
  const { controller } = makeController(client, agent)
  await controller.observe([makeActivation()])
  assert.equal(agent.followups.length, 1)
  assert.equal(controller.processed.get('act-1'), 'expired')
})

test('delivers a result notice and acks it', async () => {
  const client = makeClient()
  const agent = makeAgent()
  const { controller } = makeController(client, agent)
  const result = makeActivation({
    id: 'act-9',
    kind: 'result',
    actor: null,
    winner: 'black',
    gameStatus: 'black_win',
    agents: ['white'],
  })
  await controller.observe([result])
  assert.equal(agent.followups.length, 1)
  assert.equal(agent.followups[0].content[0].text, 'result:act-9')
  assert.deepEqual(client.acks, ['act-9'])
  assert.equal(controller.processed.get('act-9'), 'acked')
  assert.equal(client.calls.activation, 0)
})
