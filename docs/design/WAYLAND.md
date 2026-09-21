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

## Global shortcut (current shape)

The accelerator lives in the `hotkey` GSettings key, validated by
`funes/accel.py` (GTK-free, unit-tested). `FunesApplication` watches the key
and calls `funes.hotkey.apply()`, which registers or removes the Cinnamon
custom keybinding. Under a portal-based port only `hotkey.apply()` and the
capture widget change; the key, its validation and the daemon watcher stay.

## Likely migration shape

- `gtk-layer-shell` for the popup: `set_monitor()` + centered anchor gives back
  per-output placement, and removes the focus/stacking hacks in `app/popup.py`.
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
