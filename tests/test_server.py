from __future__ import annotations

import http.client
import json
import threading
import unittest
import urllib.error
import urllib.request

from gamelab.server import create_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server(port=0, quiet=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host, cls.port = cls.server.server_address[:2]
        cls.base = f"http://{cls.host}:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self) -> None:
        self.request("/api/reset", "POST", {})
        self.request("/api/mode", "POST", {"clear": True})

    # ---------------------------------------------------------------- helpers

    def request(
        self,
        path: str,
        method: str = "GET",
        payload: dict | None = None,
        timeout: float = 5.0,
        raw: bytes | None = None,
    ):
        data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    # ------------------------------------------------------------------ tests

    def test_health(self) -> None:
        status, payload = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["game"], "gomoku")

    def test_initial_state(self) -> None:
        status, payload = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "playing")
        self.assertEqual(payload["currentPlayer"], "black")
        self.assertEqual(payload["moveCount"], 0)
        self.assertEqual(payload["schemaVersion"], 1)

    def test_move_by_xy(self) -> None:
        status, payload = self.request("/api/move", "POST", {"x": 7, "y": 7})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["move"]["notation"], "H8")
        self.assertEqual(payload["state"]["board"][7][7], 1)
        self.assertEqual(payload["state"]["currentPlayer"], "white")

    def test_move_by_notation(self) -> None:
        status, payload = self.request("/api/move", "POST", {"notation": "H8"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["move"]["x"], 7)
        self.assertEqual(payload["move"]["y"], 7)

    def test_occupied_cell(self) -> None:
        self.request("/api/move", "POST", {"x": 7, "y": 7})
        status, payload = self.request("/api/move", "POST", {"x": 7, "y": 7})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "occupied")
        self.assertIn("state", payload)

    def test_out_of_range(self) -> None:
        status, payload = self.request("/api/move", "POST", {"x": 99, "y": 0})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "out_of_range")

    def test_command_and_unknown(self) -> None:
        status, payload = self.request("/api/command", "POST", {"command": "h8"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "place")

        status, payload = self.request("/api/command", "POST", {"command": "fly me to the moon"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "unknown_command")

    def test_command_requires_string(self) -> None:
        status, payload = self.request("/api/command", "POST", {"command": 42})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "missing_argument")

    def test_undo_and_reset(self) -> None:
        self.request("/api/move", "POST", {"notation": "H8"})
        status, payload = self.request("/api/undo", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "undo")
        self.assertEqual(payload["state"]["moveCount"], 0)

        self.request("/api/move", "POST", {"notation": "H8"})
        status, payload = self.request("/api/reset", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"]["moveCount"], 0)

    def test_undo_without_moves(self) -> None:
        status, payload = self.request("/api/undo", "POST", {})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "nothing_to_undo")

    def test_bad_json_body(self) -> None:
        status, payload = self.request("/api/move", "POST", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_json")

    def test_wrong_method(self) -> None:
        status, payload = self.request("/api/move")
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "method_not_allowed")

    def test_static_index(self) -> None:
        with urllib.request.urlopen(self.base + "/", timeout=5) as response:
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
        self.assertIn("五子棋", body)
        self.assertIn("/app.js", body)

    def test_traversal_blocked(self) -> None:
        status, payload = self.request("/%2e%2e/gamelab/server.py")
        self.assertIn(status, (403, 404))
        self.assertFalse(payload["ok"])

    def test_unknown_api(self) -> None:
        status, payload = self.request("/api/nope")
        self.assertEqual(status, 404)

    def test_keep_alive_drains_body(self) -> None:
        """Regression: /api/reset used to leave its body unread, desyncing HTTP/1.1."""
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(
                "POST",
                "/api/reset",
                body=json.dumps({}),
                headers={"Content-Type": "application/json"},
            )
            first = connection.getresponse()
            first.read()
            self.assertEqual(first.status, 200)

            connection.request(
                "POST",
                "/api/move",
                body=json.dumps({"notation": "H8"}),
                headers={"Content-Type": "application/json"},
            )
            second = connection.getresponse()
            payload = json.loads(second.read().decode())
            self.assertEqual(second.status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["move"]["notation"], "H8")
        finally:
            connection.close()

    def test_agent_mode_roundtrip(self) -> None:
        status, payload = self.request(
            "/api/mode", "POST", {"humanSide": "black", "agentSide": "white"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], {"humanSide": "black", "agentSide": "white"})
        self.assertEqual(payload["state"]["currentPlayer"], "black")

        status, payload = self.request("/api/move", "POST", {"notation": "H8"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "actor_required")

        status, payload = self.request("/api/move", "POST", {"notation": "H8", "as": "agent"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "not_your_turn")

        status, payload = self.request("/api/move", "POST", {"notation": "H8", "as": "human"})
        self.assertEqual(status, 200)
        status, payload = self.request("/api/move", "POST", {"notation": "I9", "as": "agent"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"]["moveCount"], 2)

        status, payload = self.request("/api/undo", "POST", {})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "mode_restricted")

        status, payload = self.request("/api/mode", "POST", {"clear": True})
        self.assertEqual(status, 200)
        self.assertIsNone(payload["state"]["mode"])
        status, payload = self.request("/api/undo", "POST", {})
        self.assertEqual(status, 200)

    def test_agent_mode_rejects_bad_sides_and_dirty_board(self) -> None:
        status, payload = self.request(
            "/api/mode", "POST", {"humanSide": "black", "agentSide": "black"}
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_mode")
        self.request("/api/move", "POST", {"notation": "H8"})
        status, payload = self.request(
            "/api/mode", "POST", {"humanSide": "black", "agentSide": "white"}
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "game_in_progress")

    def test_agent_thinking_status(self) -> None:
        self.request("/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        status, payload = self.request("/api/agent/status", "POST", {"thinking": True})
        self.assertEqual(status, 200)
        self.assertTrue(payload["state"]["agentThinking"])
        self.assertIsNotNone(payload["state"]["agentThinkingSince"])
        status, payload = self.request("/api/agent/status", "POST", {"thinking": False})
        self.assertEqual(status, 200)
        self.assertFalse(payload["state"]["agentThinking"])
        self.assertIsNone(payload["state"]["agentThinkingSince"])

    def test_agent_thinking_requires_mode(self) -> None:
        status, payload = self.request("/api/agent/status", "POST", {"thinking": True})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "no_mode")

    def test_reset_keeps_agent_mode(self) -> None:
        self.request("/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        self.request("/api/move", "POST", {"notation": "H8", "as": "human"})
        self.request("/api/agent/status", "POST", {"thinking": True})
        status, payload = self.request("/api/reset", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"]["mode"], {"humanSide": "black", "agentSide": "white"})
        self.assertEqual(payload["state"]["moveCount"], 0)
        self.assertFalse(payload["state"]["agentThinking"])
        self.assertEqual(payload["state"]["currentPlayer"], "black")

    def test_command_accepts_actor(self) -> None:
        self.request("/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        status, payload = self.request("/api/command", "POST", {"command": "H8", "as": "human"})
        self.assertEqual(status, 200)
        status, payload = self.request("/api/command", "POST", {"command": "I9"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "actor_required")

    def test_turn_envelope_is_generic(self) -> None:
        self.request("/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        status, payload = self.request("/api/turn")
        self.assertEqual(status, 200)
        self.assertEqual(payload["protocol"], 1)
        self.assertEqual(payload["gameId"], "gomoku")
        self.assertEqual(payload["matchId"], "gomoku-default")
        self.assertEqual(payload["agents"], ["white"])
        self.assertEqual(payload["actor"], "black")
        self.assertEqual(payload["status"], "playing")
        self.assertIn("A B C", payload["display"])
        self.assertIn("动作", payload["instructions"])
        self.assertEqual(payload["actionExample"], {"notation": "H8"})
        self.assertIn("notation", payload["actionSchema"]["properties"])
        self.assertEqual(payload["state"]["mode"], {"humanSide": "black", "agentSide": "white"})

    def test_turn_action_advances_the_turn(self) -> None:
        self.request("/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        self.request("/api/move", "POST", {"notation": "H8", "as": "human"})
        _, turn = self.request("/api/turn")
        self.assertEqual(turn["actor"], "white")
        status, payload = self.request(
            "/api/action",
            "POST",
            {
                "matchId": "gomoku-default",
                "turnId": turn["turnId"],
                "actor": "white",
                "action": {"notation": "I9"},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"]["currentPlayer"], "black")
        self.assertEqual(payload["state"]["moveCount"], 2)
        self.assertNotEqual(payload["turnId"], turn["turnId"])

    def test_turn_action_rejects_stale_or_wrong_actor(self) -> None:
        self.request("/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        self.request("/api/move", "POST", {"notation": "H8", "as": "human"})
        _, turn = self.request("/api/turn")
        status, payload = self.request(
            "/api/action",
            "POST",
            {"turnId": "stale", "actor": "white", "action": {"notation": "I9"}},
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "stale_turn")
        status, payload = self.request(
            "/api/action",
            "POST",
            {"turnId": turn["turnId"], "actor": "black", "action": {"notation": "I9"}},
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "wrong_actor")

    def test_turn_action_rejects_occupied_and_unknown_match(self) -> None:
        self.request("/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        self.request("/api/move", "POST", {"notation": "H8", "as": "human"})
        _, turn = self.request("/api/turn")
        status, payload = self.request(
            "/api/action",
            "POST",
            {
                "turnId": turn["turnId"],
                "actor": "white",
                "action": {"notation": "H8"},
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "occupied")
        status, payload = self.request(
            "/api/action",
            "POST",
            {
                "matchId": "nope",
                "turnId": turn["turnId"],
                "actor": "white",
                "action": {"notation": "I9"},
            },
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "unknown_match")

    def test_presence_sets_thinking(self) -> None:
        self.request("/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        status, payload = self.request(
            "/api/presence", "POST", {"actor": "white", "activity": "thinking"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["state"]["agentThinking"])
        status, payload = self.request(
            "/api/presence", "POST", {"actor": "white", "activity": "idle"}
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["state"]["agentThinking"])

    def test_turn_envelope_without_agent(self) -> None:
        status, payload = self.request("/api/turn")
        self.assertEqual(status, 200)
        self.assertEqual(payload["agents"], [])
        self.assertEqual(payload["actor"], "black")

    def test_sse_initial_state(self) -> None:
        with urllib.request.urlopen(self.base + "/api/stream", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/event-stream", response.headers["Content-Type"])
            chunk = response.read(600)
        self.assertIn(b"event: state", chunk)
        self.assertIn(b'"schemaVersion"', chunk)


if __name__ == "__main__":
    unittest.main()
