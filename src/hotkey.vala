/* Funes - global shortcut registration.
 *
 * Instead of grabbing the key in-process (libkeybinder / XGrabKey), Funes
 * registers a Cinnamon custom keybinding that runs `funes toggle`. Benefits:
 * no extra build dependency, the shortcut is visible and editable in
 * Keyboard Settings, and it also works when Funes is not running (GApplication
 * DBus activation starts it).
 */

namespace Funes {

    public class Hotkey : GLib.Object {
        private const string KB_SCHEMA = "org.cinnamon.desktop.keybindings";
        private const string CUSTOM_SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding";
        private const string CUSTOM_PATH_PREFIX = "/org/cinnamon/desktop/keybindings/custom-keybindings/";
        private const string COMMAND = "funes toggle";
        private const string NAME = "Funes clipboard history";

        public static bool cinnamon_available () {
            var source = GLib.SettingsSchemaSource.get_default ();
            return source != null && source.lookup (KB_SCHEMA, true) != null;
        }

        /* Make sure a Cinnamon custom keybinding exists for `accel`.
         * Returns true when the binding is in place. */
        public static bool ensure (string accel) {
            if (!cinnamon_available ()) {
                warning ("Funes: Cinnamon keybinding schema not found; " +
                         "bind '%s' to '%s' manually", accel, COMMAND);
                return false;
            }

            var kb = new GLib.Settings (KB_SCHEMA);
            var list = kb.get_strv ("custom-list");

            // Reuse our own entry if it already exists.
            foreach (var entry in list) {
                var id = basename_of (entry);
                if (id == "__dummy__" || id == "") {
                    continue;
                }
                var child = custom_settings (id);
                if (child.get_string ("command") == COMMAND) {
                    apply (child, accel);
                    return true;
                }
            }

            var id = next_free_id (list);
            var slot = custom_settings (id);
            apply (slot, accel);

            var updated = new GLib.GenericArray<string> ();
            foreach (var entry in list) {
                if (basename_of (entry) != id) {
                    updated.add (entry);
                }
            }
            // Cinnamon stores either bare ids ("custom0") or full paths;
            // bare ids are what cinnamon-settings writes.
            updated.add (id);
            kb.set_strv ("custom-list", strv_of (updated));
            GLib.Settings.sync ();
            message ("Funes: registered '%s' -> '%s' (%s)", accel, COMMAND, id);
            return true;
        }

        /* Remove the Funes custom keybinding. */
        public static void unregister () {
            if (!cinnamon_available ()) {
                return;
            }
            var kb = new GLib.Settings (KB_SCHEMA);
            var list = kb.get_strv ("custom-list");
            var kept = new GLib.GenericArray<string> ();
            foreach (var entry in list) {
                var id = basename_of (entry);
                if (id == "" ) {
                    continue;
                }
                if (id != "__dummy__" && custom_settings (id).get_string ("command") == COMMAND) {
                    var child = custom_settings (id);
                    child.reset ("binding");
                    child.reset ("command");
                    child.reset ("name");
                    continue;
                }
                kept.add (entry);
            }
            kb.set_strv ("custom-list", strv_of (kept));
            GLib.Settings.sync ();
        }

        private static void apply (GLib.Settings slot, string accel) {
            slot.set_string ("name", NAME);
            slot.set_string ("command", COMMAND);
            slot.set_strv ("binding", { accel });
        }

        private static GLib.Settings custom_settings (string id) {
            return new GLib.Settings.with_path (CUSTOM_SCHEMA, CUSTOM_PATH_PREFIX + id + "/");
        }

        private static string basename_of (string entry) {
            var trimmed = entry.has_suffix ("/") ? entry.substring (0, entry.length - 1) : entry;
            var idx = trimmed.last_index_of_char ('/');
            return idx < 0 ? trimmed : trimmed.substring (idx + 1);
        }

        private static string next_free_id (string[] list) {
            for (int i = 0; i < 100; i++) {
                var candidate = "custom%d".printf (i);
                bool taken = false;
                foreach (var entry in list) {
                    if (basename_of (entry) == candidate) {
                        taken = true;
                        break;
                    }
                }
                if (!taken) {
                    return candidate;
                }
            }
            return "funes0";
        }

        private static string[] strv_of (GLib.GenericArray<string> arr) {
            var result = new string[arr.length];
            for (uint i = 0; i < arr.length; i++) {
                result[i] = arr.get ((int) i);
            }
            return result;
        }
    }
}
