"""Gomoku (five-in-a-row) engine.

The engine is deliberately dependency-free and framework-agnostic:

* :class:`Gomoku` owns the rules and the complete, JSON-serialisable state.
* :meth:`Gomoku.execute` understands the same small command language that the
  browser command bar and the CLI send over HTTP.
* Coordinates are ``(x, y)`` with ``x`` counted from the left (0..14) and ``y``
  from the top (0..14). The human notation is a column letter ``A..O`` plus a
  row number ``1..15`` counted from the *bottom*, so that ``H8`` is the centre
  of the board.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

BOARD_SIZE = 15
WIN_LENGTH = 5

EMPTY = 0
BLACK = 1
WHITE = 2

COLUMNS = "ABCDEFGHIJKLMNO"
PLAYER_NAMES = {BLACK: "black", WHITE: "white"}
NAME_TO_PLAYER = {name: player for player, name in PLAYER_NAMES.items()}

SCHEMA_VERSION = 1

_COORD_RE = re.compile(r"^([A-O])\s*([0-9]{1,2})$")

HELP_LINES = [
    "H8          落子（列 A-O，行 1-15，从下往上数）",
    "place H8    同上，显式写法",
    "undo        悔棋一步",
    "reset       重开一局",
    "state       查看完整 JSON 状态",
    "help        显示本帮助",
]


class GameError(Exception):
    """An error caused by an illegal move or command (safe to show to users)."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def notation(x: int, y: int, size: int = BOARD_SIZE) -> str:
    """Convert board coordinates to the human notation, e.g. ``(7, 7) -> "H8"``."""
    if not (0 <= x < size and 0 <= y < size):
        raise GameError(
            "out_of_range",
            f"坐标超出棋盘：x={x}, y={y}（合法范围 0-{size - 1}）",
        )
    return f"{COLUMNS[x]}{size - y}"


def parse_coord(text: str, size: int = BOARD_SIZE) -> tuple[int, int]:
    """Parse human notation such as ``H8`` / ``h8`` / ``A1`` into ``(x, y)``."""
    cleaned = text.strip().upper()
    match = _COORD_RE.fullmatch(cleaned)
    if not match:
        raise GameError(
            "bad_notation",
            f"无法识别的坐标：{text!r}（示例：H8 / A1 / O15）",
        )
    x = COLUMNS.index(match.group(1))
    row = int(match.group(2))
    if not 1 <= row <= size:
        raise GameError(
            "bad_notation",
            f"行号超出范围：{row}（合法范围 1-{size}）",
        )
    return x, size - row


