"""Which keystroke pastes into which window.

Model borrowed from Diodon: <kbd>Ctrl+V</kbd> is the paste shortcut almost
everywhere (GTK, Qt, browsers, Electron, Java/IntelliJ, xed), so it is the
default and needs no configuration. Only the outliers are listed here:

* Terminals bind <kbd>Ctrl+Shift+V</kbd> to paste, because <kbd>Ctrl+V</kbd> is
  a literal-next control character. VTE (gnome-terminal, xfce4-terminal,
  terminator, tilix, mate-terminal, guake, tilda), the GPU terminals (kitty,
  alacritty, wezterm, foot) and Konsole/Yakuake all agree on it.
* xterm, urxvt and rxvt have no <kbd>Ctrl+Shift+V</kbd>; their
  <kbd>Shift+Insert</kbd> pastes the PRIMARY selection, so for those - and only
  those - the item is also put on PRIMARY. That matters because owning PRIMARY
  sends every other client a `SelectionClear`, and GTK text views (xed) drop
  their selection on it, which turns a replace-the-selection paste into an
  insert-at-the-caret paste.

Why not Shift+Insert everywhere (the CopyQ strategy): VTE terminals read
Shift+Insert from PRIMARY too, so it only works if the manager steals PRIMARY
on every paste - the exact behaviour that broke xed.

The Ctrl+Shift+V list is not hidden in the code: it ships as the default value
of `paste-ctrl-shift-v-class-regex`, so Preferences shows the whole list and a
user can add their terminal to it (or reset the key to get it back). Only the
xterm/urxvt PRIMARY rule stays built in, since it is tied to the PRIMARY
side effect rather than to a keystroke preference.

GTK-free and display-free on purpose: everything here is pure string matching
over a window's "res_name.res_class", so it is unit-tested without an X server.
"""

import re
from dataclasses import dataclass

# WM_CLASS ("res_name.res_class") of terminals that paste with Ctrl+Shift+V.
# Kept in sync with the default of paste-ctrl-shift-v-class-regex in
# data/org.x.funes.gschema.xml (tests/test_paste_keys.py checks they match).
CTRL_SHIFT_V_CLASSES = (
    r"(?i)(^|\.)("
    r"gnome-terminal[^.]*|xfce4-terminal|terminator|tilix|mate-terminal|"
    r"guake|tilda|kitty|alacritty|org\.wezfurlong\.wezterm|wezterm|foot|"
    r"konsole|yakuake"
    r")"
)

# Terminals without Ctrl+Shift+V: Shift+Insert, which pastes PRIMARY there.
PRIMARY_CLASSES = r"(?i)(^|\.)(xterm|u?rxvt(-unicode)?(c)?)"


@dataclass(frozen=True)
class PasteMethod:
    """A keystroke to inject, plus whether PRIMARY must carry the item."""

    modifiers: tuple[str, ...]
    key: str
    sets_primary: bool = False

    @property
    def label(self) -> str:
        names = {"Control_L": "Ctrl", "Shift_L": "Shift"}
        parts = [names.get(modifier, modifier) for modifier in self.modifiers]
        return "+".join([*parts, self.key])


CTRL_V = PasteMethod(("Control_L",), "v")
CTRL_SHIFT_V = PasteMethod(("Control_L", "Shift_L"), "v")
SHIFT_INSERT_PRIMARY = PasteMethod(("Shift_L",), "Insert", sets_primary=True)


def class_matches(wm_class: str, pattern: str) -> bool:
    """Match a window's "res_name.res_class" against a regex.

    An empty pattern never matches; a broken one is reported instead of
    raising into the paste path.
    """
    if not pattern or not pattern.strip() or not wm_class:
        return False
    try:
        return re.search(pattern, wm_class) is not None
    except re.error as error:
        print(f"funes: bad WM_CLASS regex /{pattern}/: {error}")
        return False


def method_for(wm_class: str, ctrl_shift_v_regex: str = CTRL_SHIFT_V_CLASSES) -> PasteMethod:
    """Pick the paste keystroke for a target window.

    `ctrl_shift_v_regex` is the user-editable terminal list (the setting,
    whose default is `CTRL_SHIFT_V_CLASSES`); emptying it means "no terminal
    exceptions". xterm/urxvt keep Shift+Insert + PRIMARY unless the user
    claims them for Ctrl+Shift+V. Everything else gets Ctrl+V.
    """
    if class_matches(wm_class, ctrl_shift_v_regex):
        return CTRL_SHIFT_V
    if class_matches(wm_class, PRIMARY_CLASSES):
        return SHIFT_INSERT_PRIMARY
    return CTRL_V
