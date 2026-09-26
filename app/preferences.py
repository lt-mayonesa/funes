"""Preferences window, built with xapp's GSettings-bound widgets.

The window subclasses ``XApp.PreferencesWindow``, the same base xed uses, so
Funes matches the Mint look: a server-side title bar (no CSD header bar), a
stack with an auto-hiding sidebar, a bottom action bar, Escape to close, and no
window-list entry.
"""

from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("XApp", "1.0")
import xapp.GSettingsWidgets as Gs
import xapp.SettingsWidgets as Xs
from gi.repository import Gdk, Gio, Gtk, XApp
from xapp.util import l10n

from funes import GETTEXT_DOMAIN, HOMEPAGE, SETTINGS_SCHEMA, autostart, monitors
from funes.config import Config
from funes.paster import Paster, on_wayland
from shortcut import ShortcutWidget

_ = l10n(GETTEXT_DOMAIN)


def _monitor_strategy_labels() -> dict[str, str]:
    return {
        monitors.FOCUSED: _("Monitor of the focused window"),
        monitors.POINTER: _("Monitor under the pointer"),
        monitors.PRIMARY: _("Primary monitor"),
    }


class MonitorOrderWidget(Xs.SettingsWidget):  # type: ignore[misc]  # xapp is untyped
    """Sortable list of popup placement rules, tried top to bottom.

    Reorder-only: all three strategies are always present, so a placement rule
    always resolves.
    """

    def __init__(self, config: Config, tooltip: str = "") -> None:
        super().__init__()
        self._config = config
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(6)
        self.set_tooltip_text(tooltip)

        label = Xs.SettingsLabel(_("Open the popup on"))
        self.pack_start(label, False, False, 0)

        # No frame: the SettingsSection already draws one, and nesting two
        # looked like a box inside a box.
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.get_style_context().add_class("funes-monitor-order")
        self.pack_start(self._list, False, False, 0)

        self._reload()

    def _reload(self) -> None:
        for child in self._list.get_children():
            self._list.remove(child)

        order = self._config.popup_monitor_order
        labels = _monitor_strategy_labels()
        last = len(order) - 1
        for index, name in enumerate(order):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.set_border_width(4)

            rank = Gtk.Label(label=f"{index + 1}.")
            rank.get_style_context().add_class("dim-label")
            row.pack_start(rank, False, False, 0)
            row.pack_start(Xs.SettingsLabel(labels[name]), False, False, 0)

            down = Gtk.Button.new_from_icon_name("go-down-symbolic", Gtk.IconSize.BUTTON)
            down.set_relief(Gtk.ReliefStyle.NONE)
            down.set_sensitive(index != last)
            down.connect("clicked", self._on_move, name, 1)
            row.pack_end(down, False, False, 0)

            up = Gtk.Button.new_from_icon_name("go-up-symbolic", Gtk.IconSize.BUTTON)
            up.set_relief(Gtk.ReliefStyle.NONE)
            up.set_sensitive(index != 0)
            up.connect("clicked", self._on_move, name, -1)
            row.pack_end(up, False, False, 0)

            list_row = Gtk.ListBoxRow()
            list_row.set_activatable(False)
            list_row.set_selectable(False)
            list_row.add(row)
            self._list.add(list_row)

        self._list.show_all()

    def _on_move(self, _button: Gtk.Button, name: str, delta: int) -> None:
        self._config.popup_monitor_order = monitors.move(
            self._config.popup_monitor_order, name, delta
        )
        self._reload()


