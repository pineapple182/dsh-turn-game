"""Game registry.

Adding a new game means dropping a module in this package that exposes
``create()`` plus a ``Gomoku``-like ``state()`` / ``execute()`` pair, then
registering it here. The HTTP server and the web UI stay game-agnostic.
"""

from __future__ import annotations

from types import ModuleType

from . import gomoku

GAMES: dict[str, ModuleType] = {
    gomoku.Gomoku.name: gomoku,
}

DEFAULT_GAME = gomoku.Gomoku.name


def create_game(name: str = DEFAULT_GAME):
    try:
        module = GAMES[name]
    except KeyError:
        raise ValueError(f"unknown game: {name!r} (available: {', '.join(GAMES)})") from None
    return module.create()
