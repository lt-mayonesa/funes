/* Funes - JSON file backed history store.
 *
 * File: $XDG_DATA_HOME/funes/history.json (mode 0600, the file holds clipboard
 * text). Writes are debounced and atomic (write tmp + rename).
 */

namespace Funes {

    public class JsonFileStore : GLib.Object, HistoryStore {
        private const int SAVE_DEBOUNCE_MS = 500;
        private const int FORMAT_VERSION = 1;

        private GLib.File file;
        private GLib.GenericArray<HistoryItem> list = new GLib.GenericArray<HistoryItem> ();
        private uint save_source = 0;
        private int _history_size = 200;

        public int history_size {
            get { return _history_size; }
            set {
                _history_size = int.max (1, value);
                if (evict ()) {
                    schedule_save ();
                    changed ();
                }
            }
        }

        public JsonFileStore (GLib.File file, int history_size = 200) {
            this.file = file;
            this._history_size = int.max (1, history_size);
            load ();
        }

        public static GLib.File default_path () {
            var dir = GLib.Path.build_filename (GLib.Environment.get_user_data_dir (), "funes");
            return GLib.File.new_for_path (GLib.Path.build_filename (dir, "history.json"));
        }

        public GLib.List<HistoryItem> items () {
            var result = new GLib.List<HistoryItem> ();
            for (int i = (int) list.length - 1; i >= 0; i--) {
                result.prepend (list.get (i));
            }
            return result;
        }

        public uint size () {
            return list.length;
        }

        public HistoryItem? add (string text) {
            if (text.strip () == "") {
                return null;
            }

            int existing = index_of_text (text);
            if (existing >= 0) {
                var item = list.get (existing);
                item.last_used = GLib.get_real_time ();
                item.copy_count += 1;
                list.remove_index (existing);
                list.insert (0, item);
                sort_pinned_first ();
                schedule_save ();
                changed ();
                return item;
            }

            var item = new HistoryItem (text);
            list.insert (0, item);
            sort_pinned_first ();
            evict ();
            schedule_save ();
            changed ();
            return item;
        }

        public void touch (HistoryItem item) {
            int idx = index_of (item);
            if (idx < 0) {
                return;
            }
            item.last_used = GLib.get_real_time ();
            list.remove_index (idx);
            list.insert (0, item);
            sort_pinned_first ();
            schedule_save ();
            changed ();
        }

        public void remove (HistoryItem item) {
            int idx = index_of (item);
            if (idx < 0) {
                return;
            }
            list.remove_index (idx);
            schedule_save ();
            changed ();
        }

        public void toggle_pin (HistoryItem item) {
            if (index_of (item) < 0) {
                return;
            }
            item.pinned = !item.pinned;
            sort_pinned_first ();
            evict ();
            schedule_save ();
            changed ();
        }

        public void clear () {
            var kept = new GLib.GenericArray<HistoryItem> ();
            for (uint i = 0; i < list.length; i++) {
                var item = list.get ((int) i);
                if (item.pinned) {
                    kept.add (item);
                }
            }
            list = kept;
            schedule_save ();
            changed ();
        }

        public void flush () {
            if (save_source != 0) {
                GLib.Source.remove (save_source);
                save_source = 0;
            }
            save ();
        }

        /* --- internals --- */

        private int index_of (HistoryItem needle) {
            for (uint i = 0; i < list.length; i++) {
                if (list.get ((int) i) == needle) {
                    return (int) i;
                }
            }
            return -1;
        }

        private int index_of_text (string text) {
            for (uint i = 0; i < list.length; i++) {
                if (list.get ((int) i).text == text) {
                    return (int) i;
                }
            }
            return -1;
        }

