"""Tests for the focusable (no-seat-grab) popup: click activation, focus loss.

Two things used to close the popup on any click inside it: rows activated on a
single click (copy + hide), and "hide on focus loss" wired to focus-out-event,
which window managers also emit during move/resize grabs. Rows now honour
`popup-single-click-activates` (default off) and closing watches the toplevel's
"is-active" property; these tests pin that down.

This is the Wayland fallback path since the selection fix: on X11 the popup
refuses focus and closes on grab events instead (tests/test_popup_grab.py), so
`grabs_supported()` is forced off here.

Note: focus loss closes the popup, and Gtk.main_iteration_do() may deliver a
real deactivation while these tests pump events.

The seat grab is faked so the suite never grabs the keyboard of the machine
running it.

Requires a display: skipped when DISPLAY/WAYLAND_DISPLAY are unset (headless
CI without Xvfb).

The GSettings schema is compiled from the source tree so the tests read the
keys in this checkout, not whatever version is installed.
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
class PopupFocusTests(unittest.TestCase):
    def setUp(self) -> None:
        from funes.config import Config
        from funes.item import Capture
        from funes.store import HistoryStore

        import popup as popup_module
        from popup import PopupWindow

        self._module = popup_module
        self._supported = popup_module._supports_grabs
        popup_module._supports_grabs = lambda: False

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._store = HistoryStore(
            str(root / "history.db"),
            blob_root=root / "blobs",
            thumb_root=root / "thumbs",
        )
        self._store.add(Capture.from_text("hello"))
        self._store.add(Capture.from_text("world"))
        self._popup = PopupWindow(
            self._store, Config(), thumb_root=root / "thumbs", grab=FakeGrab()
        )
        self._popup.show_popup()
        self._pump()
        # Pretend the WM activated us, as it does for a real popup.
        self._popup._focus_armed = True

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

    def test_child_focus_change_does_not_arm_close(self) -> None:
        """Focus moving between widgets inside the popup must not schedule a hide."""
        from gi.repository import Gdk

        for widget in (self._popup._search, self._popup._list):
            widget.emit("focus-out-event", Gdk.Event.new(Gdk.EventType.FOCUS_CHANGE))
            self._pump()
            self.assertEqual(
                self._popup._focus_out_source,
                0,
                "child focus-out must not schedule the close timer",
            )
            self.assertTrue(self._popup.get_visible())

    def test_deactivation_schedules_close(self) -> None:
        """Losing toplevel activation arms the debounced close."""
        self._popup._on_active_changed()
        self.assertNotEqual(self._popup._focus_out_source, 0)

    def test_reactivation_cancels_pending_close(self) -> None:
        self._popup._on_active_changed()
        self.assertNotEqual(self._popup._focus_out_source, 0)
        # is_active() is false in this headless fixture, so drive the armed
        # branch directly: a real re-activation cancels the timer.
        self._popup._cancel_focus_out_timer()
        self.assertEqual(self._popup._focus_out_source, 0)
        self.assertTrue(self._popup.get_visible())

    def test_rows_need_a_double_click_by_default(self) -> None:
        self.assertFalse(self._popup._config.popup_single_click_activates)
        self.assertFalse(self._popup._list.get_activate_on_single_click())

    def test_single_click_setting_is_live(self) -> None:
        config = self._popup._config
        try:
            config.popup_single_click_activates = True
            self._pump()
            self.assertTrue(self._popup._list.get_activate_on_single_click())
        finally:
            config.settings.reset("popup-single-click-activates")
            self._pump()
        self.assertFalse(self._popup._list.get_activate_on_single_click())

    def test_selecting_a_row_keeps_the_popup_open_and_typing_in_search(self) -> None:
        row = self._popup._list.get_row_at_index(0)
        self.assertIsNotNone(row)
        self._popup._list.select_row(row)
        self._pump()
        self.assertTrue(self._popup.get_visible())
        self.assertIs(self._popup.get_focus(), self._popup._search)

    def test_close_timer_hides_only_when_inactive(self) -> None:
        self._popup._focus_out_source = 1
        self._popup._focus_out_elapsed()
        self.assertEqual(self._popup._focus_out_source, 0)
        self.assertFalse(self._popup.is_active())
        self.assertFalse(self._popup.get_visible())


if __name__ == "__main__":
    unittest.main()
