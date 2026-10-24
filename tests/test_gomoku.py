from __future__ import annotations

import json
import unittest

from gamelab.games.gomoku import (
    BLACK,
    EMPTY,
    WHITE,
    Gomoku,
    GameError,
    notation,
    parse_coord,
)


class CoordinateTests(unittest.TestCase):
    def test_center_is_h8(self) -> None:
        self.assertEqual(parse_coord("H8"), (7, 7))
        self.assertEqual(parse_coord("h8"), (7, 7))
        self.assertEqual(parse_coord(" h8 "), (7, 7))
        self.assertEqual(notation(7, 7), "H8")

    def test_corners(self) -> None:
        self.assertEqual(parse_coord("A1"), (0, 14))
        self.assertEqual(parse_coord("O15"), (14, 0))
        self.assertEqual(notation(0, 14), "A1")
        self.assertEqual(notation(14, 0), "O15")

    def test_bad_notation(self) -> None:
        for text in ("Z9", "H0", "H16", "8H", "", "HH", "H8x"):
            with self.subTest(text=text), self.assertRaises(GameError):
                parse_coord(text)


class InitialStateTests(unittest.TestCase):
    def test_fresh_board(self) -> None:
        game = Gomoku()
        state = game.state()
        self.assertEqual(state["boardSize"], 15)
        self.assertEqual(state["status"], "playing")
        self.assertIsNone(state["winner"])
        self.assertEqual(state["currentPlayer"], "black")
        self.assertEqual(state["moveCount"], 0)
        self.assertIsNone(state["lastMove"])
        self.assertIsNone(state["winLine"])
        self.assertEqual(len(state["board"]), 15)
        self.assertTrue(all(cell == EMPTY for row in state["board"] for cell in row))

    def test_state_is_json_safe_and_detached(self) -> None:
        game = Gomoku()
        state = game.state()
        json.dumps(state)  # must not raise
        state["board"][0][0] = 99
        state["moves"].append({"bogus": True})
        self.assertEqual(game.board[0][0], EMPTY)
        self.assertEqual(game.moves, [])

    def test_schema_version(self) -> None:
        self.assertEqual(Gomoku().state()["schemaVersion"], 1)


class MoveTests(unittest.TestCase):
    def test_alternating_turns(self) -> None:
        game = Gomoku()
        game.place(7, 7)
        self.assertEqual(game.board[7][7], BLACK)
        self.assertEqual(game.current, WHITE)
        game.place(8, 7)
        self.assertEqual(game.board[7][8], WHITE)
        self.assertEqual(game.current, BLACK)
        self.assertEqual(game.moves[0]["notation"], "H8")
        self.assertEqual(game.moves[0]["player"], "black")
        self.assertEqual(game.moves[1]["notation"], "I8")

    def test_occupied_cell_rejected(self) -> None:
        game = Gomoku()
        game.place(7, 7)
        with self.assertRaises(GameError) as ctx:
            game.place(7, 7)
        self.assertEqual(ctx.exception.code, "occupied")
        self.assertEqual(game.state()["moveCount"], 1)

    def test_out_of_range_rejected(self) -> None:
        game = Gomoku()
        for x, y in ((-1, 0), (15, 0), (0, -1), (0, 15)):
            with self.subTest(x=x, y=y), self.assertRaises(GameError) as ctx:
                game.place(x, y)
            self.assertEqual(ctx.exception.code, "out_of_range")

    def test_move_after_game_over_rejected(self) -> None:
        game = Gomoku()
        for x in range(5):
            game.place(x, 7)  # black
            if x < 4:
                game.place(x, 8)  # white
        self.assertEqual(game.status, "black_win")
        with self.assertRaises(GameError) as ctx:
            game.place(10, 10)
        self.assertEqual(ctx.exception.code, "game_over")


