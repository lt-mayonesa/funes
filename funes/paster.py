"""Paste injection (in-process XTEST via python-xlib, no external tools).

Mirrors CopyQ's X11 strategy (src/platform/x11/x11platformwindow.cpp):

  1. Remember the target window (_NET_ACTIVE_WINDOW) *before* the popup steals
     focus.
  2. Wait briefly for it to regain focus; if it does not, raise it
     (_NET_ACTIVE_WINDOW client message + XRaiseWindow + XSetInputFocus) and
     wait again.
  3. Wait for the user to release every keyboard modifier - the global shortcut
     means Super (and maybe Shift) is still held, which would turn the injected
     Shift+Insert into something else entirely.
  4. Fake the keystroke with XTEST: modifier down, key down, hold, key up,
     modifier up.

Default keystroke is Shift+Insert, like CopyQ: Ctrl+V is not a paste binding in
VTE terminals (they use Ctrl+Shift+V), whereas Shift+Insert pastes in GTK, Qt,
VTE, browsers and Java apps alike. Windows whose WM_CLASS matches
`paste-ctrl-v-class-regex` get Ctrl+V instead.
"""

import os
import re
import time
from typing import Any

from gi.repository import GLib

try:
    from Xlib import XK, X, Xatom
    from Xlib import display as xdisplay
    from Xlib import error as xerror
    from Xlib.ext import xtest
    from Xlib.protocol import event as xevent

    HAVE_XLIB = True
except ImportError:  # pragma: no cover - python3-xlib is a hard dependency
    HAVE_XLIB = False

# CopyQ's default timings, in milliseconds.
WAIT_BEFORE_RAISE_MS = 20
WAIT_RAISED_MS = 150
WAIT_AFTER_RAISED_MS = 50
KEY_PRESS_TIME_MS = 50
WAIT_MODIFIERS_RELEASED_MS = 2000
POLL_INTERVAL_MS = 10

_MODIFIER_KEYSYMS = (
    "Shift_L",
    "Shift_R",
    "Control_L",
    "Control_R",
    "Meta_L",
    "Meta_R",
    "Alt_L",
    "Alt_R",
    "Super_L",
    "Super_R",
    "Hyper_L",
    "Hyper_R",
)


def on_wayland() -> bool:
    return (os.environ.get("XDG_SESSION_TYPE") or "").lower() == "wayland"


