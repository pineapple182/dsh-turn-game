"""Game-specific adapter for the generic turn protocol.

The Turn Gateway knows nothing about Gomoku; this module translates the engine
into the small game-agnostic envelope described in docs/TURN-PROTOCOL.md.
"""

from __future__ import annotations

from typing import Any

from ..presentation import SIDE_LABELS, render_board, status_line
from .gomoku import GameError, Gomoku, PLAYER_NAMES, parse_coord

MATCH_ID = "gomoku-default"
GAME_NAME = "五子棋"

ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "notation": {
            "type": "string",
            "description": "列 A-O + 行 1-15（从下往上），例如 H8",
        }
    },
    "required": ["notation"],
}
ACTION_EXAMPLE = {"notation": "H8"}


def _agent_side(state: dict[str, Any]) -> str | None:
    mode = state.get("mode")
    return mode.get("agentSide") if isinstance(mode, dict) else None


def instructions(state: dict[str, Any]) -> str:
    agent = _agent_side(state)
    if agent is None:
        return (
            "当前不是人机对战。15×15 无禁手五子棋：黑先，双方交替，先连成 5 子者胜。"
            "坐标：列 A-O（左到右），行 1-15（从下往上），H8 是中心。"
        )
    human = "white" if agent == "black" else "black"
    return (
        f"你执 {SIDE_LABELS[agent]}，用户执 {SIDE_LABELS[human]}。"
        "15×15 无禁手五子棋：黑先、双方交替，先连成 5 子者胜；"
        "已有棋子、越界、代对方落子都会被拒绝。"
        "坐标：列 A-O（左到右），行 1-15（从下往上），H8 是中心。"
        '动作是 JSON 对象：{"notation": "H8"}。'
    )


def compact_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "game": state.get("game"),
        "turnId": state.get("turnId"),
        "boardSize": state.get("boardSize"),
        "board": state.get("board"),
        "status": state.get("status"),
        "winner": state.get("winner"),
        "currentPlayer": state.get("currentPlayer"),
        "mode": state.get("mode"),
        "agentThinking": state.get("agentThinking"),
        "moveCount": state.get("moveCount"),
        "lastMove": state.get("lastMove"),
        "winLine": state.get("winLine"),
    }


def turn_envelope(state: dict[str, Any]) -> dict[str, Any]:
    """Build the game-agnostic turn envelope from an engine snapshot."""
    agents = [mode["agentSide"]] if (mode := state.get("mode")) else []
    return {
        "protocol": 1,
        "gameId": state.get("game", "gomoku"),
        "gameName": GAME_NAME,
        "matchId": MATCH_ID,
        "turnId": str(state.get("turnId")),
        "actor": state.get("currentPlayer") if state.get("status") == "playing" else None,
        "status": state.get("status"),
        "winner": state.get("winner"),
        "agents": agents,
        "display": f"{render_board(state)}\n{status_line(state)}",
        "instructions": instructions(state),
        "actionSchema": ACTION_SCHEMA,
        "actionExample": ACTION_EXAMPLE,
        "state": compact_state(state),
    }


def _require_match(payload: dict[str, Any]) -> None:
    match_id = payload.get("matchId")
    if match_id is not None and match_id != MATCH_ID:
        raise GameError("unknown_match", f"未知对局：{match_id}", status=404)


def _as_side_for(game: Gomoku, actor: str) -> str | None:
    mode = game.mode
    if mode is None:
        return None
    if actor == mode["agentSide"]:
        return "agent"
    if actor == mode["humanSide"]:
        return "human"
    raise GameError("bad_actor", f"未知的 actor：{actor}", status=400)


def apply_action(game: Gomoku, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and apply one turn-protocol action. Runs under the session lock."""
    _require_match(payload)
    state = game.state()
    turn_id = payload.get("turnId")
    if turn_id is None or str(turn_id) != state["turnId"]:
        raise GameError("stale_turn", "回合已经变化，请按最新状态重新动作", status=409)
    actor = payload.get("actor")
    if not isinstance(actor, str):
        raise GameError("missing_argument", "缺少 actor")
    if actor != state["currentPlayer"]:
        raise GameError("wrong_actor", f"现在轮到 {state['currentPlayer']}，不是 {actor}", status=409)
    action = payload.get("action")
    if not isinstance(action, dict):
        raise GameError("bad_action", "action 必须是 JSON 对象", status=400)
    notation = action.get("notation")
    if not isinstance(notation, str):
        raise GameError("bad_action", "action 缺少 notation 字段", status=400)
    x, y = parse_coord(notation, game.size)
    as_side = _as_side_for(game, actor)
    move = game.place(x, y, as_side)
    new_state = game.state()
    return {
        "ok": True,
        "action": "turn-action",
        "move": move,
        "actor": new_state["currentPlayer"],
        "turnId": new_state["turnId"],
        "status": new_state["status"],
        "display": f"{render_board(new_state)}\n{status_line(new_state)}",
        "state": new_state,
    }


def apply_presence(game: Gomoku, payload: dict[str, Any]) -> dict[str, Any]:
    _require_match(payload)
    state = game.state()
    mode = state.get("mode")
    if not mode:
        raise GameError("no_mode", "当前不是人机对战", status=409)
    actor = payload.get("actor")
    if actor != mode["agentSide"]:
        raise GameError("bad_actor", f"presence 只接受 agent actor（{mode['agentSide']}）", status=400)
    activity = payload.get("activity")
    if activity not in ("thinking", "idle"):
        raise GameError("bad_action", "activity 只能是 thinking 或 idle", status=400)
    new_state = game.set_agent_thinking(activity == "thinking")
    return {"ok": True, "action": "presence", "activity": activity, "state": new_state}