class WinTests(unittest.TestCase):
    def _win_with(self, black_cells: list[tuple[int, int]]) -> Gomoku:
        """Black plays the given line, white plays harmless filler moves."""
        game = Gomoku()
        filler = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (10, 0)]
        for index, cell in enumerate(black_cells):
            game.place(*cell)
            if index < len(black_cells) - 1:
                game.place(*filler[index])
        return game

    def test_horizontal_win(self) -> None:
        game = self._win_with([(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)])
        self.assertEqual(game.status, "black_win")
        self.assertEqual(game.winner, "black")
        self.assertIsNone(game.current)
        self.assertIsNotNone(game.win_line)
        self.assertGreaterEqual(len(game.win_line or []), 5)

    def test_vertical_win(self) -> None:
        game = self._win_with([(9, 2), (9, 3), (9, 4), (9, 5), (9, 6)])
        self.assertEqual(game.status, "black_win")

    def test_diagonal_win(self) -> None:
        game = self._win_with([(2, 2), (3, 3), (4, 4), (5, 5), (6, 6)])
        self.assertEqual(game.status, "black_win")

    def test_anti_diagonal_win(self) -> None:
        game = self._win_with([(2, 10), (3, 9), (4, 8), (5, 7), (6, 6)])
        self.assertEqual(game.status, "black_win")

    def test_white_can_win(self) -> None:
        game = Gomoku()
        white_line = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
        black_filler = [(0, 2), (2, 2), (4, 2), (6, 2), (8, 2)]
        for index in range(5):
            game.place(*black_filler[index])
            game.place(*white_line[index])
        self.assertEqual(game.status, "white_win")
        self.assertEqual(game.winner, "white")

    def test_four_in_a_row_is_not_a_win(self) -> None:
        game = self._win_with([(3, 7), (4, 7), (5, 7), (6, 7)])
        self.assertEqual(game.status, "playing")

    def test_gap_does_not_win(self) -> None:
        game = Gomoku()
        cells = [(0, 0), (1, 0), (2, 0), (4, 0), (5, 0)]
        filler = [(0, 5), (2, 5), (4, 5), (6, 5), (8, 5)]
        for index, cell in enumerate(cells):
            game.place(*cell)
            game.place(*filler[index])
        self.assertEqual(game.status, "playing")

    def test_win_line_is_contiguous_run(self) -> None:
        game = self._win_with([(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)])
        line = game.state()["winLine"]
        self.assertEqual([(cell["x"], cell["y"]) for cell in line], [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)])


class UndoResetTests(unittest.TestCase):
    def test_undo_restores_turn_and_cell(self) -> None:
        game = Gomoku()
        game.place(7, 7)
        game.undo()
        self.assertEqual(game.board[7][7], EMPTY)
        self.assertEqual(game.current, BLACK)
        self.assertEqual(game.moves, [])
        self.assertEqual(game.status, "playing")

    def test_undo_empty_raises(self) -> None:
        with self.assertRaises(GameError) as ctx:
            Gomoku().undo()
        self.assertEqual(ctx.exception.code, "nothing_to_undo")

    def test_undo_after_win_reopens_game(self) -> None:
        game = Gomoku()
        for x in range(5):
            game.place(x, 7)
            if x < 4:
                game.place(x, 8)
        self.assertEqual(game.status, "black_win")
        game.undo()
        self.assertEqual(game.status, "playing")
        self.assertIsNone(game.winner)
        self.assertIsNone(game.win_line)
        self.assertEqual(game.current, BLACK)

    def test_reset_clears_everything(self) -> None:
        game = Gomoku()
        game.place(7, 7)
        game.place(8, 8)
        game.reset()
        state = game.state()
        self.assertEqual(state["moveCount"], 0)
        self.assertEqual(state["status"], "playing")
        self.assertEqual(state["currentPlayer"], "black")
        self.assertTrue(all(cell == EMPTY for row in state["board"] for cell in row))

    def test_revision_changes_on_mutation(self) -> None:
        game = Gomoku()
        seen = {game.state()["revision"]}
        game.place(7, 7)
        seen.add(game.state()["revision"])
        game.undo()
        seen.add(game.state()["revision"])
        game.reset()
        seen.add(game.state()["revision"])
        self.assertEqual(len(seen), 4)


