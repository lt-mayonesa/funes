"""Preferences window, built with xapp's GSettings-bound widgets."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("XApp", "1.0")
from gi.repository import Gtk
import xapp.GSettingsWidgets as Gs
import xapp.SettingsWidgets as Xs
from xapp.util import l10n

from funes import GETTEXT_DOMAIN, SETTINGS_SCHEMA
from funes import autostart, hotkey
from funes.paster import Paster, on_wayland

_ = l10n(GETTEXT_DOMAIN)


class PreferencesWindow(Gtk.Window):
    def __init__(self, config):
        super().__init__(title=_("Funes Settings"))
        self._config = config
        self.set_default_size(560, -1)
        self.set_resizable(False)
        self.set_icon_name("edit-paste")

        header = Gtk.HeaderBar(show_close_button=True, title=_("Funes Settings"))
        self.set_titlebar(header)

        page = Xs.SettingsPage()
        page.set_margin_top(12)
        page.set_margin_bottom(12)
        page.set_margin_start(12)
        page.set_margin_end(12)
        self.add(page)

        self._build_history_section(page)
        self._build_paste_section(page)
        self._build_capture_section(page)

        self.show_all()

    # --- sections ---

    def _build_history_section(self, page):
        section = page.add_section(_("History"))

        section.add_row(Gs.GSettingsSpinButton(
            _("History size"), SETTINGS_SCHEMA, "history-size",
            mini=10, maxi=10000, step=10,
            tooltip=_("Oldest unpinned items are dropped past this count.")))

        hotkey_entry = Gs.GSettingsEntry(
            _("Global shortcut"), SETTINGS_SCHEMA, "hotkey",
            tooltip=_("GTK accelerator syntax, e.g. <Super>v or <Shift><Super>c. "
                      "Registered as a Cinnamon custom keybinding."))
        section.add_row(hotkey_entry)
        self._config.settings.connect("changed::hotkey", self._on_hotkey_changed)

        autostart_switch = Gs.GSettingsSwitch(
            _("Launch at login"), SETTINGS_SCHEMA, "launch-at-login")
        section.add_row(autostart_switch)
        self._config.settings.connect("changed::launch-at-login",
                                      self._on_autostart_changed)

    def _build_paste_section(self, page):
        section = page.add_section(_("Pasting"))

        paster = Paster()
        can_paste = paster.available() and not on_wayland()
        if can_paste:
            paste_hint = _("Injects Shift+Insert into the previously focused "
                           "window.")
        elif on_wayland():
            paste_hint = _("Unavailable: keystroke injection needs an X11 "
                           "session.")
        else:
            paste_hint = _("Unavailable: the X server has no XTEST extension.")

        paste_switch = Gs.GSettingsSwitch(
            _("Paste on select"), SETTINGS_SCHEMA, "paste-on-select",
            tooltip=paste_hint)
        paste_switch.set_sensitive(can_paste)
        section.add_row(paste_switch)
        section.add_note(paste_hint)

        section.add_row(Gs.GSettingsEntry(
            _("Paste with Ctrl+V in"), SETTINGS_SCHEMA,
            "paste-ctrl-v-class-regex",
            tooltip=_("Regex on WM_CLASS (\"res_name.res_class\"). Matching "
                      "windows get Ctrl+V instead of Shift+Insert, "
                      "e.g. Chromium|code")))

        section.add_row(Gs.GSettingsSwitch(
            _("Set PRIMARY on paste"), SETTINGS_SCHEMA, "paste-sets-primary",
            tooltip=_("Needed by xterm/urxvt, whose Shift+Insert pastes the "
                      "mouse selection. Replaces your current selection.")))

    def _build_capture_section(self, page):
        section = page.add_section(_("Capturing"))

        section.add_row(Gs.GSettingsSwitch(
            _("Keep clipboard alive"), SETTINGS_SCHEMA, "reown-clipboard",
            tooltip=_("Funes takes clipboard ownership so copied text survives "
                      "the source app closing.")))

        section.add_row(Gs.GSettingsSwitch(
            _("Pause capturing"), SETTINGS_SCHEMA, "ignore-enabled",
            tooltip=_("Clipboard changes are not recorded while on.")))

        ignore_entry = Xs.Entry(
            _("Ignore matching"), expand_width=True,
            tooltip=_("Pipe-separated regexes. Password-manager hints are "
                      "always ignored."))
        ignore_entry.content_widget.set_text(" | ".join(self._config.ignore_regexes))
        ignore_entry.content_widget.set_placeholder_text(_("regex | regex"))
        ignore_entry.content_widget.connect("activate", self._apply_ignores)
        ignore_entry.content_widget.connect("focus-out-event", self._apply_ignores)
        section.add_row(ignore_entry)

    # --- handlers ---

    def _on_hotkey_changed(self, settings, _key):
        accel = settings.get_string("hotkey").strip()
        if not accel:
            return
        key, _mods = Gtk.accelerator_parse(accel)
        if key == 0:
            return
        hotkey.ensure(accel)

    def _on_autostart_changed(self, settings, _key):
        autostart.set_enabled(settings.get_boolean("launch-at-login"))

    def _apply_ignores(self, entry, *_args):
        cleaned = [part.strip() for part in entry.get_text().split("|")
                   if part.strip()]
        self._config.ignore_regexes = cleaned
        return False
