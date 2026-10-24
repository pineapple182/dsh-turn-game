# dsh-turn-game · DSH ↔ 回合制游戏接口

这是一个**接口项目**，不是五子棋专用插件。

它把 DeepSeek Harness 的当前会话接到一个通用的 **Turn Gateway**：任何游戏只要实现两个小接口（`GET /api/turn` + `POST /api/action`），就能获得「轮到你时唤醒、落子后休眠、结束时复盘」的能力。游戏负责规则和呈现，网关负责什么时候叫醒 AI，插件只负责 DSH 会话。

**五子棋只是 `examples/gomoku` 里的参考实现。** 欢迎其他人、其他鱼带着自己的游戏来接入——不需要改插件，也不需要改网关。

> 仓库根目录就是 npm 包；`examples/` 只是随仓库发布的示例，不进入 npm tarball。

## 架构

```text
玩家 → 游戏 UI → 游戏 Host（规则 / 状态 / 动作校验）
                    │  GET /api/turn / POST /api/action
                    ▼
               Turn Gateway（通用激活层）
                    │  activation / action 转发
                    ▼
               dsh-turn-game（本插件）→ DSH Agent
```

- `turn` activation：轮到你，模型调用 `game_action`。
- `result` activation：玩家赢或和棋，模型做收尾复盘，然后 ack。
- Agent 自己下出胜手时，结果已经在落子返回里，不重复唤醒。
- 网关不认识任何具体游戏；游戏不认识 DSH。

## 安装（DSH 市场 / 镜像优先）

**插件安装不需要 clone 仓库、Python、PowerShell 脚本。** 推荐在 DSH 的插件市场/镜像里搜索 `dsh-turn-game` 安装；也可以直接用 CLI：

```powershell
dsh plugin --profile web add dsh-turn-game
# 桌面端把 web 换成 desktop
```

`dsh plugin` 会把参数转发给 pnpm，插件市场里的 Install 也走同一条下载路径。国内网络可以在 `~/.npmrc` 里配置镜像（npm 和 pnpm 共用）：

```powershell
npm config set registry https://registry.npmmirror.com
# 如果镜像尚未同步新版本，单次改用官方源：
dsh plugin --profile web add dsh-turn-game --registry=https://registry.npmjs.org
```

镜像/代理的排查见 [DSH Plugin Hub 的 npm mirror 教程](https://dsh-plugin.org/tutorials/install-plugin-slow-mirror)。

安装后需要**完全退出并重启 DSH**。

从源码开发时才需要：

```powershell
dsh plugin --profile desktop add "C:\path\to\dsh-turn-game"
```

仓库里的 `scripts/*.ps1` 只用于开发者和示例，不是安装插件的一部分。

## 信任与权限

- **零运行时依赖**：`@deepseek-ai/*` 由 DSH 宿主提供，插件没有自己的 npm 依赖树。
- **无 postinstall / 无构建脚本**：安装不会在你的机器上执行代码。
- **npm 包只有 9 个文件**：`lib/`、`cordis.patch.yml`、README、LICENSE、图标。
- **只访问本机 Gateway**（默认 `http://127.0.0.1:8766`）；不读写文件、不执行 shell、不访问外部网络。
- **MIT**；源码、协议、tarball 内容都可审计；发布 workflow 使用 npm provenance。
- 游戏规则和动作校验在游戏侧，插件不替游戏裁决。

## 开始/绑定：说人话就行

游戏端先创建或加入一局，然后在 DSH 会话里说任意一种：

> 绑定游戏、绑定对局、开始游戏、来一局、加入对局、接管回合、连接游戏、重连游戏、继续刚才那局、陪我玩一局……

`game_bind` 的触发描述覆盖这些意图，不要求出现「棋 / 棋局」字样。绑定可以先于开局：之后出现回合会自动唤醒。

| 工具 | 作用 |
| --- | --- |
| `game_bind` | 把当前会话绑定到 Turn Gateway；可选 `matchId` 只绑定某一局 |
| `game_unbind` | 解除绑定，对局继续存在 |
| `game_list` | 列出网关里的游戏对局和待处理回合 |
| `game_state` | 查看某个游戏对局的状态（`display` + JSON；只读） |
| `game_action` | 提交当前回合的动作；`activationId` + `action`（JSON 字符串） |

插件会自动处理 `whenIdle`、去重、最多一次纠正；结果通知会自动 ack。

## 接口契约与接入新游戏

- 完整契约：[docs/TURN-PROTOCOL.md](https://github.com/pineapple182/dsh-turn-game/blob/main/docs/TURN-PROTOCOL.md)
- 接入指南：[docs/ADD-A-GAME.md](https://github.com/pineapple182/dsh-turn-game/blob/main/docs/ADD-A-GAME.md)
- 示例索引：[examples/README.md](https://github.com/pineapple182/dsh-turn-game/tree/main/examples)

新增游戏只需要：

1. 实现 `GET /api/turn`，返回 `turnId`、`actor`、`agents`、`display`、`instructions`、`state`、`actionSchema`、`actionExample`。
2. 实现 `POST /api/action`，校验 `matchId` / `turnId` / `actor`，返回新的状态。
3. 可选实现 `POST /api/presence`，用于 UI 展示「思考中」。
4. 在游戏里把 AI 控制的 actor 放进 `agents`，把 URL 注册给 Gateway。

插件和网关都不用改。欢迎 PR 把新游戏放到 `examples/<game>/`，并在 [examples/README.md](https://github.com/pineapple182/dsh-turn-game/tree/main/examples) 里加一行。

## 示例：五子棋

- Python 3.12 零第三方依赖；15×15 无禁手，黑白交替，胜负/和棋/悔棋/重开。
- 浏览器 Canvas UI + JSON API + CLI + SSE；79 项 Python 测试。
- 详细文档、API 和 JSON 字段：[examples/gomoku](https://github.com/pineapple182/dsh-turn-game/tree/main/examples/gomoku)。

![大厅：对战大肥鱼](https://raw.githubusercontent.com/pineapple182/dsh-turn-game/main/docs/screenshots/lobby.png)

| 中盘 | 终局 |
| --- | --- |
| ![中盘](https://raw.githubusercontent.com/pineapple182/dsh-turn-game/main/docs/screenshots/midgame.png) | ![终局](https://raw.githubusercontent.com/pineapple182/dsh-turn-game/main/docs/screenshots/win.png) |

## 兼容性

- 已验证 DSH `0.2.1-rc.2`；`engines.dsh` 为 `>=0.2.0-rc.1 <0.3.0`。
- 插件是纯 ESM JavaScript，零运行时依赖；Node `^22.19.0 || >=24.0.0`。
- 只访问配置的本地 Gateway；没有文件、shell 或外部网络权限。
- 还没有 player token；本机 actor 身份是信任的。

## 开发与测试

插件测试（Node，无需安装依赖）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-plugin.ps1
```

示例测试（Python）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

当前：79 项 Python + 25 项 Node。仓库里的脚本只用于开发/示例，不是安装插件的前置步骤。

## 联系

- Bug / 游戏接入 / 新玩法：请开 GitHub Issue。
- 安全问题：请走 GitHub Security Advisories，不要公开贴细节。
- 提交邮箱是 GitHub noreply 地址，**它不是可收信的邮箱**；请不要通过它联系。

## 作者

大肥鱼（DeepSeek Harness AI）。维护者：[@pineapple182](https://github.com/pineapple182)。

## License

MIT，见 [LICENSE](https://github.com/pineapple182/dsh-turn-game/blob/main/LICENSE)。
