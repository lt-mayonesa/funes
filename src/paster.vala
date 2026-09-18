/* Funes - paste injection (in-process XTEST, no external tools).
 *
 * Mirrors CopyQ's X11 strategy (src/platform/x11/x11platformwindow.cpp):
 *
 *   1. Remember the target window (_NET_ACTIVE_WINDOW) *before* the popup
 *      steals focus.
 *   2. Wait briefly for it to regain focus; if it does not, raise it
 *      (_NET_ACTIVE_WINDOW client message + XRaiseWindow + XSetInputFocus)
 *      and wait again.
 *   3. Wait for the user to release every keyboard modifier - the global
 *      shortcut means Super (and maybe Shift) is still held, which would turn
 *      the injected Shift+Insert into something else entirely.
 *   4. Fake the keystroke with XTEST: modifier down, key down, hold, key up,
 *      modifier up.
 *
 * Default keystroke is Shift+Insert, like CopyQ: Ctrl+V is not a paste binding
 * in VTE terminals (they use Ctrl+Shift+V), whereas Shift+Insert pastes in GTK,
 * Qt, VTE, browsers and Java apps alike. Windows whose WM_CLASS matches
 * `paste-ctrl-v-class-regex` get Ctrl+V instead.
 */

namespace Funes {

    public class Paster : GLib.Object {
        /* X keysyms (X11/keysymdef.h). */
        private const ulong XK_SHIFT_L = 0xffe1;
        private const ulong XK_SHIFT_R = 0xffe2;
        private const ulong XK_CONTROL_L = 0xffe3;
        private const ulong XK_CONTROL_R = 0xffe4;
        private const ulong XK_META_L = 0xffe7;
        private const ulong XK_META_R = 0xffe8;
        private const ulong XK_ALT_L = 0xffe9;
        private const ulong XK_ALT_R = 0xffea;
        private const ulong XK_SUPER_L = 0xffeb;
        private const ulong XK_SUPER_R = 0xffec;
        private const ulong XK_HYPER_L = 0xffed;
        private const ulong XK_HYPER_R = 0xffee;
        private const ulong XK_INSERT = 0xff63;
        private const ulong XK_V = 0x0056;

        /* CopyQ's default timings. */
        private const int WAIT_BEFORE_RAISE_MS = 20;
        private const int WAIT_RAISED_MS = 150;
        private const int WAIT_AFTER_RAISED_MS = 50;
        private const int KEY_PRESS_TIME_MS = 50;
        private const int WAIT_MODIFIERS_RELEASED_MS = 2000;
        private const int POLL_INTERVAL_MS = 10;

        private static bool warned_no_xtest = false;
        private static bool warned_wayland = false;

        /* Window that had focus when the popup was opened. */
        private X.Window target = X.None;

        private unowned X.Display? xdisplay () {
            var display = Gdk.Display.get_default ();
            if (display == null || !(display is Gdk.X11.Display)) {
                return null;
            }
            return ((Gdk.X11.Display) display).get_xdisplay ();
        }

        public static bool on_wayland () {
            var session = GLib.Environment.get_variable ("XDG_SESSION_TYPE");
            return session != null && session.down () == "wayland";
        }

        /* True when keystrokes can be injected at all. */
        public bool available () {
            unowned X.Display? dpy = xdisplay ();
            if (dpy == null) {
                return false;
            }
            int ev, err, major, minor;
            return FunesX.test_query_extension (dpy, out ev, out err, out major, out minor);
        }

        /* Record the currently focused window. Call before showing the popup. */
        public void remember_target () {
            unowned X.Display? dpy = xdisplay ();
            target = (dpy == null) ? X.None : active_window (dpy);
        }

        public string target_class () {
            unowned X.Display? dpy = xdisplay ();
            if (dpy == null || target == X.None) {
                return "";
            }
            return window_class (dpy, target);
        }

        /* Copy-and-paste: assumes the text is already on the clipboard. */
        public void paste (string ctrl_v_class_regex = "") {
            if (on_wayland ()) {
                if (!warned_wayland) {
                    warned_wayland = true;
                    warning ("Funes: running on Wayland; keystroke injection only " +
                             "reaches XWayland clients, so the item was copied but " +
                             "not pasted.");
                }
                return;
            }

            unowned X.Display? dpy = xdisplay ();
            if (dpy == null) {
                return;
            }
            if (!available ()) {
                if (!warned_no_xtest) {
                    warned_no_xtest = true;
                    warning ("Funes: X server has no XTEST extension; item copied " +
                             "but not pasted.");
                }
                return;
            }

            bool use_ctrl_v = matches_class (dpy, ctrl_v_class_regex);
            ulong modifier = use_ctrl_v ? XK_CONTROL_L : XK_SHIFT_L;
            ulong key = use_ctrl_v ? XK_V : XK_INSERT;

            // Done on an idle/timeout chain so the popup can finish hiding and
            // the window manager can restore focus first.
            GLib.Timeout.add (WAIT_BEFORE_RAISE_MS, () => {
                inject (dpy, modifier, key);
                return GLib.Source.REMOVE;
            });
        }

        /* --- internals --- */