class PreferencesWindow(XApp.PreferencesWindow):  # type: ignore[misc]  # xapp is untyped
    def __init__(self, config: Config) -> None:
        super().__init__(title=_("Funes Preferences"))
        self._config = config
        self.set_default_size(600, 500)
        self.set_icon_name("org.x.funes")

        page = Xs.SettingsPage()
        page.set_margin_top(12)
        page.set_margin_bottom(12)
        page.set_margin_start(12)
        page.set_margin_end(12)

        self._build_history_section(page)
        self._build_paste_section(page)
        self._build_popup_section(page)
        self._build_capture_section(page)
        self._build_images_section(page)

        # A single page keeps the sidebar hidden; the stack still scrolls.
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.add(page)
        self.add_page(scroller, "general", _("General"))

        # Same pairing as xed: Help on one edge, Close on the other. A lone
        # button would sit centered in the action bar's EDGE layout.
        help_button = Gtk.Button(label=_("Help"))
        help_button.connect("clicked", self._on_help_clicked)
        self.add_button(help_button, Gtk.PackType.START)

        close = Gtk.Button(label=_("Close"))
        close.connect("clicked", lambda _button: self.close())
        self.add_button(close, Gtk.PackType.END)

        self.show_all()

    # --- sections ---

    def _build_history_section(self, page: Any) -> None:
        section = page.add_section(_("History"))

        section.add_row(
            Gs.GSettingsSpinButton(
                _("History size"),
                SETTINGS_SCHEMA,
                "history-size",
                mini=10,
                maxi=10000,
                step=10,
                tooltip=_("Oldest unpinned items are dropped past this count."),
            )
        )

        # The daemon (`FunesApplication`) watches the key and re-registers the
        # Cinnamon keybinding, so this widget only writes GSettings.
        section.add_row(
            ShortcutWidget(
                self._config,
                tooltip=_(
                    "Click, then press the combination that toggles the popup. "
                    "Registered as a Cinnamon custom keybinding."
                ),
            )
        )

        autostart_switch = Gs.GSettingsSwitch(
            _("Launch at login"), SETTINGS_SCHEMA, "launch-at-login"
        )
        section.add_row(autostart_switch)
        self._config.settings.connect("changed::launch-at-login", self._on_autostart_changed)

    def _build_paste_section(self, page: Any) -> None:
        section = page.add_section(_("Pasting"))

        paster = Paster()
        can_paste = paster.available() and not on_wayland()
        if can_paste:
            paste_hint = _("Injects Shift+Insert into the previously focused window.")
        elif on_wayland():
            paste_hint = _("Unavailable: keystroke injection needs an X11 session.")
        else:
            paste_hint = _("Unavailable: the X server has no XTEST extension.")

        paste_switch = Gs.GSettingsSwitch(
            _("Paste on select"), SETTINGS_SCHEMA, "paste-on-select", tooltip=paste_hint
        )
        paste_switch.set_sensitive(can_paste)
        section.add_row(paste_switch)
        section.add_note(paste_hint)

        section.add_row(
            Gs.GSettingsEntry(
                _("Extra Ctrl+Shift+V windows"),
                SETTINGS_SCHEMA,
                "paste-ctrl-shift-v-class-regex",
                tooltip=_(
                    "Funes pastes with Ctrl+V, and with Ctrl+Shift+V in "
                    "terminals it knows about. Add any other terminal here "
                    'as a regex on WM_CLASS ("res_name.res_class"), '
                    "e.g. myterm|weird-console"
                ),
            )
        )

    def _build_popup_section(self, page: Any) -> None:
        section = page.add_section(_("Popup"))

        section.add_row(
            MonitorOrderWidget(
                self._config,
                tooltip=_("Rules are tried top to bottom until one resolves a monitor."),
            )
        )

        section.add_row(
            Gs.GSettingsSwitch(
                _("Single click activates a row"),
                SETTINGS_SCHEMA,
                "popup-single-click-activates",
                tooltip=_(
                    "Off: one click only selects, a double click activates, so "
                    "clicking inside the popup keeps it open. On: one click "
                    "copies right away."
                ),
            )
        )

        if on_wayland():
            section.add_note(
                _("Unavailable: Wayland does not let applications position their windows.")
            )

    def _build_capture_section(self, page: Any) -> None:
        section = page.add_section(_("Capturing"))

        section.add_row(
            Gs.GSettingsSwitch(
                _("Keep clipboard alive"),
                SETTINGS_SCHEMA,
                "reown-clipboard",
                tooltip=_(
                    "Funes takes clipboard ownership so copied text survives "
                    "the source app closing."
                ),
            )
        )

        section.add_row(
            Gs.GSettingsSwitch(
                _("Pause capturing"),
                SETTINGS_SCHEMA,
                "ignore-enabled",
                tooltip=_("Clipboard changes are not recorded while on."),
            )
        )

        ignore_entry = Xs.Entry(
            _("Ignore matching"),
            expand_width=True,
            tooltip=_("Pipe-separated regexes. Password-manager hints are always ignored."),
        )
        ignore_entry.content_widget.set_text(" | ".join(self._config.ignore_regexes))
        ignore_entry.content_widget.set_placeholder_text(_("regex | regex"))
        ignore_entry.content_widget.connect("activate", self._apply_ignores)
        ignore_entry.content_widget.connect("focus-out-event", self._apply_ignores)
        section.add_row(ignore_entry)

    # --- handlers ---

    def _on_help_clicked(self, _button: Gtk.Button) -> None:
        Gtk.show_uri_on_window(self, HOMEPAGE, Gdk.CURRENT_TIME)

    def _on_autostart_changed(self, settings: Gio.Settings, _key: str) -> None:
        autostart.set_enabled(settings.get_boolean("launch-at-login"))

    def _build_images_section(self, page: Any) -> None:
        from funes.ocr import available as _ocr_available

        section = page.add_section(_("Images"))

        section.add_row(
            Gs.GSettingsSwitch(
                _("Capture images"),
                SETTINGS_SCHEMA,
                "capture-images",
                tooltip=_(
                    "When enabled, Funes records image data and any other non-text "
                    "clipboard content (files, unrecognized formats, …) in addition to text."
                ),
            )
        )

        section.add_row(
            Gs.GSettingsSpinButton(
                _("Max image size (MiB)"),
                SETTINGS_SCHEMA,
                "max-image-bytes",
                units=_("MiB"),
                mini=1,
                maxi=1024,
                step=1,
                page=10,
                tooltip=_(
                    "Any single representation larger than this limit is silently "
                    "dropped — an image format (PNG, JPEG, …), a file list, or "
                    "anything else — checked separately per representation."
                ),
            )
        )

        section.add_row(
            Gs.GSettingsComboBox(
                _("Image row height"),
                SETTINGS_SCHEMA,
                "image-row-height",
                options=[
                    (32, _("Compact (32 px)")),
                    (48, _("Normal (48 px)")),
                    (64, _("Tall (64 px)")),
                ],
                tooltip=_("Height of image rows in the popup. Thumbnails scale to fit."),
            )
        )

        ocr_switch = Gs.GSettingsSwitch(
            _("Extract text with OCR"),
            SETTINGS_SCHEMA,
            "ocr-enabled",
            tooltip=_(
                "Use Tesseract to extract text from images so they are searchable. "
                "Recognized text is stored in plain text inside history.db."
            ),
        )
        if not _ocr_available():
            ocr_switch.set_sensitive(False)
            ocr_switch.set_tooltip_text(
                _("Tesseract is not installed. Install tesseract-ocr to enable OCR.")
            )
        section.add_row(ocr_switch)

        if not _ocr_available():
            bar = Gtk.InfoBar()
            bar.set_message_type(Gtk.MessageType.WARNING)
            bar.get_content_area().add(
                Gtk.Label(
                    label=_("Install tesseract-ocr to enable image text search."),
                    xalign=0.0,
                )
            )
            btn = bar.add_button(_("Install…"), Gtk.ResponseType.ACCEPT)
            btn.get_style_context().add_class("suggested-action")
            bar.connect(
                "response",
                lambda _b, _r: Gio.AppInfo.launch_default_for_uri("apt://tesseract-ocr", None),
            )
            bar.show_all()
            section.add(bar)

    def _apply_ignores(self, entry: Gtk.Entry, *_args: object) -> bool:
        cleaned = [part.strip() for part in entry.get_text().split("|") if part.strip()]
        self._config.ignore_regexes = cleaned
        return False
