/* Funes - clipboard watcher.
 *
 * Uses Gtk.Clipboard's owner-change signal, which on X11 is driven by the
 * XFixes extension: no polling (unlike Maccy's 500ms NSPasteboard timer).
 *
 * Two subtleties handled here:
 *   1. Self-ignore guard. Funes writes to the clipboard itself (on paste and
 *      when re-owning), which triggers owner-change again. Without the guard
 *      that is an infinite loop.
 *   2. Re-owning. On X11 clipboard contents die with the owning client, so
 *      Funes takes ownership of the text after capture; copied text then
 *      survives the source application exiting (Klipper/GPaste behaviour).
 */

namespace Funes {

    public class ClipboardMonitor : GLib.Object {
        /* MIME hints used by password managers. KeePassXC/Firefox/Bitwarden set
         * `x-kde-passwordManagerHint`; GTK rejects that as an invalid MIME type
         * so the `text/`-prefixed variant is also checked. */
        private const string[] SECRET_TARGETS = {
            "x-kde-passwordManagerHint",
            "text/x-kde-passwordManagerHint",
            "application/x-nextcloud-talk-secret",
            "org.nspasteboard.ConcealedType",
        };

        public signal void captured (string text);

        private Gtk.Clipboard clipboard;
        private Config config;
        private bool self_owned = false;
        private string last_seen = "";

        public ClipboardMonitor (Config config) {
            this.config = config;
            this.clipboard = Gtk.Clipboard.get (Gdk.SELECTION_CLIPBOARD);
            clipboard.owner_change.connect (on_owner_change);
        }

        public void start () {
            // Pick up whatever is already on the clipboard at startup.
            on_owner_change (null);
        }

        /* Put text on the clipboard without recording it again.
         *
         * `also_primary` additionally sets the PRIMARY selection, which matters
         * for xterm/urxvt: their Shift+Insert pastes PRIMARY, not CLIPBOARD. */
        public void set_text (string text, bool also_primary = false) {
            self_owned = true;
            last_seen = text;
            clipboard.set_text (text, -1);
            clipboard.store ();
            if (also_primary) {
                Gtk.Clipboard.get (Gdk.SELECTION_PRIMARY).set_text (text, -1);
            }
        }

        private void on_owner_change (Gdk.EventOwnerChange? event) {
            if (self_owned) {
                self_owned = false;
                return;
            }
            if (config.ignore_enabled) {
                return;
            }

            clipboard.request_targets ((cb, atoms) => {
                if (is_secret (atoms)) {
                    debug ("Funes: skipping clipboard entry marked as secret");
                    return;
                }
                cb.request_text ((_cb, text) => {
                    handle_text (text);
                });
            });
        }

        private bool is_secret (Gdk.Atom[]? atoms) {
            if (atoms == null) {
                return false;
            }
            foreach (var atom in atoms) {
                var name = atom.name ();
                foreach (var hint in SECRET_TARGETS) {
                    if (name == hint) {
                        return true;
                    }
                }
            }
            return false;
        }

        private void handle_text (string? text) {
            if (text == null) {
                return;
            }
            if (text.strip () == "") {
                return;
            }
            if (text.length > config.max_item_bytes) {
                debug ("Funes: skipping %s clipboard entry (over limit)",
                       GLib.format_size ((uint64) text.length));
                return;
            }
            if (text == last_seen) {
                return;
            }
            foreach (var pattern in config.ignore_regexes) {
                if (pattern.strip () == "") {
                    continue;
                }
                try {
                    if (new GLib.Regex (pattern).match (text)) {
                        debug ("Funes: ignoring entry matching /%s/", pattern);
                        return;
                    }
                } catch (GLib.RegexError e) {
                    warning ("Funes: bad ignore regex /%s/: %s", pattern, e.message);
                }
            }

            last_seen = text;
            captured (text);

            if (config.reown_clipboard) {
                // Take ownership so the text outlives the source application.
                self_owned = true;
                clipboard.set_text (text, -1);
            }
        }
    }
}
