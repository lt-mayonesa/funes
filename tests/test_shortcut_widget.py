"""Capture behaviour of the Preferences shortcut widget.

Key events are synthesized, so no real grab happens; the widget's GSettings
writes are checked against a temporary in-memory backend.

Requires a display: skipped when DISPLAY/WAYLAND_DISPLAY are unset.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

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
        from gi.repository import Gdk, Gtk

        _HAS_DISPLAY = bool(Gtk.init_check()[0])
    except (ImportError, ValueError):
        _HAS_DISPLAY = False


@unittest.skipUnless(_HAS_DISPLAY, "needs a display (DISPLAY or WAYLAND_DISPLAY)")
@unittest.skipUnless(_HAS_SCHEMA, "needs glib-compile-schemas for the source schema")
class ShortcutCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        # A memory backend keeps the session's real settings untouched.
        from gi.repository import Gio

        from funes import SETTINGS_SCHEMA
        from funes.config import Config
        from shortcut import ShortcutWidget

        source = Gio.SettingsSchemaSource.get_default()
        assert source is not None
        schema = source.lookup(SETTINGS_SCHEMA, True)
        assert schema is not None
        settings = Gio.Settings.new_full(schema, Gio.memory_settings_backend_new(), None)

        self.config = Config.__new__(Config)  # bypass Gio.Settings.new(schema)
        self.config.settings = settings
        self.widget: Any = ShortcutWidget(self.config)
        self.addCleanup(self.widget.destroy)

    def _press(self, keyval: int, state: int = 0) -> bool:
        event: Any = Gdk.EventKey.new(Gdk.EventType.KEY_PRESS)
        event.keyval = keyval
        event.state = Gdk.ModifierType(state)
        handled: bool = self.widget._on_key_press(self.widget.content_widget, event)
        return handled

    def _start(self) -> None:
        self.widget._capturing = True
        self.widget._refresh()

    def test_shows_current_shortcut(self) -> None:
        self.config.hotkey = "<Shift><Super>c"
        self.assertEqual(self.widget.content_widget.get_label(), "Shift+Super+C")

    def test_capture_writes_the_combination(self) -> None:
        self._start()
        self.assertTrue(self._press(Gdk.KEY_k, Gdk.ModifierType.SUPER_MASK))
        self.assertEqual(self.config.hotkey, "<Super>k")
        self.assertFalse(self.widget._capturing)

    def test_modifier_keys_do_not_end_capture(self) -> None:
        self.config.hotkey = "<Super>v"
        self._start()
        self.assertTrue(self._press(Gdk.KEY_Super_L))
        self.assertTrue(self.widget._capturing)
        self.assertEqual(self.config.hotkey, "<Super>v")

    def test_escape_cancels(self) -> None:
        self.config.hotkey = "<Super>v"
        self._start()
        self._press(Gdk.KEY_Escape)
        self.assertFalse(self.widget._capturing)
        self.assertEqual(self.config.hotkey, "<Super>v")

    def test_backspace_clears(self) -> None:
        self.config.hotkey = "<Super>v"
        self._start()
        self._press(Gdk.KEY_BackSpace)
        self.assertEqual(self.config.hotkey, "")
        self.assertEqual(self.widget.content_widget.get_label(), "Disabled")

    def test_bare_reserved_key_is_refused(self) -> None:
        self.config.hotkey = "<Super>v"
        self._start()
        self._press(Gdk.KEY_Tab)
        self.assertEqual(self.config.hotkey, "<Super>v")
        self.assertIn("Tab", self.widget._note.get_text())

    def test_modifierless_key_is_accepted_with_a_warning(self) -> None:
        self._start()
        self._press(Gdk.KEY_F5)
        self.assertEqual(self.config.hotkey, "F5")
        self.assertIn("modifier", self.widget._note.get_text())

    def test_reset_restores_the_default(self) -> None:
        self.config.hotkey = "F5"
        self.widget._on_reset_clicked(self.widget._reset)
        self.assertEqual(self.config.hotkey, "<Super>v")

    def test_external_change_updates_the_label(self) -> None:
        self.config.settings.set_string("hotkey", "<Control><Alt>h")
        self.assertEqual(self.widget.content_widget.get_label(), "Ctrl+Alt+H")


if __name__ == "__main__":
    unittest.main()
