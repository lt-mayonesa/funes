"""Seat grab seam: keyboard + pointer input without taking the WM focus.

Why this exists
---------------
The popup used to be a normal focusable window. Mapping it made the window
manager focus Funes, which sends a real `FocusOut` (mode `NotifyNormal`) to
whatever the user was working in. Several apps drop their text selection right
there — Chrome's omnibox, nemo's rename entry, xed — so the later
Shift+Insert inserted the clipboard next to the selection instead of replacing
it (appended in Chrome, prepended in xed).

The fix is the rofi/CopyQ model: the popup never accepts the WM focus
(`gtk_window_set_accept_focus(FALSE)` -> `WM_HINTS.input = False`) and grabs
the seat instead. A grab only produces `FocusOut` with mode `NotifyGrab`, which
toolkits deliberately ignore, so the target window keeps its selection and is
still the `_NET_ACTIVE_WINDOW` when the paste keystroke is injected.

This module is the seam around `Gdk.Seat.grab()` so the popup logic stays
testable with a fake seat and so swapping the strategy (e.g. an
override-redirect window) touches one file.

X11 only: Wayland has no client-initiated seat grab for regular toplevels, so
`grabs_supported()` returns False there and the caller keeps the old focusable
popup (see docs/design/WAYLAND.md).
"""

from typing import Any, Protocol

from gi.repository import GLib

# A grab can lose a race with whatever grabbed the keyboard first (the WM's own
# keybinding grab for the global shortcut, a menu that is still closing), so it
# is retried for a short while before giving up.
GRAB_RETRY_INTERVAL_MS = 10
GRAB_TIMEOUT_MS = 500

# Gdk.GrabStatus.SUCCESS; kept as an int so fakes need no Gdk.
GRAB_SUCCESS = 0


def grabs_supported() -> bool:
    """True when the running display server supports a client seat grab."""
    from gi.repository import Gdk

    display = Gdk.Display.get_default()
    if display is None:
        return False
    # GdkX11Display without requiring the GdkX11 typelib.
    gtype_name = getattr(getattr(display, "__gtype__", None), "name", "")
    return isinstance(gtype_name, str) and gtype_name.startswith("GdkX11")


class Grab(Protocol):
    """What the popup needs from a grab; `SeatGrab` and test fakes implement it."""

    @property
    def active(self) -> bool: ...

    def acquire(self, window: Any) -> bool: ...

    def release(self) -> None: ...


class SeatGrab:
    """Holds a keyboard+pointer grab on one `Gdk.Window`.

    `seat` is injectable for tests; in production it is resolved from the
    default display at `acquire()` time.
    """

    def __init__(self, seat: Any | None = None, timeout_ms: int = GRAB_TIMEOUT_MS) -> None:
        self._seat = seat
        self._timeout_ms = timeout_ms
        self._held = False

    @property
    def active(self) -> bool:
        return self._held

    def acquire(self, window: Any) -> bool:
        """Grab the seat for `window`. Returns False when the grab never lands.

        The window must already be mapped: X refuses a grab on an unmapped
        window with `GrabNotViewable`, which is exactly the state a freshly
        `show()`-n GTK window is in until the main loop has run.
        """
        if self._held:
            return True
        if window is None:
            return False
        seat = self._seat if self._seat is not None else self._default_seat()
        if seat is None:
            return False

        capabilities = self._capabilities()
        waited = 0
        while True:
            status = seat.grab(window, capabilities, True, None, None, None)
            if _is_success(status):
                self._seat = seat
                self._held = True
                return True
            if waited >= self._timeout_ms:
                return False
            _spin(GRAB_RETRY_INTERVAL_MS)
            waited += GRAB_RETRY_INTERVAL_MS

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        if self._seat is not None:
            self._seat.ungrab()

    # --- internals ---

    @staticmethod
    def _default_seat() -> Any | None:
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        return display.get_default_seat() if display is not None else None

    @staticmethod
    def _capabilities() -> Any:
        """Keyboard + pointer: clicks outside the popup must reach it too."""
        try:
            from gi.repository import Gdk

            return Gdk.SeatCapabilities.ALL
        except (ImportError, ValueError):  # pragma: no cover - fakes ignore it
            return None


def _is_success(status: Any) -> bool:
    try:
        return int(status) == GRAB_SUCCESS
    except (TypeError, ValueError):
        return bool(status)


def _spin(milliseconds: int) -> None:
    """Wait while keeping the main loop alive, as Paster does during paste."""
    import time

    context = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + milliseconds * 1000
    while GLib.get_monotonic_time() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.001)
