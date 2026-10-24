from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request

from gamelab.gateway import create_gateway
from gamelab.server import create_server


def _request(base: str, path: str, method: str = "GET", payload: dict | None = None, timeout: float = 4.0):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {}
        return exc.code, body


def _wait_for(check, timeout: float = 4.0, interval: float = 0.05):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = check()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s (last={last!r})")


class GatewayTests(unittest.TestCase):
    activation_timeout = 1.5

    def setUp(self) -> None:
        self.game = create_server(port=0, quiet=True)
        self.game_thread = threading.Thread(target=self.game.serve_forever, daemon=True)
        self.game_thread.start()
        self.game_base = f"http://127.0.0.1:{self.game.server_address[1]}"
        self.gateway = create_gateway(
            port=0,
            games=[self.game_base],
            poll_ms=40,
            activation_timeout=self.activation_timeout,
            quiet=True,
        )
        self.gateway_thread = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        self.gateway_thread.start()
        self.gw_base = f"http://127.0.0.1:{self.gateway.server_address[1]}"
        _request(self.game_base, "/api/reset", "POST", {})
        _request(self.game_base, "/api/mode", "POST", {"clear": True})

    def tearDown(self) -> None:
        self.gateway.shutdown()
        self.gateway.server_close()
        self.gateway_thread.join(timeout=5)
        self.game.shutdown()
        self.game.server_close()
        self.game_thread.join(timeout=5)

    # ---------------------------------------------------------------- helpers

    def start_agent_turn(self) -> dict:
        _request(self.game_base, "/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        _request(self.game_base, "/api/move", "POST", {"notation": "H8", "as": "human"})
        return self.wait_activation()

    def wait_activation(self, status: str = "pending") -> dict:
        def check():
            _, body = _request(self.gw_base, f"/api/activations?status={status}")
            rows = body.get("activations") or []
            return rows[0] if rows else None

        return _wait_for(check)

    def game_state(self) -> dict:
        _, body = _request(self.game_base, "/api/state")
        return body

    def play_sequence(self, moves: list[tuple[str, str]]) -> None:
        for actor, notation in moves:
            _request(
                self.game_base,
                "/api/move",
                "POST",
                {"notation": notation, "as": actor},
            )

    def wait_result(self, timeout: float = 4.0) -> dict:
        def check():
            _, body = _request(self.gw_base, "/api/activations")
            rows = [row for row in (body.get("activations") or []) if row.get("kind") == "result"]
            return rows[0] if rows else None

        return _wait_for(check, timeout=timeout)

    # ------------------------------------------------------------------ tests

    def test_activation_and_action_round_trip(self) -> None:
        activation = self.start_agent_turn()
        self.assertEqual(activation["gameId"], "gomoku")
        self.assertEqual(activation["matchId"], "gomoku-default")
        self.assertEqual(activation["actor"], "white")
        self.assertIn("A B C", activation["display"])
        self.assertIn("H8", activation["instructions"])
        self.assertEqual(activation["actionExample"], {"notation": "H8"})
        self.assertIn("board", activation["state"])

        state = _wait_for(lambda: self.game_state() if self.game_state()["agentThinking"] else None)
        self.assertTrue(state["agentThinking"])

        status, body = _request(
            self.gw_base,
            f"/api/activations/{activation['id']}/action",
            "POST",
            {"action": {"notation": "I9"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["activation"]["status"], "acted")
        self.assertEqual(body["result"]["state"]["currentPlayer"], "black")
        self.assertEqual(body["result"]["state"]["moveCount"], 2)
        self.assertTrue(_wait_for(lambda: not self.game_state()["agentThinking"]) is True)

        # Idempotent replay returns the same settled activation.
        status, body = _request(
            self.gw_base,
            f"/api/activations/{activation['id']}/action",
            "POST",
            {"action": {"notation": "I9"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["activation"]["status"], "acted")
        self.assertEqual(self.game_state()["moveCount"], 2)

    def test_occupied_action_keeps_activation_pending(self) -> None:
        activation = self.start_agent_turn()
        status, body = _request(
            self.gw_base,
            f"/api/activations/{activation['id']}/action",
            "POST",
            {"action": {"notation": "H8"}},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "occupied")
        _, current = _request(self.gw_base, f"/api/activations/{activation['id']}")
        self.assertEqual(current["activation"]["status"], "pending")

        status, _ = _request(
            self.gw_base,
            f"/api/activations/{activation['id']}/action",
            "POST",
            {"action": {"notation": "I9"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.game_state()["moveCount"], 2)

    def test_reset_supersedes_pending_activation(self) -> None:
        activation = self.start_agent_turn()
        _request(self.game_base, "/api/reset", "POST", {})
        superseded = self.wait_activation("superseded")
        self.assertEqual(superseded["id"], activation["id"])

        status, _ = _request(
            self.gw_base,
            f"/api/activations/{activation['id']}/action",
            "POST",
            {"action": {"notation": "I9"}},
        )
        self.assertIn(status, (409, 410))

    def test_activation_expires(self) -> None:
        self.start_agent_turn()
        expired = self.wait_activation("expired")
        self.assertEqual(expired["status"], "expired")
        self.assertTrue(_wait_for(lambda: not self.game_state()["agentThinking"]) is True)

    def test_human_win_creates_result_activation(self) -> None:
        _request(self.game_base, "/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        self.play_sequence(
            [
                ("human", "H8"),
                ("agent", "A1"),
                ("human", "I8"),
                ("agent", "A2"),
                ("human", "J8"),
                ("agent", "A3"),
                ("human", "K8"),
                ("agent", "A4"),
                ("human", "L8"),
            ]
        )
        result = self.wait_result()
        self.assertEqual(result["kind"], "result")
        self.assertIsNone(result["actor"])
        self.assertEqual(result["winner"], "black")
        self.assertEqual(result["gameStatus"], "black_win")
        self.assertEqual(result["agents"], ["white"])
        self.assertIn("A B C", result["display"])

        status, body = _request(
            self.gw_base,
            f"/api/activations/{result['id']}/action",
            "POST",
            {"action": {"notation": "H8"}},
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "action_not_required")

        status, body = _request(self.gw_base, f"/api/activations/{result['id']}/ack", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["activation"]["status"], "acked")
        status, _ = _request(self.gw_base, f"/api/activations/{result['id']}/ack", "POST", {})
        self.assertEqual(status, 200)

        time.sleep(0.2)
        _, listing = _request(self.gw_base, "/api/activations")
        results = [row for row in listing["activations"] if row.get("kind") == "result"]
        self.assertEqual(len(results), 1)

    def test_agent_win_does_not_create_duplicate_result_notice(self) -> None:
        _request(self.game_base, "/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
        self.play_sequence(
            [
                ("human", "A1"),
                ("agent", "H8"),
                ("human", "C1"),
                ("agent", "I8"),
                ("human", "E1"),
                ("agent", "J8"),
                ("human", "G1"),
                ("agent", "K8"),
                ("human", "I1"),
                ("agent", "L8"),
            ]
        )
        self.assertEqual(self.game_state()["status"], "white_win")
        time.sleep(0.4)
        _, listing = _request(self.gw_base, "/api/activations")
        self.assertEqual([row for row in listing["activations"] if row.get("kind") == "result"], [])

    def test_no_activation_without_agent_mode(self) -> None:
        _request(self.game_base, "/api/move", "POST", {"notation": "H8"})
        time.sleep(0.3)
        _, body = _request(self.gw_base, "/api/activations?status=pending")
        self.assertEqual(body["activations"], [])
        _, matches = _request(self.gw_base, "/api/matches")
        self.assertEqual(len(matches["matches"]), 1)
        self.assertEqual(matches["matches"][0]["agents"], [])

    def test_register_game_at_runtime(self) -> None:
        empty = create_gateway(port=0, games=[], poll_ms=40, activation_timeout=5, quiet=True)
        thread = threading.Thread(target=empty.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{empty.server_address[1]}"
            status, body = _request(base, "/api/games", "POST", {"url": self.game_base})
            self.assertEqual(status, 200)
            _request(self.game_base, "/api/mode", "POST", {"humanSide": "black", "agentSide": "white"})
            _request(self.game_base, "/api/move", "POST", {"notation": "H8", "as": "human"})

            def check():
                _, listing = _request(base, "/api/activations?status=pending")
                rows = listing.get("activations") or []
                return rows[0] if rows else None

            self.assertIsNotNone(_wait_for(check))
        finally:
            empty.shutdown()
            empty.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
