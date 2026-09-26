"""Tests for WM_CLASS matching, the gate in front of both paste overrides.

`paste-ctrl-v-class-regex` picks the keystroke; `paste-primary-class-regex`
decides whether the item is also put on PRIMARY. The latter must stay narrow:
taking the PRIMARY selection makes GTK editors (xed) drop their own selection,
so the paste lands at the caret instead of replacing the selected text.

Pure string matching, so no display is needed.
"""

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from funes.paster import class_matches  # noqa: E402

# The shipped default of paste-primary-class-regex.
PRIMARY_DEFAULT = "xterm|urxvt|rxvt"


class ClassMatchTests(unittest.TestCase):
    def test_matches_res_name_or_res_class(self) -> None:
        self.assertTrue(class_matches("xterm.XTerm", PRIMARY_DEFAULT))
        self.assertTrue(class_matches("urxvt.URxvt", PRIMARY_DEFAULT))

    def test_does_not_match_gtk_editors(self) -> None:
        """xed must never get PRIMARY: it deselects on SelectionClear."""
        self.assertFalse(class_matches("xed.Xed", PRIMARY_DEFAULT))
        self.assertFalse(class_matches("google-chrome.Google-chrome", PRIMARY_DEFAULT))
        self.assertFalse(class_matches("jetbrains-idea.jetbrains-idea", PRIMARY_DEFAULT))
        self.assertFalse(class_matches("nemo.Nemo", PRIMARY_DEFAULT))

    def test_empty_pattern_never_matches(self) -> None:
        self.assertFalse(class_matches("xterm.XTerm", ""))
        self.assertFalse(class_matches("xterm.XTerm", "   "))

    def test_unknown_window_never_matches(self) -> None:
        self.assertFalse(class_matches("", PRIMARY_DEFAULT))

    def test_broken_regex_is_reported_not_raised(self) -> None:
        self.assertFalse(class_matches("xterm.XTerm", "xterm("))

    def test_custom_pattern(self) -> None:
        self.assertTrue(class_matches("gnome-terminal-server.Gnome-terminal", "Gnome-terminal"))


if __name__ == "__main__":
    unittest.main()
