"""The history popup.

Centered on the monitor under the pointer, keyboard-first:
  type            filter (case-insensitive substring)
  Up/Down         move selection
  Enter           copy + paste into the previously focused window
  Ctrl+Enter      copy only
  Ctrl+P          toggle pin
  Delete          remove item (BackSpace never deletes, it edits the filter)
  Escape          hide
  Ctrl+L          clear history (keeps pinned)
"""

from typing import ClassVar

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk, Pango
from xapp.util import l10n

from funes import APP_NAME, GETTEXT_DOMAIN
from funes.config import Config
from funes.item import HistoryItem
from funes.store import HistoryStore

_ = l10n(GETTEXT_DOMAIN)

# Focus-out must persist this long before the popup closes.
FOCUS_OUT_GRACE_MS = 250


class PopupWindow(Gtk.Window):
    __gsignals__: ClassVar[dict[str, tuple[object, ...]]] = {
        # (item, paste)
        "item-chosen": (GObject.SignalFlags.RUN_LAST, None, (object, bool)),
    }

    def __init__(self, store: HistoryStore, config: Config) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._store = store
        self._config = config
        self._filter_text = ""
        self._focus_armed = False
        self._focus_out_source = 0

        self.set_title(APP_NAME)
        self.set_default_size(config.popup_width, config.popup_height)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_icon_name("edit-paste")

        self._build_ui()

        store.connect("changed", self._on_store_changed)
        self.connect("key-press-event", self._on_key_press)
        # Only close on focus loss once the window actually got focus: some WMs
        # deliver focus-out right after map, which would hide the popup before
        # it is usable.
        self.connect("focus-in-event", self._on_focus_in)
        # Window managers emit short focus-out/focus-in bursts right after
        # mapping an override window, so closing is debounced and re-checked
        # instead of acting on the first focus-out.
        self.connect("focus-out-event", self._on_focus_out)
        self.connect("delete-event", self._on_delete)
        self.connect("size-allocate", self._on_size_allocate)

    # --- construction ---

    def _build_ui(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text(_("Search clipboard history"))
        self._search.set_margin_top(6)
        self._search.set_margin_bottom(6)
        self._search.set_margin_start(6)
        self._search.set_margin_end(6)
        self._search.connect("search-changed", self._on_search_changed)
        self._search.connect(
            "activate", lambda *_a: self._activate_selected(self._config.paste_on_select)
        )
        box.pack_start(self._search, False, False, 0)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self._list.set_activate_on_single_click(True)
        self._list.connect("row-activated", self._on_row_activated)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.add(self._list)
        box.pack_start(scroller, True, True, 0)

        self._status = Gtk.Label(label="")
        self._status.get_style_context().add_class(Gtk.STYLE_CLASS_DIM_LABEL)
        self._status.set_halign(Gtk.Align.START)
        self._status.set_margin_top(4)
        self._status.set_margin_bottom(4)
        self._status.set_margin_start(8)
        self._status.set_margin_end(4)
        box.pack_start(self._status, False, False, 0)

        self.add(box)

    # --- visibility ---

    def show_popup(self) -> None:
        self._reload()
        self._search.set_text("")
        self._filter_text = ""
        self._focus_armed = False
        self.set_focus_on_map(True)
        self._center_on_pointer_monitor()
        self.show_all()
        self.present_with_time(Gdk.CURRENT_TIME)
        self._search.grab_focus()
        self._select_first()

    def hide_popup(self) -> None:
        self._focus_armed = False
        self._cancel_focus_out_timer()
        self.hide()

    def toggle(self) -> None:
        if self.get_visible():
            self.hide_popup()
        else:
            self.show_popup()

    def _cancel_focus_out_timer(self) -> None:
        if self._focus_out_source:
            GLib.source_remove(self._focus_out_source)
            self._focus_out_source = 0

    def _center_on_pointer_monitor(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        seat = display.get_default_seat()
        pointer = seat.get_pointer() if seat is not None else None
        if pointer is None:
            return

        _screen, pointer_x, pointer_y = pointer.get_position()
        monitor = display.get_monitor_at_point(pointer_x, pointer_y)
        if monitor is None:
            monitor = display.get_primary_monitor()
        if monitor is None:
            return

        area = monitor.get_workarea()
        width = self._config.popup_width
        height = self._config.popup_height
        self.resize(width, height)
        self.move(area.x + (area.width - width) // 2, area.y + (area.height - height) // 2)

    # --- content ---

    def _reload(self) -> None:
        for child in self._list.get_children():
            self._list.remove(child)

        shown = 0
        total = 0
        for item in self._store.items():
            total += 1
            if self._filter_text and self._filter_text not in item.text.lower():
                continue
            self._list.add(ItemRow(item))
            shown += 1

        self._list.show_all()
        self._select_first()

        if total == 0:
            self._status.set_label(_("History is empty"))
        elif not self._filter_text:
            # Percent formatting is kept on translatable strings: the
            # placeholders are part of the msgid translators work with.
            summary = _("1 item") if total == 1 else _("%d items") % total
            hint = _("Enter paste · Ctrl+Enter copy · Ctrl+P pin · Del remove")
            self._status.set_label(f"{summary}  ·  {hint}")
        else:
            self._status.set_label(_("%d of %d match") % (shown, total))

    def _select_first(self) -> None:
        row = self._list.get_row_at_index(0)
        if row is not None:
            self._list.select_row(row)

    def _selected_row(self) -> "ItemRow | None":
        row = self._list.get_selected_row()
        return row if isinstance(row, ItemRow) else None

    def _move_selection(self, delta: int) -> None:
        row = self._list.get_selected_row()
        index = row.get_index() if row is not None else -1
        target = self._list.get_row_at_index(index + delta)
        if target is not None:
            self._list.select_row(target)
            target.grab_focus()
            self._search.grab_focus_without_selecting()

    def _activate_selected(self, paste: bool) -> None:
        row = self._selected_row()
        if row is None:
            return
        item = row.item
        self.hide_popup()
        self.emit("item-chosen", item, paste)

    # --- signal handlers ---

    def _on_store_changed(self, _store: HistoryStore) -> None:
        if self.get_visible():
            self._reload()

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._filter_text = entry.get_text().strip().lower()
        self._reload()

    def _on_row_activated(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        listbox.select_row(row)
        self._activate_selected(self._config.paste_on_select)

    def _on_focus_in(self, *_args: object) -> bool:
        self._focus_armed = True
        self._cancel_focus_out_timer()
        return False

    def _on_focus_out(self, *_args: object) -> bool:
        if not self._focus_armed:
            return False
        self._cancel_focus_out_timer()
        self._focus_out_source = GLib.timeout_add(FOCUS_OUT_GRACE_MS, self._focus_out_elapsed)
        return False

    def _focus_out_elapsed(self) -> bool:
        self._focus_out_source = 0
        if self.get_visible() and not self.has_toplevel_focus():
            self.hide_popup()
        return GLib.SOURCE_REMOVE

    def _on_delete(self, *_args: object) -> bool:
        self.hide_popup()
        return True

    def _on_size_allocate(self, *_args: object) -> None:
        if not (self._config.remember_size and self.get_visible()):
            return
        if self.is_maximized():
            return
        width, height = self.get_size()
        if width != self._config.popup_width:
            self._config.popup_width = width
        if height != self._config.popup_height:
            self._config.popup_height = height

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        key = event.keyval

        if key == Gdk.KEY_Escape:
            self.hide_popup()
            return True
        if key == Gdk.KEY_Down:
            self._move_selection(1)
            return True
        if key == Gdk.KEY_Up:
            self._move_selection(-1)
            return True
        if key == Gdk.KEY_Page_Down:
            self._move_selection(10)
            return True
        if key == Gdk.KEY_Page_Up:
            self._move_selection(-10)
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._activate_selected(not ctrl and self._config.paste_on_select)
            return True
        if key == Gdk.KEY_Delete:
            row = self._selected_row()
            if row is not None:
                self._store.remove(row.item)
            return True
        if ctrl and key in (Gdk.KEY_p, Gdk.KEY_P):
            row = self._selected_row()
            if row is not None:
                self._store.toggle_pin(row.item)
            return True
        if ctrl and key in (Gdk.KEY_l, Gdk.KEY_L):
            self._store.clear()
            return True
        return False


class ItemRow(Gtk.ListBoxRow):
    def __init__(self, item: HistoryItem) -> None:
        super().__init__()
        self.item = item

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_top(6)
        row.set_margin_bottom(6)
        row.set_margin_start(6)
        row.set_margin_end(6)

        if item.pinned:
            pin = Gtk.Image.new_from_icon_name("view-pin-symbolic", Gtk.IconSize.MENU)
            pin.set_tooltip_text(_("Pinned"))
            row.pack_start(pin, False, False, 0)

        label = Gtk.Label(label=item.preview())
        label.set_halign(Gtk.Align.START)
        label.set_xalign(0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_single_line_mode(True)
        row.pack_start(label, True, True, 0)

        self.set_tooltip_text(item.describe())
        self.add(row)
