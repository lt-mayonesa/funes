# Image support design

Tracks the implementation of clipboard image capture, storage, and paste-back for Funes, spanning 4 PRs + 1 optional OCR layer.

## Locked decisions

| Q | Decision |
|---|---|
| Model | Generic `representations(mime, bytes)` table, Maccy-shape; only `image/*` enabled now |
| Storage | Blobs on disk + SQLite metadata, sha256-keyed, refcounted |
| Thumbs | Pre-generated PNG cache on disk |
| Dedup | sha256 of canonical rep; `content_hash` UNIQUE replaces `text` UNIQUE |
| Paste | Verbatim replay of every stored rep (Maccy `setData(forType:)` equivalent) |
| Limits | `max-image-bytes` 10 MiB + `capture-images` toggle |
| Row | Taller image rows + `image-row-height` key (32/48/64, default 48) |
| Search | Image wins as kind; captured text is **hidden**, search-only |
| Formats | Any `image/*` target the source offers |
| OCR | tesseract, on by default when installed, single toggle, no extra guards |
| Migration | In-place v1→v2, backfill `content_hash`, no data loss |
| Delivery | 4 stacked PRs |

## PR 1 — store, model, migration (no user-visible change)

### `funes/blobs.py` (new, GTK-free)
```python
BlobStore(root=$XDG_DATA_HOME/funes/blobs)
  put(data: bytes) -> str           # sha256 hex; tmpfile + os.replace; 0600, dirs 0700
  path(sha) -> Path                 # blobs/<sha[:2]>/<sha>
  read(sha) -> bytes
  delete(sha)
  sweep(known: set[str]) -> int     # startup orphan GC
```

### `funes/item.py`
- `HistoryItem` gains `kind` (`"text"|"image"`), `mime`, `width`, `height`, `blob_sha`, `bytes`, `search_text`, `reps: dict[str, str]` (mime → sha).
- `text` becomes `str | None`; `preview()` unchanged for text, returns metadata label for images (`PNG · 1920×1080 · 240 kB`).
- `describe()` (tooltip) per kind.
- New `Capture` dataclass (capture-time payload): `reps: dict[str, bytes]`, `text: str | None`, `kind`, `canonical_mime`.

### `funes/store.py` — schema v2
Schema v2 with migration from v1:
```sql
CREATE TABLE items (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'text',
  content_hash TEXT NOT NULL UNIQUE,
  text TEXT,              -- canonical text payload (NULL for image items)
  search_text TEXT,       -- hidden corpus: text + meta + ocr
  mime TEXT,              -- canonical rep mime ('text/plain' or image/*)
  blob_sha TEXT,          -- canonical blob (NULL for text)
  bytes INTEGER NOT NULL DEFAULT 0,
  width INTEGER, height INTEGER,
  ocr_text TEXT,
  pinned INTEGER NOT NULL DEFAULT 0,
  created INTEGER NOT NULL, last_used INTEGER NOT NULL,
  copy_count INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE representations (
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  mime TEXT NOT NULL, blob_sha TEXT NOT NULL, bytes INTEGER NOT NULL,
  PRIMARY KEY (item_id, mime)
);
CREATE INDEX idx_items_order ON items (pinned DESC, last_used DESC);
CREATE INDEX idx_reps_blob ON representations (blob_sha);
```

