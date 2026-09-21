"""Cinnamon keybinding registration: apply() dispatch and live re-registration.

GSettings is faked, so the tests run headless and never touch the session's
real keybindings.
"""

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gi.repository import Gio

from funes import hotkey


class FakeSettings:
    """Minimal Gio.Settings stand-in backed by a dict."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values: dict[str, Any] = dict(values or {})
        self.writes: list[tuple[str, Any]] = []

    def get_strv(self, key: str) -> list[str]:
        return list(self.values.get(key, []))

    def set_strv(self, key: str, value: list[str]) -> None:
        self.values[key] = list(value)
        self.writes.append((key, list(value)))

    def get_string(self, key: str) -> str:
        return str(self.values.get(key, ""))

    def set_string(self, key: str, value: str) -> None:
        self.values[key] = value
        self.writes.append((key, value))

    def reset(self, key: str) -> None:
        self.values.pop(key, None)
        self.writes.append((key, None))


class HotkeyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.keybindings = FakeSettings({"custom-list": []})
        self.slots: dict[str, FakeSettings] = {}

        patches = [
            mock.patch.object(hotkey, "cinnamon_available", return_value=True),
            mock.patch.object(Gio.Settings, "new", return_value=self.keybindings),
            mock.patch.object(Gio.Settings, "sync"),
            mock.patch.object(hotkey, "_custom_settings", side_effect=self._slot),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _slot(self, slot_id: str) -> FakeSettings:
        return self.slots.setdefault(slot_id, FakeSettings())


class ApplyTests(HotkeyTestCase):
    def test_valid_accel_registers(self) -> None:
        self.assertTrue(hotkey.apply("<Super>v"))
        self.assertEqual(self.keybindings.get_strv("custom-list"), ["custom0"])
        slot = self.slots["custom0"]
        self.assertEqual(slot.get_strv("binding"), ["<Super>v"])
        self.assertEqual(slot.get_string("command"), hotkey.COMMAND)

    def test_blank_accel_unregisters(self) -> None:
        hotkey.apply("<Super>v")
        self.assertFalse(hotkey.apply("  "))
        self.assertEqual(self.keybindings.get_strv("custom-list"), [])
        self.assertEqual(self.slots["custom0"].get_strv("binding"), [])

    def test_reserved_accel_unregisters(self) -> None:
        hotkey.apply("<Super>v")
        self.assertFalse(hotkey.apply("Escape"))
        self.assertEqual(self.keybindings.get_strv("custom-list"), [])


class ReRegisterTests(HotkeyTestCase):
    def test_changing_accel_reuses_the_same_slot(self) -> None:
        hotkey.apply("<Super>v")
        hotkey.apply("<Shift><Super>c")
        self.assertEqual(self.keybindings.get_strv("custom-list"), ["custom0"])
        self.assertEqual(self.slots["custom0"].get_strv("binding"), ["<Shift><Super>c"])

    def test_changing_accel_bounces_custom_list(self) -> None:
        """Cinnamon only re-reads grabs when custom-list changes."""
        hotkey.apply("<Super>v")
        self.keybindings.writes.clear()
        hotkey.apply("<Shift><Super>c")
        lists = [value for key, value in self.keybindings.writes if key == "custom-list"]
        self.assertEqual(lists, [[], ["custom0"]])

    def test_foreign_entries_are_preserved(self) -> None:
        self.keybindings.values["custom-list"] = ["custom0"]
        self.slots["custom0"] = FakeSettings({"command": "other-app"})
        hotkey.apply("<Super>v")
        self.assertEqual(self.keybindings.get_strv("custom-list"), ["custom0", "custom1"])
        self.assertEqual(self.slots["custom1"].get_strv("binding"), ["<Super>v"])


if __name__ == "__main__":
    unittest.main()
