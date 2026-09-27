"""The Preferences size-cap row shows MiB but stores bytes.

Checked against an in-memory GSettings backend. Requires a display: skipped
when DISPLAY/WAYLAND_DISPLAY are unset.
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
        from gi.repository import Gtk

        _HAS_DISPLAY = bool(Gtk.init_check()[0])
    except (ImportError, ValueError):
        _HAS_DISPLAY = False


@unittest.skipUnless(_HAS_DISPLAY, "needs a display (DISPLAY or WAYLAND_DISPLAY)")
@unittest.skipUnless(_HAS_SCHEMA, "needs glib-compile-schemas for the source schema")
class MibSpinRowTests(unittest.TestCase):
    def setUp(self) -> None:
        from gi.repository import Gio

        from funes import SETTINGS_SCHEMA
        from funes.config import Config

        from preferences import MibSpinRow

        source = Gio.SettingsSchemaSource.get_default()
        assert source is not None
        schema = source.lookup(SETTINGS_SCHEMA, True)
        assert schema is not None
        self.config = Config.__new__(Config)  # bypass Gio.Settings.new(schema)
        self.config.settings = Gio.Settings.new_full(
            schema, Gio.memory_settings_backend_new(), None
        )
        self.row: Any = MibSpinRow(self.config, "max-image-bytes", "Max size")
        self.addCleanup(self.row.destroy)

    def test_default_shows_ten_mib(self) -> None:
        self.assertEqual(self.row.spin.get_value_as_int(), 10)

    def test_editing_writes_bytes(self) -> None:
        self.row.spin.set_value(25)
        self.assertEqual(self.config.max_image_bytes, 25 * 1024 * 1024)

    def test_external_change_updates_spin(self) -> None:
        self.config.max_image_bytes = 64 * 1024 * 1024
        self.assertEqual(self.row.spin.get_value_as_int(), 64)

    def test_range_follows_schema(self) -> None:
        low, high = self.row.spin.get_range()
        self.assertEqual((low, high), (1, 1024))


if __name__ == "__main__":
    unittest.main()
