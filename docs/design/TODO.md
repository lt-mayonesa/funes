# Design TODO

Tracks every change proposed in [`proposals.html`](proposals.html) (Spine /
Ledger / Palette / Atrium + the shared key map), organized by how soon it's
worth doing rather than by which proposal it came from. Icon concepts are
tracked separately — no winner has been picked yet.

Each item is tagged with the proposal it
came from (**Spine**, **Ledger**, **Palette**, **Atrium**, **Keys**) so it can
still be traced back to `proposals.html`.

All styles of Funes will actually configurable features so users can use it in the way they want. TBD how Funes ships by default: 
**Spine & Ledger** are a way of visualizing the main list.
**Pallet** can be toggled on or off, and it allows users to split the list (which is still shown with either Spine or Ledger).
**Atrium** can also be toggled on or off, and it either shows or not the side panel with the preview.

## Bugs I find
- [x] Popup window does not open in the active monitor, if I focus on a terminal in my second monitor window still opens in the primary. — `CENTER_ALWAYS` let the WM re-center on map, and the anchor was the pointer monitor; now `popup-monitor-order` (focused → pointer → primary, user-sortable in Settings) drives placement (`funes/monitors.py`, `app/popup.py`, `app/preferences.py`). X11 only, see [`WAYLAND.md`](WAYLAND.md).
- [x] Changing the global shortcut in preferences does not update it globaly. It also is a free text field, it should detect key combos. — Preferences now shows a Cinnamon-style capture button (click, press combo; Esc cancels, Backspace clears, reset button back to `<Super>v`) instead of a text entry (`app/shortcut.py`); the daemon watches `changed::hotkey` and calls `hotkey.apply()`, which re-registers or removes the Cinnamon keybinding and bounces `custom-list` so Cinnamon re-reads the grab (`app/funes_app.py`, `funes/hotkey.py`, `funes/accel.py`). Modifier-less combos are allowed but warned about, bare reserved keys refused. X11 only, see [`WAYLAND.md`](WAYLAND.md).
- [ ] In some apps, if I select a section of text (eg: in Google Chrome full URL in navigation bar) when I open Funes that selection is lost. So when pasting it's actually appended to the url instead of replaced. Also happens in nemo, doesn't happen in Intellij. In xed it prepends.

## Platform fit (Mint / XApp conventions)
- [x] Preferences window matched to nemo/xed: `XApp.PreferencesWindow` instead of `Gtk.Window` + CSD `Gtk.HeaderBar`, server-side title bar, resizable + scrolled content, Esc to close, bottom action bar with *Close*, dialog type-hint + skip-taskbar, title "Funes Preferences", tray item renamed to *Preferences* (`app/preferences.py`, `app/tray.py`).

## Cross features
- [x] Fuzzy search (FZF-style ranking via `thefuzz`, min score 50/100)
- [x] Image support
- [ ] Rich text support.
- [ ] File copy paste support: copying or cutting a file in any file manager and then pasting should work as if no clipboard manager was installed (all types supported should still be supported). Cut and copy operation should be registered in funes showing the file name, where the file was copied from and a distinctive icon. Needs `text/uri-list` + `x-special/gnome-copied-files` support — see [`CLIPBOARD.md`](CLIPBOARD.md). Partially unblocked: such a copy is no longer silently dropped (shows up as a generic `other` row now), but there's no dedicated files presentation/paste-as-files yet.
- [x] Copy pasting from software like inkscape should work correctly, currently if I copy svg data it gets pasted as an image. — root cause was `Gtk.Clipboard.set_with_data()` being unusable from PyGObject (`_unsupported_data_method`, always raises `AttributeError`), so both the reown step and paste-from-popup silently fell back to a single rasterized PNG every time. Fixed by replacing it with `Gtk.selection_add_target()`/`Gtk.selection_owner_set()` + selection signals on a `Gtk.Invisible` widget (`app/clipboard.py::_own_clipboard_verbatim`), regression-tested in `tests/test_clipboard.py`. Storing/pasting the SVG rep itself without ever decoding it to a pixbuf (thumbnail-only rsvg use) is still open, tracked below.
- [ ] Make password copying configurable, also configure whether to show the password as plain text or masked.
- [ ] **Foundational** — generalize clipboard capture to be format-agnostic (capture every offered target verbatim, not just `image/*` + a fixed text-atom allowlist) so no current or future clipboard format is silently dropped; `kind` becomes a mime-driven display hint with a guaranteed `other`/opaque fallback instead of a capture-time branch. Design + rollout plan: [`CLIPBOARD.md`](CLIPBOARD.md).
- [ ] Treat `image/svg+xml` / `image/x-inkscape-svg` as vector data end-to-end: thumbnail via rsvg, but never decode-then-reencode the stored/pasted bytes (depends on the foundational item above).
- [ ] Generic "other" row presentation for unrecognized mimes (label + byte size), so unsupported-today formats still round-trip instead of vanishing (depends on the foundational item above).

