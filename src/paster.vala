/* Funes - paste injection.
 *
 * X11 has no "paste into the focused window" API, so the keystroke is
 * synthesized. xdotool (XTEST under the hood) is used to avoid a libXtst VAPI;
 * if it is missing, Funes degrades to copy-only and says so once.
 */

namespace Funes {

    public class Paster : GLib.Object {
        /* Delay before injecting: the popup must be gone and focus restored to
         * the previously focused window first. */
        private const uint PASTE_DELAY_MS = 120;

        private static bool warned_missing = false;

        public static bool available () {
            return GLib.Environment.find_program_in_path ("xdotool") != null;
        }

        /* Synthesize Ctrl+V after a short delay. */
        public static void paste () {
            if (!available ()) {
                if (!warned_missing) {
                    warned_missing = true;
                    warning ("Funes: xdotool not found; item copied but not pasted. " +
                             "Install it with: sudo apt install xdotool");
                }
                return;
            }

            GLib.Timeout.add (PASTE_DELAY_MS, () => {
                try {
                    GLib.Process.spawn_async (
                        null,
                        { "xdotool", "key", "--clearmodifiers", "ctrl+v" },
                        null,
                        GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.DO_NOT_REAP_CHILD,
                        null,
                        null);
                } catch (GLib.SpawnError e) {
                    warning ("Funes: cannot run xdotool: %s", e.message);
                }
                return GLib.Source.REMOVE;
            });
        }
    }
}
