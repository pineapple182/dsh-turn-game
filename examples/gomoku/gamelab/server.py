"""HTTP server: static web UI + JSON API + Server-Sent Events.

Routes
------
GET  /                -> web/index.html
GET  /api/state       -> full game state (JSON)
GET  /api/stream      -> SSE feed, one ``state`` event per change
GET  /api/health      -> liveness + current revision
POST /api/move        -> {"x": 7, "y": 7} or {"notation": "H8"}
POST /api/command     -> {"command": "H8" | "undo" | "reset" | "state" | "help"}
POST /api/undo        -> take back one move
POST /api/reset       -> start a fresh game
"""

from __future__ import annotations

import json
import queue
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .games import DEFAULT_GAME
from .games import gomoku_turn
from .games.gomoku import GameError, notation
from .session import Session

MAX_BODY = 64 * 1024

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


def _as_int(value: Any) -> int | None:
    """Accept ``7`` and ``7.0`` from JSON clients, reject ``True`` and ``"7"``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


class GameLabHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "GameLab/0.1"

    # ------------------------------------------------------------- utilities

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write("[game-lab] %s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        self._send_json(status, {"ok": False, "action": "error", "error": {"code": code, "message": message}})

    def _read_json(self) -> dict[str, Any]:
        # Always drain the request body, even for endpoints that ignore it:
        # otherwise keep-alive connections desync and the next request line is
        # parsed from the leftover bytes.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise GameError("bad_request", "Content-Length 无效") from None
        if length < 0 or length > MAX_BODY:
            raise GameError("payload_too_large", "请求体过大")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GameError("bad_json", "请求体不是合法的 JSON") from None
        if not isinstance(payload, dict):
            raise GameError("bad_json", "请求体必须是 JSON 对象")
        return payload

    @property
    def session(self) -> Session:
        return self.server.session  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ HTTP

    def do_OPTIONS(self) -> None:  # noqa: N802 (stdlib naming)
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        try:
            if path == "/api/state":
                self._send_json(200, self.session.state())
            elif path == "/api/health":
                state = self.session.state()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "game": state["game"],
                        "schemaVersion": state["schemaVersion"],
                        "revision": state["revision"],
                    },
                )
            elif path == "/api/stream":
                self._serve_stream()
            elif path == "/api/turn":
                self._send_json(200, gomoku_turn.turn_envelope(self.session.state()))
            elif path == "/api/undo" or path == "/api/reset" or path == "/api/move" or path == "/api/command" or path == "/api/mode" or path == "/api/agent/status" or path == "/api/action" or path == "/api/presence":
                self._error(405, "method_not_allowed", "该接口只接受 POST 请求")
            elif path.startswith("/api/"):
                self._error(404, "not_found", f"未知接口：{path}")
            else:
                self._serve_static(path)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/move":
                text = self._move_text(payload)
                actor = payload.get("as")
                self._run(lambda game: game.execute(f"place {text}", as_side=actor))
            elif path == "/api/command":
                command = payload.get("command")
                if not isinstance(command, str) or not command.strip():
                    raise GameError("missing_argument", '缺少 command 字段，例如 {"command": "H8"}')
                actor = payload.get("as")
                self._run(lambda game: game.execute(command, as_side=actor))
            elif path == "/api/action":
                self._run(lambda game: gomoku_turn.apply_action(game, payload))
            elif path == "/api/presence":
                self._run(lambda game: gomoku_turn.apply_presence(game, payload))
            elif path == "/api/mode":
                if payload.get("clear") is True:
                    self._run(lambda game: {
                        "ok": True,
                        "action": "mode",
                        "mode": None,
                        "state": game.clear_mode(),
                    })
                else:
                    human = payload.get("humanSide")
                    agent = payload.get("agentSide")
                    if not isinstance(human, str) or not isinstance(agent, str):
                        raise GameError("missing_argument", '需要 {"humanSide": "black", "agentSide": "white"}')
                    self._run(lambda game: {
                        "ok": True,
                        "action": "mode",
                        "mode": game.set_mode(human, agent)["mode"],
                        "state": game.state(),
                    })
            elif path == "/api/agent/status":
                thinking = payload.get("thinking")
                if not isinstance(thinking, bool):
                    raise GameError("missing_argument", '需要 {"thinking": true} 或 {"thinking": false}')
                self._run(lambda game: {
                    "ok": True,
                    "action": "thinking",
                    "thinking": thinking,
                    "state": game.set_agent_thinking(thinking),
                })
            elif path == "/api/undo":
                self._run(lambda game: game.execute("undo"))
            elif path == "/api/reset":
                self._run(lambda game: game.execute("reset"))
            elif path == "/api/state" or path == "/api/health" or path == "/api/stream":
                self._error(405, "method_not_allowed", "该接口只接受 GET 请求")
            elif path.startswith("/api/"):
                self._error(404, "not_found", f"未知接口：{path}")
            else:
                self._error(404, "not_found", f"未知路径：{path}")
        except GameError as exc:
            self._error(exc.status, exc.code, exc.message)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _move_text(self, payload: dict[str, Any]) -> str:
        text = payload.get("notation", payload.get("coord"))
        if isinstance(text, str) and text.strip():
            return text.strip()
        x, y = _as_int(payload.get("x")), _as_int(payload.get("y"))
        if x is not None and y is not None:
            return notation(x, y, self.session.state()["boardSize"])
        raise GameError("missing_argument", '需要 {"x": 7, "y": 7} 或 {"notation": "H8"}')

    def _run(self, action) -> None:  # type: ignore[no-untyped-def]
        status, payload = self.session.run(action)
        self._send_json(status, payload)

    # ------------------------------------------------------------------ SSE

    def _serve_stream(self) -> None:
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()

        channel = self.session.subscribe()
        try:
            self.wfile.write(b"retry: 1500\n\n")
            self._send_event(self.session.state())
            while True:
                try:
                    state = channel.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self._send_event(state)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass
        finally:
            self.session.unsubscribe(channel)

    def _send_event(self, state: dict[str, Any]) -> None:
        data = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        chunk = f"id: {state['revision']}\nevent: state\ndata: {data}\n\n".encode("utf-8")
        self.wfile.write(chunk)
        self.wfile.flush()

    # -------------------------------------------------------------- static

    def _serve_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        relative = unquote(path.lstrip("/"))
        web_dir: Path = self.server.web_dir  # type: ignore[attr-defined]
        try:
            target = (web_dir / relative).resolve()
            target.relative_to(web_dir)
        except (ValueError, OSError):
            self._error(403, "forbidden", "非法路径")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self._error(404, "not_found", f"找不到文件：{path}")
            return
        body = target.read_bytes()
        content_type = MIME_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self._cors()
        self.end_headers()
        self.wfile.write(body)


class GameLabServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], session: Session, web_dir: Path, quiet: bool = False) -> None:
        self.session = session
        self.web_dir = Path(web_dir).resolve()
        self.quiet = quiet
        super().__init__(address, GameLabHandler)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        shown = "127.0.0.1" if host in ("0.0.0.0", "::") else str(host)
        return f"http://{shown}:{port}"


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    game: str = DEFAULT_GAME,
    web_dir: Path | None = None,
    quiet: bool = False,
) -> GameLabServer:
    session = Session(game)
    if web_dir is None:
        web_dir = Path(__file__).resolve().parent.parent / "web"
    return GameLabServer((host, port), session, web_dir, quiet=quiet)
