/* Funes - the history popup.
 *
 * Centered on the monitor under the pointer, keyboard-first:
 *   type            filter (case-insensitive substring)
 *   Up/Down         move selection
 *   Enter           copy + paste into the previously focused window
 *   Ctrl+Enter      copy only
 *   Ctrl+P          toggle pin
 *   Delete          remove item (BackSpace never deletes, it edits the filter)
 *   Escape          hide
 *   Ctrl+L          clear history (keeps pinned)
 */

namespace Funes {

    public class PopupWindow : Gtk.Window {
        /* Focus-out must persist this long before the popup closes. */
        private const uint FOCUS_OUT_GRACE_MS = 250;

        public signal void item_chosen (HistoryItem item, bool paste);

        private HistoryStore store;
        private Config config;

        private Gtk.SearchEntry search;
        private Gtk.ListBox list;
        private Gtk.Label status;
        private string filter_text = "";
        private bool focus_armed = false;
        private uint focus_out_source = 0;

        public PopupWindow (HistoryStore store, Config config) {
            Object (type: Gtk.WindowType.TOPLEVEL);
            this.store = store;
            this.config = config;

            title = Constants.APP_NAME;
            set_default_size (config.popup_width, config.popup_height);
            type_hint = Gdk.WindowTypeHint.UTILITY;
            skip_taskbar_hint = true;
            skip_pager_hint = true;
            set_keep_above (true);
            set_position (Gtk.WindowPosition.CENTER_ALWAYS);
            icon_name = "edit-paste";

            build_ui ();

            store.changed.connect (() => {
                if (visible) {
                    reload ();
                }
            });

            key_press_event.connect (on_key_press);

            // Only close on focus loss once the window actually got focus:
            // some WMs deliver focus-out right after map, which would hide the
            // popup before it is usable.
            focus_in_event.connect (() => {
                focus_armed = true;
                cancel_focus_out_timer ();
                return false;
            });
            // Window managers emit short focus-out/focus-in bursts right after
            // mapping an override window, so closing is debounced and re-checked
            // instead of acting on the first focus-out.
            focus_out_event.connect (() => {
                if (!focus_armed) {
                    return false;
                }
                cancel_focus_out_timer ();
                focus_out_source = GLib.Timeout.add (FOCUS_OUT_GRACE_MS, () => {
                    focus_out_source = 0;
                    if (visible && !has_toplevel_focus) {
                        hide_popup ();
                    }
                    return GLib.Source.REMOVE;
                });
                return false;
            });
            delete_event.connect (() => {
                hide_popup ();
                return true;
            });
            size_allocate.connect (() => {
                if (config.remember_size && visible && !is_maximized) {
                    int w, h;
                    get_size (out w, out h);
                    if (w != config.popup_width || h != config.popup_height) {
                        config.popup_width = w;
                        config.popup_height = h;
                    }
                }
            });
        }

        private void build_ui () {
            var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 0);

            search = new Gtk.SearchEntry ();
            search.placeholder_text = "Search clipboard history";
            search.margin = 6;
            search.search_changed.connect (() => {
                filter_text = search.text.down ().strip ();
                reload ();
            });
            search.activate.connect (() => activate_selected (config.paste_on_select));
            box.pack_start (search, false, false, 0);

            list = new Gtk.ListBox ();
            list.selection_mode = Gtk.SelectionMode.BROWSE;
            list.activate_on_single_click = true;
            list.row_activated.connect ((row) => {
                list.select_row (row);
                activate_selected (config.paste_on_select);
            });

            var scroller = new Gtk.ScrolledWindow (null, null);
            scroller.hscrollbar_policy = Gtk.PolicyType.NEVER;
            scroller.expand = true;
            scroller.add (list);
            box.pack_start (scroller, true, true, 0);

            status = new Gtk.Label ("");
            status.get_style_context ().add_class (Gtk.STYLE_CLASS_DIM_LABEL);
            status.halign = Gtk.Align.START;
            status.margin = 4;
            status.margin_start = 8;
            box.pack_start (status, false, false, 0);

            add (box);
        }

        public void show_popup () {
            reload ();
            search.text = "";
            filter_text = "";
            focus_armed = false;
            set_focus_on_map (true);
            center_on_pointer_monitor ();
            show_all ();
            present_with_time (Gdk.CURRENT_TIME);
            search.grab_focus ();
            select_first ();
        }

        public void hide_popup () {
            focus_armed = false;
            cancel_focus_out_timer ();
            hide ();
        }

