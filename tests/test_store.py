import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes.item import HistoryItem
from funes.store import SCHEMA_VERSION, HistoryStore


def temp_history() -> str:
    directory = tempfile.mkdtemp(prefix="funes-test-")
    return str(Path(directory) / "history.db")


class StoreTests(unittest.TestCase):
    def add(self, store: HistoryStore, text: str) -> HistoryItem:
        """store.add() rejects blank text; tests always pass real payloads."""
        item = store.add(text)
        assert item is not None
        return item

    def store(self, path: str | None = None, history_size: int = 200) -> HistoryStore:
        store = HistoryStore(path or temp_history(), history_size)
        self.addCleanup(store.close)
        return store

    def test_add_and_order(self) -> None:
        store = self.store()
        store.add("one")
        store.add("two")
        store.add("three")

        self.assertEqual(store.size(), 3)
        items = store.items()
        self.assertEqual(items[0].text, "three")
        self.assertEqual(items[2].text, "one")

    def test_dedup_moves_to_top(self) -> None:
        store = self.store()
        store.add("a")
        store.add("b")
        store.add("a")

        self.assertEqual(store.size(), 2)
        items = store.items()
        self.assertEqual(items[0].text, "a")
        self.assertEqual(items[0].copy_count, 2)
        self.assertEqual(items[1].text, "b")

    def test_rejects_blank(self) -> None:
        store = self.store()
        self.assertIsNone(store.add(""))
        self.assertIsNone(store.add("   \n\t "))
        self.assertEqual(store.size(), 0)

    def test_cap_evicts_oldest_unpinned(self) -> None:
        store = self.store(history_size=3)
        for text in ("1", "2", "3", "4"):
            store.add(text)

        self.assertEqual(store.size(), 3)
        items = store.items()
        self.assertEqual(items[0].text, "4")
        self.assertEqual(items[2].text, "2")

    def test_shrinking_cap_evicts(self) -> None:
        store = self.store(history_size=10)
        for text in ("1", "2", "3", "4"):
            store.add(text)
        store.history_size = 2

        self.assertEqual(store.size(), 2)
        self.assertEqual([item.text for item in store.items()], ["4", "3"])

    def test_pin_survives_cap_and_clear(self) -> None:
        store = self.store(history_size=2)
        pinned = self.add(store, "keep me")
        store.toggle_pin(pinned)
        for text in ("x", "y", "z"):
            store.add(text)

        kept = [item for item in store.items() if item.text == "keep me"]
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].pinned)

        store.clear()
        self.assertEqual(store.size(), 1)
        self.assertEqual(store.items()[0].text, "keep me")

    def test_pinned_sort_on_top(self) -> None:
        store = self.store()
        first = self.add(store, "first")
        store.add("second")
        store.toggle_pin(first)

        self.assertEqual([item.text for item in store.items()], ["first", "second"])

    def test_touch_moves_to_top(self) -> None:
        store = self.store()
        first = self.add(store, "first")
        store.add("second")
        store.touch(first)

        self.assertEqual(store.items()[0].text, "first")

    def test_remove(self) -> None:
        store = self.store()
        store.add("a")
        item_b = self.add(store, "b")
        store.add("c")
        store.remove(item_b)

        self.assertEqual(store.size(), 2)
        self.assertNotIn("b", [item.text for item in store.items()])

    def test_persistence_roundtrip(self) -> None:
        path = temp_history()
        store = self.store(path)
        store.add("plain")
        special = 'with "quotes" and \\ backslash\nand newline\ttab'
        store.add(special)
        pinned = self.add(store, "pinned entry")
        store.toggle_pin(pinned)
        store.flush()
        store.close()

        reloaded = self.store(path)
        self.assertEqual(reloaded.size(), 3)
        texts = {item.text: item for item in reloaded.items()}
        self.assertIn(special, texts)
        self.assertTrue(texts["pinned entry"].pinned)

    def test_unicode_roundtrip(self) -> None:
        path = temp_history()
        store = self.store(path)
        text = "emoji 🐘 — ünïcode ✓ \x01 control"
        store.add(text)
        store.flush()
        store.close()

        reloaded = self.store(path)
        self.assertEqual(reloaded.items()[0].text, text)

    def test_file_permissions(self) -> None:
        path = temp_history()
        store = self.store(path)
        store.add("secret-ish")
        store.flush()

        mode = stat.S_IMODE(Path(path).stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_schema_version_is_recorded(self) -> None:
        path = temp_history()
        self.store(path).add("x")
        with sqlite3.connect(path) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, SCHEMA_VERSION)

    def test_changed_signal(self) -> None:
        store = self.store()
        seen = []
        store.connect("changed", lambda *_a: seen.append(1))
        store.add("a")
        store.add("a")
        store.clear()
        self.assertEqual(len(seen), 3)


if __name__ == "__main__":
    unittest.main()
