# 接入一个新游戏

`dsh-turn-game` 是接口项目：游戏是示例，插件和网关都不认识具体规则。
只要你的游戏实现下面三个端点，就能直接和 DSH 对局，**不需要改本仓库的插件或网关**。

完整字段与错误码见 [TURN-PROTOCOL.md](TURN-PROTOCOL.md)。参考实现是
[examples/gomoku](../examples/gomoku/README.md)。

## 最小实现

### 1. `GET /api/turn`

返回当前回合，必须无副作用：

```json
{
  "protocol": 1,
  "gameId": "my-game",
  "gameName": "我的游戏",
  "matchId": "default",
  "turnId": "7",
  "actor": "white",
  "status": "playing",
  "winner": null,
  "agents": ["white"],
  "display": "人类可读的棋盘/局面",
  "instructions": "规则、你是谁、动作格式",
  "actionSchema": {
    "type": "object",
    "properties": { "move": { "type": "string" } },
    "required": ["move"]
  },
  "actionExample": { "move": "a1" },
  "state": { "your": "own json" }
}
```

- `turnId` 是局面版本号：落子/悔棋/重置/终局必须变；presence 和 UI 刷新不能变。
- `agents` 放 AI 控制的 actor。只有 `actor` 在 `agents` 里时，网关才会叫醒模型。
- 终局：`actor: null`、`status` 不是 `playing`、给出 `winner`（和棋 `null`）。

没有进行中的对局可以返回 `204`。

### 2. `POST /api/action`

```json
{
  "matchId": "default",
  "turnId": "7",
  "actor": "white",
  "action": { "move": "a1" }
}
```

必须校验 `matchId` / `turnId` / `actor` / 动作合法性；成功后返回新的
`turnId`、`status`、`display`、`state`。拒绝时不要改变游戏状态，错误码见协议。

### 3. `POST /api/presence`（可选）

```json
{ "matchId": "default", "actor": "white", "activity": "thinking" }
```

只用于 UI 展示思考中；不能改 `turnId` 或局面。

## 接到网关

```powershell
# 你的游戏监听 9000
python -m gamelab.gateway --game http://127.0.0.1:9000
```

或运行时注册：

```powershell
curl -X POST http://127.0.0.1:8766/api/games -H "Content-Type: application/json" -d "{\"url\":\"http://127.0.0.1:9000\"}"
```

然后在 DSH 里说「绑定游戏 / 来一局 / 开始游戏」即可。插件不用改。

## 自检

至少覆盖：

- [ ] 合法动作成功，非法动作 400，状态不变。
- [ ] 过期 `turnId` 返回 `stale_turn`，错误 actor 返回 `wrong_actor`。
- [ ] 同一动作不会重复应用。
- [ ] `turnId` 只在局面变化时变。
- [ ] 终局 `actor == null`、`winner` 可读。
- [ ] 轮询 `GET /api/turn` 不会改状态。
- [ ] `state` 可 JSON 序列化，不含密钥。

## 提交到本仓库

欢迎其他人/鱼把新游戏作为示例放进来：

1. 新建 `examples/<game>/`，自带 README、启动命令、至少一组规则/协议测试。
2. 在 [examples/README.md](../examples/README.md) 的表格里加一行。
3. PR 描述里写：游戏类型、如何启动、如何触发 AI 回合、截图/GIF（可选）。
4. 不需要改 `lib/` 或网关；如果协议不够用，先开 Issue 讨论契约，而不是在游戏里打补丁。

游戏类型不限：棋类、卡牌、文字冒险、桌游、回合制策略、猜拳……
只要能把「轮到谁」表达成 `actor`，把动作表达成 JSON，就能接。

## 约定

- 游戏是规则权威；插件和网关不替游戏裁决。
- 不要把 DSH、模型调用或重试逻辑写进游戏。
- `display` 给人看，`instructions` 给模型看；两者都可以包含中文。
- 默认只监听 `127.0.0.1`；远程部署请自己加认证和 TLS。
- 示例脚本仅用于开发，不是玩家安装插件的前置步骤。
