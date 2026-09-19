import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes import monitors


class NormalizeOrderTests(unittest.TestCase):
    def test_default_when_empty(self) -> None:
        self.assertEqual(monitors.normalize_order([]), list(monitors.DEFAULT_ORDER))
        self.assertEqual(monitors.normalize_order(None), list(monitors.DEFAULT_ORDER))

    def test_keeps_user_order(self) -> None:
        self.assertEqual(
            monitors.normalize_order(["pointer", "primary", "focused"]),
            ["pointer", "primary", "focused"],
        )

    def test_drops_unknown_and_duplicates(self) -> None:
        self.assertEqual(
            monitors.normalize_order(["pointer", "bogus", "pointer"]),
            ["pointer", "focused", "primary"],
        )

    def test_appends_missing_strategies(self) -> None:
        self.assertEqual(monitors.normalize_order(["primary"]), ["primary", "focused", "pointer"])

    def test_case_and_whitespace_tolerant(self) -> None:
        self.assertEqual(monitors.normalize_order([" Pointer "])[0], "pointer")


class MoveTests(unittest.TestCase):
    def test_move_up(self) -> None:
        self.assertEqual(
            monitors.move(["focused", "pointer", "primary"], "primary", -1),
            ["focused", "primary", "pointer"],
        )

    def test_move_down(self) -> None:
        self.assertEqual(
            monitors.move(["focused", "pointer", "primary"], "focused", 1),
            ["pointer", "focused", "primary"],
        )

    def test_clamped_at_ends(self) -> None:
        order = ["focused", "pointer", "primary"]
        self.assertEqual(monitors.move(order, "focused", -1), order)
        self.assertEqual(monitors.move(order, "primary", 1), order)

    def test_unknown_name_is_a_noop(self) -> None:
        self.assertEqual(monitors.move(["pointer"], "bogus", 1), ["pointer", "focused", "primary"])


class PickTests(unittest.TestCase):
    def test_focused_wins_by_default(self) -> None:
        chosen = monitors.pick(None, {"focused": "m2", "pointer": "m1", "primary": "m1"})
        self.assertEqual(chosen, "m2")

    def test_falls_back_to_pointer_then_primary(self) -> None:
        self.assertEqual(
            monitors.pick(None, {"focused": None, "pointer": "m1", "primary": "m0"}), "m1"
        )
        self.assertEqual(
            monitors.pick(None, {"focused": None, "pointer": None, "primary": "m0"}), "m0"
        )

    def test_user_order_is_respected(self) -> None:
        candidates = {"focused": "m2", "pointer": "m1", "primary": "m0"}
        self.assertEqual(monitors.pick(["pointer"], candidates), "m1")
        self.assertEqual(monitors.pick(["primary", "focused"], candidates), "m0")

    def test_none_when_nothing_resolves(self) -> None:
        self.assertIsNone(monitors.pick(None, {"focused": None, "pointer": None, "primary": None}))


if __name__ == "__main__":
    unittest.main()