class Gomoku:
    """A single Gomoku game.

    The board is a list of ``size`` rows, each a list of ``size`` integers:
    ``0`` empty, ``1`` black, ``2`` white. Black always moves first.
    """

    name = "gomoku"
    display_name = "五子棋"

    def __init__(self, size: int = BOARD_SIZE, win_length: int = WIN_LENGTH) -> None:
        if size < win_length:
            raise ValueError("win_length cannot be larger than size")
        self.size = size
        self.win_length = win_length
        self._revision = 0
        # Turn identity is independent from the UI revision: presence and mode
        # changes bump revision, but only a move/reset/undo starts a new turn.
        self._turn_seq = 0
        # Human-vs-agent mode lives beside the rules: the engine is still the
        # authority on whose turn it is, so a mis-timed click cannot place a
        # stone for the other side.
        self.mode: dict[str, str] | None = None
        self.agent_thinking = False
        self.agent_thinking_since: str | None = None
        self._new_game()

    # ------------------------------------------------------------------ setup

    def _new_game(self) -> None:
        self.board: list[list[int]] = [[EMPTY] * self.size for _ in range(self.size)]
        self.moves: list[dict[str, Any]] = []
        self.current: int | None = BLACK
        self.status: str = "playing"
        self.winner: str | None = None
        self.win_line: list[tuple[int, int]] | None = None
        self.created_at: str = _now()
        self.updated_at: str = self.created_at

    def _touch(self) -> None:
        self.updated_at = _now()
        self._revision += 1

    # ------------------------------------------------------------------ rules

    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size

    def _winning_line(self, x: int, y: int, player: int) -> list[tuple[int, int]] | None:
        """Return every stone of the winning run through ``(x, y)``, if any."""
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            cells = [(x, y)]
            nx, ny = x + dx, y + dy
            while self._in_bounds(nx, ny) and self.board[ny][nx] == player:
                cells.append((nx, ny))
                nx, ny = nx + dx, ny + dy
            nx, ny = x - dx, y - dy
            while self._in_bounds(nx, ny) and self.board[ny][nx] == player:
                cells.insert(0, (nx, ny))
                nx, ny = nx - dx, ny - dy
            if len(cells) >= self.win_length:
                return cells
        return None

    def _actor_check(self, as_side: str | None) -> None:
        """Enforce the human/agent split when agent mode is active."""
        if self.mode is None:
            if as_side is not None:
                raise GameError("mode_not_active", "当前不是人机对战，不能指定落子方")
            return
        if as_side is None:
            raise GameError("actor_required", "人机对战中落子必须声明 as：human 或 agent")
        if as_side not in ("human", "agent"):
            raise GameError("bad_actor", "落子方只能是 human 或 agent")
        expected = self.mode["humanSide"] if as_side == "human" else self.mode["agentSide"]
        current = PLAYER_NAMES.get(self.current)
        if current != expected:
            raise GameError(
                "not_your_turn",
                f"现在轮到 {current}，{as_side} 不能落子",
                status=409,
            )

    def place(self, x: int, y: int, as_side: str | None = None) -> dict[str, Any]:
        """Place a stone for the current player and return the recorded move."""
        if self.status != "playing":
            raise GameError("game_over", "对局已经结束，先执行 reset 重开一局")
        if not (isinstance(x, int) and isinstance(y, int)):
            raise GameError("bad_notation", "坐标必须是整数")
        if not self._in_bounds(x, y):
            raise GameError(
                "out_of_range",
                f"坐标超出棋盘：x={x}, y={y}（合法范围 0-{self.size - 1}）",
            )
        self._actor_check(as_side)
        if self.board[y][x] != EMPTY:
            raise GameError("occupied", f"{notation(x, y, self.size)} 已经有棋子了")

        player = self.current
        assert player is not None
        self.board[y][x] = player
        move: dict[str, Any] = {
            "seq": len(self.moves) + 1,
            "player": PLAYER_NAMES[player],
            "x": x,
            "y": y,
            "notation": notation(x, y, self.size),
            "at": _now(),
        }
        self.moves.append(move)

        line = self._winning_line(x, y, player)
        if line is not None:
            self.status = f"{PLAYER_NAMES[player]}_win"
            self.winner = PLAYER_NAMES[player]
            self.win_line = line
            self.current = None
        elif len(self.moves) == self.size * self.size:
            self.status = "draw"
            self.winner = None
            self.current = None
        else:
            self.current = WHITE if player == BLACK else BLACK

        self._turn_seq += 1
        self._touch()
        return dict(move)

    def undo(self) -> dict[str, Any]:
        """Take back the last move and return it."""
        if self.mode is not None:
            raise GameError("mode_restricted", "人机对局暂不支持悔棋，可以重开一局", status=409)
        if not self.moves:
            raise GameError("nothing_to_undo", "还没有落子，无可悔棋")
        move = self.moves.pop()
        self.board[move["y"]][move["x"]] = EMPTY
        self.status = "playing"
        self.winner = None
        self.win_line = None
        self.current = NAME_TO_PLAYER[move["player"]]
        self._turn_seq += 1
        self._touch()
        return dict(move)

    def reset(self) -> dict[str, Any]:
        self._new_game()
        self.agent_thinking = False
        self.agent_thinking_since = None
        self._turn_seq += 1
        self._touch()
        return self.state()

    # ------------------------------------------------------------ agent mode

    def set_mode(self, human_side: str, agent_side: str) -> dict[str, Any]:
        """Start a human-vs-agent game; requires an empty board."""
        if not isinstance(human_side, str) or not isinstance(agent_side, str):
            raise GameError("bad_mode", "humanSide / agentSide 必须是字符串")
        human_side = human_side.strip().lower()
        agent_side = agent_side.strip().lower()
        if human_side not in NAME_TO_PLAYER or agent_side not in NAME_TO_PLAYER or human_side == agent_side:
            raise GameError("bad_mode", "人机对战需要两个不同的执子方：black / white")
        if self.moves:
            raise GameError("game_in_progress", "请先重开一局，再开始人机对战", status=409)
        self.mode = {"humanSide": human_side, "agentSide": agent_side}
        self.agent_thinking = False
        self.agent_thinking_since = None
        self._touch()
        return self.state()

    def clear_mode(self) -> dict[str, Any]:
        self.mode = None
        self.agent_thinking = False
        self.agent_thinking_since = None
        self._touch()
        return self.state()

    def set_agent_thinking(self, thinking: bool) -> dict[str, Any]:
        if self.mode is None:
            raise GameError("no_mode", "当前不是人机对战，无法设置思考状态")
        if not isinstance(thinking, bool):
            raise GameError("bad_request", "thinking 必须是布尔值")
        self.agent_thinking = thinking
        self.agent_thinking_since = _now() if thinking else None
        self._touch()
        return self.state()

    # ------------------------------------------------------------------ state

    def state(self) -> dict[str, Any]:
        """Return a complete, JSON-safe snapshot of the game."""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "game": self.name,
            "revision": self._revision,
            "rules": {
                "boardSize": self.size,
                "winLength": self.win_length,
                "forbiddenMoves": False,
            },
            "boardSize": self.size,
            "board": [row[:] for row in self.board],
            "status": self.status,
            "winner": self.winner,
            "currentPlayer": PLAYER_NAMES.get(self.current) if self.current else None,
            "turnId": str(self._turn_seq),
            "mode": dict(self.mode) if self.mode is not None else None,
            "agentThinking": self.agent_thinking,
            "agentThinkingSince": self.agent_thinking_since,
            "moveCount": len(self.moves),
            "lastMove": dict(self.moves[-1]) if self.moves else None,
            "winLine": (
                [{"x": x, "y": y} for x, y in self.win_line]
                if self.win_line is not None
                else None
            ),
            "moves": [dict(move) for move in self.moves],
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    # --------------------------------------------------------------- commands

    def execute(self, command: str, as_side: str | None = None) -> dict[str, Any]:
        """Run one command and return ``{"ok": ..., "action": ..., "state": ...}``.

        Raises :class:`GameError` for anything illegal; the caller decides how
        to turn that into an HTTP error. ``as_side`` is required once agent
        mode is active, so a command cannot move for the wrong side.
        """
        tokens = command.strip().split()
        if not tokens:
            raise GameError("empty_command", "指令为空，试试 H8 或 help")

        head = tokens[0].lower()

        if head in {"place", "move", "put", "下", "落子", "下子"}:
            if len(tokens) < 2:
                raise GameError("missing_argument", "缺少坐标，例如：place H8")
            x, y = parse_coord(tokens[1], self.size)
            move = self.place(x, y, as_side)
            return {"ok": True, "action": "place", "move": move, "state": self.state()}

        if head in {"undo", "悔棋", "撤回", "撤销"}:
            move = self.undo()
            return {"ok": True, "action": "undo", "undo": move, "state": self.state()}

        if head in {"reset", "restart", "new", "重开", "新局", "重开一局"}:
            self.reset()
            return {"ok": True, "action": "reset", "state": self.state()}

        if head in {"state", "status", "board", "状态"}:
            return {"ok": True, "action": "state", "state": self.state()}

        if head in {"help", "帮助", "?"}:
            return {"ok": True, "action": "help", "help": HELP_LINES, "state": self.state()}

        # A bare coordinate is the most common thing to type.
        try:
            x, y = parse_coord(tokens[0], self.size)
        except GameError:
            raise GameError(
                "unknown_command",
                f"无法识别指令：{tokens[0]!r}（试试 H8 / undo / reset / help）",
            ) from None
        move = self.place(x, y, as_side)
        return {"ok": True, "action": "place", "move": move, "state": self.state()}


def create() -> Gomoku:
    return Gomoku()
