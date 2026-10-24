# Turn Protocol · 通用回合协议

> 目标：游戏只负责呈现回合状态；AI 的唤醒、重试、超时、去重由一个**通用的 Turn Gateway** 负责；DSH 插件只做 DSH 侧适配。新增游戏只实现两个小接口，不再写一套回馈/裁判层。

## 1. 角色

| 角色 | 负责 | 不负责 |
| --- | --- | --- |
| 游戏 Host | 规则、状态、回合归属、合法动作、视觉/文本呈现 | 唤醒 AI、重试、DSH 会话 |
| Turn Gateway | 轮询 `turn`、创建/关闭 activation、去重、超时、事件、转发动作 | 任何游戏规则 |
| DSH 插件 | 绑定 DSH 会话、收 activation、唤醒模型、提交 `game_action` | 任何游戏规则 |
| DSH Agent | 决策，调用 `game_action` | 规则与状态 |

循环：

```
人 → 游戏 UI → 游戏 Host（规则/状态）
                       │ /api/turn、/api/action
                       ▼
                  Turn Gateway（激活层）
                       │ activation 事件 / action 转发
                       ▼
                  DSH 插件（适配器）→ DSH Agent
```

## 2. 游戏 Host 接口

### `GET /api/turn`

返回 200 + 回合信封；没有进行中的回合返回 204。

```json
{
  "protocol": 1,
  "gameId": "gomoku",
  "gameName": "五子棋",
  "matchId": "gomoku-default",
  "turnId": "12",
  "actor": "white",
  "status": "playing",
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

字段约定：

- `turnId`：不透明字符串，**只在回合/局面变化时变**；presence、思考状态等不得改变它。
- `actor`：当前该谁动作；`status != "playing"` 时为 `null`。
- `agents`：由 AI 控制的 actor 列表；空数组表示纯人人对局，网关不会激活。
- `display` / `instructions`：游戏侧的呈现与规则说明；网关和插件原样透传，不解析。
- `state`：游戏自己的结构，网关原样保存。
- `actionSchema` / `actionExample`：动作格式；插件据此提示模型。

### `POST /api/action`

```json
{
  "matchId": "gomoku-default",
  "turnId": "12",
  "actor": "white",
  "action": { "notation": "H8" }
}
```

- 200：`{ "ok": true, "turnId": "13", "actor": "black", "status": "playing", "display": "...", "state": {...} }`
- 409：`stale_turn` / `wrong_actor`
- 400：非法动作（越界、占位、格式错误）
- 404：未知对局

游戏是规则权威：代对方落子、过期回合、非法动作都由游戏拒绝。

### `POST /api/presence`

可选。网关在 activation 创建/关闭时调用：

```json
{ "matchId": "gomoku-default", "actor": "white", "activity": "thinking" }
```

游戏可用于 UI 展示「思考中」；不实现也没关系。

## 3. Turn Gateway 接口

启动：

```powershell
python -m gamelab.gateway --game http://127.0.0.1:8765
```

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/matches` | 已知对局 |
| GET | `/api/matches/{key}` | 对局详情（含 display/state） |
| GET | `/api/activations?status=pending` | 待处理回合 |
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

`kind` 有两种：

- `turn`：轮到你，需要提交动作。
- `result`：对局结束的复盘通知，不需要动作；`actor` 为 `null`，带 `winner` / `gameStatus` / `agents`。插件应唤醒模型做简短复盘，然后调用 `/ack` 关闭。

状态机：

- `turn`：`pending` → `acting` → `acted`；超时 `expired`；回合被外部推进 `superseded`；对局结束 `ended`。
- `result`：`pending` → `acked`；超时 `expired`。

结束事件规则：

- 玩家（非 agent actor）下出最后一手或和棋时，网关创建 `result` activation，让 agent 有机会复盘/收尾。
- agent 自己下出胜手时，它的动作响应里已经带了最终棋盘与结果，不再额外生成 result，避免同一局复盘两次。
- 对局状态从 `playing` 变为结束的 `match` 事件始终会出现在网关事件流里；`result` 只是决定是否唤醒 agent。

规则：

- 同一个 `matchKey + turnId` 只会有一个 activation；插件重复轮询不会重复唤醒。
- `acted` 的 action 重复提交返回原结果（幂等）。
- 动作被游戏拒绝（如占位）时 activation 回到 `pending`，允许模型在同一回合重试；过期后关闭。
- 网关不修改游戏状态，只转发动作。

## 4. DSH 插件的义务

- `game_bind`：把当前会话绑定为适配器；之后只处理 `pending` activation。
- 收到 activation：把 `display` / `instructions` / `state` / `actionExample` 组成一条消息，`followup` 唤醒模型。
  - `turn`：模型应调用 `game_action({activationId, action})`；`action` 是 JSON 字符串（例如 `"{\"notation\":\"H8\"}"`）。
  - `result`：模型做简短复盘，不提交动作；插件在回合结束后调用 `/ack`。
- `whenIdle` 后检查 activation 是否 `acted`；未动作最多纠正一次，之后交给网关超时，不无限重试。
- 不本地改游戏状态，不解析游戏规则。

## 5. 接入新游戏

1. 游戏核心实现 `state`、`turn actor`、`legal actions`、`apply`。
2. 按上文实现 `GET /api/turn`、`POST /api/action`（`/api/presence` 可选）。
3. 在游戏中把「人机对战」的 actor 标进 `agents`（例如 `["white"]`）。
4. 启动网关并 `--game <url>`，或 `POST /api/games` 注册。
5. DSH 插件不用改。

## 6. 安全与后续

- 当前 MVP 信任本机 actor；生产化应为每个 actor 发 token，`/api/action` 校验 token。
- 多游戏/多 agent 时，插件可按 `matchId` 绑定；网关的 activation 已带 `matchKey` 与 `actor`。
- 网关状态在内存；重启会丢失 activation（游戏状态仍在），网关重新轮询会按当前回合重建 activation。
- 超时策略目前只关闭 activation 并清除思考状态；是否判负由游戏规则决定，后续可加 `timeout` 动作。
