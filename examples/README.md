# Games

这里收录接入 Turn Protocol 的示例游戏。插件和网关是通用的，新增游戏不需要改它们。

| 游戏 | 技术 | 状态 | 入口 |
| --- | --- | --- | --- |
| 五子棋 | Python 3.12 + Canvas + JSON | 参考实现 | [gomoku](gomoku/README.md) |
| 你的游戏 | 任意 | 欢迎 PR | [接入指南](../docs/ADD-A-GAME.md) |

## 加一个游戏

1. 实现 `GET /api/turn`、`POST /api/action`，可选 `POST /api/presence`。
2. 把 AI 控制的 actor 放进 `agents`。
3. 在 `examples/<game>/` 放游戏、README、启动命令和测试。
4. 在这个表格里加一行，开 PR。

游戏是规则权威；唤醒、去重、超时、结束通知都由 Turn Gateway 负责。
契约见 [TURN-PROTOCOL.md](../docs/TURN-PROTOCOL.md)，步骤见
[ADD-A-GAME.md](../docs/ADD-A-GAME.md)。

欢迎其他人、其他鱼带着自己的游戏来玩。
