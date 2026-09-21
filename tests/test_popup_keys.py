"""Tests for popup key handling that leaves the popup: Ctrl+, opens Preferences.

The popup must hide before the request reaches the application, otherwise the
Preferences window maps behind a keep-above popup that then closes itself on
deactivation.

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
from typing import Any, cast

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

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        _HAS_DISPLAY = bool(Gtk.init_check()[0])
    except (ImportError, ValueError):
        _HAS_DISPLAY = False


@unittest.skipUnless(_HAS_DISPLAY, "needs a display (DISPLAY or WAYLAND_DISPLAY)")
@unittest.skipUnless(_HAS_SCHEMA, "needs glib-compile-schemas for the source schema")
class PopupSettingsKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        from funes.config import Config
        from funes.item import Capture
        from funes.store import HistoryStore

        from popup import PopupWindow

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._store = HistoryStore(
            str(root / "history.db"),
            blob_root=root / "blobs",
            thumb_root=root / "thumbs",
        )
        self._store.add(Capture.from_text("hello"))
        self._popup = PopupWindow(self._store, Config(), thumb_root=root / "thumbs")
        self._popup.show_popup()
        self._pump()

    def tearDown(self) -> None:
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

    def _press(self, keyval: int, *, ctrl: bool = False) -> bool:
        from gi.repository import Gdk

        # PyGObject exposes the GdkEventKey union fields on the boxed Gdk.Event.
        event = cast(Any, Gdk.Event.new(Gdk.EventType.KEY_PRESS))
        event.keyval = keyval
        event.state = Gdk.ModifierType.CONTROL_MASK if ctrl else Gdk.ModifierType(0)
        return bool(self._popup._on_key_press(self._popup, event))

    def test_ctrl_comma_requests_settings_and_hides(self) -> None:
        from gi.repository import Gdk

        seen: list[bool] = []
        # Record visibility at emit time: the popup must already be hidden.
        self._popup.connect(
            "settings-requested", lambda *_a: seen.append(self._popup.get_visible())
        )
        self.assertTrue(self._press(Gdk.KEY_comma, ctrl=True))
        self._pump()
        self.assertEqual(seen, [False])
        self.assertFalse(self._popup.get_visible())

    def test_plain_comma_types_into_the_filter(self) -> None:
        from gi.repository import Gdk

        seen: list[object] = []
        self._popup.connect("settings-requested", lambda *_a: seen.append(None))
        self.assertFalse(self._press(Gdk.KEY_comma))
        self._pump()
        self.assertEqual(seen, [])
        self.assertTrue(self._popup.get_visible())


if __name__ == "__main__":
    unittest.main()
