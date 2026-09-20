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

from images import meta_label, probe, thumbnail

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


if __name__ == "__main__":
    unittest.main()
