"""Clipboard history entries and capture payloads.

v2 schema: items carry a ``kind`` (``"text"`` or ``"image"``), a
``content_hash`` for deduplication, and optional image metadata (mime, dims,
blob_sha).  Text is still stored inline; image bytes live on disk in
:mod:`funes.blobs`.
"""

import hashlib
import time
from dataclasses import dataclass, field

from gi.repository import GLib

_WHITESPACE = " \t\n\r\f\v"


def now_micros() -> int:
    """Unix microseconds, the timestamp unit used everywhere in Funes."""
    return int(time.time() * 1_000_000)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Capture dataclass — capture-time payload, never persisted as-is
# ---------------------------------------------------------------------------


@dataclass
class Capture:
    """All data collected at clipboard capture time.

    For text captures ``reps`` is empty and ``text`` holds the content.
    For image captures ``reps`` maps mime-type → raw bytes and ``text`` holds
    the hidden search string (e.g. captured text or OCR result).
    """

    kind: str  # "text" | "image"
    canonical_mime: str  # "text/plain" for text; "image/png" (preferred) or largest for images
    reps: dict[str, bytes] = field(default_factory=dict)  # mime → bytes (empty for text)
    text: str | None = None  # text payload (text kind) or hidden search string (image kind)

    @classmethod
    def from_text(cls, text: str) -> "Capture":
        return cls(kind="text", canonical_mime="text/plain", text=text)

    def content_hash(self) -> str:
        """SHA-256 of the canonical representation."""
        if self.kind == "text":
            assert self.text is not None
            return sha256_hex(self.text.encode("utf-8"))
        canonical = self.reps[self.canonical_mime]
        return sha256_hex(canonical)


# ---------------------------------------------------------------------------
# HistoryItem — in-memory mirror of one ``items`` row
# ---------------------------------------------------------------------------


class HistoryItem:
    """One clipboard entry. v2 supports both text and image kinds."""

    __slots__ = (
        "blob_sha",
        "bytes",
        "content_hash",
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
    kind: str  # "text" | "image"
    content_hash: str
    text: str | None  # None for image items
    search_text: str | None  # hidden search corpus
    mime: str | None  # canonical mime
    blob_sha: str | None  # canonical blob SHA (None for text)
    bytes: int
    width: int | None
    height: int | None
    ocr_text: str | None
    pinned: bool
    created: int
    last_used: int
    copy_count: int
    reps: dict[str, str]  # mime → blob_sha

    def __init__(
        self,
        *,
        kind: str = "text",
        content_hash: str,
        text: str | None = None,
        search_text: str | None = None,
        mime: str | None = None,
        blob_sha: str | None = None,
        bytes: int = 0,
        width: int | None = None,
        height: int | None = None,
        ocr_text: str | None = None,
        pinned: bool = False,
        created: int | None = None,
        last_used: int | None = None,
        copy_count: int = 1,
        rowid: int | None = None,
        reps: dict[str, str] | None = None,
    ) -> None:
        stamp = created if created is not None else now_micros()
        self.rowid = rowid
        self.kind = kind
        self.content_hash = content_hash
        self.text = text
        self.search_text = search_text
        self.mime = mime
        self.blob_sha = blob_sha
        self.bytes = bytes
        self.width = width
        self.height = height
        self.ocr_text = ocr_text
        self.pinned = pinned
        self.created = stamp
        self.last_used = last_used if last_used is not None else stamp
        self.copy_count = copy_count
        self.reps = reps or {}

    # --- display helpers ---

    def preview(self, max_chars: int = 120) -> str:
        """Single-line, whitespace-collapsed label for list rows."""
        if self.kind == "image":
            return self._image_label()
        assert self.text is not None
        collapsed = collapse_whitespace(self.text)
        if len(collapsed) <= max_chars:
            return collapsed
        return collapsed[:max_chars] + "\u2026"

    def describe(self) -> str:
        """Tooltip text."""
        if self.kind == "image":
            return self._image_label()
        assert self.text is not None
        lines = len(self.text.split("\n"))
        size = GLib.format_size(len(self.text.encode("utf-8")))
        plural = "" if lines == 1 else "s"
        return f"{lines:d} line{plural}, {size}"

    def _image_label(self) -> str:
        """E.g. ``PNG x 1920x1080 x 240 kB``."""
        parts: list[str] = []
        if self.mime:
            parts.append(self.mime.split("/")[-1].upper())
        if self.width and self.height:
            parts.append(f"{self.width}\u00d7{self.height}")
        if self.bytes:
            parts.append(GLib.format_size(self.bytes))
        return " \u00b7 ".join(parts) if parts else "Image"

    def __repr__(self) -> str:
        return (
            f"HistoryItem(kind={self.kind!r}, {self.preview(30)!r}, "
            f"pinned={self.pinned!r}, copy_count={self.copy_count:d})"
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
