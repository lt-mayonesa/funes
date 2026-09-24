"""Tests for app/images.py — probe, thumbnail, meta_label.

Uses a generated 2x2 PNG fixture so no external files are required.
GdkPixbuf is available on the CI system (it's a hard dep of GTK).
"""

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from images import MAX_ASPECT, fit_box, meta_label, probe, thumbnail

# ---------------------------------------------------------------------------
# Minimal valid PNG builder — no external dependencies
# ---------------------------------------------------------------------------


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def _make_png(width: int, height: int) -> bytes:
    """Build a minimal valid RGBA PNG with *width* x *height* pixels."""
    signature = b"\x89PNG\r\n\x1a\n"

    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)

    # Image data: one filter byte + RGB per row.
    raw_rows = b""
    for _row in range(height):
        raw_rows += b"\x00" + b"\xff\x00\x00" * width  # red pixels, no filter

    compressed = zlib.compress(raw_rows)
    idat = _png_chunk(b"IDAT", compressed)
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


PNG_2X2 = _make_png(2, 2)
PNG_4X8 = _make_png(4, 8)
PNG_WIDE = _make_png(400, 10)  # 40:1 panorama


class TestProbe(unittest.TestCase):
    def test_returns_dimensions_for_valid_png(self) -> None:
        result = probe(PNG_2X2)
        self.assertEqual(result, (2, 2))

    def test_returns_none_for_garbage(self) -> None:
        result = probe(b"\x00\x01\x02 garbage bytes")
        self.assertIsNone(result)

    def test_non_square_png(self) -> None:
        result = probe(PNG_4X8)
        self.assertEqual(result, (4, 8))


class TestThumbnail(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="funes-thumb-test-"))

    def test_generates_thumbnail_file(self) -> None:
        path = thumbnail("abc123", PNG_2X2, 32, 1, self._tmp)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "abc123@32x1.png")

    def test_cached_on_second_call(self) -> None:
        """Second call should return immediately without regenerating."""
        path1 = thumbnail("abc123", PNG_2X2, 32, 1, self._tmp)
        # Corrupt the source data — should still return cached path.
        path2 = thumbnail("abc123", b"not a png", 32, 1, self._tmp)
        self.assertIsNotNone(path1)
        self.assertIsNotNone(path2)
        self.assertEqual(path1, path2)

    def test_returns_none_for_garbage(self) -> None:
        path = thumbnail("badsha", b"\x00" * 20, 32, 1, self._tmp)
        self.assertIsNone(path)

    def test_thumbnail_permissions(self) -> None:
        import stat

        path = thumbnail("perm_test", PNG_2X2, 32, 1, self._tmp)
        self.assertIsNotNone(path)
        assert path is not None
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o600)


class TestFitBox(unittest.TestCase):
    def test_tall_image_is_height_bound(self) -> None:
        self.assertEqual(fit_box(10, 20, 160, 40), (20, 40))

    def test_wide_image_is_width_bound_and_shorter(self) -> None:
        w, h = fit_box(400, 10, 160, 40)
        self.assertEqual(w, 160)
        self.assertEqual(h, 4)

    def test_never_exceeds_box(self) -> None:
        for size in ((3000, 5), (5, 3000), (1920, 1080), (1, 1)):
            w, h = fit_box(size[0], size[1], 192, 48)
            self.assertLessEqual(w, 192)
            self.assertLessEqual(h, 48)
            self.assertGreaterEqual(w, 1)
            self.assertGreaterEqual(h, 1)

    def test_degenerate_dimensions(self) -> None:
        self.assertEqual(fit_box(0, 0, 192, 48), (48, 48))


class TestThumbnailWidthCap(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="funes-thumb-cap-"))

    def test_wide_thumbnail_is_capped(self) -> None:
        px = 32
        path = thumbnail("wide", PNG_WIDE, px, 1, self._tmp)
        self.assertIsNotNone(path)
        assert path is not None
        size = probe(path.read_bytes())
        self.assertIsNotNone(size)
        assert size is not None
        width, height = size
        self.assertLessEqual(width, px * MAX_ASPECT)
        self.assertLess(height, px)  # shrunk to fit, not cropped

    def test_square_thumbnail_fills_height(self) -> None:
        path = thumbnail("square", PNG_2X2, 32, 1, self._tmp)
        assert path is not None
        self.assertEqual(probe(path.read_bytes()), (32, 32))


class TestMetaLabel(unittest.TestCase):
    def test_full_label(self) -> None:
        label = meta_label("image/png", 1920, 1080, 245760)
        self.assertIn("PNG", label)
        self.assertIn("1920", label)
        self.assertIn("1080", label)
        # GLib.format_size uses kB / MB with locale-dependent separator; just
        # check that a non-empty size string is present.
        self.assertGreater(len(label), 10)

    def test_no_dimensions(self) -> None:
        label = meta_label("image/jpeg", None, None, 1024)
        self.assertIn("JPEG", label)
        self.assertNotIn("×", label)  # noqa: RUF001

    def test_no_mime(self) -> None:
        label = meta_label(None, 100, 100, 512)
        self.assertIn("100", label)

    def test_fallback_when_empty(self) -> None:
        label = meta_label(None, None, None, 0)
        self.assertEqual(label, "Image")

    def test_jpeg_mime_label(self) -> None:
        label = meta_label("image/jpeg", 800, 600, 20000)
        self.assertTrue(label.startswith("JPEG"))

    def test_svg_mime_label_is_short(self) -> None:
        # "image/svg+xml".split("/")[-1].upper() would read "SVG+XML".
        label = meta_label("image/svg+xml", None, None, 512)
        self.assertTrue(label.startswith("SVG"))
        self.assertNotIn("SVG+XML", label)


_SVG_FIXTURE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="32">'
    b'<rect width="64" height="32" fill="red"/></svg>'
)


@unittest.skipUnless(
    probe(_SVG_FIXTURE) is not None,
    "needs the librsvg GdkPixbuf loader (soft dependency, see CLIPBOARD.md)",
)
class TestSvgAsVector(unittest.TestCase):
    """SVG is treated as vector data everywhere except the thumbnail: probe()
    and thumbnail() decode it (when librsvg is installed) purely to render a
    preview, never to replace the stored/pasted bytes \u2014 those stay the
    original verbatim SVG (see app/clipboard.py, funes/item.py VECTOR_MIMES).
    """

    def setUp(self) -> None:
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmp_ctx.name)
        self.addCleanup(self._tmp_ctx.cleanup)

    def test_probe_reads_intrinsic_size(self) -> None:
        self.assertEqual(probe(_SVG_FIXTURE), (64, 32))

    def test_thumbnail_renders_a_raster_preview(self) -> None:
        path = thumbnail("svgfixture", _SVG_FIXTURE, 32, 1, self._tmp)
        assert path is not None
        self.assertTrue(path.exists())
        # The preview is a raster PNG on disk; this in no way implies the
        # *stored* representation was rasterized \u2014 that's a separate,
        # untouched blob (see funes/store.py representations table).
        size = probe(path.read_bytes())
        assert size is not None


if __name__ == "__main__":
    unittest.main()
