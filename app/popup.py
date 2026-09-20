"""The history popup ("Spine" layout).

Centered on the monitor chosen by `popup-monitor-order` (focused window,
pointer, primary), keyboard-first:
  type            fuzzy filter (case-insensitive, FZF-style ranking)
  Up/Down         move selection
  Alt+1..9        paste the numbered row (Ctrl+Alt+1..9 copies only)
  Enter           copy + paste into the previously focused window
  Ctrl+Enter      copy only
  Ctrl+P          toggle pin
  Delete          remove item (BackSpace never deletes, it edits the filter)
  Escape          hide
  Ctrl+L          clear history (keeps pinned)

Single-line rows, a left gutter of quick-select numbers and a right gutter of
relative age; the footer narrates what Enter will do.
"""

from pathlib import Path
from typing import ClassVar

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk, Pango
from xapp.util import l10n

from funes import APP_NAME, GETTEXT_DOMAIN, monitors
from funes.config import Config
from funes.item import HistoryItem, now_micros
from funes.presentation import (
    color_literal,
    looks_like_code,
    match_byte_spans,
    match_span,
    relative_age,
)
from funes.search import filter_indices, match_indices
from funes.store import HistoryStore

_ = l10n(GETTEXT_DOMAIN)

# Focus-out must persist this long before the popup closes.
FOCUS_OUT_GRACE_MS = 250

# Rows reachable with Alt+1..9.
QUICK_SELECT_ROWS = 9


