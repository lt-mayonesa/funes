"""Accelerator parsing/validation rules behind the shortcut capture widget."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes import accel


class SplitTests(unittest.TestCase):
    def test_modifiers_and_key(self) -> None:
        self.assertEqual(accel.split("<Shift><Super>c"), (["shift", "super"], "c"))

    def test_bare_key(self) -> None:
        self.assertEqual(accel.split("F5"), ([], "F5"))

    def test_blank(self) -> None:
        self.assertEqual(accel.split(""), ([], ""))
        self.assertEqual(accel.split(None), ([], ""))
        self.assertEqual(accel.split("   "), ([], ""))

    def test_whitespace_tolerant(self) -> None:
        self.assertEqual(accel.split("  <Primary>v "), (["primary"], "v"))


class ValidityTests(unittest.TestCase):
    def test_default_is_valid(self) -> None:
        self.assertTrue(accel.is_valid(accel.DEFAULT))

    def test_empty_is_invalid(self) -> None:
        self.assertFalse(accel.is_valid(""))
        self.assertFalse(accel.is_valid(None))
        self.assertFalse(accel.is_valid("<Super>"))

    def test_bare_reserved_keys_refused(self) -> None:
        for key in ("Escape", "Tab", "Return", "BackSpace", "space", "Delete"):
            self.assertFalse(accel.is_valid(key), key)

    def test_reserved_key_with_modifier_allowed(self) -> None:
        self.assertTrue(accel.is_valid("<Super>space"))
        self.assertTrue(accel.is_valid("<Control><Alt>Tab"))

    def test_modifierless_key_allowed(self) -> None:
        self.assertTrue(accel.is_valid("F5"))
        self.assertTrue(accel.is_valid("a"))


class WarningTests(unittest.TestCase):
    def test_modifierless_warns(self) -> None:
        self.assertIn("modifier", accel.warning_for("F5"))

    def test_with_modifier_silent(self) -> None:
        self.assertEqual(accel.warning_for("<Super>v"), "")

    def test_invalid_has_no_warning(self) -> None:
        self.assertEqual(accel.warning_for(""), "")
        self.assertEqual(accel.warning_for("Escape"), "")


class LabelTests(unittest.TestCase):
    def test_pretty_label(self) -> None:
        self.assertEqual(accel.label("<Shift><Super>c"), "Shift+Super+C")

    def test_primary_reads_as_ctrl(self) -> None:
        self.assertEqual(accel.label("<Primary>v"), "Ctrl+V")

    def test_named_keys(self) -> None:
        self.assertEqual(accel.label("<Super>space"), "Super+Space")
        self.assertEqual(accel.label("<Control>Page_Up"), "Ctrl+Page Up")

    def test_blank(self) -> None:
        self.assertEqual(accel.label(""), "")


if __name__ == "__main__":
    unittest.main()