        /* Stable: pinned block on top, each block newest-first. */
        private void sort_pinned_first () {
            var pinned = new GLib.GenericArray<HistoryItem> ();
            var rest = new GLib.GenericArray<HistoryItem> ();
            for (uint i = 0; i < list.length; i++) {
                var item = list.get ((int) i);
                if (item.pinned) {
                    pinned.add (item);
                } else {
                    rest.add (item);
                }
            }
            var merged = new GLib.GenericArray<HistoryItem> ();
            for (uint i = 0; i < pinned.length; i++) {
                merged.add (pinned.get ((int) i));
            }
            for (uint i = 0; i < rest.length; i++) {
                merged.add (rest.get ((int) i));
            }
            list = merged;
        }

        /* Drop oldest unpinned items above the cap. Returns true if changed. */
        private bool evict () {
            int unpinned = 0;
            for (uint i = 0; i < list.length; i++) {
                if (!list.get ((int) i).pinned) {
                    unpinned++;
                }
            }
            bool changed_any = false;
            while (unpinned > _history_size) {
                for (int i = (int) list.length - 1; i >= 0; i--) {
                    if (!list.get (i).pinned) {
                        list.remove_index (i);
                        unpinned--;
                        changed_any = true;
                        break;
                    }
                }
            }
            return changed_any;
        }

        private void schedule_save () {
            if (save_source != 0) {
                return;
            }
            save_source = GLib.Timeout.add (SAVE_DEBOUNCE_MS, () => {
                save_source = 0;
                save ();
                return GLib.Source.REMOVE;
            });
        }

        private void load () {
            string contents;
            try {
                if (!file.query_exists ()) {
                    return;
                }
                uint8[] data;
                file.load_contents (null, out data, null);
                contents = (string) data;
            } catch (GLib.Error e) {
                warning ("Funes: cannot read %s: %s", file.get_path (), e.message);
                return;
            }

            try {
                var root = Json.parse (contents);
                var items_node = root.kind == Json.Kind.ARRAY ? root : root.member ("items");
                if (items_node == null || items_node.kind != Json.Kind.ARRAY) {
                    return;
                }
                for (uint i = 0; i < items_node.length; i++) {
                    var node = items_node.nth (i);
                    if (node == null) {
                        continue;
                    }
                    var item = HistoryItem.from_json (node);
                    if (item != null) {
                        list.add (item);
                    }
                }
                sort_pinned_first ();
                evict ();
            } catch (Json.ParseError e) {
                warning ("Funes: corrupt history file (%s); starting empty", e.message);
                backup_corrupt_file ();
                list = new GLib.GenericArray<HistoryItem> ();
            }
        }

        private void backup_corrupt_file () {
            try {
                var backup = GLib.File.new_for_path (file.get_path () + ".corrupt");
                file.move (backup, GLib.FileCopyFlags.OVERWRITE, null, null);
            } catch (GLib.Error e) {
                warning ("Funes: cannot back up corrupt history: %s", e.message);
            }
        }

        private void save () {
            var sb = new StringBuilder ();
            sb.append_printf ("{\"format_version\":%d,\"items\":[", FORMAT_VERSION);
            for (uint i = 0; i < list.length; i++) {
                if (i > 0) {
                    sb.append_c (',');
                }
                sb.append (list.get ((int) i).to_json_string ());
            }
            sb.append ("]}\n");

            try {
                var parent = file.get_parent ();
                if (parent != null && !parent.query_exists ()) {
                    parent.make_directory_with_parents ();
                    GLib.FileUtils.chmod (parent.get_path (), 0700);
                }

                var tmp_path = file.get_path () + ".tmp";
                GLib.FileUtils.set_contents (tmp_path, sb.str);
                GLib.FileUtils.chmod (tmp_path, 0600);
                if (GLib.FileUtils.rename (tmp_path, file.get_path ()) != 0) {
                    warning ("Funes: rename of %s failed", tmp_path);
                }
            } catch (GLib.Error e) {
                warning ("Funes: cannot write %s: %s", file.get_path (), e.message);
            }
        }
    }
}