        private void inject (X.Display dpy, ulong modifier, ulong key) {
            if (target != X.None && active_window (dpy) != target) {
                raise_target (dpy);
                if (!wait_for_focus (dpy, WAIT_RAISED_MS)) {
                    warning ("Funes: could not refocus the paste target window");
                }
                spin (WAIT_AFTER_RAISED_MS);
            }

            if (!wait_for_modifiers_released (dpy)) {
                warning ("Funes: modifiers still held after %dms; paste skipped",
                         WAIT_MODIFIERS_RELEASED_MS);
                return;
            }

            uint mod_code = dpy.keysym_to_keycode (modifier);
            uint key_code = dpy.keysym_to_keycode (key);
            if (mod_code == 0 || key_code == 0) {
                warning ("Funes: no keycode for the paste shortcut");
                return;
            }

            FunesX.test_fake_key_event (dpy, mod_code, true, 0);
            FunesX.sync (dpy, false);
            FunesX.test_fake_key_event (dpy, key_code, true, 0);
            FunesX.sync (dpy, false);
            // Some apps (Chrome's address bar) need the key held briefly.
            FunesX.test_fake_key_event (dpy, key_code, false, KEY_PRESS_TIME_MS);
            FunesX.sync (dpy, false);
            FunesX.test_fake_key_event (dpy, mod_code, false, 0);
            FunesX.sync (dpy, false);
        }

        private X.Window active_window (X.Display dpy) {
            var prop = dpy.intern_atom ("_NET_ACTIVE_WINDOW", true);
            if (prop == X.None) {
                X.Window focus;
                int revert;
                dpy.get_input_focus (out focus, out revert);
                return focus;
            }

            X.Atom actual_type;
            int actual_format;
            ulong nitems, bytes_after;
            void* data = null;
            var status = dpy.get_window_property (
                dpy.default_root_window (), prop, 0, 1, false, X.XA_WINDOW,
                out actual_type, out actual_format, out nitems, out bytes_after,
                out data);

            X.Window result = X.None;
            if (status == X.Success && data != null && nitems == 1 && actual_format == 32) {
                result = *((X.Window*) data);
            }
            if (data != null) {
                FunesX.free (data);
            }
            return result;
        }

        private void raise_target (X.Display dpy) {
            X.WindowAttributes attrs;
            dpy.get_window_attributes (target, out attrs);
            if (attrs.map_state != 2 /* IsViewable */) {
                return;
            }

            X.Event ev = {};
            ev.type = 33; /* ClientMessage */
            ev.xclient.type = 33;
            ev.xclient.display = dpy;
            ev.xclient.window = target;
            ev.xclient.message_type = dpy.intern_atom ("_NET_ACTIVE_WINDOW", false);
            ev.xclient.format = 32;
            ev.xclient.l[0] = 2; /* source indication: pager */
            ev.xclient.l[1] = 0;
            ev.xclient.l[2] = 0;
            ev.xclient.l[3] = 0;
            ev.xclient.l[4] = 0;

            dpy.send_event (dpy.default_root_window (), false,
                            X.EventMask.SubstructureNotifyMask
                            | X.EventMask.SubstructureRedirectMask,
                            ref ev);
            dpy.raise_window (target);
            dpy.set_input_focus (target, X.RevertTo.PointerRoot, (int) X.CURRENT_TIME);
            dpy.flush ();
        }

        private bool wait_for_focus (X.Display dpy, int timeout_ms) {
            int waited = 0;
            while (waited < timeout_ms) {
                if (active_window (dpy) == target) {
                    return true;
                }
                spin (POLL_INTERVAL_MS);
                waited += POLL_INTERVAL_MS;
            }
            return active_window (dpy) == target;
        }

        private bool wait_for_modifiers_released (X.Display dpy) {
            int waited = 0;
            while (modifier_pressed (dpy) && waited < WAIT_MODIFIERS_RELEASED_MS) {
                spin (POLL_INTERVAL_MS);
                waited += POLL_INTERVAL_MS;
            }
            return !modifier_pressed (dpy);
        }

        private bool modifier_pressed (X.Display dpy) {
            var keymap = new char[32];
            FunesX.query_keymap (dpy, keymap);

            ulong[] mods = {
                XK_SHIFT_L, XK_SHIFT_R, XK_CONTROL_L, XK_CONTROL_R,
                XK_META_L, XK_META_R, XK_ALT_L, XK_ALT_R,
                XK_SUPER_L, XK_SUPER_R, XK_HYPER_L, XK_HYPER_R,
            };
            foreach (var keysym in mods) {
                uint code = dpy.keysym_to_keycode (keysym);
                if (code == 0) {
                    continue;
                }
                if (((keymap[code >> 3] >> (int) (code & 7)) & 1) != 0) {
                    return true;
                }
            }
            return false;
        }

        /* Keep the main loop responsive while waiting on the X server. */
        private void spin (int ms) {
            var deadline = GLib.get_monotonic_time () + (int64) ms * 1000;
            while (GLib.get_monotonic_time () < deadline) {
                while (Gtk.events_pending ()) {
                    Gtk.main_iteration_do (false);
                }
                GLib.Thread.usleep (1000);
            }
        }

        private string window_class (X.Display dpy, X.Window window) {
            FunesX.ClassHint hint;
            if (FunesX.get_class_hint (dpy, window, out hint) == 0) {
                return "";
            }
            var res_name = hint.res_name != null ? hint.res_name.dup () : "";
            var res_class = hint.res_class != null ? hint.res_class.dup () : "";
            if (hint.res_name != null) {
                FunesX.free ((void*) hint.res_name);
            }
            if (hint.res_class != null) {
                FunesX.free ((void*) hint.res_class);
            }
            return "%s.%s".printf (res_name, res_class);
        }

        private bool matches_class (X.Display dpy, string pattern) {
            if (pattern.strip () == "" || target == X.None) {
                return false;
            }
            var wm_class = window_class (dpy, target);
            if (wm_class == "") {
                return false;
            }
            try {
                // Matched against "res_name.res_class",
                // e.g. "gnome-terminal-server.Gnome-terminal".
                return new GLib.Regex (pattern).match (wm_class);
            } catch (GLib.RegexError e) {
                warning ("Funes: bad paste-ctrl-v-class-regex /%s/: %s",
                         pattern, e.message);
                return false;
            }
        }
    }
}