## Now — cheap, no store/model changes

- [x] **Spine** — number gutter (Alt+1–9 quick-select), reserved width so text never shifts
- [x] **Keys** — `Alt+1…9` pastes the numbered row; `Ctrl+Alt+1…9` copies only
- [x] **Spine** — right gutter: relative age (`12s / 4m / 1h / yest.`)
- [x] **Spine** — monospace heuristic for code-ish rows
- [x] **Spine** — match highlight (bold + accent, underline when selected)
- [x] **Spine** — pinned items float to top, star instead of a number
- [x] **Spine** — dense rows (28px), compact search row with icon + inline count
- [x] **Spine** — contextual footer: keycap legend, narrates the next `Enter` while filtering
- [x] **Spine** — dedicated empty states (no match / empty history), never a blank rectangle
- [x] **Spine** — default popup size `640×420` (9 rows)
- [ ] WONT DO - **Keys** — two-stage `Esc`: first clears the filter, second closes (`app/popup.py` `_on_key_press`)
- [ ] **Keys** — `Ctrl+Shift+V` paste as plain text, strips formatting/trailing newline (`app/popup.py`, `funes/paster.py`)
- [ ] **Keys** — `Ctrl+Z` undo last removal, session-scoped single level (`app/popup.py`, `funes/store.py`)
- [x] **Keys** — `Ctrl+,` opens Settings from the popup, closes popup first: popup hides then emits `settings-requested`, `FunesApp` presents (or re-presents) `PreferencesWindow`; footer legend, README and module docstring list it (`app/popup.py`, `app/funes_app.py`, `tests/test_popup_keys.py`)
- [ ] WONT DO - **Spine** — per-minute refresh of relative-age labels while the popup stays open (deferred in the original Spine pass)
- [ ] WONT DO - **Spine** — test dense-row ellipsis with mixed CJK/RTL strings (risk item, no code change implied yet)

## Next — Ledger + Palette increments (modest store/model work)

- [ ] **Ledger** — store: add `kind`, `source_wm_class`, `bytes` columns (`funes/store.py`, `funes/item.py`)
- [ ] **Ledger** — capture source app `WM_CLASS` at copy time; document + make it switchable off (privacy-adjacent)
- [ ] **Ledger** — sticky-ish group headers (Pinned / Today / Yesterday / Earlier) via `Gtk.ListBox.set_header_func()`
- [ ] **Ledger** — two-line rows: content line + quiet metadata line (kind · source · age · size)
- [ ] **Ledger** — kind chips: `url · sql · cmd · color · image · text`, heuristic-based
- [ ] **Ledger** — inline action chips on the selected row only (`↵ paste`, `⌃P unpin`, …), toggled on `row-selected`
- [ ] **Ledger** — header rows are non-selectable; `↑`/`↓` skip them instead of stopping dead
- [ ] **Palette** — oversized primary search line (17px text / 44px row)
- [ ] **Palette** — scope filter row (All / Pinned / Links / Code / Images), `Tab`/`Shift+Tab` cycle, resets on close
- [ ] **Palette** — footer names the real paste target window (cache focused `WM_CLASS` on popup open — `Paster` already tracks it)
- [ ] WONT DO - **Palette** — command mode entered when `>` is the first character, `Backspace` leaves it
- [ ] WONT DO - **Palette** — commands: *Clear history* (`Ctrl+L`), *Clear everything*, *Settings…*
- [ ] WONT DO - **Palette** — destructive commands show their blast radius inline before `Enter` (e.g. "removes 139 items")

## Later — Atrium (aspirational, needs compositor + bigger store work)

- [ ] **Atrium** — split view: fixed 300px list column + preview pane, min window 640px
- [ ] **Atrium** — preview renders full text (monospace), image thumbnails, full-bleed color swatch with hex/rgb/hsl
- [ ] **Atrium** — preview metadata block: kind/size, copied-from-app, use count, last used
- [ ] NICE TO HAVE **Atrium** — 90ms crossfade on selection change
- [ ] **Atrium** — store: use counters for frecency-based ranking
- [ ] **Atrium** — thumbnail cache; image payloads on disk instead of SQLite blobs
- [ ] WONT DO - **Atrium** — compositor blur/translucency with a solid fallback style when unavailable
- [ ] WONT DO - **Atrium** — RGBA visual + CSD-style drawing for the rounded floating window (brittle across WMs — needs testing per-WM)
- [ ] WONT DO - **Atrium** — narrower list-only fallback mode (~560px) for small monitors

## Explicitly out of scope for now

- Icon concepts — **done**: the ceibo-leaf mark ships as `org.x.funes` / `org.x.funes-symbolic` since 0.11.0 (`data/icons/hicolor/`). Concept galleries live in `docs/design/`.
