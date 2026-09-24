# Clipboard format fidelity

Why file copy doesn't work, why Inkscape SVG pastes as a raster image, and the
plan to make Funes never silently drop a clipboard format — including ones
that don't exist yet.

## Current architecture (as of 0.11.0)

`app/clipboard.py` branches at capture time into exactly two `kind`s:

- **`image`** — taken whenever *any* offered target starts with `image/`.
  All offered targets are captured verbatim into `Capture.reps: dict[mime,
  bytes]` and (before this fix) attempted to replay byte-for-byte on paste via
  `Gtk.Clipboard.set_with_data` — see Bug 2 below for why that call never
  actually worked.
- **`text`** — taken when one of a fixed set of text atoms (`UTF8_STRING`,
  `text/plain`, `STRING`, ...) is offered and no image target is offered.
  Only the string itself is kept; no other target survives.

Anything that is neither is **silently dropped** — nothing is captured, and
the entry never appears in history.

### Bug 1 — file copy doesn't work at all

File managers (Nemo/Nautilus/Files) put `text/uri-list` and
`x-special/gnome-copied-files` on the clipboard (the latter also encodes
cut-vs-copy). Neither matches the `has_text` atom list nor `image/*`, so
`_on_targets` takes neither branch — the copy is invisible to Funes.

### Bug 2 — Inkscape SVG pastes back as a raster image

Inkscape offers `image/svg+xml` (and `image/x-inkscape-svg`), so this *does*
match the `image/*` branch, and the multi-format capture logic runs — the
capture itself is fine. The bug is in how Funes re-serves the data, and it's
not a timing/logic bug so much as a hard PyGObject limitation:
`Gtk.Clipboard.set_with_data()` — the call both the reown step and
`_set_image_item` (the popup's own paste path) used for "verbatim multi-format
replay" — **cannot be called from PyGObject at all**. GObject Introspection
can't safely bind its raw `GtkTargetEntry[]` + owner-callback signature, so
PyGObject marks it `_unsupported_data_method`; calling it always raises
`AttributeError`. That exception was caught by a broad `except Exception` and
silently fell back to `set_image(pixbuf)`, which rasterizes to a single PNG
target — **every single time**, on any system, not just occasionally. That's
why selecting the Inkscape entry from the Funes popup and pasting always came
back as PNG/JPEG.

Confirmed by reproducing it directly:

```pycon
>>> cb.set_with_data(targets, get_func, clear_func, None)
AttributeError: 'Clipboard' object has no attribute 'set_with_data'
```

Fixed by replacing `set_with_data()` with the primitives GI *can* bind
safely — `Gtk.selection_add_target()` / `Gtk.selection_owner_set()` plus the
`selection-get`/`selection-clear-event` signals on a hidden `Gtk.Invisible`
widget — used by both the reown step and `_set_image_item`
(`app/clipboard.py::_own_clipboard_verbatim`).

## Prior art

| Project    | Model | Fidelity for unknown formats |
|---|---|---|
| **Maccy** (macOS) | Fixed allowlist of `NSPasteboard.PasteboardType`s (`fileURL, html, png, rtf, string, tiff`) + a separate ignore-list for transient/concealed markers. | Anything outside the allowlist is dropped. |
| **Parcellite** | Text-only, minimal `gtk_clipboard_wait_for_targets` use. | No fidelity beyond plain text. |
| **CopyQ** | Format-agnostic core: `copy(mimeType, data, [mimeType, data]...)` stores **any** MIME as a raw byte blob, no allowlist. Type-specific renderers/heuristics (image thumbnail, HTML preview, ...) sit on top of that as a display layer. | Nothing is dropped — unknown formats still round-trip byte-for-byte, just without a specialized preview. |

CopyQ's model is the one we're adopting: **capture is format-agnostic;
presentation is mime-driven and additive.**

## Direction (agreed)

1. **Capture model — generic, not allowlisted.** Every clipboard change
   requests *all* offered targets and stores each as a verbatim byte
   representation (already how the image path works — generalize it to run
   for every capture, not only when an `image/*` target is present).
   Per-representation size cap reuses the existing `max_image_bytes`-style
   watchdog/cap, now applied uniformly to every rep, not just image ones.
2. **`kind` becomes a display hint, not a capture gate.** Storage never
   depends on recognizing the mime. A `classify(reps, text) -> Kind`
   function runs *after* capture to pick how to render the row (`text`,
   `image`, `files`, `richtext`, ...), with **`other`** as a guaranteed
   fallback for anything unrecognized — that item is still fully stored and
   replayable, just shown with a generic "N bytes of `application/x-foo`"
   row instead of a specialized preview. This is what makes future,
   currently-unknown clipboard formats "supported out of the box": nothing
   about capture needs to change when a new mime shows up, only the
   presentation layer (optional, additive) needs to catch up.
3. **File copy/cut** needs three targets specifically:
   - `text/uri-list` — cross-desktop, minimum required for paste-as-files.
   - `x-special/gnome-copied-files` — Nemo/Nautilus cut-vs-copy flag + the
     copied path list; needed for correct cut semantics and icon.
   - `application/x-kde-cutselection` (+ KDE variants) — Dolphin interop.
   Row UI: file name(s), source app, and a distinct cut/copy icon, per the
   existing TODO bullet.
4. **SVG (Inkscape and friends)** is vector data, not a raster image:
   `image/svg+xml` / `image/x-inkscape-svg` reps are never round-tripped
   through `GdkPixbuf` for storage or paste-back — only for generating the
   list-row *thumbnail* preview (rsvg-backed `PixbufLoader` already handles
   that). The verbatim SVG bytes are what gets replayed on paste.
5. **Reown must always be a verbatim multi-format replay** (fixed for images
   in this change) — never a lossy re-encode — for every kind, so Funes
   never degrades what's on the system clipboard just by observing it.

## Rollout (small atomic commits, per AGENTS.md)

- [x] Replace `Gtk.Clipboard.set_with_data()` (unusable from PyGObject —
      `_unsupported_data_method`) with `Gtk.selection_add_target()` +
      `Gtk.selection_owner_set()` + `selection-get`/`selection-clear-event`
      on a `Gtk.Invisible` widget, shared by both the reown step and
      `_set_image_item` (`app/clipboard.py::_own_clipboard_verbatim`).
      Fixes the Inkscape-pastes-as-raster bug for any multi-format
      image/vector copy, both for passive reown and for paste-from-popup.
      Regression-tested against a real clipboard round-trip in
      `tests/test_clipboard.py`.
- [ ] Generalize the capture chain (`_on_targets` / `_capture_image`) to
      request *all* offered targets, not just `image/*` ones, gated by the
      same size cap.
- [ ] Add `classify()` mime → display-kind heuristic with `other` fallback;
      stop branching capture on `kind`.
- [ ] Add `files` kind: parse `text/uri-list` + `x-special/gnome-copied-files`
      (+ KDE variant), new `FileRow` UI, cut/copy icon, schema bump for any
      needed columns.
- [ ] Add `other`/opaque row presentation (mime label + byte size, no crash,
      no data loss) so nothing new is ever silently dropped again.
- [ ] Treat `image/svg+xml` / `image/x-inkscape-svg` as vector: thumbnail via
      rsvg, verbatim bytes for storage/paste, never re-encoded to raster.

See [`TODO.md`](TODO.md) → *Cross features* for the tracked checklist form of
this list.
