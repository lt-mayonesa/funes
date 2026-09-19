"""A single clipboard history entry."""

import time

from gi.repository import GLib

_WHITESPACE = " \t\n\r\f\v"


def now_micros() -> int:
    """Unix microseconds, the timestamp unit used everywhere in Funes."""
    return int(time.time() * 1_000_000)


class HistoryItem:
    """Plain text payload plus its bookkeeping. v1 is text-only."""

    __slots__ = ("copy_count", "created", "last_used", "pinned", "rowid", "text")

    rowid: int | None
    text: str
    pinned: bool
    created: int
    last_used: int
    copy_count: int

    def __init__(
        self,
        text: str,
        created: int | None = None,
        last_used: int | None = None,
        pinned: bool = False,
        copy_count: int = 1,
        rowid: int | None = None,
    ) -> None:
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

    def preview(self, max_chars: int = 120) -> str:
        """Single-line, whitespace-collapsed label for the list rows."""
        collapsed = collapse_whitespace(self.text)
        if len(collapsed) <= max_chars:
            return collapsed
        return collapsed[:max_chars] + "\u2026"

    def describe(self) -> str:
        lines = len(self.text.split("\n"))
        size = GLib.format_size(len(self.text.encode("utf-8")))
        plural = "" if lines == 1 else "s"
        return f"{lines:d} line{plural}, {size}"

    def __repr__(self) -> str:
        return (
            f"HistoryItem({self.preview(30)!r}, pinned={self.pinned!r}, "
            f"copy_count={self.copy_count:d})"
        )


def collapse_whitespace(raw: str) -> str:
    out: list[str] = []
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
