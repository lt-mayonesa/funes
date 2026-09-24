"""SQLite backed clipboard history — schema v2.

File: $XDG_DATA_HOME/funes/history.db (mode 0600).
Blobs: $XDG_DATA_HOME/funes/blobs/<sha[:2]>/<sha> (mode 0600).

v2 changes vs v1
----------------
- ``items`` gains ``kind``, ``content_hash`` (UNIQUE, replaces ``text`` UNIQUE),
  ``search_text``, ``mime``, ``blob_sha``, ``bytes``, ``width``, ``height``,
  ``ocr_text``.
- ``text`` is now nullable (NULL for image items).
- New ``representations`` table: (item_id, mime, blob_sha, bytes).
- Foreign-key cascade keeps rep rows in sync with item deletion.
- Migration (v1 → v2) is a table-rebuild inside one transaction.
"""

import contextlib
import logging
import sqlite3
from pathlib import Path
from typing import ClassVar

from gi.repository import GLib, GObject

from funes.blobs import BlobStore
from funes.item import Capture, HistoryItem, now_micros, sha256_hex

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2
DEFAULT_HISTORY_SIZE = 200

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY,
    kind         TEXT    NOT NULL DEFAULT 'text',
    content_hash TEXT    NOT NULL UNIQUE,
    text         TEXT,
    search_text  TEXT,
    mime         TEXT,
    blob_sha     TEXT,
    bytes        INTEGER NOT NULL DEFAULT 0,
    width        INTEGER,
    height       INTEGER,
    ocr_text     TEXT,
    pinned       INTEGER NOT NULL DEFAULT 0,
    created      INTEGER NOT NULL,
    last_used    INTEGER NOT NULL,
    copy_count   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS representations (
    item_id  INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    mime     TEXT    NOT NULL,
    blob_sha TEXT    NOT NULL,
    bytes    INTEGER NOT NULL,
    PRIMARY KEY (item_id, mime)
);

