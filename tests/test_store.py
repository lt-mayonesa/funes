import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes.item import Capture, HistoryItem
from funes.store import SCHEMA_VERSION, HistoryStore


def temp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="funes-test-"))


def temp_history() -> str:
    return str(temp_dir() / "history.db")


class StoreTests(unittest.TestCase):
    def add(self, store: HistoryStore, text: str) -> HistoryItem:
        """store.add() rejects blank text; tests always pass real payloads."""
        item = store.add(Capture.from_text(text))
        assert item is not None
        return item

    def store(
        self,
        path: str | None = None,
        history_size: int = 200,
        blob_root: Path | None = None,
    ) -> HistoryStore:
        d = temp_dir()
        store = HistoryStore(
            path or str(d / "history.db"),
            history_size,
            blob_root=blob_root or (d / "blobs"),
            thumb_root=d / "thumbs",
        )
        self.addCleanup(store.close)
        return store

    def test_add_and_order(self) -> None:
        store = self.store()
        self.add(store, "one")
        self.add(store, "two")
        self.add(store, "three")

        self.assertEqual(store.size(), 3)
        items = store.items()
        self.assertEqual(items[0].text, "three")
        self.assertEqual(items[2].text, "one")

    def test_dedup_moves_to_top(self) -> None:
        store = self.store()
        self.add(store, "a")
        self.add(store, "b")
        self.add(store, "a")

        self.assertEqual(store.size(), 2)
        items = store.items()
        self.assertEqual(items[0].text, "a")
        self.assertEqual(items[0].copy_count, 2)
        self.assertEqual(items[1].text, "b")

    def test_rejects_blank(self) -> None:
        store = self.store()
        self.assertIsNone(store.add(Capture.from_text("")))
        self.assertIsNone(store.add(Capture.from_text("   \n\t ")))
        self.assertEqual(store.size(), 0)

    def test_cap_evicts_oldest_unpinned(self) -> None:
        store = self.store(history_size=3)
        for text in ("1", "2", "3", "4"):
            self.add(store, text)

        self.assertEqual(store.size(), 3)
        items = store.items()
        self.assertEqual(items[0].text, "4")
        self.assertEqual(items[2].text, "2")

    def test_shrinking_cap_evicts(self) -> None:
        store = self.store(history_size=10)
        for text in ("1", "2", "3", "4"):
            self.add(store, text)
        store.history_size = 2

        self.assertEqual(store.size(), 2)
        self.assertEqual([item.text for item in store.items()], ["4", "3"])

    def test_pin_survives_cap_and_clear(self) -> None:
        store = self.store(history_size=2)
        pinned = self.add(store, "keep me")
        store.toggle_pin(pinned)
        for text in ("x", "y", "z"):
            self.add(store, text)

        kept = [item for item in store.items() if item.text == "keep me"]
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].pinned)

        store.clear()
        self.assertEqual(store.size(), 1)
        self.assertEqual(store.items()[0].text, "keep me")

    def test_pinned_sort_on_top(self) -> None:
        store = self.store()
        first = self.add(store, "first")
        self.add(store, "second")
        store.toggle_pin(first)

        self.assertEqual([item.text for item in store.items()], ["first", "second"])

    def test_touch_moves_to_top(self) -> None:
        store = self.store()
        first = self.add(store, "first")
        self.add(store, "second")
        store.touch(first)

        self.assertEqual(store.items()[0].text, "first")

    def test_remove(self) -> None:
        store = self.store()
        self.add(store, "a")
        item_b = self.add(store, "b")
        self.add(store, "c")
        store.remove(item_b)

        self.assertEqual(store.size(), 2)
        self.assertNotIn("b", [item.text for item in store.items()])

    def test_persistence_roundtrip(self) -> None:
        d = temp_dir()
        path = str(d / "history.db")
        blob_root = d / "blobs"
        store = HistoryStore(path, 200, blob_root=blob_root, thumb_root=d / "thumbs")
        self.addCleanup(store.close)
        self.add(store, "plain")
        special = 'with "quotes" and \\ backslash\nand newline\ttab'
        self.add(store, special)
        pinned = self.add(store, "pinned entry")
        store.toggle_pin(pinned)
        store.flush()
        store.close()

        reloaded = HistoryStore(path, 200, blob_root=blob_root, thumb_root=d / "thumbs")
        self.addCleanup(reloaded.close)
        self.assertEqual(reloaded.size(), 3)
        texts = {item.text: item for item in reloaded.items()}
        self.assertIn(special, texts)
        self.assertTrue(texts["pinned entry"].pinned)

    def test_unicode_roundtrip(self) -> None:
        d = temp_dir()
        path = str(d / "history.db")
        store = HistoryStore(path, 200, blob_root=d / "blobs", thumb_root=d / "thumbs")
        self.addCleanup(store.close)
        text = "emoji 🐘 — ünïcode ✓ \x01 control"
        self.add(store, text)
        store.flush()
        store.close()

        reloaded = HistoryStore(path, 200, blob_root=d / "blobs", thumb_root=d / "thumbs")
        self.addCleanup(reloaded.close)
        self.assertEqual(reloaded.items()[0].text, text)

    def test_file_permissions(self) -> None:
        d = temp_dir()
        path = str(d / "history.db")
        store = HistoryStore(path, 200, blob_root=d / "blobs", thumb_root=d / "thumbs")
        self.addCleanup(store.close)
        self.add(store, "secret-ish")
        store.flush()

        mode = stat.S_IMODE(Path(path).stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_schema_version_is_recorded(self) -> None:
        d = temp_dir()
        path = str(d / "history.db")
        store = HistoryStore(path, 200, blob_root=d / "blobs", thumb_root=d / "thumbs")
        self.addCleanup(store.close)
        self.add(store, "x")
        store.flush()
        store.close()
        with sqlite3.connect(path) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, SCHEMA_VERSION)

    def test_changed_signal(self) -> None:
        store = self.store()
        seen = []
        store.connect("changed", lambda *_a: seen.append(1))
        self.add(store, "a")
        self.add(store, "a")
        store.clear()
        self.assertEqual(len(seen), 3)

    # --- image-specific tests ---

    def test_add_image_capture(self) -> None:
        d = temp_dir()
        blob_root = d / "blobs"
        store = HistoryStore(
            str(d / "history.db"), 200, blob_root=blob_root, thumb_root=d / "thumbs"
        )
        self.addCleanup(store.close)

        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        cap = Capture(
            kind="image",
            canonical_mime="image/png",
            reps={"image/png": png_data},
            text=None,
        )
        item = store.add(cap)
        assert item is not None
        self.assertEqual(item.kind, "image")
        self.assertEqual(item.mime, "image/png")
        self.assertIsNotNone(item.blob_sha)
        # Blob should be on disk.
        assert item.blob_sha is not None
        blob_path = store.blob_store.path(item.blob_sha)
        self.assertTrue(blob_path.exists())
        self.assertEqual(blob_path.read_bytes(), png_data)

    def test_image_dedup(self) -> None:
        d = temp_dir()
        store = HistoryStore(
            str(d / "history.db"), 200, blob_root=d / "blobs", thumb_root=d / "thumbs"
        )
        self.addCleanup(store.close)

        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        cap = Capture(kind="image", canonical_mime="image/png", reps={"image/png": png_data})
        item1 = store.add(cap)
        item2 = store.add(cap)
        assert item1 is not None
        assert item2 is not None
        self.assertIs(item1, item2)
        self.assertEqual(item1.copy_count, 2)
        self.assertEqual(store.size(), 1)

    def test_image_blob_gc_on_remove(self) -> None:
        d = temp_dir()
        store = HistoryStore(
            str(d / "history.db"), 200, blob_root=d / "blobs", thumb_root=d / "thumbs"
        )
        self.addCleanup(store.close)

        png_data = b"\x89PNG" + b"\x00" * 64
        cap = Capture(kind="image", canonical_mime="image/png", reps={"image/png": png_data})
        item = store.add(cap)
        assert item is not None
        assert item.blob_sha is not None
        blob_path = store.blob_store.path(item.blob_sha)
        self.assertTrue(blob_path.exists())

        store.remove(item)
        self.assertFalse(blob_path.exists())

    def test_v1_migration(self) -> None:
        """A v1 history.db (text UNIQUE schema) is migrated transparently."""
        import sqlite3 as _sqlite3

        d = temp_dir()
        path = str(d / "history.db")
        # Build a minimal v1 database by hand.
        db = _sqlite3.connect(path)
        db.executescript("""
            CREATE TABLE items (
                id         INTEGER PRIMARY KEY,
                text       TEXT    NOT NULL UNIQUE,
                pinned     INTEGER NOT NULL DEFAULT 0,
                created    INTEGER NOT NULL,
                last_used  INTEGER NOT NULL,
                copy_count INTEGER NOT NULL DEFAULT 1
            );
            INSERT INTO items (text, pinned, created, last_used, copy_count)
            VALUES ('hello', 0, 1000, 2000, 1),
                   ('world', 1, 1500, 1800, 3);
            PRAGMA user_version = 1;
        """)
        db.commit()
        db.close()

        # Open with the new store — migration should happen automatically.
        store = HistoryStore(path, 200, blob_root=d / "blobs", thumb_root=d / "thumbs")
        self.addCleanup(store.close)
        self.assertEqual(store.size(), 2)
        texts = {item.text for item in store.items()}
        self.assertIn("hello", texts)
        self.assertIn("world", texts)
        pinned = [item for item in store.items() if item.pinned]
        self.assertEqual(len(pinned), 1)
        self.assertEqual(pinned[0].text, "world")
        # All migrated items should be kind=text.
        for item in store.items():
            self.assertEqual(item.kind, "text")


if __name__ == "__main__":
    unittest.main()
