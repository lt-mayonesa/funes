"""Unit tests for fuzzy search (fzy algorithm via pfzy)."""

import unittest

try:
    import pfzy  # noqa: F401

    HAS_PFZY = True
except ImportError:
    HAS_PFZY = False

from funes.search import filter_matches


class TestFilterMatches(unittest.TestCase):
    """Test fzy-based fuzzy filtering."""

    def test_exact_match(self) -> None:
        """Exact match included in results."""
        items = ["hello world", "goodbye"]
        result = filter_matches(items, "hello world")
        self.assertIn("hello world", result)

    def test_substring_match(self) -> None:
        """Substring match included."""
        items = ["hello world", "goodbye"]
        result = filter_matches(items, "hello")
        self.assertIn("hello world", result)
        self.assertNotIn("goodbye", result)

    @unittest.skipIf(not HAS_PFZY, "pfzy not installed (requires dev environment)")
    def test_typo_match(self) -> None:
        """Typos are matched (fzy strength). Requires pfzy."""
        items = ["github", "gitlab", "gitbash"]
        result = filter_matches(items, "gihub")
        self.assertIn("github", result)

    def test_url_substring_match(self) -> None:
        """Substring matching works in URLs."""
        items = ["https://github.com/lt-mayonesa/funes", "https://gitlab.com"]
        result = filter_matches(items, "github")
        self.assertIn("https://github.com/lt-mayonesa/funes", result)

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        items = ["Hello World", "Goodbye"]
        result = filter_matches(items, "hello")
        self.assertIn("Hello World", result)

    def test_empty_query(self) -> None:
        """Empty query returns all items."""
        items = ["apple", "banana", "cherry"]
        result = filter_matches(items, "")
        self.assertEqual(set(result), set(items))

    def test_whitespace_query(self) -> None:
        """Whitespace-only query returns all items."""
        items = ["test"]
        result = filter_matches(items, "   ")
        self.assertEqual(result, items)

    def test_no_match(self) -> None:
        """Non-matching items excluded."""
        items = ["apple", "banana", "cherry"]
        result = filter_matches(items, "xyz")
        self.assertEqual(result, [])

    def test_order_preserved(self) -> None:
        """Original item order is preserved."""
        items = ["cherry", "apple", "banana"]
        result = filter_matches(items, "a")
        # Both apple and banana match, should preserve original order
        self.assertEqual(result, ["apple", "banana"])

    def test_empty_items(self) -> None:
        """Empty item list returns empty."""
        result = filter_matches([], "query")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
