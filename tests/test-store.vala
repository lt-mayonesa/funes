/* Funes - unit tests for the JSON store and history semantics. */

using Funes;

private GLib.File temp_history () {
    string dir;
    try {
        dir = GLib.DirUtils.make_tmp ("funes-test-XXXXXX");
    } catch (GLib.Error e) {
        GLib.error ("cannot create temp dir: %s", e.message);
    }
    return GLib.File.new_for_path (GLib.Path.build_filename (dir, "history.json"));
}

private void test_add_and_order () {
    var store = new JsonFileStore (temp_history (), 200);
    store.add ("one");
    store.add ("two");
    store.add ("three");

    assert (store.size () == 3);
    var items = store.items ();
    assert (items.nth_data (0).text == "three");
    assert (items.nth_data (2).text == "one");
}

private void test_dedup_moves_to_top () {
    var store = new JsonFileStore (temp_history (), 200);
    store.add ("a");
    store.add ("b");
    store.add ("a");

    assert (store.size () == 2);
    var items = store.items ();
    assert (items.nth_data (0).text == "a");
    assert (items.nth_data (0).copy_count == 2);
    assert (items.nth_data (1).text == "b");
}

private void test_rejects_blank () {
    var store = new JsonFileStore (temp_history (), 200);
    assert (store.add ("") == null);
    assert (store.add ("   \n\t ") == null);
    assert (store.size () == 0);
}

private void test_cap_evicts_oldest_unpinned () {
    var store = new JsonFileStore (temp_history (), 3);
    store.add ("1");
    store.add ("2");
    store.add ("3");
    store.add ("4");

    assert (store.size () == 3);
    var items = store.items ();
    assert (items.nth_data (0).text == "4");
    assert (items.nth_data (2).text == "2");
}

private void test_pin_survives_cap_and_clear () {
    var store = new JsonFileStore (temp_history (), 2);
    var pinned = store.add ("keep me");
    store.toggle_pin (pinned);
    store.add ("x");
    store.add ("y");
    store.add ("z");

    bool found = false;
    foreach (var item in store.items ()) {
        if (item.text == "keep me") {
            found = true;
            assert (item.pinned);
        }
    }
    assert (found);

    store.clear ();
    assert (store.size () == 1);
    assert (store.items ().nth_data (0).text == "keep me");
}

private void test_persistence_roundtrip () {
    var path = temp_history ();
    var store = new JsonFileStore (path, 200);
    store.add ("plain");
    store.add ("with \"quotes\" and \\ backslash\nand newline\ttab");
    var pinned = store.add ("pinned entry");
    store.toggle_pin (pinned);
    store.flush ();

    var reloaded = new JsonFileStore (path, 200);
    assert (reloaded.size () == 3);

    bool saw_special = false;
    bool saw_pinned = false;
    foreach (var item in reloaded.items ()) {
        if (item.text == "with \"quotes\" and \\ backslash\nand newline\ttab") {
            saw_special = true;
        }
        if (item.text == "pinned entry") {
            saw_pinned = item.pinned;
        }
    }
    assert (saw_special);
    assert (saw_pinned);
}

private void test_file_permissions () {
    var path = temp_history ();
    var store = new JsonFileStore (path, 200);
    store.add ("secret-ish");
    store.flush ();

    try {
        var info = path.query_info (GLib.FileAttribute.UNIX_MODE, GLib.FileQueryInfoFlags.NONE);
        var mode = info.get_attribute_uint32 (GLib.FileAttribute.UNIX_MODE);
        assert ((mode & 0777) == 0600);
    } catch (GLib.Error e) {
        GLib.error ("cannot stat history file: %s", e.message);
    }
}

private void test_remove () {
    var store = new JsonFileStore (temp_history (), 200);
    store.add ("a");
    var b = store.add ("b");
    store.add ("c");
    store.remove (b);

    assert (store.size () == 2);
    foreach (var item in store.items ()) {
        assert (item.text != "b");
    }
}

private void test_unicode_and_json_escapes () {
    var path = temp_history ();
    var store = new JsonFileStore (path, 200);
    var text = "emoji 🐘 — ünïcode ✓ \x01 control";
    store.add (text);
    store.flush ();

    var reloaded = new JsonFileStore (path, 200);
    assert (reloaded.items ().nth_data (0).text == text);
}

private void test_json_parser_basics () {
    try {
        var node = Funes.Json.parse ("""{"a":1,"b":"x\ty","c":true,"d":[1,2,3],"e":null}""");
        assert (node.int_member ("a") == 1);
        assert (node.string_member ("b") == "x\ty");
        assert (node.bool_member ("c"));
        assert (node.member ("d").length == 3);
        assert (node.member ("e").kind == Funes.Json.Kind.NULL);
    } catch (Funes.Json.ParseError e) {
        GLib.error ("unexpected parse error: %s", e.message);
    }

    bool threw = false;
    try {
        Funes.Json.parse ("{not json");
    } catch (Funes.Json.ParseError e) {
        threw = true;
    }
    assert (threw);
}

private void test_corrupt_file_is_backed_up () {
    var path = temp_history ();
    try {
        var parent = path.get_parent ();
        if (!parent.query_exists ()) {
            parent.make_directory_with_parents ();
        }
        GLib.FileUtils.set_contents (path.get_path (), "{ this is not json");
    } catch (GLib.Error e) {
        GLib.error ("setup failed: %s", e.message);
    }

    var store = new JsonFileStore (path, 200);
    assert (store.size () == 0);
    assert (GLib.FileUtils.test (path.get_path () + ".corrupt", GLib.FileTest.EXISTS));
}

private void test_preview_is_single_line () {
    var item = new HistoryItem ("  line one\n\tline two   ");
    assert (item.preview () == "line one line two");
    assert (!item.preview ().contains ("\n"));

    var long_item = new HistoryItem (string.nfill (500, 'x'));
    assert (long_item.preview (20).char_count () == 21); // 20 chars + ellipsis
}

public static int main (string[] args) {
    GLib.Test.init (ref args);

    // The corrupt-file test intentionally triggers g_warning; don't abort on it.
    GLib.Log.set_always_fatal (GLib.LogLevelFlags.LEVEL_ERROR);
    GLib.Test.log_set_fatal_handler ((domain, level, message) => {
        return (level & GLib.LogLevelFlags.LEVEL_ERROR) != 0;
    });

    GLib.Test.add_func ("/funes/store/add-and-order", test_add_and_order);
    GLib.Test.add_func ("/funes/store/dedup", test_dedup_moves_to_top);
    GLib.Test.add_func ("/funes/store/reject-blank", test_rejects_blank);
    GLib.Test.add_func ("/funes/store/cap", test_cap_evicts_oldest_unpinned);
    GLib.Test.add_func ("/funes/store/pin", test_pin_survives_cap_and_clear);
    GLib.Test.add_func ("/funes/store/persistence", test_persistence_roundtrip);
    GLib.Test.add_func ("/funes/store/permissions", test_file_permissions);
    GLib.Test.add_func ("/funes/store/remove", test_remove);
    GLib.Test.add_func ("/funes/store/unicode", test_unicode_and_json_escapes);
    GLib.Test.add_func ("/funes/json/basics", test_json_parser_basics);
    GLib.Test.add_func ("/funes/store/corrupt-backup", test_corrupt_file_is_backed_up);
    GLib.Test.add_func ("/funes/item/preview", test_preview_is_single_line);

    return GLib.Test.run ();
}
