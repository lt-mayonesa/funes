/* Funes - Xlib/XTEST declarations missing from valac's x11.vapi.
 *
 * Only what the paster needs: XTEST key faking, XSync, XQueryKeymap (to detect
 * held modifiers) and XGetClassHint (WM_CLASS of the paste target).
 */

[CCode (cheader_filename = "X11/Xlib.h,X11/Xutil.h,X11/extensions/XTest.h")]
namespace FunesX {

    [CCode (cname = "XTestQueryExtension")]
    public bool test_query_extension (X.Display display,
                                      out int event_base,
                                      out int error_base,
                                      out int major_version,
                                      out int minor_version);

    [CCode (cname = "XTestFakeKeyEvent")]
    public int test_fake_key_event (X.Display display, uint keycode,
                                    bool is_press, ulong delay_ms);

    [CCode (cname = "XSync")]
    public int sync (X.Display display, bool discard);

    /* keys_return must be a 32-byte buffer (bit vector of pressed keycodes). */
    [CCode (cname = "XQueryKeymap")]
    public int query_keymap (X.Display display,
                             [CCode (array_length = false)] char[] keys_return);

    [CCode (cname = "XClassHint", has_type_id = false, destroy_function = "")]
    public struct ClassHint {
        public unowned string? res_name;
        public unowned string? res_class;
    }

    [CCode (cname = "XGetClassHint")]
    public int get_class_hint (X.Display display, X.Window w, out ClassHint hint);

    [CCode (cname = "XFree")]
    public int free (void* data);
}
