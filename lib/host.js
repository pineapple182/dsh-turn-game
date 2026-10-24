/**
 * Host logic for the generic DSH turn-game adapter.
 *
 * It consumes activations from the Turn Gateway and exposes five generic tools:
 * game_bind / game_unbind / game_list / game_state / game_action.
 * No game-specific code lives here — the game supplies display, instructions,
 * action schema and action example inside each activation.
 */

import { ActivationController } from './activation-controller.js'

const TEXT_OUTPUT = {
  schema: { type: 'string' },
  render: (_args, value) => [{ type: 'text', text: value }],
}

function renderActivation(activation) {
  const example = JSON.stringify(JSON.stringify(activation.actionExample ?? {}))
  const schema = activation.actionSchema ? JSON.stringify(activation.actionSchema) : null
  return [
    '[回合游戏] 轮到你。',
    `游戏：${activation.gameName ?? activation.gameId} (${activation.gameId})`,
    `对局：${activation.matchId} · 回合 ${activation.turnId} · 角色 ${activation.actor}`,
    `激活：${activation.id}`,
    '',
    activation.display ?? '',
    '',
    activation.instructions ?? '',
    ...(schema ? ['', `动作 schema：${schema}`] : []),
    '',
    '状态 JSON：',
    '```json',
    JSON.stringify(activation.state ?? {}, null, 2),
    '```',
    '',
    '请调用 game_action 提交动作：',
    `- activationId: "${activation.id}"`,
    `- action: JSON 字符串，例如 ${example}`,
    '每次只提交一次；不要用文字代替动作，也不要调用其他工具。',
  ].join('\n')
}

function renderCorrection(activation) {
  const example = JSON.stringify(JSON.stringify(activation.actionExample ?? {}))
  return [
    '[回合游戏] 上一轮没有提交动作，仍然轮到你。',
    `激活：${activation.id}`,
    `请调用 game_action：activationId="${activation.id}"，action 是 JSON 字符串，例如 ${example}。`,
    '只提交一次，不要只用文字回复。',
  ].join('\n')
}

function renderResult(activation) {
  const agents = Array.isArray(activation.agents) ? activation.agents : []
  const winner = activation.winner
  const outcome = !winner ? '和棋' : agents.includes(winner) ? '你赢了' : '用户赢了'
  return [
    '[回合游戏] 对局结束。',
    `游戏：${activation.gameName ?? activation.gameId} (${activation.gameId})`,
    `对局：${activation.matchId} · 结果：${outcome}`,
    '',
    activation.display ?? '',
    '',
    '状态 JSON：',
    '```json',
    JSON.stringify(activation.state ?? {}, null, 2),
    '```',
    '',
    '请简短复盘这一局：关键手、双方的得失，以及下一局可以改进的地方。',
    '不要提交动作，也不要调用其他工具。',
  ].join('\n')
}

function summarizeMatches(matches) {
  if (matches.length === 0) return '（网关里还没有对局）'
  return matches
    .map((match) => `- ${match.gameName ?? match.gameId} · ${match.matchId} · ${match.actor ?? '-'} · ${match.status}`)
    .join('\n')
}

function summarizeActivations(activations) {
  if (activations.length === 0) return '（没有待处理回合）'
  return activations
    .map((activation) => `- ${activation.id} · ${activation.gameName ?? activation.gameId} · ${activation.matchId} · actor=${activation.actor}`)
    .join('\n')
}

