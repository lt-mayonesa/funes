import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes.presentation import color_literal, looks_like_code, match_span, relative_age

SECOND = 1_000_000
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE
DAY = 24 * HOUR


class RelativeAgeTests(unittest.TestCase):
    def age(self, delta: int) -> str:
        now = 10_000 * DAY
        return relative_age(now - delta, now)

    def test_seconds(self) -> None:
        self.assertEqual(self.age(0), "0s")
        self.assertEqual(self.age(12 * SECOND), "12s")

    def test_minutes_and_hours(self) -> None:
        self.assertEqual(self.age(4 * MINUTE), "4m")
        self.assertEqual(self.age(HOUR), "1h")
        self.assertEqual(self.age(23 * HOUR), "23h")

    def test_days(self) -> None:
        self.assertEqual(self.age(DAY), "yest.")
        self.assertEqual(self.age(3 * DAY), "3d")
        self.assertEqual(self.age(14 * DAY), "2w")
        self.assertEqual(self.age(400 * DAY), "1y")

    def test_future_stamps_clamp_to_zero(self) -> None:
        self.assertEqual(self.age(-5 * SECOND), "0s")


class CodeHeuristicTests(unittest.TestCase):
    def test_code_like(self) -> None:
        for text in (
            "git rebase --interactive origin/main",
            "meson setup _build && meson compile -C _build",
            "ssh deploy@build-01.internal -p 2222",
            "SELECT id, name FROM projects WHERE archived = false",
            "https://github.com/linuxmint/xapp",
            "/usr/share/funes/app/popup.py",
            "#2f855a",
        ):
            self.assertTrue(looks_like_code(text), text)

    def test_prose_is_not_code(self) -> None:
        for text in (
            "Funes el memorioso — Jorge Luis Borges",
            "The clipboard is a terrible place to keep secrets.",
            "hello",
            "",
        ):
            self.assertFalse(looks_like_code(text), text)

    def test_multiline_is_never_mono(self) -> None:
        self.assertFalse(looks_like_code("git status\ngit diff"))


class ColorTests(unittest.TestCase):
    def test_hex_colors(self) -> None:
        self.assertEqual(color_literal(" #2f855a "), "#2f855a")
        self.assertEqual(color_literal("#fff"), "#fff")

    def test_non_colors(self) -> None:
        self.assertIsNone(color_literal("#2f855"))
        self.assertIsNone(color_literal("2f855a"))
        self.assertIsNone(color_literal("#2f855a and more"))


class MatchSpanTests(unittest.TestCase):
    def test_case_insensitive_span(self) -> None:
        self.assertEqual(match_span("Git rebase", "git"), (0, 3))
        self.assertEqual(match_span("run git now", "GIT"), (4, 7))

    def test_span_is_in_bytes(self) -> None:
        self.assertEqual(match_span("ñandú git", "git"), (8, 11))

    def test_no_match(self) -> None:
        self.assertIsNone(match_span("git", "svn"))
        self.assertIsNone(match_span("git", ""))


if __name__ == "__main__":
    unittest.main()
