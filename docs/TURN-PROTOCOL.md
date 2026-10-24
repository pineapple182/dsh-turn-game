# Turn Protocol · 通用回合协议

> 这是一份**游戏 ↔ 网关 ↔ DSH 插件**的接口契约，不是五子棋规则。
> 目标：游戏只呈现回合状态；AI 的唤醒、去重、超时、结束通知由通用 Turn Gateway 负责；插件只做 DSH 侧适配。新增游戏不改插件和网关。

## 1. 角色与不变量

| 角色 | MUST 负责 | MUST NOT 负责 |
| --- | --- | --- |
| 游戏 Host | 规则、状态、回合归属、合法动作、呈现、动作校验 | 唤醒 AI、重试、DSH 会话 |
| Turn Gateway | 轮询 `turn`、创建/关闭 activation、去重、超时、事件、转发动作 | 任何游戏规则 |
| DSH 插件 | 绑定当前会话、收 activation、唤醒模型、提交 `game_action` | 任何游戏规则、修改游戏状态 |
| DSH Agent | 决策并调用 `game_action` | 规则与状态 |

全局不变量：

- 游戏是唯一裁判；网关和插件不得自行判负、改棋盘或补动作。
- `turnId` 是回合版本号；`matchId` 在一局内稳定；`gameId` 表示游戏类型。
- 网关对同一个 `matchKey + turnId` 只创建一个 turn activation。
- 玩家赢/和棋时，网关创建 `result` 复盘通知；agent 自己胜出不重复发。

## 2. 传输与版本

- 所有请求/响应使用 `application/json; charset=utf-8`。
- 默认只监听 `127.0.0.1`；远程部署必须自己加认证和 TLS。
- 当前协议版本：`protocol: 1`。破坏性变更必须递增 `protocol`。
- 端点：

| 方法 | 路径 | 必需 | 作用 |
| --- | --- | --- | --- |
| GET | `/api/turn` | 是 | 返回当前回合信封 |
| POST | `/api/action` | 是 | 提交一个动作 |
| POST | `/api/presence` | 否 | 思考中/空闲状态，供 UI |

## 3. `GET /api/turn`

返回 200 + 信封；没有进行中的对局时可返回 204。该请求 MUST 无副作用，网关会高频轮询。

```json
{
  "protocol": 1,
  "gameId": "gomoku",
  "gameName": "五子棋",
  "matchId": "gomoku-default",
  "turnId": "12",
  "actor": "white",
  "status": "playing",
  "winner": null,
  "agents": ["white"],
  "display": "棋盘文本 / 给人和模型看的摘要",
  "instructions": "规则 + 角色 + 动作格式，给模型读",
  "actionSchema": {
    "type": "object",
    "properties": { "notation": { "type": "string" } },
    "required": ["notation"]
  },
  "actionExample": { "notation": "H8" },
  "state": { "...": "游戏自己的 JSON 状态" }
}
```

字段：

| 字段 | 类型 | 必需 | 约定 |
| --- | --- | --- | --- |
| `protocol` | integer | 是 | 当前为 `1` |
| `gameId` | string | 是 | 稳定的游戏类型 id，例如 `gomoku` |
| `gameName` | string | 否 | 展示名；缺省用 `gameId` |
| `matchId` | string | 是 | 一局内稳定；网关用它区分对局 |
| `turnId` | string | 是 | 不透明版本号；局面/回合变化时 MUST 改变 |
| `actor` | string \| null | 是 | 当前轮到谁；终局为 `null` |
| `status` | string | 是 | `playing` 表示进行中；其他值为终局 |
| `winner` | string \| null | 否 | 终局时获胜 actor；和棋为 `null` |
| `agents` | string[] | 是 | AI 控制的 actor；空数组 = 纯人人对局 |
| `display` | string | 是* | 给人/模型看的文本摘要 |
| `instructions` | string | 是* | 规则、角色、动作格式说明 |
| `actionSchema` | object | 是* | 动作 JSON Schema 子集 |
| `actionExample` | object | 是* | 一个合法动作示例 |
| `state` | object | 是 | 游戏自己的 JSON 状态，必须可序列化 |

