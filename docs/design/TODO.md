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
- [ ]

## Platform fit (Mint / XApp conventions)
- [x] Preferences window matched to nemo/xed: `XApp.PreferencesWindow` instead of `Gtk.Window` + CSD `Gtk.HeaderBar`, server-side title bar, resizable + scrolled content, Esc to close, bottom action bar with *Close*, dialog type-hint + skip-taskbar, title "Funes Preferences", tray item renamed to *Preferences* (`app/preferences.py`, `app/tray.py`).

## Cross features
- [ ] Fuzzy search
- [ ] Image support

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
- [ ] **Keys** — `Ctrl+,` opens Settings from the popup, closes popup first (`app/popup.py`, `app/funes_app.py`)
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

- Icon concepts (A–E in `proposals.html`) — no winner picked; tracked as a separate design decision, not part of this roadmap.
