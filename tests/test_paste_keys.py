"""Tests for the paste-keystroke table (`funes/paste_keys.py`).

Ctrl+V is the default because it pastes almost everywhere; terminals are the
outliers. The PRIMARY entry must stay limited to xterm/urxvt/rxvt: owning
PRIMARY makes GTK text views (xed) drop their selection, which turns a
replace-the-selection paste into an insert-at-the-caret paste.

Pure string matching, so no display is needed.
"""

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from funes.paste_keys import (  # noqa: E402
    CTRL_SHIFT_V,
    CTRL_SHIFT_V_CLASSES,
    CTRL_V,
    SHIFT_INSERT_PRIMARY,
    class_matches,
    method_for,
)


class MethodForTests(unittest.TestCase):
    def test_default_is_ctrl_v(self) -> None:
        for wm_class in (
            "xed.Xed",
            "google-chrome.Google-chrome",
            "jetbrains-idea.jetbrains-idea",
            "nemo.Nemo",
            "typora.Typora",
            "",
        ):
            self.assertEqual(method_for(wm_class), CTRL_V, wm_class)

    def test_terminals_use_ctrl_shift_v(self) -> None:
        for wm_class in (
            "gnome-terminal-server.Gnome-terminal",
            "xfce4-terminal.Xfce4-terminal",
            "terminator.Terminator",
            "tilix.Tilix",
            "mate-terminal.Mate-terminal",
            "guake.Guake",
            "kitty.kitty",
            "alacritty.Alacritty",
            "org.wezfurlong.wezterm.org.wezfurlong.wezterm",
            "foot.foot",
            "konsole.konsole",
            "yakuake.yakuake",
        ):
            self.assertEqual(method_for(wm_class), CTRL_SHIFT_V, wm_class)

    def test_xterm_family_uses_shift_insert_and_primary(self) -> None:
        for wm_class in ("xterm.XTerm", "urxvt.URxvt", "rxvt.Rxvt", "urxvtc.URxvt"):
            self.assertEqual(method_for(wm_class), SHIFT_INSERT_PRIMARY, wm_class)

    def test_only_shift_insert_targets_touch_primary(self) -> None:
        self.assertTrue(SHIFT_INSERT_PRIMARY.sets_primary)
        self.assertFalse(CTRL_V.sets_primary)
        self.assertFalse(CTRL_SHIFT_V.sets_primary)

    def test_user_regex_replaces_the_terminal_list(self) -> None:
        self.assertEqual(method_for("myterm.Myterm", "myterm"), CTRL_SHIFT_V)
        self.assertEqual(method_for("tilix.Tilix", "myterm"), CTRL_V)

    def test_user_regex_can_claim_xterm(self) -> None:
        self.assertEqual(method_for("xterm.XTerm", "xterm"), CTRL_SHIFT_V)

    def test_emptied_regex_disables_the_terminal_exception(self) -> None:
        self.assertEqual(method_for("tilix.Tilix", ""), CTRL_V)
        self.assertEqual(method_for("tilix.Tilix", "  "), CTRL_V)

    def test_broken_user_regex_falls_back_to_ctrl_v(self) -> None:
        self.assertEqual(method_for("xed.Xed", "xed("), CTRL_V)

    def test_schema_default_matches_the_module_default(self) -> None:
        """The setting ships the list, so the two must not drift apart."""
        import xml.etree.ElementTree as ET

        schema = ET.parse(_ROOT / "data" / "org.x.funes.gschema.xml")
        for key in schema.getroot().iter("key"):
            if key.get("name") == "paste-ctrl-shift-v-class-regex":
                default = (key.findtext("default") or "").strip()
                # GVariant string literal: 'text' with \\ meaning one backslash.
                unquoted = default[1:-1].replace("\\\\", "\\")
                self.assertEqual(unquoted, CTRL_SHIFT_V_CLASSES)
                break
        else:
            self.fail("paste-ctrl-shift-v-class-regex missing from the schema")

    def test_terminal_match_is_not_a_substring_free_for_all(self) -> None:
        """ "Kitty" in a document title or an app called 'kitty-cam' is not a terminal."""
        self.assertEqual(method_for("gitkitty.Gitkitty"), CTRL_V)

    def test_labels(self) -> None:
        self.assertEqual(CTRL_V.label, "Ctrl+v")
        self.assertEqual(CTRL_SHIFT_V.label, "Ctrl+Shift+v")
        self.assertEqual(SHIFT_INSERT_PRIMARY.label, "Shift+Insert")


class ClassMatchTests(unittest.TestCase):
    def test_empty_pattern_never_matches(self) -> None:
        self.assertFalse(class_matches("xterm.XTerm", ""))

    def test_unknown_window_never_matches(self) -> None:
        self.assertFalse(class_matches("", "xterm"))

    def test_broken_regex_is_reported_not_raised(self) -> None:
        self.assertFalse(class_matches("xterm.XTerm", "xterm("))
