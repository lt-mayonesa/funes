import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes.item import (
    VECTOR_MIMES,
    Capture,
    HistoryItem,
    classify,
    collapse_whitespace,
    mime_subtype_label,
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

    def test_svg_preview_label_is_short_not_the_raw_subtype(self) -> None:
        # "image/svg+xml".split("/")[-1].upper() would read "SVG+XML" \u2014
        # mime_subtype_label() special-cases this to plain "SVG".
        item = HistoryItem(kind="image", content_hash="abc", mime="image/svg+xml", bytes=512)
        self.assertIn("SVG", item.preview())
        self.assertNotIn("SVG+XML", item.preview())

    def test_inkscape_svg_preview_label_is_also_just_svg(self) -> None:
        item = HistoryItem(kind="image", content_hash="abc", mime="image/x-inkscape-svg", bytes=512)
        self.assertIn("SVG", item.preview())
        self.assertNotIn("X-INKSCAPE-SVG", item.preview())

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

    def test_html_with_plain_text_is_richtext(self) -> None:
        reps = {"text/html": b"<b>hi</b>", "UTF8_STRING": b"hi"}
        self.assertEqual(classify(reps, "hi"), "richtext")

    def test_rtf_with_plain_text_is_richtext(self) -> None:
        reps = {"text/rtf": b"{\\rtf1 hi}", "UTF8_STRING": b"hi"}
        self.assertEqual(classify(reps, "hi"), "richtext")

    def test_incidental_extras_with_plain_text_stay_text(self) -> None:
        # Browser source-URL atoms, GtkTextBuffer serializations: captured and
        # replayed verbatim, but the row is a plain text row.
        reps = {"X-SOURCE-URL": b"https://example.org", "UTF8_STRING": b"hi"}
        self.assertEqual(classify(reps, "hi"), "text")

    def test_html_without_plain_text_is_other(self) -> None:
        self.assertEqual(classify({"text/html": b"<img src=x>"}, "  "), "other")

    def test_image_wins_over_richtext(self) -> None:
        # Browser "Copy image": image/png + an <img> HTML snippet.
        reps = {"image/png": b"png", "text/html": b"<img src=x>"}
        self.assertEqual(classify(reps, "x"), "image")


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


class MimeSubtypeLabelTests(unittest.TestCase):
    def test_ordinary_mime_is_uppercased_subtype(self) -> None:
        self.assertEqual(mime_subtype_label("image/png"), "PNG")
        self.assertEqual(mime_subtype_label("image/jpeg"), "JPEG")

    def test_svg_mimes_are_shortened(self) -> None:
        self.assertEqual(mime_subtype_label("image/svg+xml"), "SVG")
        self.assertEqual(mime_subtype_label("image/x-inkscape-svg"), "SVG")

    def test_vector_mimes_constant_matches_the_overrides(self) -> None:
        for mime in VECTOR_MIMES:
            self.assertEqual(mime_subtype_label(mime), "SVG")


class PickCanonicalMimeTests(unittest.TestCase):
    def test_vector_wins_over_png_even_when_smaller(self) -> None:
        # Inkscape-style copy: a raster preview offered alongside the real
        # vector data. The vector rep is the richer one and must win, so
        # the item is correctly identified as SVG, not "just a PNG".
        reps = {"image/png": b"a much larger png preview", "image/svg+xml": b"<svg/>"}
        self.assertEqual(pick_canonical_mime(reps), "image/svg+xml")

    def test_svg_wins_over_inkscape_svg_when_both_present(self) -> None:
        reps = {"image/x-inkscape-svg": b"<svg inkscape:x/>", "image/svg+xml": b"<svg/>"}
        self.assertEqual(pick_canonical_mime(reps), "image/svg+xml")

    def test_inkscape_svg_wins_over_png_when_no_standard_svg(self) -> None:
        reps = {"image/png": b"a much larger png preview", "image/x-inkscape-svg": b"<svg/>"}
        self.assertEqual(pick_canonical_mime(reps), "image/x-inkscape-svg")

    def test_prefers_png_when_no_vector_rep(self) -> None:
        reps = {"image/png": b"tiny", "image/jpeg": b"a much larger jpeg"}
        self.assertEqual(pick_canonical_mime(reps), "image/png")

    def test_falls_back_to_largest_when_no_png_or_vector(self) -> None:
        reps = {"image/jpeg": b"short", "image/bmp": b"a longer representation"}
        self.assertEqual(pick_canonical_mime(reps), "image/bmp")

    def test_single_representation_wins_by_default(self) -> None:
        reps = {"image/jpeg": b"only one"}
        self.assertEqual(pick_canonical_mime(reps), "image/jpeg")

    def test_empty_reps_raises(self) -> None:
        with self.assertRaises(ValueError):
            pick_canonical_mime({})

    def test_richtext_prefers_html_over_larger_reps(self) -> None:
        reps = {
            "application/x-openoffice-embed-source-xml": b"a much larger private blob",
            "text/rtf": b"{\\rtf1}",
            "text/html": b"<b/>",
        }
        self.assertEqual(pick_canonical_mime(reps, "richtext"), "text/html")

    def test_richtext_falls_back_to_rtf(self) -> None:
        reps = {"text/rtf": b"{\\rtf1}", "UTF8_STRING": b"a longer plain text"}
        self.assertEqual(pick_canonical_mime(reps, "richtext"), "text/rtf")

    def test_text_is_always_text_plain(self) -> None:
        self.assertEqual(pick_canonical_mime({"X-SOURCE-URL": b"u"}, "text"), "text/plain")

    def test_files_prefers_gnome_copied_files(self) -> None:
        reps = {
            "text/uri-list": b"file:///a",
            "x-special/gnome-copied-files": b"copy\nfile:///a",
            "UTF8_STRING": b"a much longer plain-text path list",
        }
        self.assertEqual(pick_canonical_mime(reps, "files"), "x-special/gnome-copied-files")


class RichTextCaptureTests(unittest.TestCase):
    def _rich(self, html: bytes, text: str = "hello", **extra: bytes) -> Capture:
        reps = {"text/html": html, "UTF8_STRING": text.encode(), **extra}
        return Capture(kind="richtext", canonical_mime="text/html", reps=reps, text=text)

    def test_plain_and_formatted_hash_differently(self) -> None:
        plain = Capture.from_text("hello")
        self.assertNotEqual(plain.content_hash(), self._rich(b"<b>hello</b>").content_hash())

    def test_different_formatting_hashes_differently(self) -> None:
        self.assertNotEqual(
            self._rich(b"<b>hello</b>").content_hash(),
            self._rich(b"<i>hello</i>").content_hash(),
        )

    def test_private_targets_do_not_affect_hash(self) -> None:
        # App-private targets may carry volatile data (timestamps, ids);
        # the same visible formatted text must still dedup.
        self.assertEqual(
            self._rich(b"<b>hello</b>", **{"chromium/x-web-custom-data": b"1"}).content_hash(),
            self._rich(b"<b>hello</b>", **{"chromium/x-web-custom-data": b"2"}).content_hash(),
        )

    def test_text_capture_with_extras_hashes_like_plain_text(self) -> None:
        cap = Capture(
            kind="text",
            canonical_mime="text/plain",
            reps={"X-SOURCE-URL": b"https://example.org", "UTF8_STRING": b"hello"},
            text="hello",
        )
        self.assertEqual(cap.content_hash(), Capture.from_text("hello").content_hash())


class RichTextItemTests(unittest.TestCase):
    def test_richtext_preview_is_plain_text(self) -> None:
        item = HistoryItem(
            kind="richtext", content_hash="x", text="Quarterly\n report", mime="text/html"
        )
        self.assertEqual(item.preview(), "Quarterly report")
        self.assertTrue(item.is_rich)
        self.assertEqual(item.plain_text, "Quarterly\n report")

    def test_richtext_describe_names_the_format(self) -> None:
        item = HistoryItem(kind="richtext", content_hash="x", text="hi", mime="text/html")
        self.assertTrue(item.describe().endswith("HTML"))

    def test_plain_text_is_none_for_images(self) -> None:
        item = HistoryItem(kind="image", content_hash="x", mime="image/png")
        self.assertIsNone(item.plain_text)
        self.assertFalse(item.is_rich)


if __name__ == "__main__":
    unittest.main()