class DrawTests(unittest.TestCase):
    def test_full_board_without_five_is_draw(self) -> None:
        # 4x4 with win length 4: the colouring (x + 2y) % 4 < 2 has no run of
        # four in any direction, so filling the board produces a draw.
        size = 4
        game = Gomoku(size=size, win_length=size)
        blacks: list[tuple[int, int]] = []
        whites: list[tuple[int, int]] = []
        for y in range(size):
            for x in range(size):
                if (x + 2 * y) % 4 < 2:
                    blacks.append((x, y))
                else:
                    whites.append((x, y))
        self.assertEqual(len(blacks), len(whites))
        for index in range(len(blacks)):
            game.place(*blacks[index])
            game.place(*whites[index])
        state = game.state()
        self.assertEqual(state["moveCount"], size * size)
        self.assertEqual(state["status"], "draw")
        self.assertIsNone(state["winner"])
        self.assertIsNone(state["currentPlayer"])


class CommandTests(unittest.TestCase):
    def test_bare_coordinate(self) -> None:
        game = Gomoku()
        result = game.execute("h8")
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "place")
        self.assertEqual(result["move"]["notation"], "H8")
        self.assertEqual(result["state"]["moveCount"], 1)

    def test_place_prefixes(self) -> None:
        for command in ("place H8", "move h8", "put H8", "下 H8", "落子 H8"):
            with self.subTest(command=command):
                game = Gomoku()
                self.assertTrue(game.execute(command)["ok"])

    def test_undo_reset_state_help(self) -> None:
        game = Gomoku()
        game.execute("H8")
        undo = game.execute("undo")
        self.assertEqual(undo["action"], "undo")
        self.assertEqual(undo["state"]["moveCount"], 0)

        game.execute("H8")
        reset = game.execute("reset")
        self.assertEqual(reset["action"], "reset")
        self.assertEqual(reset["state"]["moveCount"], 0)

        state = game.execute("state")
        self.assertEqual(state["action"], "state")
        self.assertIn("board", state["state"])

        help_result = game.execute("help")
        self.assertEqual(help_result["action"], "help")
        self.assertTrue(any("H8" in line for line in help_result["help"]))

    def test_errors(self) -> None:
        cases = {
            "": "empty_command",
            "fly me to the moon": "unknown_command",
            "place": "missing_argument",
            "place Z9": "bad_notation",
        }
        for command, code in cases.items():
            with self.subTest(command=command), self.assertRaises(GameError) as ctx:
                Gomoku().execute(command)
            self.assertEqual(ctx.exception.code, code)


