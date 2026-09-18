/* Funes - thin wrapper over GSettings. */

namespace Funes {

    public class Config : GLib.Object {
        public GLib.Settings settings { get; private set; }

        public Config () {
            settings = new GLib.Settings (Constants.APP_ID);
        }

        public int history_size {
            get { return settings.get_int ("history-size"); }
            set { settings.set_int ("history-size", value); }
        }

        public string hotkey {
            owned get { return settings.get_string ("hotkey"); }
            set { settings.set_string ("hotkey", value); }
        }

        public bool paste_on_select {
            get { return settings.get_boolean ("paste-on-select"); }
            set { settings.set_boolean ("paste-on-select", value); }
        }

        public bool launch_at_login {
            get { return settings.get_boolean ("launch-at-login"); }
            set { settings.set_boolean ("launch-at-login", value); }
        }

        public int popup_width {
            get { return settings.get_int ("popup-width"); }
            set { settings.set_int ("popup-width", value); }
        }

        public int popup_height {
            get { return settings.get_int ("popup-height"); }
            set { settings.set_int ("popup-height", value); }
        }

        public bool remember_size {
            get { return settings.get_boolean ("remember-size"); }
            set { settings.set_boolean ("remember-size", value); }
        }

        public int max_item_bytes {
            get { return settings.get_int ("max-item-bytes"); }
        }

        public string paste_ctrl_v_class_regex {
            owned get { return settings.get_string ("paste-ctrl-v-class-regex"); }
            set { settings.set_string ("paste-ctrl-v-class-regex", value); }
        }

        public bool paste_sets_primary {
            get { return settings.get_boolean ("paste-sets-primary"); }
            set { settings.set_boolean ("paste-sets-primary", value); }
        }

        public bool reown_clipboard {
            get { return settings.get_boolean ("reown-clipboard"); }
            set { settings.set_boolean ("reown-clipboard", value); }
        }

        public bool ignore_enabled {
            get { return settings.get_boolean ("ignore-enabled"); }
            set { settings.set_boolean ("ignore-enabled", value); }
        }

        public string[] ignore_regexes {
            owned get { return settings.get_strv ("ignore-regexes"); }
            set { settings.set_strv ("ignore-regexes", value); }
        }
    }

    namespace Constants {
        public const string APP_ID = "org.funes.Funes";
        public const string APP_NAME = "Funes";
    }
}
