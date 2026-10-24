"""Thread-safe game session with a tiny publish/subscribe bus for SSE."""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from .games import DEFAULT_GAME, create_game
from .games.gomoku import GameError

State = dict[str, Any]


class Session:
    """One live game shared by every HTTP client."""

    def __init__(self, game_name: str = DEFAULT_GAME) -> None:
        self.game = create_game(game_name)
        self._lock = threading.RLock()
        self._subscribers: set[queue.Queue[State]] = set()

    def state(self) -> State:
        with self._lock:
            return self.game.state()

    def run(self, action: Callable[[Any], dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        """Apply an engine mutation and return ``(http_status, payload)``.

        ``action`` receives the engine and either returns a payload or raises
        :class:`GameError`. Every result carries the full current state.
        """
        with self._lock:
            status = 200
            try:
                payload = action(self.game)
            except GameError as exc:
                payload = {
                    "ok": False,
                    "action": "error",
                    "error": {"code": exc.code, "message": exc.message},
                }
                status = exc.status
            if "state" not in payload:
                payload["state"] = self.game.state()
            self._publish(payload["state"])
        return status, payload

    # ------------------------------------------------------------- subscribers

    def subscribe(self) -> queue.Queue[State]:
        channel: queue.Queue[State] = queue.Queue(maxsize=16)
        with self._lock:
            self._subscribers.add(channel)
        return channel

    def unsubscribe(self, channel: queue.Queue[State]) -> None:
        with self._lock:
            self._subscribers.discard(channel)

    def _publish(self, state: State) -> None:
        with self._lock:
            channels = list(self._subscribers)
        for channel in channels:
            try:
                channel.put_nowait(state)
            except queue.Full:
                # A stalled client is not worth blocking the game for; it will
                # recover on the next successful read.
                pass
