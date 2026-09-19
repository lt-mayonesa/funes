"""Presentation helpers for the history rows.

GTK-free on purpose so the heuristics are unit-testable without a display:
the popup only turns these results into widgets.
"""

import re

# Relative age thresholds, in seconds.
_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR

# Characters that almost never show up in prose but are everywhere in shell
# lines, code, paths and queries.
_CODEY_CHARS = set("{}[]()<>;=|&$#/\\_*@`~^%")

_CODEY_PATTERNS = (
    re.compile(r"^[a-z][\w.-]*\s.*(?:^|\s)-{1,2}[A-Za-z]"),  # cmd [sub] --flag
    re.compile(r"^(/|~/|\./|[A-Za-z]:\\)"),  # paths
    re.compile(r"^[a-z]+://"),  # url-ish
    re.compile(r"^#[0-9a-fA-F]{3,8}$"),  # color literal
    re.compile(r"^[0-9a-f]{7,40}$"),  # hashes
    re.compile(
        r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN)\b.*\b(FROM|WHERE|SET|VALUES|ON)\b",
        re.IGNORECASE,
    ),
)

_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def relative_age(created_micros: int, now_micros: int) -> str:
    """Fixed-width-ish relative age: `12s`, `4m`, `1h`, `yest.`, `3d`, `5w`."""
    seconds = max(0, (now_micros - created_micros) // 1_000_000)
    if seconds < _MINUTE:
        return f"{seconds}s"
    if seconds < _HOUR:
        return f"{seconds // _MINUTE}m"
    if seconds < _DAY:
        return f"{seconds // _HOUR}h"
    days = seconds // _DAY
    if days == 1:
        return "yest."
    if days < 7:
        return f"{days}d"
    if days < 365:
        return f"{days // 7}w"
    return f"{days // 365}y"


def looks_like_code(text: str) -> bool:
    """Cheap heuristic: should this row be rendered in a monospace face?

    Deliberately conservative — a wrong monospace row is noise, so prose with
    ordinary punctuation must stay in the UI font.
    """
    stripped = text.strip()
    if not stripped or "\n" in stripped:
        return False
    if any(pattern.search(stripped) for pattern in _CODEY_PATTERNS):
        return True
    codey = sum(1 for char in stripped if char in _CODEY_CHARS)
    if " " not in stripped and codey:
        return True
    return codey >= 3 and codey / len(stripped) >= 0.06


def color_literal(text: str) -> str | None:
    """Return the hex color this item is, or None."""
    stripped = text.strip()
    return stripped if _COLOR_RE.match(stripped) else None


def match_span(haystack: str, needle: str) -> tuple[int, int] | None:
    """Byte offsets of the first case-insensitive match, for Pango attributes."""
    if not needle:
        return None
    index = haystack.lower().find(needle.lower())
    if index < 0:
        return None
    start = len(haystack[:index].encode("utf-8"))
    end = start + len(haystack[index : index + len(needle)].encode("utf-8"))
    return start, end