        private void cancel_focus_out_timer () {
            if (focus_out_source != 0) {
                GLib.Source.remove (focus_out_source);
                focus_out_source = 0;
            }
        }

        public void toggle () {
            if (visible) {
                hide_popup ();
            } else {
                show_popup ();
            }
        }

        private void center_on_pointer_monitor () {
            var display = Gdk.Display.get_default ();
            if (display == null) {
                return;
            }
            var seat = display.get_default_seat ();
            if (seat == null) {
                return;
            }
            var pointer = seat.get_pointer ();
            if (pointer == null) {
                return;
            }

            int px, py;
            Gdk.Screen screen;
            pointer.get_position (out screen, out px, out py);

            var monitor = display.get_monitor_at_point (px, py);
            if (monitor == null) {
                monitor = display.get_primary_monitor ();
            }
            if (monitor == null) {
                return;
            }

            var area = monitor.get_workarea ();
            int w = config.popup_width;
            int h = config.popup_height;
            resize (w, h);
            move (area.x + (area.width - w) / 2, area.y + (area.height - h) / 2);
        }

        private void reload () {
            list.foreach ((child) => list.remove (child));

            uint shown = 0;
            uint total = 0;
            foreach (var item in store.items ()) {
                total++;
                if (filter_text != "" && !item.text.down ().contains (filter_text)) {
                    continue;
                }
                list.add (new ItemRow (item));
                shown++;
            }

            list.show_all ();
            select_first ();

            if (total == 0) {
                status.label = "History is empty";
            } else if (filter_text == "") {
                status.label = "%u item%s  ·  Enter paste · Ctrl+Enter copy · Ctrl+P pin · Del remove"
                    .printf (total, total == 1 ? "" : "s");
            } else {
                status.label = "%u of %u match".printf (shown, total);
            }
        }

        private void select_first () {
            var row = list.get_row_at_index (0);
            if (row != null) {
                list.select_row (row);
            }
        }

        private ItemRow? selected_row () {
            return list.get_selected_row () as ItemRow;
        }

        private void move_selection (int delta) {
            var row = list.get_selected_row ();
            int index = row != null ? row.get_index () : -1;
            var next = list.get_row_at_index (index + delta);
            if (next != null) {
                list.select_row (next);
                next.grab_focus ();
                search.grab_focus_without_selecting ();
            }
        }

        private void activate_selected (bool paste) {
            var row = selected_row ();
            if (row == null) {
                return;
            }
            var item = row.item;
            hide_popup ();
            item_chosen (item, paste);
        }

        private bool on_key_press (Gdk.EventKey event) {
            bool ctrl = (event.state & Gdk.ModifierType.CONTROL_MASK) != 0;
            var key = event.keyval;

            switch (key) {
                case Gdk.Key.Escape:
                    hide_popup ();
                    return true;
                case Gdk.Key.Down:
                    move_selection (1);
                    return true;
                case Gdk.Key.Up:
                    move_selection (-1);
                    return true;
                case Gdk.Key.Page_Down:
                    move_selection (10);
                    return true;
                case Gdk.Key.Page_Up:
                    move_selection (-10);
                    return true;
                case Gdk.Key.Return:
                case Gdk.Key.KP_Enter:
                    activate_selected (!ctrl && config.paste_on_select);
                    return true;
                case Gdk.Key.Delete:
                    var row = selected_row ();
                    if (row != null) {
                        store.remove (row.item);
                    }
                    return true;
                default:
                    break;
            }

            if (ctrl && (key == Gdk.Key.p || key == Gdk.Key.P)) {
                var row = selected_row ();
                if (row != null) {
                    store.toggle_pin (row.item);
                }
                return true;
            }
            if (ctrl && (key == Gdk.Key.l || key == Gdk.Key.L)) {
                store.clear ();
                return true;
            }
            return false;
        }

        private class ItemRow : Gtk.ListBoxRow {
            public HistoryItem item { get; construct; }

            public ItemRow (HistoryItem item) {
                Object (item: item);

                var row = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6);
                row.margin = 6;

                if (item.pinned) {
                    var pin = new Gtk.Image.from_icon_name (
                        "view-pin-symbolic", Gtk.IconSize.MENU);
                    pin.tooltip_text = "Pinned";
                    row.pack_start (pin, false, false, 0);
                }

                var label = new Gtk.Label (item.preview ());
                label.halign = Gtk.Align.START;
                label.xalign = 0;
                label.ellipsize = Pango.EllipsizeMode.END;
                label.single_line_mode = true;
                row.pack_start (label, true, true, 0);

                tooltip_text = item.describe ();
                add (row);
            }
        }
    }
}
