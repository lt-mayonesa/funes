"""SQLite backed clipboard history with image support.

File: $XDG_DATA_HOME/funes/history.db (mode 0600, it holds clipboard text + metadata).
Writes are synchronous: sqlite in WAL mode is fast enough that the old
debounced-save dance is not worth the crash window.

The whole history (metadata) is mirrored in memory. Image bytes live on disk
under $XDG_DATA_HOME/funes/blobs/, keyed by sha256. The cap is 10 000 items.
"""

import hashlib
import sqlite3
from pathlib import Path
from typing import ClassVar

from gi.repository import GLib, GObject

from funes.blobs import BlobStore
from funes.item import Capture, HistoryItem, now_micros

SCHEMA_VERSION = 2
DEFAULT_HISTORY_SIZE = 200

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS items (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'text',
    content_hash TEXT NOT NULL UNIQUE,
    text       TEXT,
    search_text TEXT,
    mime       TEXT,
    blob_sha   TEXT,
    bytes      INTEGER NOT NULL DEFAULT 0,
    width      INTEGER, height INTEGER,
    ocr_text   TEXT,
    pinned     INTEGER NOT NULL DEFAULT 0,
    created    INTEGER NOT NULL,
    last_used  INTEGER NOT NULL,
    copy_count INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS representations (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    mime TEXT NOT NULL,
    blob_sha TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    PRIMARY KEY (item_id, mime)
);
CREATE INDEX IF NOT EXISTS idx_items_order ON items (pinned DESC, last_used DESC);
CREATE INDEX IF NOT EXISTS idx_reps_blob ON representations (blob_sha);
"""


def default_path() -> str:
    return str(Path(GLib.get_user_data_dir()) / "funes" / "history.db")


def _compute_hash(data: bytes) -> str:
    """Compute sha256 hex of data."""
    return hashlib.sha256(data).hexdigest()


def _compute_text_hash(text: str) -> str:
    """Compute sha256 hex of text (utf-8 encoded)."""
    return _compute_hash(text.encode("utf-8"))


class HistoryStore(GObject.Object):
    """Newest first, pinned items first within that ordering."""

    __gsignals__: ClassVar[dict[str, tuple[object, ...]]] = {
        # Emitted whenever the in-memory list changed.
        "changed": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, path: str | None = None, history_size: int = DEFAULT_HISTORY_SIZE) -> None:
        super().__init__()
        self._path = path if path is not None else default_path()
        self._history_size = max(1, history_size)
        self._items: list[HistoryItem] = []
        self._blob_store = BlobStore()
        self._connect()
        self._load()
        self._sweep_blobs()

    # --- storage plumbing ---

    def _connect(self) -> None:
        if self._path != ":memory:":
            path = Path(self._path)
            if path.parent != Path():
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            # Create with restrictive permissions before sqlite writes to it.
            path.touch(mode=0o600, exist_ok=True)
            path.chmod(0o600)

        self._db = sqlite3.connect(self._path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_SCHEMA_V2)

        current_version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if current_version == 0:
            # Fresh DB: set v2.
            self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION:d}")
            self._db.commit()
        elif current_version == 1:
            # Migrate v1 -> v2.
            self._migrate_v1_to_v2()
        elif current_version != SCHEMA_VERSION:
            raise RuntimeError(f"Unsupported schema version: {current_version}")

    def _migrate_v1_to_v2(self) -> None:
        """Migrate from schema v1 (text-only) to v2 (text+images)."""
        # Check if migration already happened (e.g., crash recovery).
        try:
            self._db.execute("SELECT 1 FROM items LIMIT 1")
            # If items table has content_hash, we're already v2.
            self._db.execute("SELECT content_hash FROM items LIMIT 1")
            self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION:d}")
            self._db.commit()
            return
        except sqlite3.OperationalError:
            # Old schema: content_hash column doesn't exist yet.
            pass

        # Rebuild: create items_new with v2 schema, migrate data.
        try:
            self._db.execute("BEGIN TRANSACTION")

            # Create new table with v2 schema.
            self._db.execute("""
                CREATE TABLE items_new (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL DEFAULT 'text',
                    content_hash TEXT NOT NULL UNIQUE,
                    text TEXT,
                    search_text TEXT,
                    mime TEXT,
                    blob_sha TEXT,
                    bytes INTEGER NOT NULL DEFAULT 0,
                    width INTEGER, height INTEGER,
                    ocr_text TEXT,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    created INTEGER NOT NULL,
                    last_used INTEGER NOT NULL,
                    copy_count INTEGER NOT NULL DEFAULT 1
                )
            """)

            # Copy data from old items table, computing content_hash for each row.
            self._db.execute("""
                INSERT INTO items_new
                    (id, kind, content_hash, text, search_text, mime, blob_sha,
                     bytes, pinned, created, last_used, copy_count)
                SELECT id, 'text',
                       hex(substr(zeroblob(32), 1, 32)) as dummy_hash,
                       text, text, 'text/plain', NULL,
                       0, pinned, created, last_used, copy_count
                FROM items
            """)

            # Now backfill content_hash with real sha256 hashes (must do this via Python).
            rows = self._db.execute("SELECT id, text FROM items_new").fetchall()
            for item_id, text_val in rows:
                if text_val is not None:
                    hash_val = _compute_text_hash(text_val)
                    self._db.execute(
                        "UPDATE items_new SET content_hash = ? WHERE id = ?",
                        (hash_val, item_id),
                    )

            # Drop old table and rename new one.
            self._db.execute("DROP TABLE items")
            self._db.execute("ALTER TABLE items_new RENAME TO items")

            # Recreate indices.
            self._db.execute("CREATE INDEX idx_items_order ON items (pinned DESC, last_used DESC)")
            self._db.execute("CREATE INDEX idx_reps_blob ON representations (blob_sha)")

            # Create representations table (empty for v1 items, they have no reps).
            self._db.execute("""
                CREATE TABLE representations (
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    mime TEXT NOT NULL,
                    blob_sha TEXT NOT NULL,
                    bytes INTEGER NOT NULL,
                    PRIMARY KEY (item_id, mime)
                )
            """)

            self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION:d}")
            self._db.commit()
        except Exception as e:
            self._db.rollback()
            raise RuntimeError(f"Failed to migrate schema v1 -> v2: {e}") from e

    def _load(self) -> None:
        """Load all items from DB into memory."""
        rows = self._db.execute(
            "SELECT id, kind, content_hash, text, search_text, mime, blob_sha, bytes,"
            "       width, height, ocr_text, pinned, created, last_used, copy_count"
            " FROM items ORDER BY pinned DESC, last_used DESC"
        ).fetchall()

        self._items = []
        for row in rows:
            (
                rowid,
                kind,
                _content_hash,
                text,
                search_text,
                mime,
                blob_sha,
                bytes_,
                width,
                height,
                ocr_text,
                pinned,
                created,
                last_used,
                copy_count,
            ) = row
            # Load representations for this item.
            rep_rows = self._db.execute(
                "SELECT mime, blob_sha FROM representations WHERE item_id = ?", (rowid,)
            ).fetchall()
            reps = dict(rep_rows)

            item = HistoryItem(
                text=text,
                created=created,
                last_used=last_used,
                pinned=bool(pinned),
                copy_count=copy_count,
                rowid=rowid,
                kind=kind,
                mime=mime,
                blob_sha=blob_sha,
                bytes=bytes_,
                width=width,
                height=height,
                search_text=search_text,
                reps=reps,
                ocr_text=ocr_text,
            )
            self._items.append(item)

        if self._evict():
            self.emit("changed")

    def _sweep_blobs(self) -> None:
        """Orphan GC: delete blobs not referenced by any representation."""
        rows = self._db.execute("SELECT DISTINCT blob_sha FROM representations").fetchall()
        known_shas = {sha for (sha,) in rows if sha}
        self._blob_store.sweep(known_shas)

    # --- public API ---

    @property
    def path(self) -> str:
        return self._path

    @property
    def history_size(self) -> int:
        return self._history_size

    @history_size.setter
    def history_size(self, value: int) -> None:
        self._history_size = max(1, int(value))
        if self._evict():
            self.emit("changed")

    def items(self) -> list[HistoryItem]:
        return list(self._items)

    def size(self) -> int:
        return len(self._items)

    def add(self, capture: Capture) -> HistoryItem | None:
        """Add a capture to history.

        For text captures: dedup by content_hash (text items with same text
        are moved to top, copy_count incremented).

        For image captures: dedup by sha256 of canonical rep.

        Returns the item now at the top, or None if rejected.
        """
        if capture.kind == "text":
            # Text-only capture.
            if not capture.text or not capture.text.strip():
                return None
            content_hash = _compute_text_hash(capture.text)
        else:
            # Image capture: use canonical rep's hash.
            if not capture.canonical_mime or capture.canonical_mime not in capture.reps:
                return None
            canonical_bytes = capture.reps[capture.canonical_mime]
            content_hash = _compute_hash(canonical_bytes)

        # Check for duplicate (by content_hash).
        existing = self._find_by_hash(content_hash)
        if existing is not None:
            existing.last_used = now_micros()
            existing.copy_count += 1
            self._db.execute(
                "UPDATE items SET last_used = ?, copy_count = ? WHERE id = ?",
                (existing.last_used, existing.copy_count, existing.rowid),
            )
            self._db.commit()
            self._sort()
            self.emit("changed")
            return existing

        # New item: store it.
        item = HistoryItem(
            text=capture.text if capture.kind == "text" else None,
            kind=capture.kind,
            search_text=capture.text,  # For now, search_text = captured text (no OCR yet).
            mime=capture.canonical_mime,
        )

        # For images: store representations and compute metadata.
        if capture.kind == "image":
            item.reps = {}
            for mime_, data in capture.reps.items():
                sha = self._blob_store.put(data)
                item.reps[mime_] = sha
                if mime_ == capture.canonical_mime:
                    item.blob_sha = sha
                    item.bytes = len(data)

        cursor = self._db.execute(
            "INSERT INTO items"
            " (kind, content_hash, text, search_text, mime, blob_sha, bytes, pinned,"
            "  created, last_used, copy_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (
                item.kind,
                content_hash,
                item.text,
                item.search_text,
                item.mime,
                item.blob_sha,
                item.bytes,
                item.created,
                item.last_used,
                item.copy_count,
            ),
        )
        item.rowid = cursor.lastrowid

        # Insert representations.
        for mime_, sha in item.reps.items():
            data_len = len(capture.reps[mime_])
            self._db.execute(
                "INSERT INTO representations (item_id, mime, blob_sha, bytes) VALUES (?, ?, ?, ?)",
                (item.rowid, mime_, sha, data_len),
            )

        self._db.commit()
        self._items.insert(0, item)
        self._sort()
        self._evict()
        self.emit("changed")
        return item

    def touch(self, item: HistoryItem) -> None:
        if item not in self._items:
            return
        item.last_used = now_micros()
        self._db.execute(
            "UPDATE items SET last_used = ? WHERE id = ?", (item.last_used, item.rowid)
        )
        self._db.commit()
        self._sort()
        self.emit("changed")

    def remove(self, item: HistoryItem) -> None:
        if item not in self._items:
            return
        self._items.remove(item)
        # Cascade delete via FK will remove representations.
        self._db.execute("DELETE FROM items WHERE id = ?", (item.rowid,))
        self._db.commit()
        # Clean up orphan blobs.
        self._sweep_blobs()
        self.emit("changed")

    def toggle_pin(self, item: HistoryItem) -> None:
        if item not in self._items:
            return
        item.pinned = not item.pinned
        self._db.execute(
            "UPDATE items SET pinned = ? WHERE id = ?", (1 if item.pinned else 0, item.rowid)
        )
        self._db.commit()
        self._sort()
        self._evict()
        self.emit("changed")

    def clear(self) -> None:
        """Drop everything except pinned items."""
        self._items = [item for item in self._items if item.pinned]
        self._db.execute("DELETE FROM items WHERE pinned = 0")
        self._db.commit()
        # Clean up orphan blobs.
        self._sweep_blobs()
        self.emit("changed")

    def set_ocr_text(self, item: HistoryItem, ocr_text: str) -> None:
        """Update OCR-extracted text for an image item."""
        if item not in self._items:
            return
        item.ocr_text = ocr_text
        # Append OCR text to search_text for fuzzy matching.
        if item.search_text:
            item.search_text = f"{item.search_text} {ocr_text}"
        else:
            item.search_text = ocr_text
        self._db.execute(
            "UPDATE items SET ocr_text = ?, search_text = ? WHERE id = ?",
            (ocr_text, item.search_text, item.rowid),
        )
        self._db.commit()
        self.emit("changed")

    def flush(self) -> None:
        """Kept for symmetry with the old debounced store: writes are already
        committed, this only makes sure nothing is left in the WAL."""
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- internals ---

    def _find_by_hash(self, content_hash: str) -> HistoryItem | None:
        """Find item by content_hash (dedup check)."""
        for stored in self._items:
            if stored.rowid:
                check = self._db.execute(
                    "SELECT 1 FROM items WHERE content_hash = ? AND id = ?",
                    (content_hash, stored.rowid),
                ).fetchone()
                if check:
                    return stored
        return None

    def _sort(self) -> None:
        """Pinned block on top, each block newest-first."""
        self._items.sort(key=lambda item: (not item.pinned, -item.last_used))

    def _evict(self) -> bool:
        """Drop the oldest unpinned items above the cap."""
        unpinned = [item for item in self._items if not item.pinned]
        excess = len(unpinned) - self._history_size
        if excess <= 0:
            return False
        doomed = sorted(unpinned, key=lambda item: item.last_used)[:excess]
        # Delete from DB (cascade will remove representations).
        for item in doomed:
            self._db.execute("DELETE FROM items WHERE id = ?", (item.rowid,))
        self._db.commit()
        # Clean up orphan blobs.
        self._sweep_blobs()
        for item in doomed:
            self._items.remove(item)
        return True
