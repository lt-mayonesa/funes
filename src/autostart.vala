/* Funes - launch at login via ~/.config/autostart. */

namespace Funes {

    public class Autostart : GLib.Object {
        private const string FILENAME = "org.funes.Funes.desktop";

        private static GLib.File target () {
            var dir = GLib.Path.build_filename (GLib.Environment.get_user_config_dir (), "autostart");
            return GLib.File.new_for_path (GLib.Path.build_filename (dir, FILENAME));
        }

        /* Prefer an installed `funes`; fall back to the running binary so the
         * entry also works when running from a build tree. */
        private static string executable_path () {
            var in_path = GLib.Environment.find_program_in_path ("funes");
            if (in_path != null) {
                return in_path;
            }
            try {
                var self = GLib.FileUtils.read_link ("/proc/self/exe");
                if (self != null && self != "") {
                    return self;
                }
            } catch (GLib.FileError e) {
                // fall through
            }
            return "funes";
        }

        public static bool enabled () {
            return target ().query_exists ();
        }

        public static void set_enabled (bool enable) {
            var file = target ();
            try {
                if (!enable) {
                    if (file.query_exists ()) {
                        file.delete ();
                    }
                    return;
                }
                if (file.query_exists ()) {
                    return;
                }
                var parent = file.get_parent ();
                if (parent != null && !parent.query_exists ()) {
                    parent.make_directory_with_parents ();
                }
                var exec = executable_path ();
                var contents = """[Desktop Entry]
Type=Application
Name=Funes
Comment=Clipboard history that never forgets
Exec=%s
Icon=edit-paste
Terminal=false
Categories=Utility;GTK;
X-GNOME-Autostart-enabled=true
NoDisplay=true
""".printf (exec);
                GLib.FileUtils.set_contents (file.get_path (), contents);
            } catch (GLib.Error e) {
                warning ("Funes: cannot update autostart entry: %s", e.message);
            }
        }
    }
}