class PopupWindow(Gtk.Window):
    __gsignals__: ClassVar[dict[str, tuple[object, ...]]] = {
        # (item, paste)
        "item-chosen": (GObject.SignalFlags.RUN_LAST, None, (object, bool)),
    }

    def __init__(self, store: HistoryStore, config: Config, thumb_root: Path | None = None) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._store = store
        self._config = config
        self._thumb_root = thumb_root or (Path(GLib.get_user_cache_dir()) / "funes" / "thumbs")
        self._filter_text = ""
        self._focus_armed = False
        self._focus_out_source = 0
        self._placement: tuple[int, int] | None = None

        self.set_title(APP_NAME)
        self.set_default_size(config.popup_width, config.popup_height)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_decorated(False)
        # Not CENTER_ALWAYS: it makes the WM re-center the window on every map,
        # which overrode our own move() and parked the popup on the primary
        # monitor no matter which one was active.
        self.set_position(Gtk.WindowPosition.NONE)
        self.set_icon_name("edit-paste")
        self.get_style_context().add_class("funes-popup")

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

        box.pack_start(self._build_search(), False, False, 0)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self._list.set_activate_on_single_click(True)
        self._list.get_style_context().add_class("funes-list")
        self._list.connect("row-activated", self._on_row_activated)

        self._scroller = Gtk.ScrolledWindow()
        self._scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroller.set_hexpand(True)
        self._scroller.set_vexpand(True)
        self._scroller.add(self._list)

        self._empty = EmptyState()

        # Only one of the two is ever visible; the stack keeps the popup from
        # ever showing a blank rectangle.
        self._stack = Gtk.Stack()
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        self._stack.add_named(self._scroller, "list")
        self._stack.add_named(self._empty, "empty")
        box.pack_start(self._stack, True, True, 0)

        self._footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._footer.get_style_context().add_class("funes-footer")
        box.pack_start(self._footer, False, False, 0)

        self.add(box)

    def _build_search(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        row.get_style_context().add_class("funes-search")

        icon = Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.MENU)
        icon.get_style_context().add_class("funes-search-icon")
        row.pack_start(icon, False, False, 0)

        self._search = Gtk.Entry()
        self._search.set_has_frame(False)
        self._search.set_placeholder_text(_("Search clipboard history"))
        self._search.connect("changed", self._on_search_changed)
        self._search.connect(
            "activate", lambda *_a: self._activate_selected(self._config.paste_on_select)
        )
        row.pack_start(self._search, True, True, 0)

        self._count = Gtk.Label(label="")
        self._count.get_style_context().add_class("funes-count")
        row.pack_start(self._count, False, False, 0)

        return row

    # --- visibility ---

    def show_popup(self) -> None:
        self._search.set_text("")
        self._filter_text = ""
        self._reload()
        self._focus_armed = False
        self.set_focus_on_map(True)
        # Must run before show_all(): once the popup is mapped it becomes the
        # active window, and the "focused" strategy would resolve to itself.
        self._place_on_target_monitor()
        self.show_all()
        # Some WMs only honour a position once the window is realized, others
        # place it themselves at map time, so the move is applied three times.
        self._apply_placement()
        self.present_with_time(Gdk.CURRENT_TIME)
        GLib.idle_add(self._apply_placement)
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

    def _place_on_target_monitor(self) -> None:
        """Center the popup on the monitor the user's strategy order picks.

        No-op under Wayland, where GTK3 toplevels cannot be positioned at all
        (see docs/design/WAYLAND.md).
        """
        self._placement = None
        width = self._config.popup_width
        height = self._config.popup_height
        self.resize(width, height)

        monitor = self._target_monitor()
        if monitor is None:
            return

        area = monitor.get_workarea()
        self._placement = (
            area.x + (area.width - width) // 2,
            area.y + (area.height - height) // 2,
        )
        self._apply_placement()

    def _apply_placement(self) -> bool:
        if self._placement is not None:
            self.move(*self._placement)
        return GLib.SOURCE_REMOVE

    def _target_monitor(self) -> Gdk.Monitor | None:
        display = Gdk.Display.get_default()
        if display is None:
            return None
        return monitors.pick(
            self._config.popup_monitor_order,
            {
                monitors.FOCUSED: self._focused_monitor(display),
                monitors.POINTER: self._pointer_monitor(display),
                monitors.PRIMARY: display.get_primary_monitor(),
            },
        )

    def _focused_monitor(self, display: Gdk.Display) -> Gdk.Monitor | None:
        screen = display.get_default_screen()
        active = screen.get_active_window() if screen is not None else None
        if active is None or active == self.get_window():
            return None
        return display.get_monitor_at_window(active)

    def _pointer_monitor(self, display: Gdk.Display) -> Gdk.Monitor | None:
        seat = display.get_default_seat()
        pointer = seat.get_pointer() if seat is not None else None
        if pointer is None:
            return None
        _screen, pointer_x, pointer_y = pointer.get_position()
        return display.get_monitor_at_point(pointer_x, pointer_y)

    # --- content ---

    def _reload(self) -> None:
        for child in self._list.get_children():
            self._list.remove(child)

        stamp = now_micros()
        shown = 0
        total = 0

        all_items = list(self._store.items())
        total = len(all_items)

        # Filter by fuzzy search using index-based API so duplicate corpora
        # (e.g. two image items with the same search_text) are handled correctly.
        if self._filter_text:
            search_corpora = [item.search_text or item.text or "" for item in all_items]
            matched_indices = filter_indices(search_corpora, self._filter_text)
            items_to_show = [all_items[i] for i in matched_indices]
        else:
            items_to_show = all_items

        for item in items_to_show:
            number = shown + 1 if shown < QUICK_SELECT_ROWS else None
            if item.kind == "image":
                row: Gtk.ListBoxRow = ImageRow(
                    item,
                    number,
                    self._config.image_row_height,
                    self._thumb_root,
                    self._store.blob_store,
                    stamp,
                )
            else:
                row = TextRow(item, number, self._filter_text, stamp)
            self._list.add(row)
            shown += 1

        self._list.show_all()
        self._select_first()
        self._update_count(shown, total)
        self._update_body(shown, total)
        self._update_footer()

    def _update_count(self, shown: int, total: int) -> None:
        if not self._filter_text:
            self._count.set_label(f"{total:d}")
        else:
            self._count.set_label(_("%(shown)d of %(total)d") % {"shown": shown, "total": total})

    def _update_body(self, shown: int, total: int) -> None:
        if shown:
            self._stack.set_visible_child_name("list")
            return
        if total == 0:
            self._empty.show_reason(
                _("History is empty"),
                _("Copy something and it shows up here"),
                close_hint=True,
            )
        else:
            self._empty.show_reason(
                _("No match for “%s”") % self._search.get_text().strip(),
                _("to widen the search"),
                widen_hint=True,
                close_hint=True,
            )
        self._stack.set_visible_child_name("empty")

    def _update_footer(self) -> None:
        for child in self._footer.get_children():
            self._footer.remove(child)

        row = self._selected_row()
        if row is None:
            # The empty state already carries the way out; a second legend
            # would only repeat it.
            self._footer.set_no_show_all(True)
            self._footer.hide()
            return
        self._footer.set_no_show_all(False)
        if self._filter_text:
            # While filtering the footer narrates the next Enter instead of
            # reciting the full mantra.
            self._footer_legend(
                [("↵", _("paste “%s”") % row.item.preview(48))],
                trailing=("Esc", _("close")),
            )
        else:
            self._footer_legend(
                [
                    ("↵", _("paste")),
                    ("⌃↵", _("copy")),
                    ("⌃P", _("pin")),
                    ("Del", _("remove")),
                ],
                trailing=("Alt+1–9", _("paste")),  # noqa: RUF001 - en dash reads as a range
            )
        self._footer.show_all()

    def _footer_legend(
        self,
        entries: list[tuple[str, str]],
        trailing: tuple[str, str] | None,
    ) -> None:
        for index, (key, text) in enumerate(entries):
            if index:
                self._footer.pack_start(_separator(), False, False, 0)
            self._footer.pack_start(_legend_item(key, text), False, False, 0)
        if trailing is not None:
            item = _legend_item(*trailing)
            item.set_halign(Gtk.Align.END)
            self._footer.pack_end(item, False, False, 0)

    def _select_first(self) -> None:
        row = self._list.get_row_at_index(0)
        if row is not None:
            self._list.select_row(row)

    def _selected_row(self) -> "TextRow | ImageRow | None":
        row = self._list.get_selected_row()
        return row if isinstance(row, (TextRow, ImageRow)) else None

    def _move_selection(self, delta: int) -> None:
        row = self._list.get_selected_row()
        index = row.get_index() if row is not None else -1
        target = self._list.get_row_at_index(index + delta)
        if target is not None:
            self._select(target)

    def _jump_to(self, index: int, paste: bool) -> None:
        target = self._list.get_row_at_index(index)
        if target is None:
            return
        self._select(target)
        self._activate_selected(paste)

    def _select(self, row: Gtk.ListBoxRow) -> None:
        self._list.select_row(row)
        row.grab_focus()
        self._search.grab_focus_without_selecting()
        self._update_footer()

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

    def _on_search_changed(self, entry: Gtk.Entry) -> None:
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
        alt = bool(event.state & Gdk.ModifierType.MOD1_MASK)
        key = event.keyval

        if alt:
            index = _quick_select_index(key)
            if index is not None:
                self._jump_to(index, paste=not ctrl and self._config.paste_on_select)
                return True

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


