import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes.item import Capture, HistoryItem, collapse_whitespace


class ItemTests(unittest.TestCase):
    def test_preview_is_single_line(self) -> None:
        item = HistoryItem(text="  line one\n\tline two   ", kind="text")
        self.assertEqual(item.preview(), "line one line two")
        self.assertNotIn("\n", item.preview())

    def test_preview_is_truncated(self) -> None:
        item = HistoryItem(text="x" * 500, kind="text")
        self.assertEqual(len(item.preview(20)), 21)  # 20 chars + ellipsis
        self.assertTrue(item.preview(20).endswith("\u2026"))

    def test_preview_for_image(self) -> None:
        """Image items return label as preview."""
        item = HistoryItem(kind="image", mime="image/png", width=640, height=480, bytes=5000)
        preview = item.preview()
        self.assertIn("PNG", preview)
        self.assertIn("640", preview)
        self.assertIn("480", preview)

    def test_label_for_text_falls_back_to_preview(self) -> None:
        item = HistoryItem(text="hello", kind="text")
        self.assertEqual(item.label(), item.preview())

    def test_label_for_image(self) -> None:
        item = HistoryItem(kind="image", mime="image/jpeg", width=1920, height=1080, bytes=102400)
        label = item.label()
        self.assertIn("JPEG", label)
        self.assertIn("1920", label)
        self.assertIn("1080", label)
        self.assertIn("100 kB", label)

    def test_collapse_whitespace(self) -> None:
        self.assertEqual(collapse_whitespace(" a \t b\n\nc "), "a b c")

    def test_describe_counts_lines(self) -> None:
        self.assertIn("1 line", HistoryItem(text="one", kind="text").describe())
        self.assertIn("3 lines", HistoryItem(text="a\nb\nc", kind="text").describe())

    def test_describe_for_image(self) -> None:
        item = HistoryItem(kind="image", mime="image/png", width=640, height=480, bytes=20480)
        desc = item.describe()
        self.assertIn("640", desc)
        self.assertIn("480", desc)
        self.assertIn("PNG", desc)

    def test_timestamps_default_to_now(self) -> None:
        item = HistoryItem(text="x", kind="text")
        self.assertEqual(item.created, item.last_used)
        self.assertEqual(item.copy_count, 1)
        self.assertFalse(item.pinned)

    def test_capture_text(self) -> None:
        capture = Capture(
            reps={"text/plain": b"hello"}, text="hello", kind="text", canonical_mime="text/plain"
        )
        self.assertEqual(capture.kind, "text")
        self.assertEqual(capture.text, "hello")

    def test_capture_image(self) -> None:
        png_data = b"\x89PNG" + b"x" * 100
        capture = Capture(
            reps={"image/png": png_data}, text=None, kind="image", canonical_mime="image/png"
        )
        self.assertEqual(capture.kind, "image")
        self.assertIsNone(capture.text)
        self.assertIn("image/png", capture.reps)


if __name__ == "__main__":
    unittest.main()
