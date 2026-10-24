# Changelog

## 0.1.0

- Generic Turn Gateway protocol: `GET /api/turn`, `POST /api/action`,
  optional `POST /api/presence`.
- Generic DSH adapter: `game_bind`, `game_unbind`, `game_list`, `game_state`,
  `game_action`.
- Activation lifecycle with deduplication, one correction, timeout, and
  stale-turn handling.
- `kind: "result"` review notice when the human wins or draws; the agent
  acknowledges it after the review.
- Interface-first README: DSH plugin market/mirror install, broad bind
  intents, trust signals, and an invitation for new games.
- Turn envelope exposes top-level `winner`; the gateway prefers it and falls
  back to `state.winner`.
- Gomoku example: 15×15 Canvas UI, JSON state, CLI, SSE, agent mode,
  79 Python tests.
- 25 Node tests for packaging metadata, the gateway client, activation
  controller, and host tools.