# ---------------------------------------------------------------------------
# Row widgets
# ---------------------------------------------------------------------------


class TextRow(Gtk.ListBoxRow):
    """One single-line text entry: number gutter · content · age gutter."""

    def __init__(
        self,
        item: HistoryItem,
        number: int | None,
        filter_text: str,
        now: int,
    ) -> None:
        super().__init__()
        self.item = item

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.get_style_context().add_class("funes-row")

        # The gutter is always reserved so text never shifts between rows that
        # do and do not have a quick-select number.
        gutter = Gtk.Label(label=str(number) if number is not None else "")
        gutter.set_width_chars(2)
        gutter.get_style_context().add_class(
            "funes-num" if number is not None else "funes-num-placeholder"
        )
        row.pack_start(gutter, False, False, 0)

        if item.pinned:
            pin = Gtk.Image.new_from_icon_name("starred-symbolic", Gtk.IconSize.MENU)
            pin.set_tooltip_text(_("Pinned"))
            row.pack_start(pin, False, False, 0)

        color = color_literal(item.text) if item.text else None
        if color is not None:
            row.pack_start(_color_swatch(color), False, False, 0)

        text = item.preview()
        self._label = Gtk.Label(label=text)
        self._label.set_halign(Gtk.Align.START)
        self._label.set_xalign(0)
        self._label.set_ellipsize(Pango.EllipsizeMode.END)
        self._label.set_single_line_mode(True)
        if looks_like_code(text):
            self._label.get_style_context().add_class("funes-mono")
        row.pack_start(self._label, True, True, 0)

        age = Gtk.Label(label=_("pinned") if item.pinned else relative_age(item.created, now))
        age.get_style_context().add_class("funes-age")
        row.pack_start(age, False, False, 0)

        # Use fzy match indices for fuzzy highlighting; fall back to the
        # legacy substring span when there is no filter.
        self._match_spans: list[tuple[int, int]] = []
        if filter_text:
            indices = match_indices(filter_text, text)
            if indices is not None:
                self._match_spans = match_byte_spans(text, indices)
        else:
            span = match_span(text, filter_text)
            if span is not None:
                self._match_spans = [span]

        if self._match_spans:
            self._apply_match_attrs()
            # Accent-on-accent is unreadable while selected — switch to underline.
            self.connect("state-flags-changed", lambda *_a: self._apply_match_attrs())

        self.set_tooltip_text(item.describe())
        self.add(row)

    def _apply_match_attrs(self) -> None:
        if not self._match_spans:
            return
        attrs = Pango.AttrList()
        is_selected = self.is_selected()

        accent_color = None
        if not is_selected:
            accent = self.get_style_context().lookup_color("theme_selected_bg_color")
            if accent[0]:
                c = accent[1]
                accent_color = (
                    int(c.red * 65535),
                    int(c.green * 65535),
                    int(c.blue * 65535),
                )

        for start, end in self._match_spans:
            weight = Pango.attr_weight_new(Pango.Weight.BOLD)
            weight.start_index, weight.end_index = start, end
            attrs.insert(weight)

            if is_selected:
                underline = Pango.attr_underline_new(Pango.Underline.SINGLE)
                underline.start_index, underline.end_index = start, end
                attrs.insert(underline)
            elif accent_color is not None:
                foreground = Pango.attr_foreground_new(*accent_color)
                foreground.start_index, foreground.end_index = start, end
                attrs.insert(foreground)

        self._label.set_attributes(attrs)


