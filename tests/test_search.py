"""Unit tests for fuzzy search (fzy algorithm, inline implementation)."""

import unittest

from funes.presentation import match_byte_spans
from funes.search import filter_indices, filter_matches, match_indices


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

    def test_typo_match(self) -> None:
        """Typos matched as subsequences (fzy strength)."""
        items = ["github", "gitlab", "gitbash"]
        result = filter_matches(items, "gihub")
        self.assertIn("github", result)

    def test_url_substring_match(self) -> None:
        """Subsequence matching works in URLs."""
        items = ["https://github.com/lt-mayonesa/funes", "https://gitlab.com"]
        result = filter_matches(items, "github")
        self.assertIn("https://github.com/lt-mayonesa/funes", result)

    def test_noncontiguous_chars(self) -> None:
        """Non-contiguous chars matched as subsequence ('ghb' -> 'github')."""
        items = ["https://github.com/lt-mayonesa/funes", "https://gitlab.com"]
        result = filter_matches(items, "ghb")
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


class TestMatchIndices(unittest.TestCase):
    """Test fzy match index extraction for highlighting."""

    def test_exact_word_indices(self) -> None:
        """Exact word match returns contiguous indices."""
        indices = match_indices("github", "https://github.com")
        self.assertIsNotNone(indices)
        assert indices is not None
        text = "https://github.com"
        matched_chars = [text[i] for i in indices]
        self.assertEqual("".join(matched_chars).lower(), "github")

    def test_noncontiguous_indices(self) -> None:
        """Non-contiguous query returns scattered indices."""
        indices = match_indices("ghb", "https://github.com")
        self.assertIsNotNone(indices)
        assert indices is not None
        text = "https://github.com"
        matched_chars = [text[i] for i in indices]
        self.assertEqual("".join(matched_chars).lower(), "ghb")

    def test_no_match_returns_none(self) -> None:
        """Non-subsequence returns None."""
        indices = match_indices("xyz", "github")
        self.assertIsNone(indices)

    def test_empty_needle_returns_empty_list(self) -> None:
        """Empty query returns empty list (not None)."""
        indices = match_indices("", "github")
        self.assertEqual(indices, [])

    def test_indices_are_sorted(self) -> None:
        """Returned indices are in ascending order."""
        indices = match_indices("githb", "https://github.com")
        self.assertIsNotNone(indices)
        assert indices is not None
        self.assertEqual(indices, sorted(indices))


class TestMatchByteSpans(unittest.TestCase):
    """Test byte-span conversion for Pango highlighting."""

    def test_contiguous_indices_merge(self) -> None:
        """Adjacent indices produce a single merged span."""
        # 'github' at positions 8-13 in 'https://github.com'
        spans = match_byte_spans("https://github.com", [8, 9, 10, 11, 12, 13])
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0], (8, 14))  # bytes 8..14

    def test_noncontiguous_indices_split(self) -> None:
        """Non-adjacent indices produce separate spans."""
        # g=8, h=11, b=13 in 'https://github.com'
        spans = match_byte_spans("https://github.com", [8, 11, 13])
        self.assertEqual(len(spans), 3)

    def test_empty_indices_returns_empty(self) -> None:
        """Empty index list returns empty spans."""
        self.assertEqual(match_byte_spans("anything", []), [])


if __name__ == "__main__":
    unittest.main()


class TestFilterIndices(unittest.TestCase):
    """Test index-based filtering (image-safe — handles duplicate corpora)."""

    def test_returns_all_indices_when_no_needle(self) -> None:
        corpora = ["one", "two", "three"]
        self.assertEqual(filter_indices(corpora, ""), [0, 1, 2])

    def test_returns_matching_indices(self) -> None:
        corpora = ["github", "gitlab", "bitbucket"]
        result = filter_indices(corpora, "gitb")
        # "github" and "gitlab" both contain 'g','i','t','b' as subsequence.
        self.assertIn(0, result)
        self.assertIn(1, result)

    def test_no_match_returns_empty(self) -> None:
        corpora = ["aaa", "bbb"]
        result = filter_indices(corpora, "zzz")
        self.assertEqual(result, [])

    def test_duplicate_corpora_both_returned(self) -> None:
        """Two image items sharing the same search_text both appear."""
        corpora = ["png screenshot", "png screenshot"]
        result = filter_indices(corpora, "png")
        self.assertEqual(result, [0, 1])

    def test_indices_ascending(self) -> None:
        corpora = ["alpha", "beta", "gamma", "delta"]
        result = filter_indices(corpora, "a")
        self.assertEqual(result, sorted(result))
