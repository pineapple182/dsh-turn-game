# Contributing

Thanks for trying `dsh-turn-game`. This repo contains the generic plugin
(`lib/`, `test/`) and a Gomoku example (`examples/gomoku/`).

## Layout

- `lib/` — generic DSH adapter. It knows nothing about any game.
- `test/` — Node tests, no dependencies.
- `examples/gomoku/` — Python 3.12 zero-dependency game + Turn Gateway.
- `docs/TURN-PROTOCOL.md` — the game ↔ gateway ↔ plugin contract.

## Requirements

- Node `^22.19.0 || >=24.0.0` (DSH bundles one).
- Python 3.12 for the example only.
- DeepSeek Harness `0.2.x` for live testing.

## Tests

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-plugin.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

`scripts\test.ps1` expects `examples/gomoku/.venv`. Run `scripts\dev.ps1`
once to create it, or create it manually with `python -m venv`.

## Running the example

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\play-agent.ps1
```

Then open <http://127.0.0.1:8765>, click 「对战大肥鱼」, and in DSH say
「绑定游戏」「来一局」or「开始游戏」. Play.

## Installing the plugin

For users, install from the DSH plugin market/mirror or by package name:

```powershell
dsh plugin --profile web add dsh-turn-game
```

No repository clone or PowerShell script is required. The script below is
only for developing this repository from source:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-plugin.ps1
```

Fully quit and restart DSH afterwards.

## Bring a game

The plugin and gateway are generic. New games are welcome:

1. Implement `GET /api/turn` and `POST /api/action` (optional
   `POST /api/presence`); put AI-controlled actors in `agents`.
2. Run the gateway against your game and verify the conformance checklist in
   `docs/TURN-PROTOCOL.md`.
3. Add `examples/<game>/` with a README, a start command, and tests.
4. Add a row to `examples/README.md` and open a PR.

Do not add game-specific branches to `lib/` or the gateway. If the protocol is
insufficient, open an issue to discuss the contract first.

## Protocol changes

The gateway is the only component that decides *when* to wake the model.
Games only expose `GET /api/turn`, `POST /api/action`, and optional
`POST /api/presence`. Keep game-specific logic out of the plugin and out of
the gateway.

Before changing the wire format, update `docs/TURN-PROTOCOL.md` and the
gateway tests.

## License

By contributing you agree that your changes are licensed under the MIT
License in `LICENSE`.