CREATE INDEX IF NOT EXISTS idx_items_order ON items (pinned DESC, last_used DESC);
CREATE INDEX IF NOT EXISTS idx_reps_blob   ON representations (blob_sha);
"""

# ---------------------------------------------------------------------------
# Migration: v1 → v2
# ---------------------------------------------------------------------------


def _migrate_v1_to_v2(db: sqlite3.Connection) -> None:
    """Rebuild the items table in-place, preserving all text entries.

    SQLite cannot drop a column constraint (the old ``text UNIQUE``), so the
    strategy is create-new / insert-select / drop-old / rename.
    Runs inside a single transaction; if anything fails the DB is untouched.
    """
    log.info("migrating history.db v1 → v2")
    db.executescript("""
        BEGIN;

        CREATE TABLE items_v2 (
            id           INTEGER PRIMARY KEY,
            kind         TEXT    NOT NULL DEFAULT 'text',
            content_hash TEXT    NOT NULL UNIQUE,
            text         TEXT,
            search_text  TEXT,
            mime         TEXT,
            blob_sha     TEXT,
            bytes        INTEGER NOT NULL DEFAULT 0,
            width        INTEGER,
            height       INTEGER,
            ocr_text     TEXT,
            pinned       INTEGER NOT NULL DEFAULT 0,
            created      INTEGER NOT NULL,
            last_used    INTEGER NOT NULL,
            copy_count   INTEGER NOT NULL DEFAULT 1
        );

        INSERT INTO items_v2
            (id, kind, content_hash, text, search_text, mime, blob_sha,
             bytes, width, height, ocr_text, pinned, created, last_used, copy_count)
        SELECT
            id,
            'text',
            lower(hex(sha256(text))),
            text,
            text,
            'text/plain',
            NULL,
            length(text),
            NULL,
            NULL,
            NULL,
            pinned,
            created,
            last_used,
            copy_count
        FROM items;

        CREATE TABLE representations (
            item_id  INTEGER NOT NULL REFERENCES items_v2 (id) ON DELETE CASCADE,
            mime     TEXT    NOT NULL,
            blob_sha TEXT    NOT NULL,
            bytes    INTEGER NOT NULL,
            PRIMARY KEY (item_id, mime)
        );

        DROP TABLE items;
        ALTER TABLE items_v2 RENAME TO items;

        CREATE INDEX idx_items_order ON items (pinned DESC, last_used DESC);
        CREATE INDEX idx_reps_blob   ON representations (blob_sha);

        COMMIT;
    """)


def default_path() -> str:
    return str(Path(GLib.get_user_data_dir()) / "funes" / "history.db")


def default_blob_root() -> Path:
    return Path(GLib.get_user_data_dir()) / "funes" / "blobs"


def default_thumb_root() -> Path:
    return Path(GLib.get_user_cache_dir()) / "funes" / "thumbs"


# ---------------------------------------------------------------------------
# HistoryStore
# ---------------------------------------------------------------------------


class HistoryStore(GObject.Object):
    """Newest first, pinned items first within that ordering."""

    __gsignals__: ClassVar[dict[str, tuple[object, ...]]] = {
        "changed": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(
        self,
        path: str | None = None,
        history_size: int = DEFAULT_HISTORY_SIZE,
        blob_root: Path | None = None,
        thumb_root: Path | None = None,
    ) -> None:
        super().__init__()
        self._path = path if path is not None else default_path()
        self._history_size = max(1, history_size)
        self._items: list[HistoryItem] = []
        self._blob_store = BlobStore(blob_root if blob_root is not None else default_blob_root())
        self._thumb_root = thumb_root if thumb_root is not None else default_thumb_root()
        self._connect()
        self._load()

    # --- storage plumbing ---

    def _connect(self) -> None:
        if self._path != ":memory:":
            path = Path(self._path)
            if path.parent != Path():
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.touch(mode=0o600, exist_ok=True)
            path.chmod(0o600)

        self._db = sqlite3.connect(self._path)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = NORMAL")

        version = self._db.execute("PRAGMA user_version").fetchone()[0]

        if version == 0:
            # Check if this is a v1 database (has items table without content_hash).
            tables = {
                row[0]
                for row in self._db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "items" in tables:
                # v1 database — check if sha256 is available (SQLite ≥ 3.43).
                try:
                    self._db.execute("SELECT lower(hex(sha256('test')))")
                    _migrate_v1_to_v2(self._db)
                except sqlite3.OperationalError:
                    # sha256() not available; fall back to Python-side migration.
                    self._migrate_v1_to_v2_python()
            else:
                # Fresh database — create schema from scratch.
                self._db.executescript(_SCHEMA)
        elif version == 1:
            try:
                self._db.execute("SELECT lower(hex(sha256('test')))")
                _migrate_v1_to_v2(self._db)
            except sqlite3.OperationalError:
                self._migrate_v1_to_v2_python()

        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION:d}")
        self._db.commit()

    def _migrate_v1_to_v2_python(self) -> None:
        """Fallback migration when SQLite's sha256() is not available."""
        log.info("migrating history.db v1 → v2 (Python sha256 fallback)")
        rows = self._db.execute(
            "SELECT id, text, pinned, created, last_used, copy_count FROM items"
        ).fetchall()

        with self._db:
            self._db.execute("""
                CREATE TABLE items_v2 (
                    id           INTEGER PRIMARY KEY,
                    kind         TEXT    NOT NULL DEFAULT 'text',
                    content_hash TEXT    NOT NULL UNIQUE,
                    text         TEXT,
                    search_text  TEXT,
                    mime         TEXT,
                    blob_sha     TEXT,
                    bytes        INTEGER NOT NULL DEFAULT 0,
                    width        INTEGER,
                    height       INTEGER,
                    ocr_text     TEXT,
                    pinned       INTEGER NOT NULL DEFAULT 0,
                    created      INTEGER NOT NULL,
                    last_used    INTEGER NOT NULL,
                    copy_count   INTEGER NOT NULL DEFAULT 1
                )
            """)
            self._db.executemany(
                """INSERT INTO items_v2
                   (id, kind, content_hash, text, search_text, mime,
                    bytes, pinned, created, last_used, copy_count)
                   VALUES (?, 'text', ?, ?, ?, 'text/plain', length(?), ?, ?, ?, ?)""",
                [
                    (
                        rowid,
                        sha256_hex(text.encode()),
                        text,
                        text,
                        text,
                        pinned,
                        created,
                        last_used,
                        count,
                    )
                    for rowid, text, pinned, created, last_used, count in rows
                ],
            )
            self._db.execute("""
                CREATE TABLE representations (
                    item_id  INTEGER NOT NULL REFERENCES items_v2 (id) ON DELETE CASCADE,
                    mime     TEXT    NOT NULL,
                    blob_sha TEXT    NOT NULL,
                    bytes    INTEGER NOT NULL,
                    PRIMARY KEY (item_id, mime)
                )
            """)
            self._db.execute("DROP TABLE items")
            self._db.execute("ALTER TABLE items_v2 RENAME TO items")
            self._db.execute("CREATE INDEX idx_items_order ON items (pinned DESC, last_used DESC)")
            self._db.execute("CREATE INDEX idx_reps_blob ON representations (blob_sha)")

    def _load(self) -> None:
        rows = self._db.execute(
            """SELECT id, kind, content_hash, text, search_text, mime,
                      blob_sha, bytes, width, height, ocr_text,
                      pinned, created, last_used, copy_count
               FROM items
               ORDER BY pinned DESC, last_used DESC"""
        ).fetchall()
        self._items = []
        for row in rows:
            (
                rowid,
                kind,
                content_hash,
                text,
                search_text,
                mime,
                blob_sha,
                nbytes,
                width,
                height,
                ocr_text,
                pinned,
                created,
                last_used,
                copy_count,
            ) = row
            # Load representations for any non-text item (image, other, ...).
            reps: dict[str, str] = {}
            if kind != "text":
                rep_rows = self._db.execute(
                    "SELECT mime, blob_sha FROM representations WHERE item_id = ?", (rowid,)
                ).fetchall()
                reps = dict(rep_rows)

            self._items.append(
                HistoryItem(
                    rowid=rowid,
                    kind=kind,
                    content_hash=content_hash,
                    text=text,
                    search_text=search_text,
                    mime=mime,
                    blob_sha=blob_sha,
                    bytes=nbytes,
                    width=width,
                    height=height,
                    ocr_text=ocr_text,
                    pinned=bool(pinned),
                    created=created,
                    last_used=last_used,
                    copy_count=copy_count,
                    reps=reps,
                )
            )
        if self._evict():
            self.emit("changed")
        self._startup_sweep()

    def _startup_sweep(self) -> None:
        """Remove orphan blobs whose SHA has no matching representation row."""
        known: set[str] = set()
        for row in self._db.execute("SELECT blob_sha FROM items WHERE blob_sha IS NOT NULL"):
            known.add(row[0])
        for row in self._db.execute("SELECT blob_sha FROM representations"):
            known.add(row[0])
        removed = self._blob_store.sweep(known)
        if removed:
            log.info("startup sweep: removed %d orphan blob(s)", removed)
        # Also sweep thumbnail cache.
        self._sweep_thumbs(known)

    def _sweep_thumbs(self, known: set[str]) -> None:
        if not self._thumb_root.is_dir():
            return
        removed = 0
        for p in self._thumb_root.iterdir():
            # Thumb names: <sha>@<px>x<scale>.png
            sha = p.name.split("@")[0] if "@" in p.name else None
            if sha not in known:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        if removed:
            log.debug("startup sweep: removed %d orphan thumb(s)", removed)

    # --- public API ---

    @property
    def path(self) -> str:
        return self._path

    @property
    def blob_store(self) -> BlobStore:
        return self._blob_store

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
        """Insert a capture at the top.

        If a capture with the same ``content_hash`` already exists, that entry
        is moved to the top instead of being duplicated. Returns the item now
        at the top, or None if the capture was rejected (blank text).
        """
        if capture.kind == "text" and (not capture.text or not capture.text.strip()):
            return None

        content_hash = capture.content_hash()
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

        # --- Build item fields from the capture ---
        if capture.kind == "text":
            assert capture.text is not None
            item = HistoryItem(
                kind="text",
                content_hash=content_hash,
                text=capture.text,
                search_text=capture.text,
                mime="text/plain",
                bytes=len(capture.text.encode("utf-8")),
            )
        else:
            # Store blobs first; collect sha per mime.
            reps_sha: dict[str, str] = {}
            canonical_sha: str | None = None
            canonical_bytes = 0
            for mime, data in capture.reps.items():
                sha = self._blob_store.put(data)
                reps_sha[mime] = sha
                if mime == capture.canonical_mime:
                    canonical_sha = sha
                    canonical_bytes = len(data)
            if canonical_sha is None and reps_sha:
                # Fallback: pick whatever we have.
                canonical_sha = next(iter(reps_sha.values()))

            item = HistoryItem(
                kind=capture.kind,
                content_hash=content_hash,
                text=None,
                search_text=capture.text,
                mime=capture.canonical_mime,
                blob_sha=canonical_sha,
                bytes=canonical_bytes,
                reps=reps_sha,
            )

        cursor = self._db.execute(
            """INSERT INTO items
               (kind, content_hash, text, search_text, mime, blob_sha,
                bytes, width, height, ocr_text, pinned, created, last_used, copy_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
            (
                item.kind,
                item.content_hash,
                item.text,
                item.search_text,
                item.mime,
                item.blob_sha,
                item.bytes,
                item.width,
                item.height,
                item.ocr_text,
                item.created,
                item.last_used,
                item.copy_count,
            ),
        )
        item.rowid = cursor.lastrowid

        if item.kind != "text" and item.reps:
            self._db.executemany(
                "INSERT INTO representations (item_id, mime, blob_sha, bytes) VALUES (?, ?, ?, ?)",
                [
                    (item.rowid, mime, sha, len(capture.reps[mime]))
                    for mime, sha in item.reps.items()
                ],
            )

        self._db.commit()
        self._items.insert(0, item)
        self._sort()
        self._evict()
        self.emit("changed")
        return item

    def set_image_dimensions(self, item: HistoryItem, width: int, height: int) -> None:
        """Update width/height for an image item and rebuild search_text baseline.

        The baseline search_text for images is always ``<mime_short> <w>x<h>``
        (e.g. ``png 1920x1080``) so images are findable by type/size even when
        OCR is not installed.  Any existing OCR text is preserved.
        """
        if item not in self._items:
            return
        item.width = width
        item.height = height
        # Rebuild baseline search_text: mime short name + dimensions.
        short_mime = (item.mime or "").split("/")[-1].lower()  # e.g. "png"
        baseline = f"{short_mime} {width}x{height}".strip()
        # Preserve any previously written OCR text.
        ocr_part = item.ocr_text or ""
        item.search_text = f"{baseline}\n{ocr_part}".strip() if ocr_part else baseline
        self._db.execute(
            "UPDATE items SET width = ?, height = ?, search_text = ? WHERE id = ?",
            (width, height, item.search_text, item.rowid),
        )
        self._db.commit()
        self.emit("changed")

    def set_ocr_text(self, item: HistoryItem, ocr_text: str) -> None:
        """Store OCR result and update the search corpus.

        Keeps the existing baseline (mime + dimensions set by
        set_image_dimensions) and appends the OCR text so both remain
        searchable.
        """
        if item not in self._items:
            return
        item.ocr_text = ocr_text
        # Rebuild: baseline (mime + dims) + OCR text.
        short_mime = (item.mime or "").split("/")[-1].lower()
        dims = f"{item.width}x{item.height}" if item.width and item.height else ""
        baseline = f"{short_mime} {dims}".strip()
        item.search_text = f"{baseline}\n{ocr_text}".strip() if baseline else ocr_text
        self._db.execute(
            "UPDATE items SET ocr_text = ?, search_text = ? WHERE id = ?",
            (item.ocr_text, item.search_text, item.rowid),
        )
        self._db.commit()
        self.emit("changed")

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
        # Collect blob SHAs before deleting (FK cascade removes rep rows).
        blob_shas = list(item.reps.values())
        if item.blob_sha:
            blob_shas.append(item.blob_sha)
        self._db.execute("DELETE FROM items WHERE id = ?", (item.rowid,))
        self._db.commit()
        self._gc_blobs(blob_shas)
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
        doomed = [item for item in self._items if not item.pinned]
        blob_shas: list[str] = []
        for item in doomed:
            blob_shas.extend(item.reps.values())
            if item.blob_sha:
                blob_shas.append(item.blob_sha)

        self._items = [item for item in self._items if item.pinned]
        self._db.execute("DELETE FROM items WHERE pinned = 0")
        self._db.commit()
        self._gc_blobs(blob_shas)
        self.emit("changed")

    def flush(self) -> None:
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- internals ---

    def _find_by_hash(self, content_hash: str) -> HistoryItem | None:
        for item in self._items:
            if item.content_hash == content_hash:
                return item
        return None

    def _sort(self) -> None:
        self._items.sort(key=lambda item: (not item.pinned, -item.last_used))

    def _evict(self) -> bool:
        """Drop the oldest unpinned items above the cap."""
        unpinned = [item for item in self._items if not item.pinned]
        excess = len(unpinned) - self._history_size
        if excess <= 0:
            return False
        doomed = sorted(unpinned, key=lambda item: item.last_used)[:excess]
        blob_shas: list[str] = []
        for item in doomed:
            blob_shas.extend(item.reps.values())
            if item.blob_sha:
                blob_shas.append(item.blob_sha)

        self._db.executemany("DELETE FROM items WHERE id = ?", [(item.rowid,) for item in doomed])
        self._db.commit()
        for item in doomed:
            self._items.remove(item)
        self._gc_blobs(blob_shas)
        return True

    def _gc_blobs(self, shas: list[str]) -> None:
        """Delete blobs that have no remaining representation row."""
        for sha in set(shas):
            row = self._db.execute(
                "SELECT 1 FROM representations WHERE blob_sha = ? LIMIT 1", (sha,)
            ).fetchone()
            if row is None:
                # Also check canonical blob_sha on items (in case reps was empty).
                row2 = self._db.execute(
                    "SELECT 1 FROM items WHERE blob_sha = ? LIMIT 1", (sha,)
                ).fetchone()
                if row2 is None:
                    self._blob_store.delete(sha)
                    self._gc_thumbs(sha)

    def _gc_thumbs(self, sha: str) -> None:
        if not self._thumb_root.is_dir():
            return
        for p in self._thumb_root.glob(f"{sha}@*.png"):
            with contextlib.suppress(OSError):
                p.unlink()