export function createGameHost({
  client,
  config = {},
  defineTool,
  createUserMessage,
  log = console,
  tools,
  timers = globalThis,
}) {
  const pollMs = Math.max(200, Math.min(5000, Number(config.pollMs) || 400))

  let binding = null
  let timer = null
  let polling = false
  let offline = false

  const controller = new ActivationController({
    client,
    log,
    buildMessage: renderActivation,
    buildCorrection: renderCorrection,
    buildResult: renderResult,
    toUserMessage: (text) =>
      createUserMessage({
        content: [{ type: 'text', text }],
        source: { kind: 'turn-game' },
      }),
  })

  function startPolling() {
    if (timer) return
    timer = timers.setInterval(() => {
      void refresh()
    }, pollMs)
    timer?.unref?.()
  }

  function stopPolling() {
    if (!timer) return
    timers.clearInterval(timer)
    timer = null
  }

  async function refresh() {
    if (!binding || polling) return
    polling = true
    try {
      const activations = await client.pending()
      if (offline) {
        offline = false
        log.info?.('[turn-game] reconnected to the gateway')
      }
      await controller.observe(activations)
    } catch (error) {
      if (!offline) {
        offline = true
        log.warn?.(`[turn-game] gateway unavailable: ${error?.message ?? error}`)
      }
    } finally {
      polling = false
    }
  }

  function bind(agent, matchId = null) {
    controller.bind(agent, matchId)
    binding = { agent, sessionId: String(agent.session.id), matchId: matchId ?? null }
    startPolling()
    timers.setTimeout(() => {
      void refresh()
    }, 250)
  }

  function unbind() {
    controller.unbind()
    binding = null
    stopPolling()
  }

  async function bindTool(args, exec) {
    const agent = exec.agent
    if (!agent?.session?.id) throw new Error('game_bind 只能由带会话的 agent 调用')
    const matchId = typeof args?.matchId === 'string' && args.matchId.trim() ? args.matchId.trim() : null
    bind(agent, matchId)
    try {
      const [matches, pending] = await Promise.all([client.matches(), client.pending()])
      const filtered = matchId === null ? pending : pending.filter((row) => row.matchId === matchId)
      const lines = [
        '已绑定当前会话到 Turn Gateway。',
        `对局：\n${summarizeMatches(matches)}`,
        `待处理回合：${filtered.length}\n${summarizeActivations(filtered)}`,
      ]
      if (matches.length === 0) {
        lines.push('网关里还没有对局。先在游戏网页点「对战大肥鱼」，出现回合后会自动唤醒我。')
      }
      return lines.join('\n')
    } catch (error) {
      return `已绑定当前会话，但网关暂时不可用：${error?.message ?? error}\n稍后出现回合会自动重试。`
    }
  }

  function register() {
    tools.register(
      defineTool({
        name: 'game_bind',
        description:
          '把当前会话绑定到 Turn Gateway，开始接收「轮到你」的 activation。用户说“绑定棋局 / 开始下棋 / 陪我玩”时调用；可选 matchId 只绑定某一局。',
        parameters: {
          matchId: {
            type: 'string',
            description: '只绑定这个 matchId；省略则接收所有对局',
          },
        },
        output: TEXT_OUTPUT,
        async execute(args, exec) {
          return bindTool(args, exec)
        },
      }),
    )

    tools.register(
      defineTool({
        name: 'game_unbind',
        description: '解除当前会话与 Turn Gateway 的绑定；棋局继续存在，但不会自动唤醒大肥鱼。',
        parameters: {},
        output: TEXT_OUTPUT,
        async execute() {
          unbind()
          return '已解除绑定。'
        },
      }),
    )

    tools.register(
      defineTool({
        name: 'game_list',
        description: '列出 Turn Gateway 里已知的对局和待处理回合。',
        parameters: {},
        output: TEXT_OUTPUT,
        async execute() {
          const [matches, pending] = await Promise.all([client.matches(), client.pending()])
          return `对局：\n${summarizeMatches(matches)}\n\n待处理回合：${pending.length}\n${summarizeActivations(pending)}`
        },
      }),
    )

    tools.register(
      defineTool({
        name: 'game_state',
        description: '查看某个对局当前的棋盘/状态（只读，不提交动作）。',
        parameters: {
          matchId: {
            type: 'string',
            description: '对局 id；省略时若只有一局就用它',
          },
        },
        output: TEXT_OUTPUT,
        async execute(args) {
          const matches = await client.matches()
          if (matches.length === 0) return '网关里还没有对局。'
          const wanted = typeof args?.matchId === 'string' && args.matchId.trim() ? args.matchId.trim() : null
          if (wanted === null && matches.length > 1) {
            return `有多个对局，请指定 matchId：\n${summarizeMatches(matches)}`
          }
          const match = wanted === null ? matches[0] : matches.find((row) => row.matchId === wanted || row.key === wanted)
          if (!match) return `没有找到对局：${wanted}`
          const detail = await client.matchDetail(match.key)
          if (!detail) return `对局详情不可用：${match.key}`
          return `${detail.display ?? ''}\n\n${JSON.stringify(detail.state ?? {}, null, 2)}`
        },
      }),
    )

    tools.register(
      defineTool({
        name: 'game_action',
        description:
          '提交一个 activation 的动作。activationId 来自「回合游戏」消息；action 是 JSON 字符串（例如 "{\\"notation\\":\\"H8\\"}"）。',
        parameters: {
          activationId: {
            type: 'string',
            required: true,
            description: '回合游戏消息里的 activation id',
          },
          action: {
            type: 'string',
            required: true,
            description: 'JSON 对象字符串，例如 {"notation":"H8"}',
          },
        },
        output: TEXT_OUTPUT,
        async execute(args, exec) {
          if (!binding || !exec.agent || binding.sessionId !== String(exec.agent.session.id)) {
            throw new Error('当前会话没有绑定 Turn Gateway；先调用 game_bind')
          }
          const activationId = String(args?.activationId ?? '').trim()
          if (!activationId) throw new Error('缺少 activationId')
          let action
          try {
            action = JSON.parse(String(args?.action ?? ''))
          } catch {
            throw new Error('action 必须是 JSON 字符串，例如 "{\\"notation\\":\\"H8\\"}"')
          }
          if (action === null || typeof action !== 'object' || Array.isArray(action)) {
            throw new Error('action 必须解析为 JSON 对象')
          }
          const result = await client.action(activationId, action)
          const display = result?.result?.display
          const status = result?.activation?.status ?? 'acted'
          return `已提交动作（activation ${activationId}：${status}）。${display ? `\n\n${display}` : ''}`
        },
      }),
    )
  }

  function dispose() {
    stopPolling()
    controller.unbind()
    binding = null
  }

  return {
    register,
    refresh,
    dispose,
    bind,
    unbind,
    get binding() {
      return binding
    },
  }
}
