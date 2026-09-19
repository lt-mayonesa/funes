"""SQLite backed clipboard history.

File: $XDG_DATA_HOME/funes/history.db (mode 0600, it holds clipboard text).
Writes are synchronous: sqlite in WAL mode is fast enough that the old
debounced-save dance is not worth the crash window.

The whole history is mirrored in memory. The cap is 10 000 items, so the list
is small, and keeping it around makes filtering in the popup instant.
"""

import os
import sqlite3

from gi.repository import GLib, GObject

from funes.item import HistoryItem, now_micros

SCHEMA_VERSION = 1
DEFAULT_HISTORY_SIZE = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id         INTEGER PRIMARY KEY,
    text       TEXT    NOT NULL UNIQUE,
    pinned     INTEGER NOT NULL DEFAULT 0,
    created    INTEGER NOT NULL,
    last_used  INTEGER NOT NULL,
    copy_count INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_items_order ON items (pinned DESC, last_used DESC);
"""


def default_path():
    return os.path.join(GLib.get_user_data_dir(), "funes", "history.db")


class HistoryStore(GObject.Object):
    """Newest first, pinned items first within that ordering."""

    __gsignals__ = {
        # Emitted whenever the in-memory list changed.
        "changed": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, path=None, history_size=DEFAULT_HISTORY_SIZE):
        super().__init__()
        self._path = path if path is not None else default_path()
        self._history_size = max(1, history_size)
        self._items = []
        self._connect()
        self._load()

    # --- storage plumbing ---

    def _connect(self):
        if self._path != ":memory:":
            directory = os.path.dirname(self._path)
            if directory:
                os.makedirs(directory, mode=0o700, exist_ok=True)
            fresh = not os.path.exists(self._path)
            if fresh:
                # Create with restrictive permissions before sqlite writes to it.
                os.close(os.open(self._path, os.O_CREAT | os.O_WRONLY, 0o600))
            os.chmod(self._path, 0o600)

        self._db = sqlite3.connect(self._path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)
        self._db.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
        self._db.commit()

    def _load(self):
        rows = self._db.execute(
            "SELECT id, text, pinned, created, last_used, copy_count FROM items"
            " ORDER BY pinned DESC, last_used DESC"
        ).fetchall()
        self._items = [
            HistoryItem(text, created=created, last_used=last_used,
                        pinned=bool(pinned), copy_count=copy_count, rowid=rowid)
            for rowid, text, pinned, created, last_used, copy_count in rows
        ]
        if self._evict():
            self.emit("changed")

    # --- public API ---

    @property
    def path(self):
        return self._path

    @property
    def history_size(self):
        return self._history_size

    @history_size.setter
    def history_size(self, value):
        self._history_size = max(1, int(value))
        if self._evict():
            self.emit("changed")

    def items(self):
        return list(self._items)

    def size(self):
        return len(self._items)

    def add(self, text):
        """Insert text at the top.

        If identical text already exists that entry is moved to the top instead
        of being duplicated (Maccy behaviour). Returns the item that now sits at
        the top, or None if the text was rejected.
        """
        if not text or not text.strip():
            return None

        existing = self._find_by_text(text)
        if existing is not None:
            existing.last_used = now_micros()
            existing.copy_count += 1
            self._db.execute(
                "UPDATE items SET last_used = ?, copy_count = ? WHERE id = ?",
                (existing.last_used, existing.copy_count, existing.rowid))
            self._db.commit()
            self._sort()
            self.emit("changed")
            return existing

        item = HistoryItem(text)
        cursor = self._db.execute(
            "INSERT INTO items (text, pinned, created, last_used, copy_count)"
            " VALUES (?, 0, ?, ?, ?)",
            (item.text, item.created, item.last_used, item.copy_count))
        item.rowid = cursor.lastrowid
        self._db.commit()
        self._items.insert(0, item)
        self._sort()
        self._evict()
        self.emit("changed")
        return item

    def touch(self, item):
        if item not in self._items:
            return
        item.last_used = now_micros()
        self._db.execute("UPDATE items SET last_used = ? WHERE id = ?",
                         (item.last_used, item.rowid))
        self._db.commit()
        self._sort()
        self.emit("changed")

    def remove(self, item):
        if item not in self._items:
            return
        self._items.remove(item)
        self._db.execute("DELETE FROM items WHERE id = ?", (item.rowid,))
        self._db.commit()
        self.emit("changed")

    def toggle_pin(self, item):
        if item not in self._items:
            return
        item.pinned = not item.pinned
        self._db.execute("UPDATE items SET pinned = ? WHERE id = ?",
                         (1 if item.pinned else 0, item.rowid))
        self._db.commit()
        self._sort()
        self._evict()
        self.emit("changed")

    def clear(self):
        """Drop everything except pinned items."""
        self._items = [item for item in self._items if item.pinned]
        self._db.execute("DELETE FROM items WHERE pinned = 0")
        self._db.commit()
        self.emit("changed")

    def flush(self):
        """Kept for symmetry with the old debounced store: writes are already
        committed, this only makes sure nothing is left in the WAL."""
        self._db.commit()

    def close(self):
        self._db.close()

    # --- internals ---

    def _find_by_text(self, text):
        for item in self._items:
            if item.text == text:
                return item
        return None

    def _sort(self):
        """Pinned block on top, each block newest-first."""
        self._items.sort(key=lambda item: (not item.pinned, -item.last_used))

    def _evict(self):
        """Drop the oldest unpinned items above the cap."""
        unpinned = [item for item in self._items if not item.pinned]
        excess = len(unpinned) - self._history_size
        if excess <= 0:
            return False
        doomed = sorted(unpinned, key=lambda item: item.last_used)[:excess]
        self._db.executemany("DELETE FROM items WHERE id = ?",
                             [(item.rowid,) for item in doomed])
        self._db.commit()
        for item in doomed:
            self._items.remove(item)
        return True
