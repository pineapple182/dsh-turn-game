import { test } from 'node:test'
import assert from 'node:assert/strict'

import { createGameHost } from '../lib/host.js'

const match = {
  key: 'gomoku:gomoku-default',
  gameId: 'gomoku',
  gameName: '五子棋',
  matchId: 'gomoku-default',
  actor: 'white',
  status: 'playing',
  agents: ['white'],
  online: true,
}

function makeActivation(overrides = {}) {
  return {
    id: 'act-1',
    matchKey: match.key,
    gameId: 'gomoku',
    gameName: '五子棋',
    matchId: 'gomoku-default',
    turnId: '12',
    actor: 'white',
    status: 'pending',
    display: 'board…',
    instructions: '请用 H8 格式落子。',
    actionSchema: { type: 'object' },
    actionExample: { notation: 'H8' },
    state: { currentPlayer: 'white' },
    ...overrides,
  }
}

function makeGateway({ activations = [makeActivation()] } = {}) {
  const gateway = {
    activations,
    status: 'acted',
    calls: { actions: [] },
    acks: [],
    async pending() {
      return gateway.activations.filter((row) => row.status === 'pending')
    },
    async matches() {
      return [match]
    },
    async matchDetail(key) {
      assert.equal(key, match.key)
      return { ...match, display: 'current board', state: { currentPlayer: 'white' } }
    },
    async activation(id) {
      const row = gateway.activations.find((item) => item.id === id)
      return row ? { ...row, status: gateway.status } : null
    },
    async ack(id) {
      gateway.acks.push(id)
      return { ok: true }
    },
    async action(id, action) {
      gateway.calls.actions.push({ id, action })
      return {
        ok: true,
        activation: { ...makeActivation({ id, status: 'acted' }) },
        result: { display: 'next board' },
      }
    },
  }
  return gateway
}

function makeTools() {
  const defs = {}
  return {
    defs,
    register(definition) {
      defs[definition.name] = definition
    },
  }
}

function makeAgent(sessionId = 'session-1') {
  return {
    session: { id: sessionId },
    followups: [],
    followup(message) {
      this.followups.push(message)
    },
    whenIdle: async () => {},
  }
}

function makeHost(gateway) {
  const tools = makeTools()
  const host = createGameHost({
    client: gateway,
    config: { pollMs: 400 },
    defineTool: (definition) => definition,
    createUserMessage: (payload) => payload,
    log: { info() {}, warn() {} },
    tools,
    timers: {
      setInterval: () => 1,
      clearInterval: () => {},
      setTimeout: () => 1,
    },
  })
  host.register()
  return { host, tools }
}

test('registers the five generic tools', () => {
  const { tools } = makeHost(makeGateway())
  assert.deepEqual(Object.keys(tools.defs).sort(), [
    'game_action',
    'game_bind',
    'game_list',
    'game_state',
    'game_unbind',
  ])
})

test('game_bind binds the calling session and reports matches', async () => {
  const { host, tools } = makeHost(makeGateway())
  const agent = makeAgent()
  const text = await tools.defs.game_bind.execute({}, { agent })
  assert.equal(host.binding.sessionId, 'session-1')
  assert.match(text, /五子棋/)
  assert.match(text, /待处理回合：1/)
})

test('refresh injects a generic turn message with the activation', async () => {
  const gateway = makeGateway()
  const { host } = makeHost(gateway)
  const agent = makeAgent()
  host.bind(agent)
  await host.refresh()
  assert.equal(agent.followups.length, 1)
  const text = agent.followups[0].content[0].text
  assert.match(text, /\[回合游戏\] 轮到你/)
  assert.match(text, /game_action/)
  assert.match(text, /act-1/)
  assert.match(text, /board…/)
  assert.match(text, /H8/)
})

test('game_action parses a JSON string and submits it', async () => {
  const gateway = makeGateway()
  const { host, tools } = makeHost(gateway)
  const agent = makeAgent()
  await tools.defs.game_bind.execute({}, { agent })
  const text = await tools.defs.game_action.execute(
    { activationId: 'act-1', action: '{"notation":"H8"}' },
    { agent },
  )
  assert.deepEqual(gateway.calls.actions[0], { id: 'act-1', action: { notation: 'H8' } })
  assert.match(text, /已提交动作/)
  assert.match(text, /next board/)
})

test('game_action rejects a different session and malformed JSON', async () => {
  const { tools } = makeHost(makeGateway())
  const agent = makeAgent()
  await tools.defs.game_bind.execute({}, { agent })
  await assert.rejects(
    () => tools.defs.game_action.execute({ activationId: 'act-1', action: '{}' }, { agent: makeAgent('other') }),
    /没有绑定/,
  )
  await assert.rejects(
    () => tools.defs.game_action.execute({ activationId: 'act-1', action: 'not json' }, { agent }),
    /JSON 字符串/,
  )
})

test('game_state and game_list read through the gateway', async () => {
  const { tools } = makeHost(makeGateway())
  const agent = makeAgent()
  const state = await tools.defs.game_state.execute({ matchId: 'gomoku-default' }, { agent })
  assert.match(state, /current board/)
  const list = await tools.defs.game_list.execute({}, { agent })
  assert.match(list, /五子棋/)
})

test('game_unbind clears the binding', async () => {
  const { host, tools } = makeHost(makeGateway())
  const agent = makeAgent()
  await tools.defs.game_bind.execute({}, { agent })
  await tools.defs.game_unbind.execute({}, { agent })
  assert.equal(host.binding, null)
})

test('result activation triggers a review, not an action', async () => {
  const result = makeActivation({
    id: 'act-9',
    kind: 'result',
    actor: null,
    winner: 'black',
    gameStatus: 'black_win',
    agents: ['white'],
  })
  const gateway = makeGateway({ activations: [result] })
  const { host } = makeHost(gateway)
  const agent = makeAgent()
  host.bind(agent)
  await host.refresh()
  assert.equal(agent.followups.length, 1)
  const text = agent.followups[0].content[0].text
  assert.match(text, /对局结束/)
  assert.match(text, /用户赢了/)
  assert.match(text, /复盘/)
  assert.deepEqual(gateway.acks, ['act-9'])
  assert.deepEqual(gateway.calls.actions, [])
})
