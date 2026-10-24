# dsh-turn-game

通用 DSH 适配器：把当前会话绑定到 **Turn Gateway**，接收「轮到你」的 activation，让大肥鱼在任意实现了回合协议的游戏里落子。

它**不认识五子棋**——也不认识任何具体游戏。游戏负责提供棋盘、规则说明和动作格式；网关负责在轮到你时创建 activation；插件只负责唤醒 DSH 会话和提交动作。

## 前置

1. 游戏服务已启动（例如 `python -m gamelab serve`，默认 `http://127.0.0.1:8765`）。
2. Turn Gateway 已启动并注册了游戏：

   ```powershell
   python -m gamelab.gateway --game http://127.0.0.1:8765
   ```

   默认监听 `http://127.0.0.1:8766`。
3. DSH 桌面端 / Web 端（验证版本 `0.2.1-rc.2`）。

## 安装

在 `game-lab/` 根目录执行（绝对路径）：

```powershell
dsh plugin --profile desktop add "C:\Users\Eric Li\Documents\deepseek-harness\default-workspace\game-lab\dsh-plugin"
```

如果你用 `web` profile，把 `desktop` 换成 `web`。也可以在 GUI 的「插件 → 添加插件」里填这个绝对路径。安装后需要**完全退出并重启 DSH**。

## 使用

1. 打开游戏网页，点「对战大肥鱼」——你执黑，大肥鱼执白。
2. 在对话里说：**绑定棋局**。
3. 你落子后，网关创建 activation，插件把「回合游戏」消息送进当前会话；大肥鱼思考并调用 `game_action` 落子。
4. 想停就点网页上的「退出人机对战」，或让大肥鱼调用 `game_unbind`。

绑定可以先于开局：`game_bind` 之后即使网关里还没有对局，也会在出现回合时自动唤醒。

## 工具

| 工具 | 作用 |
| --- | --- |
| `game_bind` | 绑定当前会话；可选 `matchId` 只绑定某一局 |
| `game_unbind` | 解除绑定，棋局继续存在 |
| `game_list` | 列出网关里的对局和待处理回合 |
| `game_state` | 查看某局当前的 display / JSON 状态（只读） |
| `game_action` | 提交动作；`activationId` + `action`（JSON 字符串） |

所有工具只访问本机 Turn Gateway，不读写文件、不执行 shell。游戏规则和动作校验都在游戏侧。

## 配置

`cordis.patch.yml`：

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

## 边界

- 绑定是内存态：DSH 重启后要重新说一次「绑定棋局」。
- 一步是一次完整模型调用；只在轮到你时发生。
- 对局结束（玩家赢或和棋）时，网关会发一个 `result` activation，让大肥鱼做收尾复盘；大肥鱼自己下出胜手时，结果已经在落子工具返回里，不再额外唤醒。
- 模型没有提交动作时最多纠正一次，之后交给网关超时；不会无限重试。
- 人机模式下的悔棋由游戏侧禁用，避免“人类悔一手、AI 立刻补一手”。
- Turn Gateway 需要单独启动；插件不会拉起 Python 服务。

## 测试

纯逻辑与 DSH 适配层分离，可直接用 Node 跑：

```powershell
node test/gateway-client.test.mjs
node test/activation-controller.test.mjs
node test/host.test.mjs
```

覆盖：网关 HTTP 客户端、待处理 activation 去重/纠正、绑定会话、动作 JSON 解析、错误与过滤。