class Paster:
    _warned_no_xtest = False
    _warned_wayland = False

    def __init__(self) -> None:
        # Xlib is untyped, so its objects stay `Any` on purpose.
        self._display: Any | None = None
        self._target: int | None = None
        if HAVE_XLIB and not on_wayland():
            try:
                self._display = xdisplay.Display()
            except Exception as error:  # DISPLAY unset, no X server, ...
                print(f"funes: cannot open X display: {error}")

    # --- public API ---

    def available(self) -> bool:
        """True when keystrokes can be injected at all."""
        if self._display is None:
            return False
        try:
            return bool(self._display.query_extension("XTEST") is not None)
        except Exception:
            return False

    def remember_target(self) -> None:
        """Record the currently focused window. Call before showing the popup."""
        self._target = self._active_window()

    def target_class(self) -> str:
        if self._target is None:
            return ""
        return self._window_class(self._target)

    def paste(self, ctrl_v_class_regex: str = "") -> None:
        """Copy-and-paste: assumes the text is already on the clipboard."""
        if on_wayland():
            if not Paster._warned_wayland:
                Paster._warned_wayland = True
                print(
                    "funes: running on Wayland; keystroke injection only reaches "
                    "XWayland clients, so the item was copied but not pasted."
                )
            return
        if self._display is None:
            return
        if not self.available():
            if not Paster._warned_no_xtest:
                Paster._warned_no_xtest = True
                print("funes: X server has no XTEST extension; item copied but not pasted.")
            return

        use_ctrl_v = self._matches_class(ctrl_v_class_regex)
        modifier = "Control_L" if use_ctrl_v else "Shift_L"
        key = "v" if use_ctrl_v else "Insert"

        # Deferred so the popup can finish hiding and the window manager can
        # restore focus first.
        GLib.timeout_add(WAIT_BEFORE_RAISE_MS, self._inject, modifier, key)

    # --- internals ---

    def _inject(self, modifier: str, key: str) -> bool:
        try:
            if self._target is not None and self._active_window() != self._target:
                self._raise_target()
                if not self._wait_for_focus(WAIT_RAISED_MS):
                    print("funes: could not refocus the paste target window")
                self._spin(WAIT_AFTER_RAISED_MS)

            if not self._wait_for_modifiers_released():
                print(
                    f"funes: modifiers still held after "
                    f"{WAIT_MODIFIERS_RELEASED_MS:d}ms; paste skipped"
                )
                return GLib.SOURCE_REMOVE

            mod_code = self._keycode(modifier)
            key_code = self._keycode(key)
            if not mod_code or not key_code:
                print("funes: no keycode for the paste shortcut")
                return GLib.SOURCE_REMOVE

            self._fake_key(mod_code, True)
            self._fake_key(key_code, True)
            # Some apps (Chrome's address bar) need the key held briefly.
            self._fake_key(key_code, False, delay_ms=KEY_PRESS_TIME_MS)
            self._fake_key(mod_code, False)
        except xerror.XError as error:
            print(f"funes: paste injection failed: {error}")
        return GLib.SOURCE_REMOVE

    def _fake_key(self, keycode: int, press: bool, delay_ms: int = 0) -> None:
        if self._display is None:
            return
        xtest.fake_input(
            self._display, X.KeyPress if press else X.KeyRelease, keycode, time=delay_ms
        )
        self._display.sync()

    def _keycode(self, keysym_name: str) -> int:
        keysym = XK.string_to_keysym(keysym_name)
        if keysym == X.NoSymbol or self._display is None:
            return 0
        return int(self._display.keysym_to_keycode(keysym))

    def _active_window(self) -> int | None:
        if self._display is None:
            return None
        root = self._display.screen().root
        try:
            prop = root.get_full_property(
                self._display.intern_atom("_NET_ACTIVE_WINDOW"), Xatom.WINDOW
            )
            if prop is not None and prop.value:
                window_id = int(prop.value[0])
                if window_id:
                    return window_id
            focus = self._display.get_input_focus().focus
            return int(focus.id) if hasattr(focus, "id") else int(focus)
        except xerror.XError:
            return None

    def _window_object(self, window_id: int | None) -> Any:
        if self._display is None:
            return None
        return self._display.create_resource_object("window", window_id)

    def _raise_target(self) -> None:
        if self._display is None:
            return
        window = self._window_object(self._target)
        try:
            if window.get_attributes().map_state != X.IsViewable:
                return
        except xerror.XError:
            return

        root = self._display.screen().root
        message = xevent.ClientMessage(
            window=window,
            client_type=self._display.intern_atom("_NET_ACTIVE_WINDOW"),
            data=(32, [2, 0, 0, 0, 0]),  # source indication: pager
        )
        root.send_event(message, event_mask=(X.SubstructureNotifyMask | X.SubstructureRedirectMask))
        window.configure(stack_mode=X.Above)
        self._display.set_input_focus(window, X.RevertToPointerRoot, X.CurrentTime)
        self._display.flush()

    def _wait_for_focus(self, timeout_ms: int) -> bool:
        waited = 0
        while waited < timeout_ms:
            if self._active_window() == self._target:
                return True
            self._spin(POLL_INTERVAL_MS)
            waited += POLL_INTERVAL_MS
        return self._active_window() == self._target

    def _wait_for_modifiers_released(self) -> bool:
        waited = 0
        while self._modifier_pressed() and waited < WAIT_MODIFIERS_RELEASED_MS:
            self._spin(POLL_INTERVAL_MS)
            waited += POLL_INTERVAL_MS
        return not self._modifier_pressed()

    def _modifier_pressed(self) -> bool:
        if self._display is None:
            return False
        keymap = self._display.query_keymap()
        for name in _MODIFIER_KEYSYMS:
            code = self._keycode(name)
            if not code:
                continue
            if (keymap[code >> 3] >> (code & 7)) & 1:
                return True
        return False

    @staticmethod
    def _spin(milliseconds: int) -> None:
        """Keep the main loop responsive while waiting on the X server."""
        context = GLib.MainContext.default()
        deadline = GLib.get_monotonic_time() + milliseconds * 1000
        while GLib.get_monotonic_time() < deadline:
            while context.pending():
                context.iteration(False)
            time.sleep(0.001)

    def _window_class(self, window_id: int | None) -> str:
        try:
            wm_class = self._window_object(window_id).get_wm_class()
        except xerror.XError:
            return ""
        if not wm_class:
            return ""
        res_name, res_class = wm_class
        return f"{res_name or ''}.{res_class or ''}"

    def _matches_class(self, pattern: str) -> bool:
        if not pattern or not pattern.strip() or self._target is None:
            return False
        wm_class = self._window_class(self._target)
        if not wm_class:
            return False
        try:
            # Matched against "res_name.res_class",
            # e.g. "gnome-terminal-server.Gnome-terminal".
            return re.search(pattern, wm_class) is not None
        except re.error as error:
            print(f"funes: bad paste-ctrl-v-class-regex /{pattern}/: {error}")
            return False
