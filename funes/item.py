"""A single clipboard history entry."""

import time
from dataclasses import dataclass

from gi.repository import GLib

_WHITESPACE = " \t\n\r\f\v"


def now_micros() -> int:
    """Unix microseconds, the timestamp unit used everywhere in Funes."""
    return int(time.time() * 1_000_000)


class HistoryItem:
    """Clipboard history entry: text or image, with metadata and representations.

    v2: added kind, mime, blob_sha, dimensions, search_text, reps, ocr_text.
    """

    __slots__ = (
        "blob_sha",
        "bytes",
        "copy_count",
        "created",
        "height",
        "kind",
        "last_used",
        "mime",
        "ocr_text",
        "pinned",
        "reps",
        "rowid",
        "search_text",
        "text",
        "width",
    )

    rowid: int | None
    text: str | None
    kind: str  # "text" or "image"
    mime: str | None  # "text/plain" or image MIME type
    blob_sha: str | None  # sha256 of canonical blob (None for text items)
    bytes: int  # payload size in bytes
    width: int | None  # image width in pixels
    height: int | None  # image height in pixels
    search_text: str | None  # hidden corpus: text content + metadata + ocr
    reps: dict[str, str]  # mime -> sha256 for all stored representations
    ocr_text: str | None  # recognized text from OCR
    pinned: bool
    created: int
    last_used: int
    copy_count: int

    def __init__(
        self,
        text: str | None = None,
        created: int | None = None,
        last_used: int | None = None,
        pinned: bool = False,
        copy_count: int = 1,
        rowid: int | None = None,
        kind: str = "text",
        mime: str | None = None,
        blob_sha: str | None = None,
        bytes: int = 0,
        width: int | None = None,
        height: int | None = None,
        search_text: str | None = None,
        reps: dict[str, str] | None = None,
        ocr_text: str | None = None,
    ) -> None:
        stamp = created if created is not None else now_micros()
        self.rowid = rowid
        self.text = text
        self.kind = kind
        self.mime = mime
        self.blob_sha = blob_sha
        self.bytes = bytes
        self.width = width
        self.height = height
        self.search_text = search_text
        self.reps = reps or {}
        self.ocr_text = ocr_text
        self.pinned = pinned
        # Unix microseconds of first capture.
        self.created = stamp
        # Unix microseconds of last copy (used for ordering).
        self.last_used = last_used if last_used is not None else stamp
        # How many times this exact text was copied.
        self.copy_count = copy_count

    def preview(self, max_chars: int = 120) -> str:
        """Single-line label for list rows: text content or image metadata."""
        if self.kind == "image":
            # Return metadata label for image items.
            return self.label()
        if not self.text:
            return "(empty)"
        collapsed = collapse_whitespace(self.text)
        if len(collapsed) <= max_chars:
            return collapsed
        return collapsed[:max_chars] + "\u2026"

    def label(self) -> str:
        """Metadata label for image rows: 'PNG · 1920x1080 · 240 kB'."""
        if self.kind != "image":
            return self.preview()
        parts = []
        if self.mime:
            parts.append(self.mime.split("/")[-1].upper())
        if self.width is not None and self.height is not None:
            parts.append(f"{self.width}x{self.height}")
        if self.bytes > 0:
            parts.append(GLib.format_size(self.bytes))
        return " · ".join(parts) if parts else "(image)"

    def describe(self) -> str:
        """Tooltip text: dimensions, size, line count."""
        if self.kind == "image":
            parts = []
            if self.width is not None and self.height is not None:
                parts.append(f"{self.width}x{self.height} pixels")
            if self.bytes > 0:
                parts.append(GLib.format_size(self.bytes))
            if self.mime:
                parts.append(self.mime)
            return ", ".join(parts) if parts else "(image)"
        if not self.text:
            return "(empty)"
        lines = len(self.text.split("\n"))
        size = GLib.format_size(len(self.text.encode("utf-8")))
        plural = "" if lines == 1 else "s"
        return f"{lines:d} line{plural}, {size}"

    def __repr__(self) -> str:
        kind_tag = f", kind={self.kind}" if self.kind != "text" else ""
        return (
            f"HistoryItem({self.preview(30)!r}, pinned={self.pinned!r}, "
            f"copy_count={self.copy_count:d}{kind_tag})"
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


@dataclass(frozen=True)
class Capture:
    """A clipboard capture payload: representations + optional text.

    Attributes:
        reps: mime -> bytes mapping of every stored representation.
        text: hidden search corpus (captured text or None).
        kind: 'text' if no image reps, 'image' if ≥1 image rep present.
        canonical_mime: preferred MIME type for dedup (image/png or largest).
    """

    reps: dict[str, bytes]
    text: str | None = None
    kind: str = "text"  # "text" or "image"
    canonical_mime: str = "text/plain"
