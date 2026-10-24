"""Shared, game-agnostic text rendering helpers.

Both the CLI and the turn protocol use these so the board a human sees and the
board an agent reads are produced by the same code.
"""

from __future__ import annotations

from typing import Any

COLUMNS = "ABCDEFGHIJKLMNO"
SYMBOLS = {0: "·", 1: "●", 2: "○"}
SIDE_LABELS = {"black": "黑方 ●", "white": "白方 ○"}


def render_board(state: dict[str, Any]) -> str:
    """Render the board as fixed-width text with coordinates."""
    size = int(state.get("boardSize") or 15)
    columns = COLUMNS[:size]
    header = "    " + " ".join(columns)
    lines = [header]
    board = state.get("board") or []
    for row_index in range(size):
        row = board[row_index] if row_index < len(board) else []
        cells = " ".join(SYMBOLS.get(row[x], "?") if x < len(row) else "?" for x in range(size))
        label = f"{size - row_index:>2}"
        lines.append(f"{label}  {cells}  {label}")
    lines.append(header)
    last = state.get("lastMove")
    if last:
        lines.append(f"最后一手：{SIDE_LABELS.get(last.get('player'), last.get('player'))} {last.get('notation')}")
    return "\n".join(lines)


def status_line(state: dict[str, Any]) -> str:
    status = state.get("status")
    if status == "draw":
        return "和棋，棋盘已下满"
    if status in ("black_win", "white_win"):
        winner = state.get("winner")
        return f"{SIDE_LABELS.get(winner, winner)} 五子连珠，获胜！"
    current = state.get("currentPlayer")
    return f"轮到 {SIDE_LABELS.get(current, current)} 行棋"
