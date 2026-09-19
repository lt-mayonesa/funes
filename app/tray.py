"""Tray icon.

XAppStatusIcon talks to the Cinnamon applet over DBus and falls back to
Gtk.StatusIcon when no XApp-aware applet is present.

Left click opens the history popup, right click the actions menu. Note that
XAppStatusIcon only emits ::activate when no *primary* menu is set, so the menu
is registered as the secondary (right button) menu only.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("XApp", "1.0")
from gi.repository import GObject, Gtk, XApp
from xapp.util import l10n

from funes import APP_NAME, GETTEXT_DOMAIN

_ = l10n(GETTEXT_DOMAIN)


class Tray(GObject.Object):
    __gsignals__ = {
        "open-requested": (GObject.SignalFlags.RUN_LAST, None, ()),
        "settings-requested": (GObject.SignalFlags.RUN_LAST, None, ()),
        "clear-requested": (GObject.SignalFlags.RUN_LAST, None, ()),
        "quit-requested": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self._icon = XApp.StatusIcon()
        self._icon.set_name(APP_NAME)
        self._icon.set_icon_name("edit-paste")
        self._icon.set_tooltip_text(_("Funes — clipboard history"))

        self._menu = self._build_menu()
        self._icon.set_primary_menu(None)
        self._icon.set_secondary_menu(self._menu)
        self._icon.connect("activate", lambda *_args: self.emit("open-requested"))

    def _build_menu(self):
        menu = Gtk.Menu()

        open_item = Gtk.MenuItem.new_with_label(_("Open Funes"))
        open_item.connect("activate", lambda *_a: self.emit("open-requested"))
        menu.append(open_item)

        menu.append(Gtk.SeparatorMenuItem())

        clear_item = Gtk.MenuItem.new_with_label(_("Clear History"))
        clear_item.connect("activate", lambda *_a: self.emit("clear-requested"))
        menu.append(clear_item)

        prefs_item = Gtk.MenuItem.new_with_label(_("Settings…"))
        prefs_item.connect("activate", lambda *_a: self.emit("settings-requested"))
        menu.append(prefs_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem.new_with_label(_("Quit"))
        quit_item.connect("activate", lambda *_a: self.emit("quit-requested"))
        menu.append(quit_item)

        menu.show_all()
        return menu

    def set_count(self, count):
        if count == 1:
            self._icon.set_tooltip_text(_("Funes — 1 item"))
        else:
            self._icon.set_tooltip_text(_("Funes — %d items") % count)
