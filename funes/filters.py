"""Capture filters: decide whether a clipboard payload is worth storing.

Kept free of GTK so the rules are unit-testable without a display.
"""

import re
from collections.abc import Callable, Iterable, Sequence

# MIME hints used by password managers. KeePassXC/Firefox/Bitwarden set
# `x-kde-passwordManagerHint`; GTK rejects that as an invalid MIME type so the
# `text/`-prefixed variant is checked too.
SECRET_TARGETS = (
    "x-kde-passwordManagerHint",
    "text/x-kde-passwordManagerHint",
    "application/x-nextcloud-talk-secret",
    "org.nspasteboard.ConcealedType",
)


def is_secret(target_names: Iterable[str] | None) -> bool:
    """True when the clipboard owner flagged the payload as a secret."""
    if not target_names:
        return False
    return any(name in SECRET_TARGETS for name in target_names)


def is_blank(text: str | None) -> bool:
    return text is None or not text.strip()


def is_too_big(text: str, max_bytes: int) -> bool:
    return len(text.encode("utf-8")) > max_bytes


def matching_ignore_regex(
    text: str,
    patterns: Sequence[str] | None,
    on_bad_pattern: Callable[[str, re.error], None] | None = None,
) -> str | None:
    """Return the first ignore regex matching text, or None."""
    for pattern in patterns or ():
        if not pattern.strip():
            continue
        try:
            if re.search(pattern, text):
                return pattern
        except re.error as error:
            if on_bad_pattern is not None:
                on_bad_pattern(pattern, error)
    return None
