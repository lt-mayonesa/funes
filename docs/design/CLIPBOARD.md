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

## Bug 3 — local `file://` image copy registers nothing at all

Reported after the rest of this rollout landed: "Copy Image" on a browser
tab that's literally a local file (`file:///home/.../pic.png`, the browser's
built-in standalone image view, not an `<img>` inside an HTML page) produced
**no entry at all** in Funes — not even a wrong/mislabeled one. The exact
same image copied from a remote URL, or from a `data:` URL, worked fine.

Root cause: `_capture_reps`'s async chain requested targets **sequentially**
(`request_next()` only moves on once the previous `request_contents()`
callback fires) behind a single 500ms watchdog that only *set a flag* —
it never actually called `_finish()`. GTK/X11 give no delivery guarantee for
`request_contents()`: if a source advertises a target in `TARGETS` it
doesn't actually implement serving, the callback for that target may simply
never fire, not just fire late. Whatever the browser does differently for a
local-file "document" (plausibly: it also advertises a target — e.g.
`text/uri-list` pointing at the file — that its own "Copy Image" codepath
doesn't reliably answer for this case), if the stuck target happened to be
requested *before* the image bytes, `request_next()` never got called again:
no more requests fired, nothing captured, `_finish()` never ran, no signal,
no log line tied to the actual drop. This same architecture already existed
pre-CLIPBOARD.md for image-only capture; it just never got exercised because
image/\* targets are almost always served reliably, and the old code never
requested anything else alongside them.

Fixed two ways in `app/clipboard.py::_capture_reps`:

1. The watchdog now calls `_finish()` directly when it fires, using whatever
   was captured so far, instead of only marking a flag that's checked
   reactively inside callbacks that may never run.
2. Every mime (plus text) is now requested **concurrently** up front rather
   than sequentially, tracked via a `pending` set and `SelectionData.get_target()`
   (not `get_data_type()`, which isn't reliable for a declined request) —
   so a stuck target can no longer block ones requested alongside it,
   regardless of list order.

Regression-tested in `tests/test_clipboard.py::WatchdogTests` using a
duck-typed fake clipboard whose `request_contents()` never calls back for
one chosen mime — deterministic and fast (no real X11/browser timing
dependency), verified to fail (one hangs past a 15s hard timeout, the other
fails immediately with a clear assertion) against the pre-fix code and pass
against the fix.

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
- [x] Make the capture watchdog actually finish a stalled chain (using
      whatever was captured so far) instead of only setting a flag nothing
      re-checks if the stuck target's callback never fires at all, and
      request every target concurrently instead of sequentially so a stuck
      target can't block others requested alongside it. Fixes Bug 3 above.
      Regression-tested in `tests/test_clipboard.py::WatchdogTests` with a
      fake clipboard that never answers one chosen mime.
- [x] Foundation: extract the capture chain into a reusable, kind-agnostic
      `_capture_reps()` (was `_capture_image()`, hardcoded to image mimes),
      and pull the canonical-mime-selection logic out into a pure,
      display-independent `pick_canonical_mime()` (`funes/item.py`, unit
      tested in `tests/test_item.py`). No user-visible behavior change —
      sets up the rest of this list without adding new risk on its own.
- [ ] Actually widen the capture *trigger* to request every non-meta target
      (not just `image/*`), gated by the same size cap, and add `classify()`
      (mime → display-kind heuristic) with an `other` fallback so nothing
      newly captured this way is ever unrenderable. These two land together
      deliberately: widening what's captured without a safe fallback
      presentation would be a regression, not an improvement.
- [ ] Add `files` kind: parse `text/uri-list` + `x-special/gnome-copied-files`
      (+ KDE variant), new `FileRow` UI, cut/copy icon, schema bump for any
      needed columns.
- [ ] Add `other`/opaque row presentation (mime label + byte size, no crash,
      no data loss) so nothing new is ever silently dropped again.
- [ ] Treat `image/svg+xml` / `image/x-inkscape-svg` as vector: thumbnail via
      rsvg, verbatim bytes for storage/paste, never re-encoded to raster.

See [`TODO.md`](TODO.md) → *Cross features* for the tracked checklist form of
this list.
