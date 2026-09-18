/* Funes - tray icon.
 *
 * XAppStatusIcon talks to the Cinnamon applet over DBus and falls back to
 * Gtk.StatusIcon when no XApp-aware applet is present.
 *
 * Left click opens the history popup, right click the actions menu. Note that
 * XAppStatusIcon only emits ::activate when no *primary* menu is set, so the
 * menu is registered as the secondary (right button) menu only.
 */

namespace Funes {

    public class Tray : GLib.Object {
        public signal void open_requested ();
        public signal void settings_requested ();
        public signal void clear_requested ();
        public signal void quit_requested ();

        private XApp.StatusIcon icon;
        private Gtk.Menu menu;

        public Tray () {
            icon = new XApp.StatusIcon ();
            icon.set_name (Constants.APP_NAME);
            icon.set_icon_name ("edit-paste");
            icon.set_tooltip_text ("Funes — clipboard history");

            menu = build_menu ();
            icon.set_primary_menu (null);
            icon.set_secondary_menu (menu);
            icon.activate.connect ((button, time) => {
                open_requested ();
            });
        }

        private Gtk.Menu build_menu () {
            var m = new Gtk.Menu ();

            var open = new Gtk.MenuItem.with_label ("Open Funes");
            open.activate.connect (() => open_requested ());
            m.append (open);

            m.append (new Gtk.SeparatorMenuItem ());

            var clear = new Gtk.MenuItem.with_label ("Clear History");
            clear.activate.connect (() => clear_requested ());
            m.append (clear);

            var prefs = new Gtk.MenuItem.with_label ("Settings…");
            prefs.activate.connect (() => settings_requested ());
            m.append (prefs);

            m.append (new Gtk.SeparatorMenuItem ());

            var quit = new Gtk.MenuItem.with_label ("Quit");
            quit.activate.connect (() => quit_requested ());
            m.append (quit);

            m.show_all ();
            return m;
        }

        public void set_count (uint count) {
            icon.set_tooltip_text ("Funes — %u item%s".printf (count, count == 1 ? "" : "s"));
        }
    }
}
