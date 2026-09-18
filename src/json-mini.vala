/* Funes - minimal JSON reader/writer.
 *
 * json-glib development files are not installed on the target system and we
 * want zero extra build deps, so Funes ships a tiny JSON implementation that
 * covers exactly what the history file needs: an object at the root, arrays of
 * objects, and string / bool / int / double / null values.
 */

namespace Funes.Json {

    public errordomain ParseError {
        MALFORMED,
    }

    public string escape (string raw) {
        var sb = new StringBuilder.sized (raw.length + 8);
        unichar c;
        int i = 0;
        while (raw.get_next_char (ref i, out c)) {
            switch (c) {
                case '"': sb.append ("\\\""); break;
                case '\\': sb.append ("\\\\"); break;
                case '\n': sb.append ("\\n"); break;
                case '\r': sb.append ("\\r"); break;
                case '\t': sb.append ("\\t"); break;
                case '\b': sb.append ("\\b"); break;
                case '\f': sb.append ("\\f"); break;
                default:
                    if (c < 0x20) {
                        sb.append_printf ("\\u%04x", (uint) c);
                    } else {
                        sb.append_unichar (c);
                    }
                    break;
            }
        }
        return sb.str;
    }

    /* A parsed JSON value. Deliberately simple: no subclassing, one struct-ish
     * class with a kind tag. */
    public enum Kind {
        NULL,
        BOOL,
        NUMBER,
        STRING,
        ARRAY,
        OBJECT,
    }

    public class Node : GLib.Object {
        public Kind kind { get; construct; }
        public bool bool_value { get; set; default = false; }
        public double number_value { get; set; default = 0.0; }
        public string string_value { get; set; default = ""; }

        private GLib.GenericArray<Node> items = new GLib.GenericArray<Node> ();
        private GLib.HashTable<string, Node> members =
            new GLib.HashTable<string, Node> (str_hash, str_equal);

        public Node (Kind kind) {
            Object (kind: kind);
        }

        public uint length {
            get { return items.length; }
        }

        public Node? nth (uint index) {
            return index < items.length ? items.get ((int) index) : null;
        }

        public void add (Node child) {
            items.add (child);
        }

        public void set_member (string name, Node child) {
            members.insert (name, child);
        }

        public Node? member (string name) {
            return members.lookup (name);
        }

        public string string_member (string name, string fallback = "") {
            var n = member (name);
            return (n != null && n.kind == Kind.STRING) ? n.string_value : fallback;
        }

        public bool bool_member (string name, bool fallback = false) {
            var n = member (name);
            return (n != null && n.kind == Kind.BOOL) ? n.bool_value : fallback;
        }

        public int64 int_member (string name, int64 fallback = 0) {
            var n = member (name);
            return (n != null && n.kind == Kind.NUMBER) ? (int64) n.number_value : fallback;
        }
    }

    public Node parse (string text) throws ParseError {
        var p = new Parser (text);
        p.skip_ws ();
        var node = p.parse_value ();
        p.skip_ws ();
        if (!p.at_end ()) {
            throw new ParseError.MALFORMED ("trailing data at offset %d", p.offset);
        }
        return node;
    }

    private class Parser : GLib.Object {
        private string src;
        private int len;
        public int offset = 0;

        public Parser (string src) {
            this.src = src;
            this.len = src.length;
        }

        public bool at_end () {
            return offset >= len;
        }

        private char peek () {
            return offset < len ? src[offset] : '\0';
        }

        public void skip_ws () {
            while (offset < len) {
                char c = src[offset];
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
                    offset++;
                } else {
                    break;
                }
            }
        }

        private void expect (char c) throws ParseError {
            if (peek () != c) {
                throw new ParseError.MALFORMED (
                    "expected '%c' at offset %d, got '%c'", c, offset, peek ());
            }
            offset++;
        }

        private bool accept_literal (string lit) {
            if (offset + lit.length <= len && src.substring (offset, lit.length) == lit) {
                offset += lit.length;
                return true;
            }
            return false;
        }

        public Node parse_value () throws ParseError {
            skip_ws ();
            char c = peek ();
            switch (c) {
                case '{': return parse_object ();
                case '[': return parse_array ();
                case '"':
                    var n = new Node (Kind.STRING);
                    n.string_value = parse_string ();
                    return n;
                default:
                    break;
            }
            if (accept_literal ("true")) {
                var n = new Node (Kind.BOOL);
                n.bool_value = true;
                return n;
            }
            if (accept_literal ("false")) {
                var n = new Node (Kind.BOOL);
                n.bool_value = false;
                return n;
            }
            if (accept_literal ("null")) {
                return new Node (Kind.NULL);
            }
            return parse_number ();
        }