# Keep the old name as an alias for any code that still references it.
ItemRow = TextRow


class ImageRow(Gtk.ListBoxRow):
    """Taller image row: number gutter · thumbnail · meta label · age gutter.

    The height is driven by ``image-row-height`` (32/48/64, default 48).
    Missing or corrupt thumbnails fall back to the ``image-missing`` icon so
    the row remains selectable and pasteable.
    """

    def __init__(
        self,
        item: HistoryItem,
        number: int | None,
        row_height: int,
        thumb_root: Path,
        blob_store: object,
        now: int,
    ) -> None:
        super().__init__()
        self.item = item

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        outer.get_style_context().add_class("funes-row")
        outer.set_size_request(-1, row_height)

        # Left gutter — quick-select number or placeholder (same width as TextRow).
        gutter = Gtk.Label(label=str(number) if number is not None else "")
        gutter.set_width_chars(2)
        gutter.get_style_context().add_class(
            "funes-num" if number is not None else "funes-num-placeholder"
        )
        outer.pack_start(gutter, False, False, 0)

        if item.pinned:
            pin = Gtk.Image.new_from_icon_name("starred-symbolic", Gtk.IconSize.MENU)
            pin.set_tooltip_text(_("Pinned"))
            outer.pack_start(pin, False, False, 0)

        # Thumbnail.
        thumb_px = row_height - 8
        thumb_widget = self._build_thumb(item, thumb_px, thumb_root, blob_store)
        outer.pack_start(thumb_widget, False, False, 0)

        # Meta label: e.g. "PNG · 1920\u00d71080 · 240 kB".
        from images import meta_label as _meta_label

        label_text = _meta_label(item.mime, item.width, item.height, item.bytes)
        meta = Gtk.Label(label=label_text)
        meta.set_halign(Gtk.Align.START)
        meta.set_xalign(0)
        meta.set_ellipsize(Pango.EllipsizeMode.END)
        meta.set_single_line_mode(True)
        outer.pack_start(meta, True, True, 0)

        age = Gtk.Label(label=_("pinned") if item.pinned else relative_age(item.created, now))
        age.get_style_context().add_class("funes-age")
        outer.pack_start(age, False, False, 0)

        self.set_tooltip_text(item.describe())
        self.add(outer)

    @staticmethod
    def _build_thumb(
        item: HistoryItem,
        px: int,
        thumb_root: Path,
        blob_store: object,
    ) -> Gtk.Widget:
        """Load thumbnail from cache or generate on the fly."""
        from funes.blobs import BlobStore
        from images import thumbnail as _thumbnail

        assert isinstance(blob_store, BlobStore)
        thumb_path: Path | None = None
        if item.blob_sha:
            # Check cache first (cheap).
            scale = 1  # TODO: read window scale factor when available
            candidate = thumb_root / f"{item.blob_sha}@{px}x{scale}.png"
            if candidate.exists():
                thumb_path = candidate
            else:
                try:
                    data = blob_store.read(item.blob_sha)
                    thumb_path = _thumbnail(item.blob_sha, data, px, scale, thumb_root)
                except Exception:
                    thumb_path = None

        if thumb_path is not None:
            try:
                # Load proportionally: constrain height only, let width be natural.
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(thumb_path), -1, px, True)
                if pixbuf is None:
                    raise ValueError("null pixbuf")
                img = Gtk.Image.new_from_pixbuf(pixbuf)
                img.set_size_request(pixbuf.get_width(), px)
                return img
            except Exception:
                pass

        # Fallback: missing-image icon.
        img = Gtk.Image.new_from_icon_name("image-missing", Gtk.IconSize.LARGE_TOOLBAR)
        img.set_size_request(px, px)
        return img


