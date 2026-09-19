import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes import filters


class FilterTests(unittest.TestCase):
    def test_secret_targets(self) -> None:
        self.assertTrue(filters.is_secret(["text/plain", "x-kde-passwordManagerHint"]))
        self.assertTrue(filters.is_secret(["org.nspasteboard.ConcealedType"]))
        self.assertFalse(filters.is_secret(["text/plain", "UTF8_STRING"]))
        self.assertFalse(filters.is_secret([]))
        self.assertFalse(filters.is_secret(None))

    def test_blank(self) -> None:
        self.assertTrue(filters.is_blank(None))
        self.assertTrue(filters.is_blank(""))
        self.assertTrue(filters.is_blank("  \n\t "))
        self.assertFalse(filters.is_blank(" x "))

    def test_size_limit_counts_bytes(self) -> None:
        self.assertFalse(filters.is_too_big("abc", 3))
        self.assertTrue(filters.is_too_big("abcd", 3))
        # Multi-byte characters count as their UTF-8 length.
        self.assertTrue(filters.is_too_big("é", 1))

    def test_ignore_regexes(self) -> None:
        self.assertEqual(filters.matching_ignore_regex("ghp_secret", [r"^ghp_"]), r"^ghp_")
        self.assertIsNone(filters.matching_ignore_regex("hello", [r"^ghp_"]))
        self.assertIsNone(filters.matching_ignore_regex("hello", ["", "   "]))
        self.assertIsNone(filters.matching_ignore_regex("hello", None))

    def test_bad_regex_is_reported_not_raised(self) -> None:
        seen = []
        result = filters.matching_ignore_regex(
            "hello", ["("], on_bad_pattern=lambda p, e: seen.append(p)
        )
        self.assertIsNone(result)
        self.assertEqual(seen, ["("])


if __name__ == "__main__":
    unittest.main()