- `PRAGMA foreign_keys=ON`.
- Migration guarded by `PRAGMA user_version`: v1→v2 is table rebuild inside one transaction (SQLite can't drop `text UNIQUE`): create `items_new`, `INSERT ... SELECT` with `content_hash = sha256(text)`, `kind='text'`, `mime='text/plain'`, `search_text=text`, drop old, rename. Duplicate-hash rows impossible (old UNIQUE guaranteed it).
- `add(text)` → `add(capture: Capture)`; text path keeps identical semantics (dedup bumps `last_used`/`copy_count`, moves to top).
- Image bytes never held in the in-memory mirror — only sha/metadata. Reads go through `BlobStore` on demand.
- `remove()`/`_evict()`/`clear()` delete rep rows then drop blobs whose refcount hits 0 (`SELECT 1 FROM representations WHERE blob_sha=? LIMIT 1`), and their thumbs.
- Startup `sweep()` of orphan blobs/thumbs.
- `history-size` cap counts all kinds.

## PR 2 — capture + copy-back (still no new UI)

### `app/clipboard.py`
- `captured` signal signature `(str,)` → `(object,)` carrying `Capture`.
- On `owner-change`: `request_targets` → secret filter (unchanged) → partition targets: `image/*` (any, per decision) vs text.
- If images present and `capture-images` on: async chain `request_contents(atom, cb)` over each image target, accumulate bytes; also `request_text` for the hidden search string. Async (not `wait_for_contents`) so a slow/hostile owner cannot freeze the popup; a 500 ms watchdog aborts the chain.
- Reject rep if `len(bytes) > max_image_bytes` (per-rep); reject whole capture if all reps rejected. Log at debug like oversized text.
- `kind = "image"` whenever ≥1 image rep survived; text goes to `search_text` only.
- Canonical rep: `image/png` if offered, else largest-bytes rep. `content_hash = sha256(canonical bytes)`.
- Hashing + PNG decode for `width/height` in a worker thread, result delivered via `GLib.idle_add` → keeps 10 MiB screenshots off the UI thread.
- `set_item(item)` replaces `set_text(text)`:
  - text item → current path (incl. PRIMARY when configured).
  - image item → `Gtk.Clipboard.set_with_data(targets, get_func, clear_func, data)` serving every stored rep byte-for-byte via `selection_data.set(atom, 8, blob_bytes)`; PRIMARY not set for images.
  - **Spike first**: `set_with_data` is historically flaky under PyGObject introspection. Fallback if unusable: `set_image(pixbuf)` (re-encode, fidelity loss) — decided at spike, documented in code comment.
  - `set_can_store(targets)` + `store()` so clipboard managers can persist it; self-owned guard already handles the echo.
- `reown-clipboard` for images: re-own via the same `set_with_data` path (blobs on disk make the payload outlive the source app, which is exactly the point).

### `app/funes_app.py`
- `_on_captured(monitor, capture)` → `store.add(capture)`.
- `_on_item_chosen` → `monitor.set_item(item)`.

### `funes/config.py` + gschema
- `capture-images` (b, default true)
- `max-image-bytes` (i, 1024…1073741824, default 10485760)

## PR 3 — UI: thumbnails, image rows, search (feature becomes visible)

### `funes/images.py` (new; uses `GdkPixbuf` only, no display needed)
- `probe(data, mime) -> (width, height)` via `PixbufLoader`.
- `thumbnail(sha, data, px, scale) -> Path` → `$XDG_CACHE_HOME/funes/thumbs/<sha>@<px>x<scale>.png`, generated at capture, regenerable, safe to delete.
- `meta_label(item) -> str` → `"PNG · 1920×1080 · 240 kB"` (pure, unit-tested in `tests/test_presentation.py` style).

### `app/popup.py`
- `ItemRow` split: `TextRow` (today's 28 px layout, untouched) and `ImageRow` (height from `image-row-height`, thumb at `height - 8` px, `scale-factor`-aware, meta label, same number gutter / pin / age gutter so Alt+1–9 and the gutters stay aligned). Mixed heights are fine for `Gtk.ListBox`; quick-select is index-based.
- Missing/corrupt thumb → `image-missing` icon, row still selectable/pasteable.
- No match highlight on image rows (the visible label is metadata, not the matched corpus).

### `funes/search.py`
- `filter_matches` moves from "list of strings, map back by text" to index-based (`list[tuple[int, str]]`) — required, since two image items can share the same `search_text`.
- Corpus per item = `search_text` (captured text) + `"image png 1920x1080"` synthetic terms for image items.

### Preferences
- New *Images* section — capture toggle, max size (MiB spin), row height combo (32/48/64).

### Tests
- `tests/test_images.py` (probe/thumbnail against a generated 2×2 PNG, meta labels)
- `tests/test_search.py` extended for index-based API + hidden-corpus matching

### Docs
- README feature line
- `docs/design/WAYLAND.md` row — image capture under Wayland inherits the existing focus-only clipboard limitation.

## PR 4 — OCR search

### `funes/ocr.py` (new, GTK-free)
- `available() -> bool` via `shutil.which("tesseract")`.
- `recognize(path) -> str` → `subprocess.run(["tesseract", path, "-", "-l", "eng"], timeout=20)`, stdout captured, no shell (bandit-clean).
- Serialized single worker thread + queue, so a burst of screenshots cannot spawn N tesseract processes.

### Wiring
- After an image item is stored, enqueue OCR.
- On completion `GLib.idle_add` → `store.set_ocr_text(item, text)` (updates `ocr_text` + `search_text`, emits `changed`).
- Backfill of pre-existing images: none (new captures only).

### Config
- `ocr-enabled` (b, default true)
- Preferences toggle, insensitive with an explanatory label when the binary is missing

### Packaging
- `debian/control`: `Recommends: tesseract-ocr`

## Risks / open technical spikes

1. **`set_with_data` under PyGObject** — blocking risk for PR 2; spike before writing the rest of that PR. Fallback = `set_image`.
2. **X11 INCR transfers** for >256 KB payloads: `request_contents` handles it, `wait_for_contents` can stall — another reason the capture chain is async.
3. **Disk growth** — Maccy #1496 (1.89 GB in 11 days) came from orphaned content rows; countered here by FK cascade + refcount GC + startup sweep. No total-disk budget (per-item cap only); can be added later.
4. **OCR privacy** — recognized text lands in `history.db` in plain text, on by default. README + Preferences will state it, no additional guards.
5. **`funes/` GTK-free rule** — `funes/images.py` imports `GdkPixbuf` (no display required). If that rule should be kept strict, the module moves to `app/`.
