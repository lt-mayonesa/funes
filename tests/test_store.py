import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes.item import Capture, HistoryItem
from funes.store import HistoryStore


def temp_history() -> str:
    directory = tempfile.mkdtemp(prefix="funes-test-")
    return str(Path(directory) / "history.db")


class StoreTests(unittest.TestCase):
    def add_text(self, store: HistoryStore, text: str) -> HistoryItem:
        """Helper: add text via Capture. Rejects blank; tests always pass real payloads."""
        capture = Capture(reps={"text/plain": text.encode("utf-8")}, text=text, kind="text")
        item = store.add(capture)
        assert item is not None
        return item

    def add_image(self, store: HistoryStore, data: bytes, mime: str = "image/png") -> HistoryItem:
        """Helper: add image via Capture."""
        capture = Capture(reps={mime: data}, text=None, kind="image", canonical_mime=mime)
        item = store.add(capture)
        assert item is not None
        return item

    def store(self, path: str | None = None, history_size: int = 200) -> HistoryStore:
        store = HistoryStore(path or temp_history(), history_size)
        self.addCleanup(store.close)
        return store

    def test_add_text_and_order(self) -> None:
        store = self.store()
        self.add_text(store, "one")
        self.add_text(store, "two")
        self.add_text(store, "three")

        self.assertEqual(store.size(), 3)
        items = store.items()
        self.assertEqual(items[0].text, "three")
        self.assertEqual(items[2].text, "one")
        self.assertEqual(items[0].kind, "text")

    def test_add_image(self) -> None:
        store = self.store()
        png_data = b"\x89PNG\r\n\x1a\n" + b"x" * 100
        item = self.add_image(store, png_data, "image/png")

        self.assertEqual(item.kind, "image")
        self.assertEqual(item.mime, "image/png")
        self.assertEqual(item.bytes, len(png_data))
        self.assertIn("image/png", item.reps)

    def test_text_dedup_moves_to_top(self) -> None:
        store = self.store()
        self.add_text(store, "a")
        self.add_text(store, "b")
        self.add_text(store, "a")

        self.assertEqual(store.size(), 2)
        items = store.items()
        self.assertEqual(items[0].text, "a")
        self.assertEqual(items[0].copy_count, 2)
        self.assertEqual(items[1].text, "b")

    def test_image_dedup_moves_to_top(self) -> None:
        store = self.store()
        png_data = b"\x89PNG\r\n\x1a\n" + b"y" * 100

        item1 = self.add_image(store, png_data)
        self.add_image(store, b"different" * 10)
        item2 = self.add_image(store, png_data)  # Same image again

        self.assertEqual(store.size(), 2)
        self.assertEqual(item1.rowid, item2.rowid)
        items = store.items()
        self.assertEqual(items[0].copy_count, 2)

    def test_rejects_blank_text(self) -> None:
        store = self.store()
        capture_empty = Capture(reps={"text/plain": b""}, text="", kind="text")
        capture_blank = Capture(reps={"text/plain": b"   "}, text="   ", kind="text")

        self.assertIsNone(store.add(capture_empty))
        self.assertIsNone(store.add(capture_blank))
        self.assertEqual(store.size(), 0)

    def test_cap_evicts_oldest_unpinned(self) -> None:
        store = self.store(history_size=3)
        self.add_text(store, "a")
        self.add_text(store, "b")
        self.add_text(store, "c")
        self.add_text(store, "d")  # Should evict "a"

        self.assertEqual(store.size(), 3)
        items = store.items()
        texts = [item.text for item in items]
        self.assertNotIn("a", texts)
        self.assertIn("b", texts)
        self.assertIn("c", texts)
        self.assertIn("d", texts)

    def test_pinned_items_never_evicted(self) -> None:
        store = self.store(history_size=2)
        item_a = self.add_text(store, "a")
        self.add_text(store, "b")

        store.toggle_pin(item_a)
        self.add_text(store, "c")
        self.add_text(store, "d")

        self.assertEqual(store.size(), 2)
        items = store.items()
        texts = [item.text for item in items]
        self.assertIn("a", texts)
        self.assertTrue(any(item.pinned for item in items if item.text == "a"))

    def test_touch_updates_order(self) -> None:
        store = self.store()
        item_a = self.add_text(store, "a")
        self.add_text(store, "b")

        store.touch(item_a)

        items = store.items()
        self.assertEqual(items[0], item_a)

    def test_toggle_pin(self) -> None:
        store = self.store()
        item = self.add_text(store, "a")
        self.assertFalse(item.pinned)

        store.toggle_pin(item)
        self.assertTrue(item.pinned)

        items = store.items()
        self.assertEqual(items[0], item)  # Pinned moves to top

    def test_remove(self) -> None:
        store = self.store()
        item_a = self.add_text(store, "a")
        item_b = self.add_text(store, "b")

        store.remove(item_b)
        self.assertEqual(store.size(), 1)
        self.assertEqual(store.items()[0], item_a)

    def test_clear(self) -> None:
        store = self.store()
        item_a = self.add_text(store, "a")
        self.add_text(store, "b")
        store.toggle_pin(item_a)

        store.clear()
        self.assertEqual(store.size(), 1)
        self.assertEqual(store.items()[0], item_a)

    def test_permissions(self) -> None:
        path = temp_history()
        store = self.store(path)
        self.add_text(store, "test")
        store.close()

        db_stat = Path(path).stat()
        perms = db_stat.st_mode & 0o777
        self.assertEqual(perms, 0o600)

    def test_schema_version_v2(self) -> None:
        """Fresh store uses schema v2."""
        path = temp_history()
        store = self.store(path)
        self.add_text(store, "test")
        store.close()

        db = sqlite3.connect(path)
        version = db.execute("PRAGMA user_version").fetchone()[0]
        db.close()

        self.assertEqual(version, 2)

    def test_schema_migration_v1_to_v2(self) -> None:
        """Migrate from v1 (text-only) to v2 (text+images)."""
        path = temp_history()

        # Create a v1 database manually.
        db = sqlite3.connect(path)
        db.execute(
            "CREATE TABLE items ("
            "  id INTEGER PRIMARY KEY,"
            "  text TEXT NOT NULL UNIQUE,"
            "  pinned INTEGER NOT NULL DEFAULT 0,"
            "  created INTEGER NOT NULL,"
            "  last_used INTEGER NOT NULL,"
            "  copy_count INTEGER NOT NULL DEFAULT 1"
            ")"
        )
        db.execute("CREATE INDEX idx_items_order ON items (pinned DESC, last_used DESC)")
        db.execute("PRAGMA user_version=1")

        now_micros = int(__import__("time").time() * 1_000_000)
        db.execute(
            "INSERT INTO items (text, pinned, created, last_used, copy_count)"
            " VALUES (?, 0, ?, ?, 1)",
            ("hello world", now_micros, now_micros),
        )
        db.commit()
        db.close()

        # Open with HistoryStore: should migrate.
        store = self.store(path)
        self.assertEqual(store.size(), 1)

        items = store.items()
        self.assertEqual(items[0].text, "hello world")
        self.assertEqual(items[0].kind, "text")
        self.assertEqual(items[0].mime, "text/plain")

        store.close()

        # Verify v2 schema in the DB.
        db = sqlite3.connect(path)
        version = db.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 2)

        # Check content_hash column exists.
        cursor = db.execute("SELECT content_hash FROM items LIMIT 1")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        content_hash = row[0]
        self.assertEqual(len(content_hash), 64)  # sha256 hex

        db.close()

    def test_image_blob_refcounting(self) -> None:
        """Image blobs are refcounted; deleting an item cleans up unreferenced blobs."""
        store = self.store()
        png_data = b"image data x" * 100

        item1 = self.add_image(store, png_data, "image/png")
        blob_sha = item1.blob_sha

        # Verify blob exists.
        blob_path = store._blob_store.path(blob_sha)
        self.assertTrue(blob_path.exists())

        # Remove the item.
        store.remove(item1)
        self.assertEqual(store.size(), 0)

        # Blob should be deleted (no other refs).
        with self.assertRaises(FileNotFoundError):
            store._blob_store.path(blob_sha)

    def test_image_blob_survives_when_shared(self) -> None:
        """If two items share a blob, deleting one doesn't delete the blob."""
        store = self.store()
        png_data = b"image data x" * 100

        item1 = self.add_image(store, png_data, "image/png")
        item2 = self.add_image(store, png_data, "image/png")  # Same data

        # Both should be deduped (same item).
        self.assertEqual(store.size(), 1)
        self.assertEqual(item1.rowid, item2.rowid)

    def test_repr(self) -> None:
        store = self.store()
        item = self.add_text(store, "test data")
        repr_str = repr(item)
        self.assertIn("HistoryItem", repr_str)
        self.assertIn("test", repr_str)

    def test_item_label_image(self) -> None:
        """Image items have a label showing metadata."""
        store = self.store()
        png_data = b"\x89PNG\r\n\x1a\n" + b"x" * 1000
        item = self.add_image(store, png_data, "image/png")
        item.width = 1920
        item.height = 1080

        label = item.label()
        self.assertIn("PNG", label)
        self.assertIn("1920", label)
        self.assertIn("1080", label)

    def test_item_preview_for_text(self) -> None:
        store = self.store()
        item = self.add_text(store, "hello world")
        preview = item.preview()
        self.assertEqual(preview, "hello world")

    def test_item_preview_for_image(self) -> None:
        store = self.store()
        png_data = b"\x89PNG\r\n\x1a\n" + b"x" * 100
        item = self.add_image(store, png_data)
        item.width = 100
        item.height = 100
        preview = item.preview()
        # Preview for images is the same as label.
        self.assertIn("100", preview)


if __name__ == "__main__":
    unittest.main()