`*` 进行中（`status == "playing"`）时必需；终局可省略动作字段。

关键语义：

- **`turnId`**：MUST 在落子、悔棋、重置、换人、终局等局面变化时改变；MUST NOT 因 presence、思考动画、UI 刷新而改变。
- **`actor`**：进行中时 SHOULD 属于 `agents` 表示轮到 AI；人类回合时通常是人类 actor，网关不会激活。
- **`agents`**：由游戏决定谁由 AI 控制。网关只对 `actor ∈ agents` 创建 turn activation。
- **`display` / `instructions`**：网关和插件原样透传，不解析。
- **`state`**：网关原样保存；插件只展示/透传，不修改。
- **`actionSchema` / `actionExample`**：插件据此提示模型；动作字段由游戏定义。

## 4. `POST /api/action`

请求：

```json
{
  "matchId": "gomoku-default",
  "turnId": "12",
  "actor": "white",
  "action": { "notation": "H8" }
}
```

成功（200）：

```json
{
  "ok": true,
  "turnId": "13",
  "actor": "black",
  "status": "playing",
  "display": "...",
  "state": { "...": "新的完整状态" }
}
```

游戏 MUST 校验：

1. `matchId` 与当前对局一致；
2. `turnId` 与当前回合一致；
3. `actor` 确实是当前 actor；
4. `action` 是合法动作。

错误：

| HTTP | `error.code` | 含义 |
| --- | --- | --- |
| 400 | `bad_action` | 动作格式/字段错误 |
| 400 | `missing_argument` | 缺少必需参数 |
| 400 | `bad_actor` | actor 不属于该对局 |
| 404 | `unknown_match` | matchId 不存在 |
| 409 | `stale_turn` | turnId 已过期 |
| 409 | `wrong_actor` | 还没轮到该 actor |
| 409 | `game_over` | 对局已结束（如实现） |
| 409 | `no_mode` | 当前不是人机模式（游戏自定义） |

错误响应：

```json
{ "ok": false, "error": { "code": "stale_turn", "message": "回合已经变化" } }
```

规则：

- 动作被拒绝时游戏 MUST 保持状态不变。
- 同一 `turnId` 的重复动作，第二次通常会因 `stale_turn` 被拒绝；网关负责把已成功的动作幂等返回。
- 游戏 MAY 提供更细的错误码，但 MUST 保持上表的语义。

## 5. `POST /api/presence`（可选）

网关在 activation 创建/关闭时调用：

```json
{ "matchId": "gomoku-default", "actor": "white", "activity": "thinking" }
```

- `activity`：`thinking` | `idle`。
- 游戏可用于 UI 展示「思考中」；不实现也不影响协议。
- presence MUST NOT 改变 `turnId`、当前 actor 或棋盘状态。

## 6. Turn Gateway

启动：

```powershell
# 在 examples/gomoku/ 下
python -m gamelab.gateway --game http://127.0.0.1:8765
# 或仓库根目录启动示例游戏 + 网关
powershell -ExecutionPolicy Bypass -File .\scripts\play-agent.ps1
```

