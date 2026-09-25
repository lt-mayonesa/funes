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


class _FakeAtom:
    """Duck-typed stand-in for Gdk.Atom \u2014 only .name() is ever called on it."""

    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


class _FakeSelectionData:
    """Duck-typed stand-in for Gtk.SelectionData \u2014 only get_data() and
    get_target() are ever called on it by _capture_reps. get_target()
    reports back the *requested* mime, exactly like the real GTK object
    does even when the request was declined (no data set)."""

    def __init__(self, mime: str, data: bytes | None) -> None:
        self._mime = mime
        self._data = data

    def get_data(self) -> bytes | None:
        return self._data

    def get_target(self) -> _FakeAtom:
        return _FakeAtom(self._mime)


class _StuckMimeClipboard:
    """Fake clipboard: answers every mime except *stuck_mime*, whose
    request_contents() callback is simply never invoked \u2014 simulating a
    source that advertised a target in TARGETS but doesn't actually serve
    it. GTK/X11 give no guarantee request_contents() ever gets a reply at
    all in this case (not just a slow one).
    """

    def __init__(self, reps: dict[str, bytes], stuck_mime: str) -> None:
        self._reps = reps
        self._stuck_mime = stuck_mime

    def request_contents(self, atom: _FakeAtom, callback: object) -> None:
        mime = atom.name()
        if mime == self._stuck_mime:
            return  # never call back, ever
        data = self._reps.get(mime)
        sel = _FakeSelectionData(mime, data)
        GLib.idle_add(lambda: (callback(self, sel), False)[1])  # type: ignore[operator]

    def request_text(self, callback: object) -> None:
        GLib.idle_add(lambda: (callback(self, None), False)[1])  # type: ignore[operator]


@unittest.skipUnless(_HAS_DISPLAY, "needs a display (DISPLAY or WAYLAND_DISPLAY)")
@unittest.skipUnless(_HAS_SCHEMA, "needs glib-compile-schemas for the source schema")
class WatchdogTests(unittest.TestCase):
    """Regression coverage: a target that's advertised but never actually
    answered used to hang the whole capture chain forever — nothing
    captured, no signal emitted, not even for other targets that had
    already succeeded (or would have, had requests still been sequential).
    Reported symptom: copying a local file:// image in a browser (which,
    unlike remote images, seems to also advertise a target the browser
    doesn't reliably serve) registered nothing at all in Funes, while the
    exact same image from a remote URL worked fine.
    """

    def setUp(self) -> None:
        from funes.config import Config

        from clipboard import ClipboardMonitor

        self._monitor = ClipboardMonitor(Config())

    def test_watchdog_finishes_with_reps_captured_before_the_stall(self) -> None:
        png_bytes = b"\x89PNG\r\n\x1a\nnot-a-real-png-but-thats-fine"
        reps = {"image/png": png_bytes}  # "text/uri-list" deliberately absent: it's the stuck one
        fake_clipboard = _StuckMimeClipboard(reps, stuck_mime="text/uri-list")

        captured: list[object] = []
        self._monitor.connect("captured", lambda _m, capture: captured.append(capture))

        self._monitor._capture_reps(
            fake_clipboard,  # type: ignore[arg-type]
            ["image/png", "text/uri-list"],
            kind="image",
            also_request_text=False,
        )

        context = GLib.MainContext.default()
        # Comfortably past the 500ms watchdog; fails fast if it never fires.
        deadline = GLib.get_monotonic_time() + 2000 * 1000
        while not captured and GLib.get_monotonic_time() < deadline:
            context.iteration(False)

        self.assertEqual(len(captured), 1, "watchdog never finished the stalled chain")
        from funes.item import Capture

        capture = captured[0]
        assert isinstance(capture, Capture)
        self.assertEqual(capture.reps, {"image/png": png_bytes})

    def test_stuck_target_order_does_not_matter(self) -> None:
        """Every mime is requested concurrently, not sequentially, so a
        stuck target listed *first* must not block one listed after it from
        still being captured (this used to matter when requests were
        sequential; it must not anymore)."""
        png_bytes = b"\x89PNG\r\n\x1a\nnot-a-real-png-but-thats-fine"
        reps = {"image/png": png_bytes}
        fake_clipboard = _StuckMimeClipboard(reps, stuck_mime="text/uri-list")

        captured: list[object] = []
        self._monitor.connect("captured", lambda _m, capture: captured.append(capture))

        self._monitor._capture_reps(
            fake_clipboard,  # type: ignore[arg-type]
            ["text/uri-list", "image/png"],  # stuck mime listed first this time
            kind="image",
            also_request_text=False,
        )

        context = GLib.MainContext.default()
        deadline = GLib.get_monotonic_time() + 2000 * 1000
        while not captured and GLib.get_monotonic_time() < deadline:
            context.iteration(False)

        self.assertEqual(len(captured), 1, "watchdog never finished the stalled chain")
        from funes.item import Capture

        capture = captured[0]
        assert isinstance(capture, Capture)
        self.assertEqual(capture.reps, {"image/png": png_bytes})


if __name__ == "__main__":
    unittest.main()
