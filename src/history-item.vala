/* Funes - a single clipboard history entry. */

namespace Funes {

    public class HistoryItem : GLib.Object {
        /* Plain text payload. v1 is text-only. */
        public string text { get; set; default = ""; }
        /* Pinned items are never evicted by the history-size cap. */
        public bool pinned { get; set; default = false; }
        /* Unix microseconds of first capture. */
        public int64 created { get; set; default = 0; }
        /* Unix microseconds of last copy (used for ordering). */
        public int64 last_used { get; set; default = 0; }
        /* How many times this exact text was copied. */
        public int copy_count { get; set; default = 1; }

        public HistoryItem (string text, int64 now = GLib.get_real_time ()) {
            Object (text: text, created: now, last_used: now);
        }

        /* Single-line, whitespace-collapsed label for the list rows. */
        public string preview (int max_chars = 120) {
            var collapsed = collapse_whitespace (text);
            if (collapsed.char_count () <= max_chars) {
                return collapsed;
            }
            return collapsed.substring (0, collapsed.index_of_nth_char (max_chars)) + "…";
        }

        private static string collapse_whitespace (string raw) {
            var sb = new StringBuilder.sized (raw.length);
            bool in_space = false;
            unichar c;
            int i = 0;
            while (raw.get_next_char (ref i, out c)) {
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f'
                    || c == 0x0b) {
                    in_space = true;
                    continue;
                }
                if (in_space && sb.len > 0) {
                    sb.append_c (' ');
                }
                in_space = false;
                sb.append_unichar (c);
            }
            return sb.str;
        }

        public string describe () {
            var lines = text.split ("\n").length;
            var bytes = text.length;
            return "%d line%s, %s".printf (
                lines,
                lines == 1 ? "" : "s",
                GLib.format_size ((uint64) bytes));
        }

        public Json.Node to_json () {
            var o = new Json.Node (Json.Kind.OBJECT);
            var t = new Json.Node (Json.Kind.STRING);
            t.string_value = text;
            o.set_member ("text", t);

            var p = new Json.Node (Json.Kind.BOOL);
            p.bool_value = pinned;
            o.set_member ("pinned", p);

            o.set_member ("created", number_node (created));
            o.set_member ("last_used", number_node (last_used));
            o.set_member ("copy_count", number_node (copy_count));
            return o;
        }

        private static Json.Node number_node (int64 v) {
            var n = new Json.Node (Json.Kind.NUMBER);
            n.number_value = (double) v;
            return n;
        }

        public static HistoryItem? from_json (Json.Node node) {
            if (node.kind != Json.Kind.OBJECT) {
                return null;
            }
            var text = node.string_member ("text");
            if (text == "") {
                return null;
            }
            var now = GLib.get_real_time ();
            var item = new HistoryItem (text, now);
            item.pinned = node.bool_member ("pinned");
            item.created = node.int_member ("created", now);
            item.last_used = node.int_member ("last_used", item.created);
            item.copy_count = (int) node.int_member ("copy_count", 1);
            return item;
        }

        /* Serialize a JSON string value (used by the store's writer). */
        public string to_json_string () {
            return "{\"text\":\"%s\",\"pinned\":%s,\"created\":%s,\"last_used\":%s,\"copy_count\":%d}"
                .printf (
                    Json.escape (text),
                    pinned ? "true" : "false",
                    created.to_string (),
                    last_used.to_string (),
                    copy_count);
        }
    }
}
