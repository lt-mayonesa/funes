"""Tests for the focusless popup: seat grab instead of window-manager focus.

Taking the WM focus made apps drop their text selection (Chrome's omnibox,
nemo, xed), so the pasted item was inserted next to the selection instead of
replacing it. The popup now refuses focus and grabs the seat; these tests pin
down that it refuses focus, that a failed grab means "not shown" rather than a
dead window, and that the grab (not deactivation) drives closing.

The grab itself is faked — a real seat grab in a test would freeze the machine
running it.

Requires a display: skipped when DISPLAY/WAYLAND_DISPLAY are unset (headless
CI without Xvfb). The GSettings schema is compiled from the source tree so the
tests read the keys in this checkout, not whatever version is installed.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeGrab  # noqa: E402


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

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        _HAS_DISPLAY = bool(Gtk.init_check()[0])
    except (ImportError, ValueError):
        _HAS_DISPLAY = False


@unittest.skipUnless(_HAS_DISPLAY, "needs a display (DISPLAY or WAYLAND_DISPLAY)")
@unittest.skipUnless(_HAS_SCHEMA, "needs glib-compile-schemas for the source schema")
class PopupGrabTests(unittest.TestCase):
    def setUp(self) -> None:
        from funes.config import Config
        from funes.item import Capture
        from funes.store import HistoryStore

        import popup as popup_module

        self._module = popup_module
        self._supported = popup_module._supports_grabs
        # Pretend X11 even when the suite runs on Wayland: the focusless path
        # is what these tests are about.
        popup_module._supports_grabs = lambda: True

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._store = HistoryStore(
            str(root / "history.db"),
            blob_root=root / "blobs",
            thumb_root=root / "thumbs",
        )
        self._store.add(Capture.from_text("hello"))
        self._store.add(Capture.from_text("world"))
        self._grab = FakeGrab()
        self._popup = popup_module.PopupWindow(
            self._store, Config(), thumb_root=root / "thumbs", grab=self._grab
        )

    def tearDown(self) -> None:
        self._module._supports_grabs = self._supported
        self._popup.destroy()
        self._store.close()
        self._tmp.cleanup()
        self._pump()

    def _pump(self) -> None:
        from gi.repository import Gtk

        for _ in range(50):
            if not Gtk.events_pending():
                break
            Gtk.main_iteration_do(False)

    def test_popup_refuses_the_window_manager_focus(self) -> None:
        self.assertTrue(self._popup.show_popup())
        self._pump()
        self.assertFalse(self._popup.get_accept_focus())
        self.assertFalse(self._popup.get_focus_on_map())
        self.assertEqual(self._grab.acquired, 1)
        self.assertTrue(self._grab.active)

    def test_search_entry_is_typable_without_real_focus(self) -> None:
        """The faked toplevel focus-in is what gives the entry a caret and IM."""
        self._popup.show_popup()
        self._pump()
        self.assertTrue(self._popup._search.has_focus())

    def test_failed_grab_keeps_the_popup_hidden(self) -> None:
        self._grab.succeed = False
        self.assertFalse(self._popup.show_popup())
        self._pump()
        self.assertFalse(self._popup.get_visible())

    def test_hide_releases_the_grab(self) -> None:
        self._popup.show_popup()
        self._pump()
        self._popup.hide_popup()
        self._pump()
        self.assertEqual(self._grab.released, 1)
        self.assertFalse(self._popup.get_visible())

    def test_click_inside_keeps_the_popup_open(self) -> None:
        from gi.repository import Gdk

        self._popup.show_popup()
        self._pump()
        window = self._popup.get_window()
        assert window is not None
        origin = window.get_origin()
        x, y = origin[1], origin[2]
        event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
        event.button.x_root = x + 5
        event.button.y_root = y + 5
        self.assertFalse(self._popup._on_button_press(self._popup, event.button))
        self.assertTrue(self._popup.get_visible())

    def test_click_outside_closes_the_popup(self) -> None:
        from gi.repository import Gdk

        self._popup.show_popup()
        self._pump()
        window = self._popup.get_window()
        assert window is not None
        origin = window.get_origin()
        width, height = self._popup.get_size()
        event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
        event.button.x_root = origin[1] + width + 50
        event.button.y_root = origin[2] + height + 50
        self.assertTrue(self._popup._on_button_press(self._popup, event.button))
        self._pump()
        self.assertFalse(self._popup.get_visible())
        self.assertFalse(self._grab.active)

    def test_broken_grab_closes_the_popup(self) -> None:
        from gi.repository import Gdk

        self._popup.show_popup()
        self._pump()
        broken = Gdk.Event.new(Gdk.EventType.GRAB_BROKEN)
        self._popup._on_grab_broken(self._popup, broken.grab_broken)
        self._pump()
        self.assertFalse(self._popup.get_visible())
        self.assertFalse(self._grab.active)

    def test_faked_focus_events_do_not_arm_the_deactivation_close(self) -> None:
        """Focusless popups close on the grab, never on `is-active` changes."""
        self._popup.show_popup()
        self._pump()
        self._popup._on_active_changed()
        self.assertEqual(self._popup._focus_out_source, 0)
        self.assertTrue(self._popup.get_visible())

    def test_without_grab_support_the_popup_stays_focusable(self) -> None:
        """Wayland: no seat grab, so the old focusable popup is kept."""
        self._module._supports_grabs = lambda: False
        self.assertTrue(self._popup.show_popup())
        self._pump()
        self.assertTrue(self._popup.get_accept_focus())
        self.assertEqual(self._grab.acquired, 0)


if __name__ == "__main__":
    unittest.main()