class AgentModeTests(unittest.TestCase):
    def test_start_mode_on_empty_board(self) -> None:
        game = Gomoku()
        state = game.set_mode("black", "white")
        self.assertEqual(state["mode"], {"humanSide": "black", "agentSide": "white"})
        self.assertFalse(state["agentThinking"])
        self.assertIsNone(state["agentThinkingSince"])

    def test_mode_rejects_same_or_unknown_sides(self) -> None:
        game = Gomoku()
        for human, agent in (("black", "black"), ("red", "white"), ("black", "blue")):
            with self.subTest(human=human, agent=agent), self.assertRaises(GameError) as ctx:
                game.set_mode(human, agent)
            self.assertEqual(ctx.exception.code, "bad_mode")

    def test_mode_requires_empty_board(self) -> None:
        game = Gomoku()
        game.place(7, 7)
        with self.assertRaises(GameError) as ctx:
            game.set_mode("black", "white")
        self.assertEqual(ctx.exception.code, "game_in_progress")
        self.assertEqual(ctx.exception.status, 409)

    def test_actor_is_rejected_outside_agent_mode(self) -> None:
        game = Gomoku()
        with self.assertRaises(GameError) as ctx:
            game.place(7, 7, "human")
        self.assertEqual(ctx.exception.code, "mode_not_active")

    def test_actor_is_required_in_agent_mode(self) -> None:
        game = Gomoku()
        game.set_mode("black", "white")
        with self.assertRaises(GameError) as ctx:
            game.place(7, 7)
        self.assertEqual(ctx.exception.code, "actor_required")

    def test_wrong_actor_cannot_move(self) -> None:
        game = Gomoku()
        game.set_mode("black", "white")
        with self.assertRaises(GameError) as ctx:
            game.place(7, 7, "agent")
        self.assertEqual(ctx.exception.code, "not_your_turn")
        self.assertEqual(ctx.exception.status, 409)

    def test_alternating_human_and_agent_moves(self) -> None:
        game = Gomoku()
        game.set_mode("black", "white")
        game.place(7, 7, "human")
        self.assertEqual(game.state()["currentPlayer"], "white")
        game.place(8, 8, "agent")
        self.assertEqual(game.state()["currentPlayer"], "black")
        game.place(6, 7, "human")
        self.assertEqual(game.state()["moveCount"], 3)

    def test_command_accepts_actor(self) -> None:
        game = Gomoku()
        game.set_mode("black", "white")
        result = game.execute("H8", "human")
        self.assertEqual(result["move"]["notation"], "H8")
        with self.assertRaises(GameError) as ctx:
            game.execute("undo")
        self.assertEqual(ctx.exception.code, "mode_restricted")

    def test_undo_is_restricted_in_agent_mode(self) -> None:
        game = Gomoku()
        game.set_mode("black", "white")
        game.place(7, 7, "human")
        with self.assertRaises(GameError) as ctx:
            game.undo()
        self.assertEqual(ctx.exception.code, "mode_restricted")

    def test_reset_keeps_mode_but_clears_thinking(self) -> None:
        game = Gomoku()
        game.set_mode("black", "white")
        game.place(7, 7, "human")
        game.set_agent_thinking(True)
        state = game.reset()
        self.assertEqual(state["mode"], {"humanSide": "black", "agentSide": "white"})
        self.assertFalse(state["agentThinking"])
        self.assertIsNone(state["agentThinkingSince"])
        self.assertEqual(state["moveCount"], 0)
        self.assertEqual(state["currentPlayer"], "black")

    def test_thinking_requires_mode(self) -> None:
        game = Gomoku()
        with self.assertRaises(GameError) as ctx:
            game.set_agent_thinking(True)
        self.assertEqual(ctx.exception.code, "no_mode")

    def test_thinking_toggles_state(self) -> None:
        game = Gomoku()
        game.set_mode("black", "white")
        revision = game.state()["revision"]
        state = game.set_agent_thinking(True)
        self.assertTrue(state["agentThinking"])
        self.assertIsNotNone(state["agentThinkingSince"])
        self.assertGreater(state["revision"], revision)
        state = game.set_agent_thinking(False)
        self.assertFalse(state["agentThinking"])
        self.assertIsNone(state["agentThinkingSince"])

    def test_turn_id_changes_only_on_turn_boundaries(self) -> None:
        game = Gomoku()
        start = game.state()["turnId"]
        game.set_mode("black", "white")
        self.assertEqual(game.state()["turnId"], start)
        game.set_agent_thinking(True)
        self.assertEqual(game.state()["turnId"], start)
        game.place(7, 7, "human")
        after_move = game.state()["turnId"]
        self.assertNotEqual(after_move, start)
        game.set_agent_thinking(False)
        self.assertEqual(game.state()["turnId"], after_move)
        game.reset()
        self.assertNotEqual(game.state()["turnId"], after_move)

    def test_clear_mode_restores_free_play(self) -> None:
        game = Gomoku()
        game.set_mode("black", "white")
        game.place(7, 7, "human")
        state = game.clear_mode()
        self.assertIsNone(state["mode"])
        self.assertFalse(state["agentThinking"])
        game.place(8, 8)
        self.assertEqual(game.state()["moveCount"], 2)


if __name__ == "__main__":
    unittest.main()
