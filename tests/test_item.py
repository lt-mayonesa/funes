import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes.item import (
    Capture,
    HistoryItem,
    classify,
    collapse_whitespace,
    pick_canonical_mime,
    sha256_hex,
)


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


class ClassifyTests(unittest.TestCase):
    def test_image_mime_present_classifies_as_image(self) -> None:
        self.assertEqual(classify({"image/png": b"data"}), "image")

    def test_files_mime_wins_over_image(self) -> None:
        # A file manager offering a thumbnail image/* alongside the uri-list
        # is still a file copy, not an image copy — files > image priority.
        reps = {"image/svg+xml": b"<svg/>", "text/uri-list": b"file:///tmp/x.svg"}
        self.assertEqual(classify(reps), "files")

    def test_unrecognized_mime_falls_back_to_other(self) -> None:
        self.assertEqual(classify({"application/x-unknown-format": b"data"}), "other")

    def test_uri_list_alone_classifies_as_files(self) -> None:
        self.assertEqual(classify({"text/uri-list": b"file:///tmp/x.txt"}), "files")

    def test_gnome_copied_files_alone_classifies_as_files(self) -> None:
        reps = {"x-special/gnome-copied-files": b"copy\nfile:///tmp/x.txt"}
        self.assertEqual(classify(reps), "files")


class FilesLabelTests(unittest.TestCase):
    def _files_item(self, names: list[str], operation: str | None = "copy") -> HistoryItem:
        return HistoryItem(
            kind="files",
            content_hash="x",
            search_text="\n".join(names),
            operation=operation,
            bytes=0,
        )

    def test_single_file_copy(self) -> None:
        item = self._files_item(["report.pdf"], operation="copy")
        self.assertEqual(item.preview(), "Copied: report.pdf")

    def test_single_file_cut(self) -> None:
        item = self._files_item(["report.pdf"], operation="cut")
        self.assertEqual(item.preview(), "Cut: report.pdf")

    def test_multiple_files_lists_first_three(self) -> None:
        item = self._files_item(["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"])
        self.assertEqual(item.preview(), "Copied 5 files: a.txt, b.txt, c.txt +2 more")

    def test_no_filenames_falls_back_to_byte_size(self) -> None:
        item = HistoryItem(
            kind="files", content_hash="x", search_text=None, operation="copy", bytes=1024
        )
        self.assertIn("Copied", item.preview())

    def test_long_label_is_truncated(self) -> None:
        item = self._files_item(["a-very-long-filename-that-pushes-past-the-limit.txt"])
        label = item.preview(max_chars=20)
        self.assertLessEqual(len(label), 21)  # 20 + ellipsis
        self.assertTrue(label.endswith("\u2026"))


class PickCanonicalMimeTests(unittest.TestCase):
    def test_prefers_png_even_when_smaller(self) -> None:
        reps = {"image/png": b"tiny", "image/svg+xml": b"a much larger svg document"}
        self.assertEqual(pick_canonical_mime(reps), "image/png")

    def test_falls_back_to_largest_when_no_png(self) -> None:
        reps = {"image/svg+xml": b"short", "image/x-inkscape-svg": b"a longer representation"}
        self.assertEqual(pick_canonical_mime(reps), "image/x-inkscape-svg")

    def test_single_representation_wins_by_default(self) -> None:
        reps = {"image/jpeg": b"only one"}
        self.assertEqual(pick_canonical_mime(reps), "image/jpeg")

    def test_empty_reps_raises(self) -> None:
        with self.assertRaises(ValueError):
            pick_canonical_mime({})


if __name__ == "__main__":
    unittest.main()
