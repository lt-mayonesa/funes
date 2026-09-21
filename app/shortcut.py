"""Global-shortcut capture row for Preferences.

xapp ships no keybinding widget, so this is the cinnamon-settings interaction
rebuilt on a plain button: click it, the next key combination is written to
GSettings, Escape cancels, Backspace/Delete clears the shortcut. The daemon
watches the key and (un)registers the Cinnamon keybinding, so a captured combo
is live immediately — no restart, no re-login.

Validation lives in `funes.accel` (GTK-free, unit-tested); this file only
turns key events into accelerator strings and renders the result.
"""

import gi

gi.require_version("Gtk", "3.0")
import xapp.SettingsWidgets as Xs
from gi.repository import Gdk, Gio, Gtk
from xapp.util import l10n

from funes import GETTEXT_DOMAIN
from funes import accel as accel_mod
from funes.config import Config

_ = l10n(GETTEXT_DOMAIN)

# Modifier keyvals never make a shortcut on their own: while one is held the
# widget keeps waiting for the real key.
_MODIFIER_KEYVALS = {
    Gdk.KEY_Shift_L,
    Gdk.KEY_Shift_R,
    Gdk.KEY_Control_L,
    Gdk.KEY_Control_R,
    Gdk.KEY_Alt_L,
    Gdk.KEY_Alt_R,
    Gdk.KEY_Super_L,
    Gdk.KEY_Super_R,
    Gdk.KEY_Meta_L,
    Gdk.KEY_Meta_R,
    Gdk.KEY_Hyper_L,
    Gdk.KEY_Hyper_R,
    Gdk.KEY_ISO_Level3_Shift,
    Gdk.KEY_Caps_Lock,
    Gdk.KEY_Num_Lock,
}


class ShortcutWidget(Xs.SettingsWidget):  # type: ignore[misc]  # xapp is untyped
    """Label + capture button + reset, bound to the ``hotkey`` GSettings key."""

    def __init__(self, config: Config, tooltip: str = "") -> None:
        super().__init__()
        self._config = config
        self._capturing = False
        self._message = ""

        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(4)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.pack_start(row, False, False, 0)

        self.label = Xs.SettingsLabel(_("Global shortcut"))
        row.pack_start(self.label, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_end(controls, False, False, 0)

        self.content_widget = Gtk.Button(valign=Gtk.Align.CENTER)
        self.content_widget.set_tooltip_text(
            tooltip or _("Click, then press the key combination that opens Funes.")
        )
        self.content_widget.connect("clicked", self._on_clicked)
        controls.pack_start(self.content_widget, False, False, 0)

        self._reset = Gtk.Button(valign=Gtk.Align.CENTER)
        self._reset.set_image(Gtk.Image.new_from_icon_name("edit-undo-symbolic", Gtk.IconSize.MENU))
        self._reset.set_relief(Gtk.ReliefStyle.NONE)
        self._reset.set_tooltip_text(_("Reset to the default shortcut (Super+V)"))
        self._reset.connect("clicked", self._on_reset_clicked)
        controls.pack_start(self._reset, False, False, 0)

        self._note = Gtk.Label(xalign=0.0)
        self._note.set_line_wrap(True)
        self._note.get_style_context().add_class("dim-label")
        self.pack_start(self._note, False, False, 0)

        self.content_widget.connect("key-press-event", self._on_key_press)
        self._handler = config.settings.connect("changed::hotkey", lambda *_a: self._refresh())
        self.connect("destroy", self._on_destroy)

        self._refresh()

    # --- rendering ---

    def _refresh(self) -> None:
        accel = accel_mod.normalize(self._config.hotkey)
        if self._capturing:
            self.content_widget.set_label(_("Press a key combination…"))
        else:
            self.content_widget.set_label(accel_mod.label(accel) or _("Disabled"))
        self._reset.set_sensitive(accel != accel_mod.DEFAULT)

        note = self._message or accel_mod.warning_for(accel)
        if self._capturing:
            note = _("Esc cancels, Backspace clears the shortcut.")
        elif not accel:
            note = note or _("No global shortcut: open Funes from the tray icon or `funes toggle`.")
        self._note.set_text(note)
        self._note.set_visible(bool(note))

    # --- capture ---

    def _on_clicked(self, _button: Gtk.Button) -> None:
        if self._capturing:
            self._stop_capture()
            return
        self._capturing = True
        self._message = ""
        self._refresh()
        self._grab()

    def _grab(self) -> None:
        window = self.content_widget.get_window()
        seat = self.content_widget.get_display().get_default_seat()
        if window is None or seat is None:
            return
        # Keyboard-only grab: the combo must reach us, not the focused widget
        # or a window-manager binding that already owns it.
        seat.grab(window, Gdk.SeatCapabilities.KEYBOARD, False, None, None, None, None)

    def _ungrab(self) -> None:
        seat = self.content_widget.get_display().get_default_seat()
        if seat is not None:
            seat.ungrab()

    def _stop_capture(self) -> None:
        self._capturing = False
        self._ungrab()
        self._refresh()

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if not self._capturing:
            return False

        keyval = event.keyval
        if keyval in _MODIFIER_KEYVALS:
            return True

        mods = event.state & Gtk.accelerator_get_default_mod_mask()

        if keyval == Gdk.KEY_Escape and not mods:
            self._message = ""
            self._stop_capture()
            return True

        if keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete) and not mods:
            self._message = ""
            self._config.hotkey = ""
            self._stop_capture()
            return True

        accel = Gtk.accelerator_name(keyval, mods)
        if not accel_mod.is_valid(accel):
            self._message = _("%s cannot be used on its own.") % (
                accel_mod.label(accel) or accel or "?"
            )
            self._stop_capture()
            return True

        self._message = ""
        self._config.hotkey = accel
        self._stop_capture()
        return True

    def _on_reset_clicked(self, _button: Gtk.Button) -> None:
        self._message = ""
        self._config.hotkey = accel_mod.DEFAULT

    def _on_destroy(self, *_args: object) -> None:
        if self._capturing:
            self._ungrab()
        settings: Gio.Settings = self._config.settings
        if self._handler:
            settings.disconnect(self._handler)
            self._handler = 0
