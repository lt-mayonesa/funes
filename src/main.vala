/* Funes - clipboard history that never forgets.
 *
 * Single-instance GApplication: `funes toggle` from the global shortcut is
 * delivered to the running instance over DBus (and starts one if needed).
 */

namespace Funes {

    public class App : Gtk.Application {
        private Config config;
        private HistoryStore store;
        private ClipboardMonitor monitor;
        private Tray tray;
        private PopupWindow? popup = null;
        private SettingsDialog? settings_dialog = null;
        private bool started = false;

        public App () {
            Object (application_id: Constants.APP_ID,
                    flags: GLib.ApplicationFlags.HANDLES_COMMAND_LINE);
        }

        protected override void startup () {
            base.startup ();

            config = new Config ();
            store = new JsonFileStore (JsonFileStore.default_path (), config.history_size);

            config.settings.changed["history-size"].connect (() => {
                store.history_size = config.history_size;
            });

            monitor = new ClipboardMonitor (config);
            monitor.captured.connect ((text) => {
                store.add (text);
                tray.set_count (store.size ());
            });

            tray = new Tray ();
            tray.open_requested.connect (() => show_popup ());
            tray.settings_requested.connect (() => show_settings ());
            tray.clear_requested.connect (() => {
                store.clear ();
                tray.set_count (store.size ());
            });
            tray.quit_requested.connect (() => {
                store.flush ();
                quit ();
            });
            tray.set_count (store.size ());

            monitor.start ();

            if (config.launch_at_login && !Autostart.enabled ()) {
                Autostart.set_enabled (true);
            }
            Hotkey.ensure (config.hotkey);

            // Tray-only app: keep running with no window open.
            hold ();
            started = true;
        }

        protected override void activate () {
            // Plain `funes` just starts the daemon; nothing to show.
            if (!started) {
                startup ();
            }
        }

        protected override int command_line (GLib.ApplicationCommandLine cmdline) {
            var args = cmdline.get_arguments ();
            var verb = args.length > 1 ? args[1] : "";

            switch (verb) {
                case "":
                    activate ();
                    break;
                case "toggle":
                    toggle_popup ();
                    break;
                case "show":
                    show_popup ();
                    break;
                case "clear":
                    store.clear ();
                    tray.set_count (store.size ());
                    store.flush ();
                    break;
                case "settings":
                    show_settings ();
                    break;
                case "quit":
                    store.flush ();
                    quit ();
                    break;
                default:
                    cmdline.printerr ("funes: unknown command '%s'\n", verb);
                    cmdline.printerr (
                        "usage: funes [toggle|show|clear|settings|quit|--version]\n");
                    return 2;
            }
            return 0;
        }

        private PopupWindow ensure_popup () {
            if (popup == null) {
                popup = new PopupWindow (store, config);
                popup.item_chosen.connect (on_item_chosen);
                add_window (popup);
            }
            return popup;
        }

        private void show_popup () {
            ensure_popup ().show_popup ();
        }

        private void toggle_popup () {
            ensure_popup ().toggle ();
        }

        private void on_item_chosen (HistoryItem item, bool paste) {
            monitor.set_text (item.text);
            store.touch (item);
            if (paste) {
                Paster.paste ();
            }
        }

        private void show_settings () {
            if (settings_dialog != null) {
                settings_dialog.present ();
                return;
            }
            settings_dialog = new SettingsDialog (config);
            settings_dialog.destroy.connect (() => {
                settings_dialog = null;
            });
            settings_dialog.present ();
        }

        protected override void shutdown () {
            if (store != null) {
                store.flush ();
            }
            base.shutdown ();
        }
    }

    public static int main (string[] args) {
        // Handle --version locally so it works without DBus round-trips.
        foreach (var arg in args) {
            if (arg == "--version" || arg == "-V") {
                print ("funes %s\n", VERSION);
                return 0;
            }
            if (arg == "--help" || arg == "-h") {
                print ("""Funes %s — clipboard history that never forgets

usage:
  funes              start the tray daemon
  funes toggle       show/hide the history popup
  funes show         show the history popup
  funes clear        clear history (pinned items are kept)
  funes settings     open the settings dialog
  funes quit         stop the running instance
  funes --version    print version
""", VERSION);
                return 0;
            }
        }

        GLib.Environment.set_application_name (Constants.APP_NAME);
        GLib.Environment.set_prgname ("funes");
        var app = new App ();
        return app.run (args);
    }
}
