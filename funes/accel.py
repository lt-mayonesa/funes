"""Accelerator string handling for the global shortcut.

GTK-free on purpose: the capture widget turns a key event into a GTK
accelerator string (``<Super>v``) and everything else — splitting, validation,
warnings, labels for display — lives here so it is unit-testable without an X
server.

Policy (see `docs/design/TODO.md`):

* anything GTK can spell is accepted, so exotic combos are not second-guessed;
* a bare reserved key (Escape, Tab, Return, BackSpace, space, …) is refused,
  those belong to the capture widget itself and to text entry;
* a modifier-less key is accepted but warned about, because it swallows that
  key system-wide;
* the empty string means "no global shortcut" and unregisters the binding.
"""

import re

DEFAULT = "<Super>v"

# Keys that must never be grabbed on their own. With a modifier they are fine
# (``<Super>space`` is a common launcher binding), so this is checked only for
# modifier-less accelerators.
RESERVED_KEYS: frozenset[str] = frozenset(
    {
        "Escape",
        "Tab",
        "ISO_Left_Tab",
        "Return",
        "KP_Enter",
        "BackSpace",
        "Delete",
        "space",
    }
)

# Modifier names GTK emits in accelerator strings, lowercased.
_KNOWN_MODIFIERS: frozenset[str] = frozenset(
    {"shift", "control", "ctrl", "primary", "alt", "mod1", "super", "hyper", "meta"}
)

_MODIFIER_RE = re.compile(r"<([^<>]+)>")

_LABELS: dict[str, str] = {
    "control": "Ctrl",
    "ctrl": "Ctrl",
    "primary": "Ctrl",
    "mod1": "Alt",
    "alt": "Alt",
    "shift": "Shift",
    "super": "Super",
    "hyper": "Hyper",
    "meta": "Meta",
}

_KEY_LABELS: dict[str, str] = {
    "space": "Space",
    "Return": "Enter",
    "KP_Enter": "Enter",
    "BackSpace": "Backspace",
    "Escape": "Esc",
    "Page_Up": "Page Up",
    "Page_Down": "Page Down",
}


def normalize(accel: str | None) -> str:
    """Trim an accelerator; ``None`` and blanks collapse to the empty string."""
    return (accel or "").strip()


def split(accel: str | None) -> tuple[list[str], str]:
    """Return ``(modifiers, key)`` for an accelerator string.

    Modifiers keep their written order, lowercased and without the angle
    brackets. Unparseable input yields ``([], "")``.
    """
    text = normalize(accel)
    if not text:
        return [], ""
    modifiers = [name.strip().lower() for name in _MODIFIER_RE.findall(text)]
    key = _MODIFIER_RE.sub("", text).strip()
    return [name for name in modifiers if name], key


def has_modifier(accel: str | None) -> bool:
    modifiers, _key = split(accel)
    return any(name in _KNOWN_MODIFIERS for name in modifiers)


def is_reserved(accel: str | None) -> bool:
    """True for a bare reserved key such as ``Escape`` or ``space``."""
    modifiers, key = split(accel)
    return not modifiers and key in RESERVED_KEYS


def is_valid(accel: str | None) -> bool:
    """True when the accelerator can be registered as a global shortcut."""
    _modifiers, key = split(accel)
    return bool(key) and not is_reserved(accel)


def warning_for(accel: str | None) -> str:
    """Human-readable caveat for a valid accelerator, or an empty string.

    Only one case today: a modifier-less shortcut is legal but eats that key
    everywhere, so the Preferences row says so instead of silently trapping it.
    """
    if not is_valid(accel) or has_modifier(accel):
        return ""
    return "No modifier: this key will be captured in every application."


def label(accel: str | None) -> str:
    """Pretty, keycap-style rendering: ``<Shift><Super>c`` → ``Shift+Super+C``."""
    modifiers, key = split(accel)
    if not key:
        return ""
    parts = [_LABELS.get(name, name.capitalize()) for name in modifiers]
    parts.append(_key_label(key))
    return "+".join(parts)


def _key_label(key: str) -> str:
    if key in _KEY_LABELS:
        return _KEY_LABELS[key]
    if len(key) == 1:
        return key.upper()
    return key.replace("_", " ")
