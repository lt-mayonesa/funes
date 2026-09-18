# Funes

Clipboard history that never forgets — a Linux clipboard manager in the spirit of
[Maccy](https://github.com/p0deje/Maccy), named after Borges' *Funes el memorioso*.

Maccy itself cannot be ported: it is Swift on AppKit/SwiftUI with `NSPasteboard`,
`NSStatusItem`, Carbon hotkeys and SwiftData, i.e. macOS-only end to end. Funes
re-implements its behaviour on the [xapp](https://github.com/linuxmint/xapp)
stack (Vala + GTK 3 + libxapp), which is what Linux Mint / Cinnamon uses natively.

## Status

v1, X11 only. Text clipboard entries.

| Area | Implementation |
| --- | --- |
| Clipboard watch | `Gtk.Clipboard::owner-change` (XFixes-backed, no polling) |
| Storage | JSON file, atomic writes, mode `0600` (SQLite backend planned) |
| Tray | `XAppStatusIcon` (falls back to `Gtk.StatusIcon`) |
| Popup | GTK window, centered on the monitor under the pointer |
| Global shortcut | Cinnamon custom keybinding running `funes toggle` |
| Paste | in-process XTEST (`libXtst`), Shift+Insert, CopyQ-style |
| Settings | GSettings `org.funes.Funes` + preferences dialog |
| Autostart | `~/.config/autostart/org.funes.Funes.desktop` |

## Build

Requires: `valac`, `meson`, `ninja`, `libgtk-3-dev`, `libxapp-dev`, `libx11-dev`,
`libxtst-dev`. No runtime tools are needed — keystrokes are injected in-process
through XTEST, so there is no `xdotool` dependency.

```sh
meson setup _build
meson compile -C _build
meson test -C _build
```

Run from the build tree (compiles the schema into `_build/data`):

```sh
./scripts/run.sh
```

Install:

```sh
sudo meson install -C _build
```

## Usage

```
funes              start the tray daemon
funes toggle       show/hide the history popup
funes show         show the history popup
funes clear        clear history (pinned items are kept)
funes settings     open the settings dialog
funes quit         stop the running instance
funes --version    print version
```

Default global shortcut: <kbd>Super</kbd>+<kbd>V</kbd>. It is registered as a
Cinnamon custom keybinding, so it is visible and editable in
*Keyboard → Shortcuts → Custom Shortcuts*, and it starts Funes on demand via
DBus activation if the daemon is not running.

Popup keys:

| Key | Action |
| --- | --- |
| type | filter (case-insensitive substring) |
| <kbd>↑</kbd> / <kbd>↓</kbd>, <kbd>PgUp</kbd> / <kbd>PgDn</kbd> | move selection |
| <kbd>Enter</kbd> | copy + paste into the previously focused window |
| <kbd>Ctrl</kbd>+<kbd>Enter</kbd> | copy only |
| <kbd>Ctrl</kbd>+<kbd>P</kbd> | toggle pin (pinned items never expire) |
| <kbd>Delete</kbd> | remove the selected item |
| <kbd>Ctrl</kbd>+<kbd>L</kbd> | clear history (keeps pinned) |
| <kbd>Esc</kbd> | hide |

Tray icon: left click opens the popup, right click the menu (*Open Funes*,
*Clear History*, *Settings…*, *Quit*).

<kbd>BackSpace</kbd> only edits the search filter; removing items is
<kbd>Delete</kbd> only.

### How pasting works

Following [CopyQ](https://github.com/hluk/CopyQ)
(`src/platform/x11/x11platformwindow.cpp`), Funes:

1. remembers the focused window (`_NET_ACTIVE_WINDOW`) *before* the popup opens;
2. waits for that window to regain focus, raising it if needed
   (`_NET_ACTIVE_WINDOW` client message + `XRaiseWindow` + `XSetInputFocus`);
3. waits (up to 2s) for all keyboard modifiers to be released — you are still
   holding <kbd>Super</kbd> from the shortcut;
4. injects **Shift+Insert** via XTEST.

Shift+Insert rather than Ctrl+V because VTE terminals (GNOME Terminal,
Terminator, xfce4-terminal…) do not paste on Ctrl+V — they use Ctrl+Shift+V —
while Shift+Insert pastes in GTK, Qt, VTE, browsers and Java apps. Terminals
map Shift+Insert to the PRIMARY selection, so Funes sets **both** CLIPBOARD and
PRIMARY when an item is activated (also what CopyQ does, see
`MainWindow::setClipboard`). Disable with `paste-sets-primary=false` if you do
not want your mouse selection replaced.

Apps that need Ctrl+V instead can be listed by WM_CLASS regex in
`paste-ctrl-v-class-regex`, matched against `"res_name.res_class"`, e.g.:

```sh
gsettings set org.funes.Funes paste-ctrl-v-class-regex 'Chromium|jetbrains'
```

## Data and privacy

History lives in `$XDG_DATA_HOME/funes/history.json` (usually
`~/.local/share/funes/history.json`), created with mode `0600` in a `0700`
directory. It is plain text: anything you copy is on disk until evicted.

Entries are skipped when the clipboard advertises a password-manager hint
(`x-kde-passwordManagerHint`, `text/x-kde-passwordManagerHint`,
`org.nspasteboard.ConcealedType`), when the text is blank, or when it exceeds
`max-item-bytes` (1 MiB default). Additional regex filters and a global pause
switch are in Settings.

## Settings (GSettings `org.funes.Funes`)

| Key | Default | Meaning |
| --- | --- | --- |
| `history-size` | 200 | max unpinned items |
| `hotkey` | `<Super>v` | global shortcut |
| `paste-on-select` | true | inject the paste keystroke after copying |
| `paste-ctrl-v-class-regex` | `''` | WM_CLASS regex pasted with Ctrl+V instead of Shift+Insert |
| `paste-sets-primary` | true | also set the PRIMARY selection when pasting |
| `launch-at-login` | true | manage the autostart entry |
| `popup-width` / `popup-height` | 500 / 400 | popup size |
| `remember-size` | true | persist size after resizing |
| `max-item-bytes` | 1048576 | ignore larger clipboard text |
| `reown-clipboard` | true | keep copied text alive after the source app exits |
| `ignore-enabled` | false | pause capturing |
| `ignore-regexes` | `[]` | drop entries matching any regex |

`reown-clipboard` exists because on X11 clipboard contents die with the owning
client; Funes takes ownership after each capture so copied text survives closing
the source application (Klipper/GPaste behaviour).

## Known limitations

- **X11 only.** Wayland needs `wlr-data-control` / portals; the clipboard code is
  isolated in `src/clipboard-monitor.vala` and the injection code in
  `src/paster.vala` for future backends. Under Wayland, paste-on-select is
  disabled (XTEST would only reach XWayland clients).
- **Text only.** Images and rich text are not stored yet.
- **One clipboard manager at a time.** Running Funes alongside CopyQ, Klipper,
  GPaste, Diodon, etc. makes both fight over clipboard ownership. Disable the
  others first.
- Global shortcut registration assumes Cinnamon's keybinding schema; on other
  desktops bind `funes toggle` manually.

## Layout

```
src/json-mini.vala        minimal JSON reader/writer (no json-glib dependency)
src/history-item.vala     one history entry
src/history-store.vala    storage interface (SQLite can implement this later)
src/json-file-store.vala  JSON file backend: dedup, pinning, cap, atomic save
src/settings.vala         GSettings wrapper
src/clipboard-monitor.vala XFixes clipboard watch, secret filtering, re-owning
src/paster.vala           XTEST keystroke injection, window raise/focus logic
vapi/funes-x11.vapi       Xlib/XTEST declarations missing from valac's x11.vapi
src/hotkey.vala           Cinnamon custom keybinding registration
src/autostart.vala        launch at login
src/tray.vala             XAppStatusIcon + menu
src/popup-window.vala     centered history popup
src/settings-dialog.vala  preferences
src/main.vala             GApplication, CLI verbs
tests/test-store.vala     store/JSON unit tests
```

## License

GPL-3.0-or-later. See [COPYING](COPYING).
