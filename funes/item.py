"""A single clipboard history entry."""

import time

from gi.repository import GLib

_WHITESPACE = " \t\n\r\f\v"


def now_micros():
    """Unix microseconds, the timestamp unit used everywhere in Funes."""
    return int(time.time() * 1_000_000)


class HistoryItem:
    """Plain text payload plus its bookkeeping. v1 is text-only."""

    __slots__ = ("copy_count", "created", "last_used", "pinned", "rowid", "text")

    def __init__(self, text, created=None, last_used=None, pinned=False, copy_count=1, rowid=None):
        stamp = created if created is not None else now_micros()
        self.rowid = rowid
        self.text = text
        self.pinned = pinned
        # Unix microseconds of first capture.
        self.created = stamp
        # Unix microseconds of last copy (used for ordering).
        self.last_used = last_used if last_used is not None else stamp
        # How many times this exact text was copied.
        self.copy_count = copy_count

    def preview(self, max_chars=120):
        """Single-line, whitespace-collapsed label for the list rows."""
        collapsed = collapse_whitespace(self.text)
        if len(collapsed) <= max_chars:
            return collapsed
        return collapsed[:max_chars] + "\u2026"

    def describe(self):
        lines = len(self.text.split("\n"))
        size = GLib.format_size(len(self.text.encode("utf-8")))
        plural = "" if lines == 1 else "s"
        return f"{lines:d} line{plural}, {size}"

    def __repr__(self):
        return (
            f"HistoryItem({self.preview(30)!r}, pinned={self.pinned!r}, "
            f"copy_count={self.copy_count:d})"
        )


def collapse_whitespace(raw):
    out = []
    in_space = False
    for char in raw:
        if char in _WHITESPACE:
            in_space = True
            continue
        if in_space and out:
            out.append(" ")
        in_space = False
        out.append(char)
    return "".join(out)
