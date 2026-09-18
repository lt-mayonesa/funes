/* Funes - preferences dialog. */

namespace Funes {

    public class SettingsDialog : Gtk.Dialog {
        private Config config;

        public SettingsDialog (Config config) {
            Object (title: "Funes Settings",
                    use_header_bar: 1,
                    resizable: false);
            this.config = config;

            add_button ("Close", Gtk.ResponseType.CLOSE);
            response.connect (() => destroy ());

            var grid = new Gtk.Grid ();
            grid.row_spacing = 8;
            grid.column_spacing = 12;
            grid.margin = 16;

            int row = 0;

            // History size
            var size_spin = new Gtk.SpinButton.with_range (10, 10000, 10);
            size_spin.value = config.history_size;
            size_spin.value_changed.connect (() => {
                config.history_size = (int) size_spin.value;
            });
            add_row (grid, ref row, "History size", size_spin,
                     "Oldest unpinned items are dropped past this count.");

            // Hotkey
            var hotkey_entry = new Gtk.Entry ();
            hotkey_entry.text = config.hotkey;
            hotkey_entry.width_chars = 16;
            hotkey_entry.tooltip_text = "GTK accelerator syntax, e.g. <Super>v or <Shift><Super>c";
            hotkey_entry.activate.connect (() => apply_hotkey (hotkey_entry));
            hotkey_entry.focus_out_event.connect (() => {
                apply_hotkey (hotkey_entry);
                return false;
            });
            add_row (grid, ref row, "Global shortcut", hotkey_entry,
                     "Registered as a Cinnamon custom keybinding.");

            // Paste on select
            var paste_switch = new Gtk.Switch ();
            paste_switch.active = config.paste_on_select;
            paste_switch.halign = Gtk.Align.START;
            paste_switch.notify["active"].connect (() => {
                config.paste_on_select = paste_switch.active;
            });
            var paster = new Paster ();
            var can_paste = paster.available () && !Paster.on_wayland ();
            var paste_hint = can_paste
                ? "Injects Shift+Insert into the previously focused window."
                : (Paster.on_wayland ()
                    ? "Unavailable: keystroke injection needs an X11 session."
                    : "Unavailable: the X server has no XTEST extension.");
            paste_switch.sensitive = can_paste;
            add_row (grid, ref row, "Paste on select", paste_switch, paste_hint);

            // Ctrl+V override per WM_CLASS
            var ctrl_v_entry = new Gtk.Entry ();
            ctrl_v_entry.text = config.paste_ctrl_v_class_regex;
            ctrl_v_entry.placeholder_text = "Chromium|code";
            ctrl_v_entry.width_chars = 24;
            ctrl_v_entry.activate.connect (() => {
                config.paste_ctrl_v_class_regex = ctrl_v_entry.text.strip ();
            });
            ctrl_v_entry.focus_out_event.connect (() => {
                config.paste_ctrl_v_class_regex = ctrl_v_entry.text.strip ();
                return false;
            });
            add_row (grid, ref row, "Paste with Ctrl+V in", ctrl_v_entry,
                     "Regex on WM_CLASS (\"res_name.res_class\"). Matching windows " +
                     "get Ctrl+V instead of Shift+Insert.");

            // PRIMARY selection
            var primary_switch = new Gtk.Switch ();
            primary_switch.active = config.paste_sets_primary;
            primary_switch.halign = Gtk.Align.START;
            primary_switch.notify["active"].connect (() => {
                config.paste_sets_primary = primary_switch.active;
            });
            add_row (grid, ref row, "Set PRIMARY on paste", primary_switch,
                     "Needed by xterm/urxvt, whose Shift+Insert pastes the mouse " +
                     "selection. Replaces your current selection.");

            // Re-own clipboard
            var reown_switch = new Gtk.Switch ();
            reown_switch.active = config.reown_clipboard;
            reown_switch.halign = Gtk.Align.START;
            reown_switch.notify["active"].connect (() => {
                config.reown_clipboard = reown_switch.active;
            });
            add_row (grid, ref row, "Keep clipboard alive", reown_switch,
                     "Funes takes clipboard ownership so copied text survives the source app closing.");

            // Autostart
            var autostart_switch = new Gtk.Switch ();
            autostart_switch.active = Autostart.enabled ();
            autostart_switch.halign = Gtk.Align.START;
            autostart_switch.notify["active"].connect (() => {
                config.launch_at_login = autostart_switch.active;
                Autostart.set_enabled (autostart_switch.active);
            });
            add_row (grid, ref row, "Launch at login", autostart_switch, null);

            // Ignore everything
            var ignore_switch = new Gtk.Switch ();
            ignore_switch.active = config.ignore_enabled;
            ignore_switch.halign = Gtk.Align.START;
            ignore_switch.notify["active"].connect (() => {
                config.ignore_enabled = ignore_switch.active;
            });
            add_row (grid, ref row, "Pause capturing", ignore_switch,
                     "Clipboard changes are not recorded while on.");

            // Ignore regexes
            var ignore_entry = new Gtk.Entry ();
            ignore_entry.text = string.joinv (" | ", config.ignore_regexes);
            ignore_entry.placeholder_text = "regex | regex";
            ignore_entry.width_chars = 24;
            ignore_entry.activate.connect (() => apply_ignores (ignore_entry));
            ignore_entry.focus_out_event.connect (() => {
                apply_ignores (ignore_entry);
                return false;
            });
            add_row (grid, ref row, "Ignore matching", ignore_entry,
                     "Pipe-separated regexes. Password-manager hints are always ignored.");

            get_content_area ().add (grid);
            show_all ();
        }

        private void apply_hotkey (Gtk.Entry entry) {
            var accel = entry.text.strip ();
            if (accel == "" || accel == config.hotkey) {
                return;
            }
            uint key;
            Gdk.ModifierType mods;
            Gtk.accelerator_parse (accel, out key, out mods);
            if (key == 0) {
                entry.text = config.hotkey;
                return;
            }
            config.hotkey = accel;
            Hotkey.ensure (accel);
        }

        private void apply_ignores (Gtk.Entry entry) {
            var parts = entry.text.split ("|");
            var cleaned = new GLib.GenericArray<string> ();
            foreach (var part in parts) {
                var p = part.strip ();
                if (p != "") {
                    cleaned.add (p);
                }
            }
            var result = new string[cleaned.length];
            for (uint i = 0; i < cleaned.length; i++) {
                result[i] = cleaned.get ((int) i);
            }
            config.ignore_regexes = result;
        }

        private void add_row (Gtk.Grid grid, ref int row, string label,
                              Gtk.Widget control, string? hint) {
            var lbl = new Gtk.Label (label);
            lbl.halign = Gtk.Align.END;
            grid.attach (lbl, 0, row, 1, 1);
            grid.attach (control, 1, row, 1, 1);
            row++;

            if (hint != null) {
                var hint_label = new Gtk.Label (hint);
                hint_label.halign = Gtk.Align.START;
                hint_label.xalign = 0;
                hint_label.max_width_chars = 44;
                hint_label.wrap = true;
                hint_label.get_style_context ().add_class (Gtk.STYLE_CLASS_DIM_LABEL);
                grid.attach (hint_label, 1, row, 1, 1);
                row++;
            }
        }
    }
}
