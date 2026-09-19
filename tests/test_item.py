import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes.item import HistoryItem, collapse_whitespace


class ItemTests(unittest.TestCase):
    def test_preview_is_single_line(self) -> None:
        item = HistoryItem("  line one\n\tline two   ")
        self.assertEqual(item.preview(), "line one line two")
        self.assertNotIn("\n", item.preview())

    def test_preview_is_truncated(self) -> None:
        item = HistoryItem("x" * 500)
        self.assertEqual(len(item.preview(20)), 21)  # 20 chars + ellipsis
        self.assertTrue(item.preview(20).endswith("\u2026"))

    def test_collapse_whitespace(self) -> None:
        self.assertEqual(collapse_whitespace(" a \t b\n\nc "), "a b c")

    def test_describe_counts_lines(self) -> None:
        self.assertIn("1 line", HistoryItem("one").describe())
        self.assertIn("3 lines", HistoryItem("a\nb\nc").describe())

    def test_timestamps_default_to_now(self) -> None:
        item = HistoryItem("x")
        self.assertEqual(item.created, item.last_used)
        self.assertEqual(item.copy_count, 1)
        self.assertFalse(item.pinned)


if __name__ == "__main__":
    unittest.main()
