"""Regression coverage for PopupWindow._selected_row() missing a row class.

Every row class the popup can render (TextRow, ImageRow, OtherRow,
FileRow) must be recognized by _selected_row() --
anything missed makes that kind's rows silently un-activatable:
Enter/click-to-paste, Delete-to-remove, and Ctrl+P-to-pin all route through
_selected_row() and treat None as "nothing selected", so they quietly no-op
instead of erroring. This is exactly what happened when OtherRow (and
later FileRow) were added: the _selected_row() type hint was updated but
the isinstance() check wasn't.

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

        gi.require_version("Gdk", "3.0")
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk

        _HAS_DISPLAY = bool(Gtk.init_check()[0])
    except (ImportError, ValueError):
        _HAS_DISPLAY = False


@unittest.skipUnless(_HAS_DISPLAY, "needs a display (DISPLAY or WAYLAND_DISPLAY)")
@unittest.skipUnless(_HAS_SCHEMA, "needs glib-compile-schemas for the source schema")
class PopupRowSelectionTests(unittest.TestCase):
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
        # One item of every kind the popup can render a dedicated row for.
        self._store.add(Capture.from_text("plain text item"))
        self._store.add(
            Capture(
                kind="image",
                canonical_mime="image/png",
                reps={"image/png": b"\x89PNG\r\n\x1a\nfake-but-fine-for-this-test"},
            )
        )
        self._store.add(
            Capture(
                kind="other",
                canonical_mime="application/x-unknown",
                reps={"application/x-unknown": b"opaque-bytes"},
            )
        )
        self._store.add(
            Capture(
                kind="files",
                canonical_mime="text/uri-list",
                reps={"text/uri-list": b"file:///tmp/report.pdf\r\n"},
                text="report.pdf",
                operation="copy",
            )
        )
        self._popup = PopupWindow(self._store, Config(), thumb_root=root / "thumbs")
        self._popup.show_popup()
        self._pump()
        self._popup._focus_armed = True

    def tearDown(self) -> None:
        self._popup.destroy()
        self._store.close()
        self._tmp.cleanup()
        self._pump()

    def _pump(self) -> None:
        for _ in range(50):
            if not Gtk.events_pending():
                break
            Gtk.main_iteration_do(False)

    def _select_row_for_item_kind(self, kind: str) -> None:
        for item in self._store.items():
            if item.kind == kind:
                for index in range(len(self._store.items())):
                    row = self._popup._list.get_row_at_index(index)
                    if row is not None and getattr(row, "item", None) is item:
                        self._popup._list.select_row(row)
                        self._pump()
                        return
        self.fail(f"no {kind!r} item/row found")

    def test_every_row_kind_is_recognized_by_selected_row(self) -> None:
        from popup import FileRow, ImageRow, OtherRow, TextRow

        expectations = {
            "text": TextRow,
            "image": ImageRow,
            "other": OtherRow,
            "files": FileRow,
        }
        for kind, row_cls in expectations.items():
            with self.subTest(kind=kind):
                self._select_row_for_item_kind(kind)
                selected = self._popup._selected_row()
                self.assertIsNotNone(
                    selected, f"_selected_row() returned None for a selected {kind!r} row"
                )
                assert selected is not None
                self.assertIsInstance(selected, row_cls)
                self.assertEqual(selected.item.kind, kind)

    def test_delete_key_removes_every_kind(self) -> None:
        for kind in ("text", "image", "other", "files"):
            with self.subTest(kind=kind):
                before = self._store.size()
                self._select_row_for_item_kind(kind)
                handled = self._popup._on_key_press(self._popup, _fake_key_event(Gdk.KEY_Delete))
                self._pump()
                self.assertTrue(handled)
                self.assertEqual(self._store.size(), before - 1)
                self.assertFalse(any(item.kind == kind for item in self._store.items()))

    def test_activating_every_kind_emits_item_chosen(self) -> None:
        chosen: list[str] = []
        self._popup.connect("item-chosen", lambda _p, item, _paste: chosen.append(item.kind))

        for kind in ("text", "image", "other", "files"):
            with self.subTest(kind=kind):
                self._select_row_for_item_kind(kind)
                self._popup._activate_selected(paste=False)
                self._pump()

        self.assertEqual(set(chosen), {"text", "image", "other", "files"})


def _fake_key_event(keyval: int) -> Any:
    # PyGObject exposes the GdkEventKey union fields on the boxed Gdk.Event.
    event = cast(Any, Gdk.Event.new(Gdk.EventType.KEY_PRESS))
    event.keyval = keyval
    event.state = Gdk.ModifierType(0)
    return event


if __name__ == "__main__":
    unittest.main()
