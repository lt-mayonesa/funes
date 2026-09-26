# Wayland support

Tracking document for the eventual Wayland port. Funes is X11-only today; every
platform-specific assumption lives in a small number of modules, and this file
records what breaks under Wayland, why, and what the replacement is.

Status: **not started**. Nothing here is scheduled; items become TODO entries
once a migration is actually planned.

## Why X11 only

| Feature | X11 implementation | Wayland status |
| --- | --- | --- |
| Clipboard capture | `Gtk.Clipboard` owner-change on `app/clipboard.py` | Partial: GTK only sees clipboard changes while an app of ours has focus. Needs `wlr-data-control` or `xdg-desktop-portal`. |
| Image capture | `request_contents(image/*)` async chain in `app/clipboard.py` | Inherits the focus-only limitation above; images copied in other apps are missed unless focus returns to Funes first. Same fix as text capture. |
| Paste injection | XTEST fake key events (`funes/paster.py`) | Unavailable: XTEST reaches XWayland clients only. Needs a compositor protocol (`virtual-keyboard-v1`, `ydotool`/uinput) or portal RemoteDesktop. |
| Target-window tracking | `_NET_ACTIVE_WINDOW` + `WM_CLASS` (`funes/paster.py`) | Unavailable: no client-visible window list. Portals expose no equivalent. |
| Popup placement | `Gtk.Window.move()` onto the monitor picked by `popup-monitor-order` (`app/popup.py`, `funes/monitors.py`) | Unavailable: GTK3 cannot position toplevels on Wayland; the compositor decides. Needs `layer-shell` (`gtk-layer-shell`) to anchor to an output. |
| Global hotkey | Cinnamon custom keybinding running `funes toggle` (`funes/hotkey.py`) | Per-compositor; `xdg-desktop-portal` GlobalShortcuts is the portable route. |
| Focusless popup | `set_accept_focus(False)` + `Gdk.Seat.grab()` on the popup (`app/grab.py`, `app/popup.py`) so the source window keeps focus and its selection | Unavailable: no client seat grab for regular toplevels. `grabs_supported()` returns False and the old focusable popup is used, so the selection-loss bug persists there. Needs `gtk-layer-shell` (`keyboard-interactivity: exclusive` on a layer surface) or a portal. |
| Shortcut capture | Keyboard-only `Gdk.Seat.grab()` on the Preferences row (`app/shortcut.py`) | Unavailable as written: Wayland grants no global keyboard grab. The portal GlobalShortcuts API owns both capture UI and binding, so the widget becomes a portal request, not a key grab. |

## Popup monitor placement (current bug context)

`popup-monitor-order` is honoured only on X11. The strategies are:

1. `focused` — monitor of the window that was focused before the popup opened
   (`Gdk.Screen.get_active_window()`).
2. `pointer` — monitor under the mouse.
3. `primary` — primary monitor.

Selection logic is GTK-free and unit-tested in `funes/monitors.py` /
`tests/test_monitors.py`, so a Wayland backend only has to supply candidate
outputs, not reimplement the policy.

Under Wayland `_place_on_target_monitor()` silently does nothing: `move()` is a
no-op and the compositor centers the window on whichever output it prefers.
The Preferences section shows a note saying so.

## Focusless popup (current shape)

On X11 the popup refuses the WM focus and grabs the seat instead, because
taking the focus made apps drop their text selection (Chrome's omnibox, nemo,
xed) and the paste then landed next to the selection instead of replacing it.
GTK is told to behave as a focused toplevel by a synthesized focus-in event
(`PopupWindow._fake_toplevel_focus`), and closing is driven by the grab (click
outside, `grab-broken-event`) rather than by window deactivation.

Under Wayland `app/grab.py::grabs_supported()` is False, so `show_popup()`
keeps the focusable popup with the old deactivation-based close. A layer-shell
port would replace both halves: `keyboard-interactivity` on the layer surface
instead of the grab, and `closed`/focus events instead of `grab-broken-event`.

## Global shortcut (current shape)

The accelerator lives in the `hotkey` GSettings key, validated by
`funes/accel.py` (GTK-free, unit-tested). `FunesApplication` watches the key
and calls `funes.hotkey.apply()`, which registers or removes the Cinnamon
custom keybinding. Under a portal-based port only `hotkey.apply()` and the
capture widget change; the key, its validation and the daemon watcher stay.

## Likely migration shape

- `gtk-layer-shell` for the popup: `set_monitor()` + centered anchor gives back
  per-output placement, and replaces both the focus/stacking hacks and the seat
  grab in `app/popup.py` / `app/grab.py`.
- `wlr-data-control` for capture on wlroots compositors; portal Clipboard
  elsewhere once it exists.
- `xdg-desktop-portal` RemoteDesktop for synthetic key events, with a
  copy-only fallback when the user denies the permission.
- GTK4 is probably a prerequisite for layer-shell + portal ergonomics; the
  GTK-free core (`funes/`) is already isolated from that decision.

## Open questions

- Is copy-only (no paste injection) an acceptable default Wayland experience?
- Do we ship one binary with runtime backend detection, or separate sessions?
- Can the focused-window strategy be approximated at all, or does Wayland force
  `pointer` to be the effective default order?