默认监听 `http://127.0.0.1:8766`。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/matches` | 已知对局 |
| GET | `/api/matches/{key}` | 对局详情（含 display/state） |
| GET | `/api/activations?status=pending` | 待处理 activation |
| GET | `/api/activations/{id}` | 单个 activation |
| POST | `/api/activations/{id}/action` | `{"action": {...}}`（仅 turn） |
| POST | `/api/activations/{id}/ack` | 确认 result 通知（仅 result） |
| POST | `/api/games` | 运行时注册游戏 `{"url": "http://..."}` |
| GET | `/api/events` | SSE：snapshot / activation / match |

Activation：

```json
{
  "id": "act-3",
  "kind": "turn",
  "matchKey": "gomoku:gomoku-default",
  "gameId": "gomoku",
  "gameName": "五子棋",
  "matchId": "gomoku-default",
  "turnId": "12",
  "actor": "white",
  "winner": null,
  "gameStatus": "playing",
  "agents": ["white"],
  "status": "pending",
  "display": "...",
  "instructions": "...",
  "actionSchema": {...},
  "actionExample": {"notation": "H8"},
  "state": {...},
  "createdAt": "2026-10-24T15:00:00Z",
  "deadline": 1799
}
```

`kind`：

- `turn`：轮到你，需要提交动作。
- `result`：终局复盘通知，不需要动作；`actor` 为 `null`，带 `winner` / `gameStatus` / `agents`。插件唤醒模型做简短复盘，然后 `/ack`。

状态机：

- `turn`：`pending` → `acting` → `acted`；超时 `expired`；回合被外部推进 `superseded`；终局 `ended`。
- `result`：`pending` → `acked`；超时 `expired`。

网关规则：

- 同一 `matchKey + turnId` 只有一个 turn activation；重复轮询不会重复唤醒。
- `acted` 的 action 重复提交返回原结果（幂等）。
- 动作被游戏拒绝（如占位）时 activation 回到 `pending`，允许同回合重试；过期后关闭。
- 终局时关闭 pending turn activation；必要时创建 result 通知。
- 玩家（非 agent actor）下最后一手或和棋 → 创建 result；agent 自己胜出 → 该轮动作返回已带结果，不重复创建。
- 网关不修改游戏状态，只转发动作；activation 内存态，重启后按当前回合重建。

## 7. DSH 插件义务

- `game_bind`：把当前会话绑定为适配器；之后只处理 `pending` activation。
- `game_unbind`：解除绑定，对局继续存在。
- 收到 turn：把 `display` / `instructions` / `state` / `actionExample` 组成消息，`followup` 唤醒模型；模型调用 `game_action({activationId, action})`，`action` 是 JSON 字符串。
- 收到 result：唤醒模型复盘，不提交动作；回合结束后 `/ack`。
- `whenIdle` 后检查 activation 是否 `acted`；未动作最多纠正一次，之后交给网关超时，不无限重试。
- 不本地改游戏状态，不解析游戏规则。

绑定意图 SHOULD 覆盖自然语言变体：绑定游戏/对局、开始游戏、来一局、加入对局、接管回合、连接/重连游戏、继续刚才的对局、陪我玩一局……不应只匹配「棋局」。

## 8. 接入新游戏 / 一致性清单

指南见 [ADD-A-GAME.md](ADD-A-GAME.md)；参考实现见 [examples/gomoku](../examples/gomoku/README.md)。

实现方 MUST 通过：

- [ ] `GET /api/turn` 无副作用，返回 200 信封或 204。
- [ ] 信封含 `protocol` / `gameId` / `matchId` / `turnId` / `actor` / `status` / `agents` / `state`。
- [ ] 进行中时含 `display`、`instructions`、`actionSchema`、`actionExample`。
- [ ] 终局时 `actor == null`，`status != "playing"`，`winner`（或 `state.winner`）可读。
- [ ] 合法动作 200；非法动作 400；错误码符合第 4 节。
- [ ] `stale_turn` / `wrong_actor` 不会改变游戏状态。
- [ ] 同一 `turnId` 的动作不会重复应用。
- [ ] presence 不改变 `turnId` 或局面。
- [ ] 网关轮询不会造成状态变化。
- [ ] `state` 是 JSON 可序列化对象；不包含密钥。
- [ ] 默认只监听本机，或自行提供认证。

建议实现方 SHOULD 通过：

- [ ] 终局 `state.winner` 与顶层 `winner` 一致。
- [ ] 动作响应包含新的 `turnId`、`status`、`display`、`state`。
- [ ] 有单元测试覆盖：合法/非法/过期/错误 actor/终局。
- [ ] 提供 `?static=1` 或无动画的健康检查路径（示例有）。

## 9. 安全与后续

- 当前 MVP 信任本机 actor；生产化应为每个 actor 发 token，并在 `/api/action` 校验。
- 多游戏/多 agent 时，插件可按 `matchId` 绑定；activation 已带 `matchKey` / `actor`。
- 网关状态在内存；重启会丢失 activation（游戏状态仍在），重新轮询会按当前回合重建。
- 超时只关闭 activation 并清除思考状态；是否判负由游戏规则决定，后续可加显式 `timeout` 动作。
- 协议版本变化必须更新本文件、网关测试和示例实现。
