import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes.item import Capture, HistoryItem, collapse_whitespace, sha256_hex


def _text_item(text: str, **kwargs: object) -> HistoryItem:
    """Build a text HistoryItem the same way the store would."""
    return HistoryItem(
        kind="text",
        content_hash=sha256_hex(text.encode()),
        text=text,
        search_text=text,
        mime="text/plain",
        bytes=len(text.encode()),
        **kwargs,  # type: ignore[arg-type]
    )


class ItemTests(unittest.TestCase):
    def test_preview_is_single_line(self) -> None:
        item = _text_item("  line one\n\tline two   ")
        self.assertEqual(item.preview(), "line one line two")
        self.assertNotIn("\n", item.preview())

    def test_preview_is_truncated(self) -> None:
        item = _text_item("x" * 500)
        self.assertEqual(len(item.preview(20)), 21)  # 20 chars + ellipsis
        self.assertTrue(item.preview(20).endswith("\u2026"))

    def test_collapse_whitespace(self) -> None:
        self.assertEqual(collapse_whitespace(" a \t b\n\nc "), "a b c")

    def test_describe_counts_lines(self) -> None:
        self.assertIn("1 line", _text_item("one").describe())
        self.assertIn("3 lines", _text_item("a\nb\nc").describe())

    def test_timestamps_default_to_now(self) -> None:
        item = _text_item("x")
        self.assertEqual(item.created, item.last_used)
        self.assertEqual(item.copy_count, 1)
        self.assertFalse(item.pinned)

    def test_image_preview(self) -> None:
        item = HistoryItem(
            kind="image",
            content_hash="abc",
            mime="image/png",
            width=1920,
            height=1080,
            bytes=245760,
        )
        label = item.preview()
        self.assertIn("PNG", label)
        self.assertIn("1920", label)
        self.assertIn("1080", label)

    def test_capture_from_text(self) -> None:
        cap = Capture.from_text("hello")
        self.assertEqual(cap.kind, "text")
        self.assertEqual(cap.text, "hello")
        self.assertEqual(cap.content_hash(), sha256_hex(b"hello"))

    def test_capture_image_hash(self) -> None:
        data = b"\x89PNG fake"
        cap = Capture(
            kind="image",
            canonical_mime="image/png",
            reps={"image/png": data},
        )
        self.assertEqual(cap.content_hash(), sha256_hex(data))


if __name__ == "__main__":
    unittest.main()
