"""Regression tests for verbatim multi-format clipboard replay.

Gtk.Clipboard.set_with_data() cannot be called from PyGObject — GObject
Introspection cannot bind its raw TargetEntry-array + callback signature, so
PyGObject marks it ``_unsupported_data_method`` and any call to it raises
AttributeError. Both the "select an item in the popup and paste" path
(``ClipboardMonitor._set_image_item``) and the "re-own after capture" path
used to call it directly, silently swallow the AttributeError, and fall back
to a single rasterized PNG — which is why a multi-format copy (e.g. an
Inkscape ``image/svg+xml`` copy) came back as a raster image once routed
through Funes. These tests exercise the real Gtk.Clipboard machinery (via
``Gtk.selection_add_target``/``Gtk.selection_owner_set``) to pin down that
every representation actually round-trips byte-for-byte.

Requires a display: skipped when DISPLAY/WAYLAND_DISPLAY are unset (headless
CI without Xvfb). The GSettings schema is compiled from the source tree so
Config() reads the keys in this checkout, not whatever version is installed.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "app"))


def _use_source_schema() -> bool:
    """Point GSettings at data/ compiled into a temp dir. Must precede any Gio use."""
    compiler = shutil.which("glib-compile-schemas")
    if compiler is None:
        return False
    target = tempfile.mkdtemp(prefix="funes-schemas-")
    result = subprocess.run(  # fixed argv, compiler path resolved by shutil.which
        [compiler, "--targetdir", target, str(_ROOT / "data")],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    existing = os.environ.get("GSETTINGS_SCHEMA_DIR")
    os.environ["GSETTINGS_SCHEMA_DIR"] = f"{target}{os.pathsep}{existing}" if existing else target
    return True


_HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
_HAS_SCHEMA = _HAS_DISPLAY and _use_source_schema()

if _HAS_DISPLAY:
    try:
        import gi

        gi.require_version("Gdk", "3.0")
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, GLib, Gtk

        _HAS_DISPLAY = bool(Gtk.init_check()[0])
    except (ImportError, ValueError):
        _HAS_DISPLAY = False


class _Timeout:
    """Sentinel distinguishing 'round-trip never completed' from a real
    (possibly empty/None) clipboard reply."""

    def __repr__(self) -> str:
        return "<clipboard round-trip timed out>"


_TIMED_OUT = _Timeout()


def _request_contents_sync(
    clipboard: "Gtk.Clipboard", mime: str, timeout_ms: int = 3000
) -> bytes | None | _Timeout:
    """Request *mime* from *clipboard* and pump the main loop for a reply.

    Uses a bounded, non-blocking pump (``iteration(False)``) so a stuck
    intra-process selection round-trip (observed in bare-Xvfb sandboxes with
    no window manager) reliably times out instead of hanging the test suite.
    Returns ``_TIMED_OUT`` rather than raising so callers can decide whether
    that's a real failure or an environment limitation to skip on.
    """
    result: dict[str, bytes | None] = {}

    def on_contents(
        _clipboard: "Gtk.Clipboard", sel: "Gtk.SelectionData", _data: object = None
    ) -> None:
        data = sel.get_data() if sel is not None else None
        result["data"] = bytes(data) if data else None

    clipboard.request_contents(Gdk.Atom.intern(mime, False), on_contents)

    context = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + timeout_ms * 1000
    while "data" not in result:
        if GLib.get_monotonic_time() >= deadline:
            return _TIMED_OUT
        context.iteration(False)
    return result["data"]


@unittest.skipUnless(_HAS_DISPLAY, "needs a display (DISPLAY or WAYLAND_DISPLAY)")
@unittest.skipUnless(_HAS_SCHEMA, "needs glib-compile-schemas for the source schema")
class VerbatimReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        from funes.config import Config

        from clipboard import ClipboardMonitor

        self._monitor = ClipboardMonitor(Config())
        self._clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

    def test_own_clipboard_verbatim_serves_every_mime_byte_for_byte(self) -> None:
        reps = {
            "image/svg+xml": b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
            "image/png": b"\x89PNG\r\n\x1a\nnot-a-real-png-but-thats-fine",
        }

        took_ownership = self._monitor._own_clipboard_verbatim(reps.keys(), reps.get)
        self.assertTrue(took_ownership)

        for mime, expected in reps.items():
            with self.subTest(mime=mime):
                actual = _request_contents_sync(self._clipboard, mime)
                if actual is _TIMED_OUT:
                    self.skipTest(
                        "clipboard round-trip did not complete in time "
                        "(likely no window manager in this sandbox)"
                    )
                self.assertEqual(actual, expected)

    def test_set_image_item_replays_a_non_canonical_representation(self) -> None:
        """The exact shape of the reported bug: selecting a multi-format image
        item (SVG + PNG reps, PNG canonical) from the popup and pasting must
        still hand back the *original* SVG bytes to whatever requests them —
        not a rasterized copy of the canonical PNG rep.
        """
        from funes.item import Capture
        from funes.store import HistoryStore

        svg_bytes = b"<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>"
        png_bytes = b"\x89PNG\r\n\x1a\nnot-a-real-png-but-thats-fine"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = HistoryStore(
                str(root / "history.db"),
                blob_root=root / "blobs",
                thumb_root=root / "thumbs",
            )
            capture = Capture(
                kind="image",
                canonical_mime="image/png",  # PNG picked as canonical, like Inkscape copies today
                reps={"image/svg+xml": svg_bytes, "image/png": png_bytes},
            )
            item = store.add(capture)
            assert item is not None

            self._monitor._blob_store = store.blob_store  # type: ignore[attr-defined]
            self._monitor.set_item(item)

            svg_reply = _request_contents_sync(self._clipboard, "image/svg+xml")
            png_reply = _request_contents_sync(self._clipboard, "image/png")
            if svg_reply is _TIMED_OUT or png_reply is _TIMED_OUT:
                self.skipTest(
                    "clipboard round-trip did not complete in time "
                    "(likely no window manager in this sandbox)"
                )
            self.assertEqual(svg_reply, svg_bytes)
            self.assertEqual(png_reply, png_bytes)


if __name__ == "__main__":
    unittest.main()