class EmptyState(Gtk.Box):
    """Never a blank rectangle: always a reason and always the way out."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_valign(Gtk.Align.CENTER)
        self.get_style_context().add_class("funes-empty")

        self._icon = Gtk.Image.new_from_icon_name("edit-find-symbolic", Gtk.IconSize.DND)
        self._icon.set_opacity(0.55)
        self.pack_start(self._icon, False, False, 0)

        self._title = Gtk.Label(label="")
        self._title.get_style_context().add_class("funes-empty-title")
        self.pack_start(self._title, False, False, 0)

        self._hint = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._hint.set_halign(Gtk.Align.CENTER)
        self.pack_start(self._hint, False, False, 0)

    def show_reason(
        self,
        title: str,
        hint: str,
        widen_hint: bool = False,
        close_hint: bool = False,
    ) -> None:
        self._title.set_label(title)
        for child in self._hint.get_children():
            self._hint.remove(child)
        if widen_hint:
            self._hint.pack_start(_legend_item("⌫", hint), False, False, 0)
        else:
            self._hint.pack_start(Gtk.Label(label=hint), False, False, 0)
        if close_hint:
            self._hint.pack_start(_separator(), False, False, 0)
            self._hint.pack_start(_legend_item("Esc", _("close")), False, False, 0)
        self._hint.show_all()


def _quick_select_index(keyval: int) -> int | None:
    """Alt+1..9 → zero-based row index."""
    for offset in range(QUICK_SELECT_ROWS):
        if keyval in (Gdk.KEY_1 + offset, Gdk.KEY_KP_1 + offset):
            return offset
    return None


def _legend_item(key: str, text: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    cap = Gtk.Label(label=key)
    cap.get_style_context().add_class("funes-key")
    box.pack_start(cap, False, False, 0)
    label = Gtk.Label(label=text)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    box.pack_start(label, False, False, 0)
    return box


def _separator() -> Gtk.Label:
    label = Gtk.Label(label="·")
    label.set_opacity(0.45)
    return label


def _color_swatch(color: str) -> Gtk.Widget:
    swatch = Gtk.DrawingArea()
    swatch.set_size_request(13, 13)
    swatch.set_valign(Gtk.Align.CENTER)
    swatch.get_style_context().add_class("funes-swatch")
    rgba = Gdk.RGBA()
    if not rgba.parse(color):
        rgba.parse("#000000")

    def draw(_area: Gtk.Widget, cr: object) -> bool:
        Gdk.cairo_set_source_rgba(cr, rgba)
        cr.rectangle(0, 0, 13, 13)  # type: ignore[attr-defined]
        cr.fill()  # type: ignore[attr-defined]
        return False

    swatch.connect("draw", draw)
    return swatch
