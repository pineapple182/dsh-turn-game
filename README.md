# dsh-turn-game

让 **DeepSeek Harness 的当前会话**去和任何实现了回合协议的游戏对局：轮到你时被唤醒，落子后休眠；对局结束（玩家赢或和棋）时还会收到一次复盘通知。

插件本身不认识五子棋——也不认识任何具体游戏。游戏只负责呈现与规则；一个通用的 **Turn Gateway** 负责「什么时候该叫醒 AI」；插件负责唤醒 DSH 会话和提交动作。

> 仓库里附带一个完整的五子棋示例：[examples/gomoku](https://github.com/pineapple182/dsh-turn-game/tree/main/examples/gomoku)。

> 仓库根目录就是 npm 包；`examples/` 只是随仓库发布的示例，不进入 npm tarball。

## 架构

```text
人 → 游戏 UI → 游戏 Host（规则 / 状态）
                    │  GET /api/turn / POST /api/action
                    ▼
               Turn Gateway（通用激活层）
                    │  activation / action 转发
                    ▼
               dsh-turn-game（本插件）→ DSH Agent
```

- `turn` activation：轮到你，模型调用 `game_action`。
- `result` activation：玩家赢或和棋，模型做一次收尾复盘，然后 ack；不需要落子。
- 大肥鱼自己下出胜手时，结果已经在落子返回里，不重复唤醒。

协议细节见 [docs/TURN-PROTOCOL.md](https://github.com/pineapple182/dsh-turn-game/blob/main/docs/TURN-PROTOCOL.md)。

## 安装

```powershell
dsh plugin --profile web add dsh-turn-game
# 桌面端把 web 换成 desktop
```

也可以从源码开发：

```powershell
dsh plugin --profile desktop add "C:\path\to\dsh-turn-game"
```

安装后需要**完全退出并重启 DSH**。插件只访问本机 Turn Gateway，不读写文件、不执行 shell。

## 快速开始（五子棋示例）

前置：DSH `0.2.x`、Python 3.12（仅示例需要）、Node（DSH 自带）。示例默认只监听 `127.0.0.1`。

1. 启动示例游戏和网关（在仓库根目录）：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\play-agent.ps1
   ```

2. 打开 <http://127.0.0.1:8765>，点「对战大肥鱼」。
3. 在 DSH 会话里说：**绑定棋局**。
4. 你落子；轮到白方时插件会唤醒模型，模型调用 `game_action` 落子。
5. 你赢或和棋时，网关会发 `result` 通知，大肥鱼做收尾复盘。

![大厅：对战大肥鱼](https://raw.githubusercontent.com/pineapple182/dsh-turn-game/main/docs/screenshots/lobby.png)

## 工具

| 工具 | 作用 |
| --- | --- |
| `game_bind` | 把当前会话绑定到 Turn Gateway；可选 `matchId` 只绑定某一局 |
| `game_unbind` | 解除绑定，棋局继续存在 |
| `game_list` | 列出网关里的对局和待处理回合 |
| `game_state` | 查看某局当前的 display / JSON 状态（只读） |
| `game_action` | 提交动作；`activationId` + `action`（JSON 字符串） |

模型会自动遵守 `whenIdle`、去重、最多一次纠正；结果通知会自动 ack。

## 配置

根目录的 `cordis.patch.yml`：

```yaml
- id: turn-game
  config:
    gatewayUrl: http://127.0.0.1:8766
    pollMs: 400
    enabled: true
```

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `gatewayUrl` | `http://127.0.0.1:8766` | Turn Gateway 地址 |
| `pollMs` | `400` | 轮询 activation 的间隔 |
| `enabled` | `true` | 关闭后不注册工具 |

## 兼容性与权限

- 已验证 DSH `0.2.1-rc.2`；`engines.dsh` 声明 `>=0.2.0-rc.1 <0.3.0`。
- 插件是纯 ESM JavaScript，零运行时依赖；`@deepseek-ai/*` 由宿主提供。
- 只访问配置的本地 Gateway；没有文件、shell 或外部网络权限。
- 动作校验在游戏侧；插件提交的 `action` 由游戏最终裁决。

## 示例：五子棋

- Python 3.12 零第三方依赖；15×15 无禁手、黑白交替、胜负/和棋/悔棋/重开。
- 浏览器 Canvas UI + JSON API + CLI + SSE。
- Turn Gateway 与游戏服务分离，后续换游戏只需实现 `turn`/`action`。
- 详细文档、API 和 JSON 字段：[examples/gomoku](https://github.com/pineapple182/dsh-turn-game/tree/main/examples/gomoku)。

| 中盘 | 终局 |
| --- | --- |
| ![中盘](https://raw.githubusercontent.com/pineapple182/dsh-turn-game/main/docs/screenshots/midgame.png) | ![终局](https://raw.githubusercontent.com/pineapple182/dsh-turn-game/main/docs/screenshots/win.png) |

## 开发与测试

插件测试（Node，无需安装依赖）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-plugin.ps1
```

示例测试（Python）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

当前：79 项 Python + 25 项 Node。

## 已知边界

- 绑定和 activation 是内存态：DSH/网关重启后要重新 `game_bind`；网关会按当前回合重建 activation。
- 示例目前需要 Python；插件本身只需要 Node。
- 对局结束的 `result` 通知只在玩家最后一手/和棋时唤醒；agent 自己胜出时依赖它那一轮的工具结果复盘。
- 还没有 player token；本机 actor 身份是信任的。
- 示例的对局创建走网页「对战大肥鱼」；通用 `POST /match` 还没做。

## 作者

大肥鱼（DeepSeek Harness AI）。维护者：[@pineapple182](https://github.com/pineapple182)。

## License

MIT，见 [LICENSE](https://github.com/pineapple182/dsh-turn-game/blob/main/LICENSE)。
