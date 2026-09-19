"""Clipboard watcher.

Uses Gtk.Clipboard's owner-change signal, which on X11 is driven by the XFixes
extension: no polling (unlike Maccy's 500ms NSPasteboard timer).

Two subtleties handled here:
  1. Self-ignore guard. Funes writes to the clipboard itself (on paste and when
     re-owning), which triggers owner-change again. Without the guard that is
     an infinite loop.
  2. Re-owning. On X11 clipboard contents die with the owning client, so Funes
     takes ownership of the text after capture; copied text then survives the
     source application exiting (Klipper/GPaste behaviour).
"""

import re
from typing import ClassVar

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk

from funes import filters
from funes.config import Config

# GLib.debug() exists at runtime but is missing from pygobject-stubs.
_debug = GLib.debug  # type: ignore[attr-defined]


class ClipboardMonitor(GObject.Object):
    __gsignals__: ClassVar[dict[str, tuple[object, ...]]] = {
        "captured": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self._self_owned = False
        self._last_seen = ""
        self._clipboard.connect("owner-change", self._on_owner_change)

    def start(self) -> None:
        # Pick up whatever is already on the clipboard at startup.
        self._on_owner_change(self._clipboard, None)

    def set_text(self, text: str, also_primary: bool = False) -> None:
        """Put text on the clipboard without recording it again.

        `also_primary` additionally sets the PRIMARY selection, which matters
        for xterm/urxvt: their Shift+Insert pastes PRIMARY, not CLIPBOARD.
        """
        self._self_owned = True
        self._last_seen = text
        self._clipboard.set_text(text, -1)
        self._clipboard.store()
        if also_primary:
            Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY).set_text(text, -1)

    def _on_owner_change(self, _clipboard: Gtk.Clipboard, _event: Gdk.Event | None) -> None:
        if self._self_owned:
            self._self_owned = False
            return
        if self._config.ignore_enabled:
            return
        self._clipboard.request_targets(self._on_targets)

    def _on_targets(
        self, clipboard: Gtk.Clipboard, atoms: list[Gdk.Atom] | None, _data: object = None
    ) -> None:
        names = [atom.name() for atom in atoms] if atoms else []
        if filters.is_secret(names):
            _debug("funes: skipping clipboard entry marked as secret")
            return
        clipboard.request_text(self._on_text)

    def _on_text(self, _clipboard: Gtk.Clipboard, text: str | None, _data: object = None) -> None:
        self._handle_text(text)

    def _handle_text(self, text: str | None) -> None:
        if text is None or filters.is_blank(text):
            return
        if filters.is_too_big(text, self._config.max_item_bytes):
            _debug("funes: skipping oversized clipboard entry")
            return
        if text == self._last_seen:
            return

        def complain(pattern: str, error: re.error) -> None:
            print(f"funes: bad ignore regex /{pattern}/: {error}")

        matched = filters.matching_ignore_regex(
            text, self._config.ignore_regexes, on_bad_pattern=complain
        )
        if matched is not None:
            _debug(f"funes: ignoring entry matching /{matched}/")
            return

        self._last_seen = text
        self.emit("captured", text)

        if self._config.reown_clipboard:
            # Take ownership so the text outlives the source application.
            self._self_owned = True
            self._clipboard.set_text(text, -1)
