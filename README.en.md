# dsh-turn-game · DSH ↔ turn-based games

[中文](https://github.com/pineapple182/dsh-turn-game/blob/main/README.md) | **English**

This is an **interface project**, not a Gomoku-only plugin.

It connects the current DeepSeek Harness session to a generic **Turn Gateway**. Any game that implements two small endpoints (`GET /api/turn` + `POST /api/action`) gets "wake the agent on its turn, sleep after the move, review at the end" for free. The game owns rules and presentation, the gateway decides *when* to wake the agent, and the plugin only handles the DSH session.

**Gomoku is just the reference implementation in `examples/gomoku`.** Other people — and other fish — are welcome to bring their own games. You do not need to change the plugin or the gateway.

> The repository root is the npm package. `examples/` ships with the repository for demonstration and is not included in the npm tarball.

## Architecture

```text
player → game UI → game host (rules / state / action validation)
                    │  GET /api/turn / POST /api/action
                    ▼
               Turn Gateway (generic activation layer)
                    │  activation / action forwarding
                    ▼
               dsh-turn-game (this plugin) → DSH agent
```

- `turn` activation: it is your turn; the model calls `game_action`.
- `result` activation: the human won or drew; the model writes a short review, then acks.
- When the agent itself makes the winning move, the result is already in the action response, so no duplicate review is triggered.
- The gateway knows no specific game; the game knows nothing about DSH.

## Install (DSH market / mirror first)

**Installing the plugin does not require cloning this repository, Python, or any PowerShell script.** Install it from the DSH plugin market/mirror, or use the CLI:

```powershell
dsh plugin --profile web add dsh-turn-game
# use `desktop` instead of `web` on the desktop app
```

`dsh plugin` forwards to pnpm, and the Install button in the plugin market follows the same download path. On a slow network, configure an npm mirror in `~/.npmrc` (npm and pnpm share it):

```powershell
npm config set registry https://registry.npmmirror.com
# if the mirror has not synced a new version yet, use the official registry once:
dsh plugin --profile web add dsh-turn-game --registry=https://registry.npmjs.org
```

See the [DSH Plugin Hub npm mirror guide](https://dsh-plugin.org/tutorials/install-plugin-slow-mirror) for mirror and proxy troubleshooting.

Restart DSH completely after installing.

For source development only:

```powershell
dsh plugin --profile desktop add "C:\path\to\dsh-turn-game"
```

The `scripts/*.ps1` files are for development and the example. They are not part of plugin installation.

## Trust and permissions

- **Zero runtime dependencies**: `@deepseek-ai/*` comes from the DSH host; the plugin brings no dependency tree of its own.
- **No postinstall / no build scripts**: installation does not execute code on your machine.
- **Small npm tarball**: `lib/`, `cordis.patch.yml`, README, LICENSE, and the icon.
- **Local gateway only** (default `http://127.0.0.1:8766`); no filesystem access, no shell, no external network.
- **MIT**; source, protocol, and tarball contents are auditable; the release workflow publishes with npm provenance.
- The game is the rules authority; the plugin never decides game outcomes.

## Start / bind: just say it

Create or join a match in the game first, then say any of these in DSH:

> bind the game, bind the match, start a game, start a match, join the match, take the turn, connect the game, reconnect, continue the game, play a game with me…

`game_bind` matches the intent; you do not need to say "chess" or "Gomoku". You can bind before a match exists — the session will wake when a turn appears.

| Tool | Purpose |
| --- | --- |
| `game_bind` | Bind the current session to the Turn Gateway; optional `matchId` |
| `game_unbind` | Remove the binding; the match keeps running |
| `game_list` | List known matches and pending turns |
| `game_state` | Read a match's `display` + JSON state (read-only) |
| `game_action` | Submit the current turn's action: `activationId` + `action` (JSON string) |

The plugin handles `whenIdle`, deduplication, and at most one correction; result notices are acked automatically.

## Contract and adding games

- Full contract: [docs/TURN-PROTOCOL.md](https://github.com/pineapple182/dsh-turn-game/blob/main/docs/TURN-PROTOCOL.md)
- Adding a game: [docs/ADD-A-GAME.md](https://github.com/pineapple182/dsh-turn-game/blob/main/docs/ADD-A-GAME.md)
- Example index: [examples/README.md](https://github.com/pineapple182/dsh-turn-game/tree/main/examples)

A new game only needs to:

1. Implement `GET /api/turn` with `turnId`, `actor`, `agents`, `display`, `instructions`, `state`, `actionSchema`, and `actionExample`.
2. Implement `POST /api/action`, validating `matchId`, `turnId`, and `actor`, and returning the new state.
3. Optionally implement `POST /api/presence` for a "thinking" indicator.
4. Put AI-controlled actors in `agents` and register the game URL with the gateway.

The plugin and gateway stay unchanged. PRs adding a game under `examples/<game>/` and a row in [examples/README.md](https://github.com/pineapple182/dsh-turn-game/tree/main/examples) are welcome.

## Example: Gomoku

- Python 3.12, zero third-party dependencies; 15×15, no forbidden moves, alternating colors, win/draw/undo/reset.
- Canvas UI + JSON API + CLI + SSE; 79 Python tests.
- Full documentation, API, and JSON fields: [examples/gomoku](https://github.com/pineapple182/dsh-turn-game/tree/main/examples/gomoku).

![Lobby: play the fish](https://raw.githubusercontent.com/pineapple182/dsh-turn-game/main/docs/screenshots/lobby.png)

| Midgame | Finished |
| --- | --- |
| ![Midgame](https://raw.githubusercontent.com/pineapple182/dsh-turn-game/main/docs/screenshots/midgame.png) | ![Finished](https://raw.githubusercontent.com/pineapple182/dsh-turn-game/main/docs/screenshots/win.png) |

## Compatibility

- Verified with DSH `0.2.1-rc.2`; `engines.dsh` is `>=0.2.0-rc.1 <0.3.0`.
- Pure ESM JavaScript, zero runtime dependencies; Node `^22.19.0 || >=24.0.0`.
- Talks only to the configured local Gateway; no filesystem, shell, or external network access.
- No player tokens yet; local actors are trusted.

## Development and tests

Plugin tests (Node, no install required):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-plugin.ps1
```

Example tests (Python):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

Currently 79 Python tests and 25 Node tests. The scripts are for development and the example only; they are not a prerequisite for installing the plugin.

## Contact

- Bugs, game integrations, new game ideas: open a GitHub Issue.
- Security: use GitHub Security Advisories; do not post details publicly.
- The commit email is a GitHub noreply address. **It is not a monitored mailbox**; please do not use it for contact.

## Author

大肥鱼 (DeepSeek Harness AI). Maintainer: [@pineapple182](https://github.com/pineapple182).

## License

MIT, see [LICENSE](https://github.com/pineapple182/dsh-turn-game/blob/main/LICENSE).
