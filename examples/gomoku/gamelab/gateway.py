"""Turn Gateway: the game-agnostic AI activation / dispatch layer.

A game host only exposes two small endpoints:

* ``GET  /api/turn``  -> a turn envelope (or 204 when there is no turn)
* ``POST /api/action`` -> apply one action

The gateway polls registered games, creates an *activation* whenever the
current actor is an AI agent, and lets a DSH adapter submit the action. It knows
nothing about Gomoku — or any other game — which is the point: adding a game
means implementing the two endpoints, not another feedback loop.

Run it alongside the game::

    python -m gamelab.gateway --game http://127.0.0.1:8765

then point the DSH plugin at ``http://127.0.0.1:8766``.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

MAX_BODY = 64 * 1024


class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fetch_json(url: str, timeout: float = 4.0) -> dict[str, Any] | None:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status == 204:
            return None
        raw = response.read()
        if not raw:
            return None
        payload = json.loads(raw.decode("utf-8"))
        return payload if isinstance(payload, dict) else None


def _post_json(url: str, payload: dict[str, Any], timeout: float = 6.0) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw) if raw else {}
            return response.status, body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"error": {"code": "http_error", "message": raw[:300]}}
        return exc.code, body if isinstance(body, dict) else {}


class Gateway:
    """Match registry, poller and activation lifecycle."""

    def __init__(
        self,
        games: list[str],
        poll_ms: int = 400,
        activation_timeout: float = 120.0,
        quiet: bool = False,
    ) -> None:
        self._games = [self._normalize_url(url) for url in games]
        self._poll_seconds = max(0.05, poll_ms / 1000.0)
        self._timeout = max(2.0, float(activation_timeout))
        self._quiet = quiet
        self._lock = threading.RLock()
        self._matches: dict[str, dict[str, Any]] = {}
        self._activations: dict[str, dict[str, Any]] = {}
        self._counter = 0
        self._subscribers: set[queue.Queue[dict[str, Any]]] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offline: set[str] = set()

    # ------------------------------------------------------------- lifecycle

    @staticmethod
    def _normalize_url(url: str) -> str:
        return url.strip().rstrip("/")

    @property
    def urls(self) -> list[str]:
        with self._lock:
            return list(self._games)

    def add_game(self, url: str) -> str:
        url = self._normalize_url(url)
        if not url.startswith("http://") and not url.startswith("https://"):
            raise GatewayError(400, "bad_url", "游戏地址必须是 http(s) URL")
        with self._lock:
            if url not in self._games:
                self._games.append(url)
        return url

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="turn-gateway-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            for url in self.urls:
                if self._stop.is_set():
                    return
                self._poll_game(url)
            self._expire()
            self._stop.wait(self._poll_seconds)

    def _poll_game(self, url: str) -> None:
        try:
            envelope = _fetch_json(url + "/api/turn", timeout=4.0)
        except Exception as error:  # noqa: BLE001 - offline is an expected state
            if url not in self._offline:
                self._offline.add(url)
                self._log(f"game offline: {url} ({error})")
            with self._lock:
                for match in self._matches.values():
                    if match["url"] == url:
                        match["online"] = False
            return
        if url in self._offline:
            self._offline.discard(url)
            self._log(f"game online: {url}")
        if envelope is not None:
            self._ingest(url, envelope)

    # --------------------------------------------------------------- ingest

    def _ingest(self, url: str, envelope: dict[str, Any]) -> None:
        game_id = envelope.get("gameId")
        match_id = envelope.get("matchId")
        turn_id = envelope.get("turnId")
        if not isinstance(game_id, str) or not isinstance(match_id, str) or turn_id is None:
            return
        turn_id = str(turn_id)
        actor = envelope.get("actor")
        status = envelope.get("status")
        agents = envelope.get("agents") if isinstance(envelope.get("agents"), list) else []
        key = f"{game_id}:{match_id}"
        now = time.time()
        presence: tuple[str, str, str, str] | None = None
        events: list[dict[str, Any]] = []

        with self._lock:
            match = {
                "key": key,
                "gameId": game_id,
                "gameName": envelope.get("gameName") or game_id,
                "matchId": match_id,
                "url": url,
                "turnId": turn_id,
                "actor": actor,
                "status": status,
                "agents": [str(a) for a in agents],
                "display": envelope.get("display"),
                "instructions": envelope.get("instructions"),
                "actionSchema": envelope.get("actionSchema"),
                "actionExample": envelope.get("actionExample"),
                "state": envelope.get("state"),
                "online": True,
                "updatedAt": _now_iso(),
            }
            self._matches[key] = match
            pending = self._pending_for(key, "turn")
            existing = self._activation_for_turn(key, turn_id)

            if status != "playing":
                if pending is not None:
                    pending["status"] = "ended"
                    pending["closedAt"] = _now_iso()
                    presence = (url, match_id, pending["actor"], "idle")
                    events.append({"type": "activation", "activation": self._public_activation(pending)})
                # A result notice wakes the agent when the ending action came
                # from the human (or was a draw). If the agent itself made the
                # finishing move, its action response already carried the result.
                state = envelope.get("state") if isinstance(envelope.get("state"), dict) else {}
                last_move = state.get("lastMove") if isinstance(state.get("lastMove"), dict) else {}
                last_player = last_move.get("player")
                winner = envelope.get("winner")
                if winner is None:
                    winner = state.get("winner")
                result = self._result_for(key, turn_id)
                if agents and last_player not in agents and result is None:
                    self._counter += 1
                    notice = {
                        "id": f"act-{self._counter}",
                        "kind": "result",
                        "matchKey": key,
                        "gameId": game_id,
                        "gameName": match["gameName"],
                        "matchId": match_id,
                        "turnId": turn_id,
                        "actor": None,
                        "winner": winner,
                        "gameStatus": status,
                        "agents": [str(a) for a in agents],
                        "display": envelope.get("display"),
                        "instructions": (
                            "对局已经结束。请简短复盘这一局：关键手、双方的得失，"
                            "以及下一局可以改进的地方。不要提交动作。"
                        ),
                        "actionSchema": None,
                        "actionExample": None,
                        "state": envelope.get("state"),
                        "status": "pending",
                        "createdAt": _now_iso(),
                        "deadline": now + self._timeout,
                        "result": None,
                        "lastError": None,
                    }
                    self._activations[notice["id"]] = notice
                    events.append({"type": "activation", "activation": self._public_activation(notice)})
                events.append({"type": "match", "match": self._public_match(match)})
            elif actor in agents:
                if existing is not None:
                    existing["state"] = envelope.get("state")
                    existing["display"] = envelope.get("display")
                else:
                    if pending is not None:
                        pending["status"] = "superseded"
                        pending["closedAt"] = _now_iso()
                        presence = (url, match_id, pending["actor"], "idle")
                        events.append({"type": "activation", "activation": self._public_activation(pending)})
                    self._counter += 1
                    activation = {
                        "id": f"act-{self._counter}",
                        "kind": "turn",
                        "matchKey": key,
                        "gameId": game_id,
                        "gameName": match["gameName"],
                        "matchId": match_id,
                        "turnId": turn_id,
                        "actor": actor,
                        "winner": None,
                        "gameStatus": status,
                        "agents": [str(a) for a in agents],
                        "display": envelope.get("display"),
                        "instructions": envelope.get("instructions"),
                        "actionSchema": envelope.get("actionSchema"),
                        "actionExample": envelope.get("actionExample"),
                        "state": envelope.get("state"),
                        "status": "pending",
                        "createdAt": _now_iso(),
                        "deadline": now + self._timeout,
                        "result": None,
                        "lastError": None,
                    }
                    self._activations[activation["id"]] = activation
                    presence = (url, match_id, actor, "thinking")
                    events.append({"type": "activation", "activation": self._public_activation(activation)})
                events.append({"type": "match", "match": self._public_match(match)})
            else:
                if pending is not None:
                    pending["status"] = "superseded"
                    pending["closedAt"] = _now_iso()
                    presence = (url, match_id, pending["actor"], "idle")
                    events.append({"type": "activation", "activation": self._public_activation(pending)})
                events.append({"type": "match", "match": self._public_match(match)})

        if presence is not None:
            self._presence(*presence)
        for event in events:
            self._broadcast(event)

    def _pending_for(self, key: str, kind: str = "turn") -> dict[str, Any] | None:
        for activation in self._activations.values():
            if (
                activation["matchKey"] == key
                and activation.get("kind", "turn") == kind
                and activation["status"] in ("pending", "acting")
            ):
                return activation
        return None

    def _activation_for_turn(self, key: str, turn_id: str) -> dict[str, Any] | None:
        for activation in self._activations.values():
            if (
                activation["matchKey"] == key
                and activation["turnId"] == turn_id
                and activation.get("kind", "turn") == "turn"
            ):
                return activation
        return None

    def _result_for(self, key: str, turn_id: str) -> dict[str, Any] | None:
        for activation in self._activations.values():
            if (
                activation["matchKey"] == key
                and activation["turnId"] == turn_id
                and activation.get("kind", "turn") == "result"
            ):
                return activation
        return None

    def _expire(self) -> None:
        now = time.time()
        expired: list[dict[str, Any]] = []
        with self._lock:
            for activation in self._activations.values():
                if activation["status"] == "pending" and activation["deadline"] <= now:
                    activation["status"] = "expired"
                    activation["closedAt"] = _now_iso()
                    expired.append(activation)
        for activation in expired:
            self._presence(
                self._matches[activation["matchKey"]]["url"],
                activation["matchId"],
                activation["actor"],
                "idle",
            )
            self._broadcast({"type": "activation", "activation": self._public_activation(activation)})
            self._log(f"activation expired: {activation['id']} ({activation['gameId']})")

    # --------------------------------------------------------------- actions

    def submit_action(self, activation_id: str, action: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(action, dict):
            raise GatewayError(400, "bad_action", "action 必须是 JSON 对象")
        with self._lock:
            activation = self._activations.get(activation_id)
            if activation is None:
                raise GatewayError(404, "activation_not_found", f"未知 activation：{activation_id}")
            if activation.get("kind", "turn") != "turn":
                raise GatewayError(
                    409,
                    "action_not_required",
                    "这是一个对局结束（result）通知，不需要提交动作",
                )
            if activation["status"] == "acted":
                return 200, {
                    "ok": True,
                    "activation": self._public_activation(activation),
                    "result": activation.get("result"),
                }
            if activation["status"] != "pending":
                raise GatewayError(
                    410,
                    "activation_closed",
                    f"该 activation 已关闭：{activation['status']}",
                )
            match = self._matches.get(activation["matchKey"])
            if match is None or match["turnId"] != activation["turnId"]:
                activation["status"] = "superseded"
                activation["closedAt"] = _now_iso()
                self._broadcast({"type": "activation", "activation": self._public_activation(activation)})
                raise GatewayError(409, "stale_turn", "回合已经变化，请按最新状态重新动作")
            activation["status"] = "acting"
            url = match["url"]
            payload = {
                "matchId": activation["matchId"],
                "turnId": activation["turnId"],
                "actor": activation["actor"],
                "action": action,
            }

        status, body = _post_json(url + "/api/action", payload)
        with self._lock:
            if status == 200:
                activation["status"] = "acted"
                activation["result"] = body
                activation["closedAt"] = _now_iso()
            else:
                error = body.get("error") if isinstance(body, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
                activation["lastError"] = error
                if code in ("stale_turn", "wrong_actor", "unknown_match"):
                    activation["status"] = "superseded"
                    activation["closedAt"] = _now_iso()
                else:
                    activation["status"] = "pending"
        if activation["status"] != "pending":
            self._presence(url, activation["matchId"], activation["actor"], "idle")
            self._broadcast({"type": "activation", "activation": self._public_activation(activation)})
        if status == 200:
            return 200, {
                "ok": True,
                "activation": self._public_activation(activation),
                "result": body,
            }
        if activation["status"] == "superseded":
            raise GatewayError(409, "stale_turn", "回合已经变化，请按最新状态重新动作")
        return status, body

    def ack_result(self, activation_id: str) -> tuple[int, dict[str, Any]]:
        """Acknowledge a result (review) activation; no game action is involved."""
        with self._lock:
            activation = self._activations.get(activation_id)
            if activation is None:
                raise GatewayError(404, "activation_not_found", f"未知 activation：{activation_id}")
            if activation.get("kind", "turn") != "result":
                raise GatewayError(409, "ack_not_applicable", "只有 result activation 需要 ack")
            if activation["status"] == "acked":
                return 200, {"ok": True, "activation": self._public_activation(activation)}
            if activation["status"] != "pending":
                raise GatewayError(
                    410,
                    "activation_closed",
                    f"该 activation 已关闭：{activation['status']}",
                )
            activation["status"] = "acked"
            activation["closedAt"] = _now_iso()
        self._broadcast({"type": "activation", "activation": self._public_activation(activation)})
        return 200, {"ok": True, "activation": self._public_activation(activation)}

    # --------------------------------------------------------------- presence

    def _presence(self, url: str, match_id: str, actor: str | None, activity: str) -> None:
        if not actor:
            return
        try:
            _post_json(
                url + "/api/presence",
                {"matchId": match_id, "actor": actor, "activity": activity},
                timeout=2.0,
            )
        except Exception:  # noqa: BLE001 - presence is best effort
            pass

    # ---------------------------------------------------------------- public

    def _public_activation(self, activation: dict[str, Any]) -> dict[str, Any]:
        return {
            key: activation.get(key)
            for key in (
                "id",
                "kind",
                "matchKey",
                "gameId",
                "gameName",
                "matchId",
                "turnId",
                "actor",
                "winner",
                "gameStatus",
                "agents",
                "display",
                "instructions",
                "actionSchema",
                "actionExample",
                "state",
                "status",
                "createdAt",
                "deadline",
                "lastError",
            )
        }

    def _public_match(self, match: dict[str, Any]) -> dict[str, Any]:
        return {
            key: match.get(key)
            for key in (
                "key",
                "gameId",
                "gameName",
                "matchId",
                "actor",
                "turnId",
                "status",
                "agents",
                "online",
                "updatedAt",
            )
        }

    def matches(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public_match(match) for match in self._matches.values()]

    def match_detail(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            match = self._matches.get(key)
            if match is None:
                return None
            detail = self._public_match(match)
            detail.update(
                {
                    "display": match.get("display"),
                    "instructions": match.get("instructions"),
                    "state": match.get("state"),
                    "actionSchema": match.get("actionSchema"),
                    "actionExample": match.get("actionExample"),
                }
            )
            return detail

    def activations(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                self._public_activation(activation)
                for activation in self._activations.values()
                if status is None or activation["status"] == status
            ]
        return sorted(rows, key=lambda row: row.get("createdAt") or "")

    def activation(self, activation_id: str) -> dict[str, Any] | None:
        with self._lock:
            activation = self._activations.get(activation_id)
            return self._public_activation(activation) if activation else None

    def health(self) -> dict[str, Any]:
        with self._lock:
            pending = sum(1 for a in self._activations.values() if a["status"] == "pending")
            return {
                "ok": True,
                "games": list(self._games),
                "matches": len(self._matches),
                "activations": len(self._activations),
                "pending": pending,
            }

    # ------------------------------------------------------------ subscribers

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        channel: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.add(channel)
        return channel

    def unsubscribe(self, channel: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(channel)

    def _broadcast(self, event: dict[str, Any]) -> None:
        with self._lock:
            channels = list(self._subscribers)
        for channel in channels:
            try:
                channel.put_nowait(event)
            except queue.Full:
                pass

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "type": "snapshot",
                "matches": [self._public_match(match) for match in self._matches.values()],
                "activations": [
                    self._public_activation(activation)
                    for activation in self._activations.values()
                    if activation["status"] == "pending"
                ],
            }

    def _log(self, message: str) -> None:
        if not self._quiet:
            sys.stderr.write(f"[turn-gateway] {message}\n")


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TurnGateway/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        gateway: Gateway = self.server.gateway  # type: ignore[attr-defined]
        if not gateway._quiet:  # noqa: SLF001 - internal flag, intentional
            sys.stderr.write("[turn-gateway] %s - %s\n" % (self.address_string(), fmt % args))

    @property
    def gateway(self) -> Gateway:
        return self.server.gateway  # type: ignore[attr-defined]

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
        self._send_json(status, {"ok": False, "error": {"code": code, "message": message}})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise GatewayError(400, "bad_request", "Content-Length 无效") from None
        if length < 0 or length > MAX_BODY:
            raise GatewayError(413, "payload_too_large", "请求体过大")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GatewayError(400, "bad_json", "请求体不是合法的 JSON") from None
        if not isinstance(payload, dict):
            raise GatewayError(400, "bad_json", "请求体必须是 JSON 对象")
        return payload

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        if path == "/api/health":
            self._send_json(200, self.gateway.health())
            return
        if path == "/api/matches":
            self._send_json(200, {"ok": True, "matches": self.gateway.matches()})
            return
        if path.startswith("/api/matches/"):
            key = path[len("/api/matches/"):]
            match = self.gateway.match_detail(key)
            if match is None:
                self._error(404, "match_not_found", f"未知对局：{key}")
                return
            self._send_json(200, {"ok": True, "match": match})
            return
        if path == "/api/activations":
            query = parse_qs(urlsplit(self.path).query)
            status = (query.get("status") or [None])[0]
            self._send_json(200, {"ok": True, "activations": self.gateway.activations(status)})
            return
        if path.startswith("/api/activations/"):
            activation_id = path[len("/api/activations/"):]
            activation = self.gateway.activation(activation_id)
            if activation is None:
                self._error(404, "activation_not_found", f"未知 activation：{activation_id}")
                return
            self._send_json(200, {"ok": True, "activation": activation})
            return
        if path == "/api/events":
            self._serve_events()
            return
        self._error(404, "not_found", f"未知路径：{path}")

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        try:
            payload = self._read_json()
            if path == "/api/games":
                url = payload.get("url")
                if not isinstance(url, str):
                    raise GatewayError(400, "missing_argument", '需要 {"url": "http://..."}')
                self._send_json(200, {"ok": True, "url": self.gateway.add_game(url)})
                return
            if path.startswith("/api/activations/") and path.endswith("/action"):
                activation_id = path[len("/api/activations/"):-len("/action")]
                action = payload.get("action")
                status, body = self.gateway.submit_action(activation_id, action)
                self._send_json(status, body)
                return
            if path.startswith("/api/activations/") and path.endswith("/ack"):
                activation_id = path[len("/api/activations/"):-len("/ack")]
                status, body = self.gateway.ack_result(activation_id)
                self._send_json(status, body)
                return
            self._error(404, "not_found", f"未知路径：{path}")
        except GatewayError as exc:
            self._error(exc.status, exc.code, exc.message)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_events(self) -> None:
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        channel = self.gateway.subscribe()
        try:
            self.wfile.write(b"retry: 1500\n\n")
            self._event(self.gateway.snapshot())
            while True:
                try:
                    event = channel.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self._event(event)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass
        finally:
            self.gateway.unsubscribe(channel)

    def _event(self, event: dict[str, Any]) -> None:
        data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        self.wfile.write(f"event: {event.get('type', 'message')}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], gateway: Gateway) -> None:
        self.gateway = gateway
        super().__init__(address, GatewayHandler)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        return f"http://{shown}:{port}"

    def server_close(self) -> None:
        self.gateway.stop()
        super().server_close()


def create_gateway(
    host: str = "127.0.0.1",
    port: int = 8766,
    games: list[str] | None = None,
    poll_ms: int = 400,
    activation_timeout: float = 120.0,
    quiet: bool = False,
) -> GatewayServer:
    gateway = Gateway(games or [], poll_ms=poll_ms, activation_timeout=activation_timeout, quiet=quiet)
    server = GatewayServer((host, port), gateway)
    gateway.start()
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gamelab-gateway",
        description="Turn Gateway：通用回合激活层（游戏 ↔ DSH 的中间站）",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--game", action="append", default=[], help="游戏地址，可重复，如 http://127.0.0.1:8765")
    parser.add_argument("--poll-ms", type=int, default=400)
    parser.add_argument("--activation-timeout", type=float, default=120.0, help="一次 activation 的等待秒数")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    server = create_gateway(
        host=args.host,
        port=args.port,
        games=args.game,
        poll_ms=args.poll_ms,
        activation_timeout=args.activation_timeout,
        quiet=args.quiet,
    )
    print(f"turn-gateway 已启动：{server.url}")
    print(f"  游戏：{', '.join(args.game) if args.game else '（尚未注册，可 POST /api/games）'}")
    print(f"  health：{server.url}/api/health")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