        private Node parse_object () throws ParseError {
            expect ('{');
            var node = new Node (Kind.OBJECT);
            skip_ws ();
            if (peek () == '}') {
                offset++;
                return node;
            }
            while (true) {
                skip_ws ();
                string name = parse_string ();
                skip_ws ();
                expect (':');
                node.set_member (name, parse_value ());
                skip_ws ();
                if (peek () == ',') {
                    offset++;
                    continue;
                }
                expect ('}');
                break;
            }
            return node;
        }

        private Node parse_array () throws ParseError {
            expect ('[');
            var node = new Node (Kind.ARRAY);
            skip_ws ();
            if (peek () == ']') {
                offset++;
                return node;
            }
            while (true) {
                node.add (parse_value ());
                skip_ws ();
                if (peek () == ',') {
                    offset++;
                    continue;
                }
                expect (']');
                break;
            }
            return node;
        }

        private string parse_string () throws ParseError {
            expect ('"');
            var sb = new StringBuilder ();
            while (true) {
                if (offset >= len) {
                    throw new ParseError.MALFORMED ("unterminated string");
                }
                char c = src[offset];
                if (c == '"') {
                    offset++;
                    break;
                }
                if (c == '\\') {
                    offset++;
                    if (offset >= len) {
                        throw new ParseError.MALFORMED ("unterminated escape");
                    }
                    char e = src[offset++];
                    switch (e) {
                        case '"': sb.append_c ('"'); break;
                        case '\\': sb.append_c ('\\'); break;
                        case '/': sb.append_c ('/'); break;
                        case 'n': sb.append_c ('\n'); break;
                        case 'r': sb.append_c ('\r'); break;
                        case 't': sb.append_c ('\t'); break;
                        case 'b': sb.append_c ('\b'); break;
                        case 'f': sb.append_c ('\f'); break;
                        case 'u':
                            sb.append_unichar (parse_unicode_escape ());
                            break;
                        default:
                            throw new ParseError.MALFORMED ("bad escape '\\%c'", e);
                    }
                    continue;
                }
                sb.append_c (c);
                offset++;
            }
            return sb.str;
        }

        private unichar parse_unicode_escape () throws ParseError {
            uint32 cp = read_hex4 ();
            if (cp >= 0xD800 && cp <= 0xDBFF) {
                // surrogate pair
                if (offset + 1 < len && src[offset] == '\\' && src[offset + 1] == 'u') {
                    offset += 2;
                    uint32 low = read_hex4 ();
                    if (low >= 0xDC00 && low <= 0xDFFF) {
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
                    }
                }
            }
            return (unichar) cp;
        }

        private uint32 read_hex4 () throws ParseError {
            if (offset + 4 > len) {
                throw new ParseError.MALFORMED ("truncated \\u escape");
            }
            uint32 v = 0;
            for (int i = 0; i < 4; i++) {
                char c = src[offset++];
                int d;
                if (c >= '0' && c <= '9') {
                    d = c - '0';
                } else if (c >= 'a' && c <= 'f') {
                    d = c - 'a' + 10;
                } else if (c >= 'A' && c <= 'F') {
                    d = c - 'A' + 10;
                } else {
                    throw new ParseError.MALFORMED ("bad hex digit '%c'", c);
                }
                v = (v << 4) | (uint32) d;
            }
            return v;
        }

        private Node parse_number () throws ParseError {
            int start = offset;
            if (peek () == '-' || peek () == '+') {
                offset++;
            }
            while (offset < len) {
                char c = src[offset];
                if ((c >= '0' && c <= '9') || c == '.' || c == 'e' || c == 'E'
                    || c == '-' || c == '+') {
                    offset++;
                } else {
                    break;
                }
            }
            if (offset == start) {
                throw new ParseError.MALFORMED ("unexpected character at offset %d", offset);
            }
            var slice = src.substring (start, offset - start);
            double d;
            if (!double.try_parse (slice, out d)) {
                throw new ParseError.MALFORMED ("bad number '%s'", slice);
            }
            var node = new Node (Kind.NUMBER);
            node.number_value = d;
            return node;
        }
    }
}
