/* Funes - storage interface.
 *
 * The JSON file backend is the v1 implementation; a SQLite backend can be
 * dropped in later without touching the UI, as long as it implements this
 * interface.
 */

namespace Funes {

    public interface HistoryStore : GLib.Object {
        /* Emitted whenever the in-memory list changed. */
        public signal void changed ();

        /* Newest first, pinned items first within that ordering. */
        public abstract GLib.List<HistoryItem> items ();

        public abstract uint size ();

        /* Insert text at the top. If identical text already exists, that entry
         * is moved to the top instead of being duplicated (Maccy behaviour).
         * Returns the item that now sits at the top, or null if rejected. */
        public abstract HistoryItem? add (string text);

        public abstract void touch (HistoryItem item);

        public abstract void remove (HistoryItem item);

        public abstract void toggle_pin (HistoryItem item);

        public abstract void clear ();

        /* Flush pending changes to disk immediately. */
        public abstract void flush ();

        public abstract int history_size { get; set; }
    }
}
