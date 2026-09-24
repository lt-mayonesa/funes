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


# Mimes a file manager copy/cut puts on the clipboard. Presence of either
# one is enough to classify as "files", even alongside other reps (e.g. some
# file managers also offer a thumbnail image/* rep for a single-file copy).
FILE_MIMES = frozenset({"text/uri-list", "x-special/gnome-copied-files"})


def classify(reps: dict[str, bytes]) -> str:
    """Pick a display-kind hint from a captured representation set.

    This is display-only: every representation is always stored and replayed
    verbatim on paste regardless of what this returns \u2014 classify() only
    decides how the row *looks* in the popup. ``"other"`` is a guaranteed
    fallback for any mime combination not specifically recognized (a generic
    row showing the mime label + byte size, see HistoryItem._binary_label),
    so a clipboard format Funes doesn't have a dedicated presentation for is
    never left unrenderable \u2014 just plain instead of specialized. Meant to
    grow new branches over time (vector graphics, rich text, ...) without
    ever removing the ``"other"`` fallback.

    Priority when a copy offers signals for more than one kind at once:
    files > image > other. A file manager deliberately offering uri-list (or
    a thumbnail image alongside it) is a more specific, intentional signal
    than an incidental fallback another kind might also be offering.

    Never called for plain-text-only captures: those stay ``"text"`` and
    never populate ``reps`` at all (see ``Capture.from_text``).
    """
    if any(mime in FILE_MIMES for mime in reps):
        return "files"
    if any(mime.startswith("image/") for mime in reps):
        return "image"
    return "other"


# Vector image formats: never decode-then-reencode these for storage or
# paste — GdkPixbuf is only ever used to render a *preview thumbnail* for
# these mimes (images.py), the stored/pasted bytes are always the original
# verbatim SVG. image/svg+xml is the standard mime; image/x-inkscape-svg is
# Inkscape's own variant (adds its own namespaced attributes).
VECTOR_MIMES = frozenset({"image/svg+xml", "image/x-inkscape-svg"})


# Mime subtype -> short display label, for cases where naively upper-casing
# everything after the last "/" reads badly ("image/svg+xml" -> "SVG+XML",
# "image/x-inkscape-svg" -> "X-INKSCAPE-SVG").
_MIME_LABEL_OVERRIDES = {
    "image/svg+xml": "SVG",
    "image/x-inkscape-svg": "SVG",
}


def mime_subtype_label(mime: str) -> str:
    """Short display label for a mime, e.g. ``"image/png"`` -> ``"PNG"``."""
    if mime in _MIME_LABEL_OVERRIDES:
        return _MIME_LABEL_OVERRIDES[mime]
    return mime.split("/")[-1].upper()


def pick_canonical_mime(reps: dict[str, bytes]) -> str:
    """Pick the canonical mime out of a captured representation set.

    Priority: a vector rep (``VECTOR_MIMES``) first — some apps (Inkscape
    included) also offer a raster preview alongside the real vector data,
    and the vector rep is the richer/most-editable one, so it should be
    what a row identifies the item as, not an incidental PNG preview.
    Otherwise ``image/png`` (the historical default); otherwise the largest
    representation wins, on the theory that a bigger payload for the same
    clipboard entry is more likely to be the richest/most complete one
    (e.g. a full-resolution raster fallback next to a tiny icon-sized
    alternate).

    Pure and display-independent on purpose so it's unit-testable without a
    running GTK main loop or a real clipboard.
    """
    if not reps:
        raise ValueError("pick_canonical_mime: reps must not be empty")
    for vector_mime in ("image/svg+xml", "image/x-inkscape-svg"):
        if vector_mime in reps:
            return vector_mime
    if "image/png" in reps:
        return "image/png"
    return max(reps, key=lambda mime: len(reps[mime]))


# ---------------------------------------------------------------------------
# Capture dataclass — capture-time payload, never persisted as-is
# ---------------------------------------------------------------------------


@dataclass
class Capture:
    """All data collected at clipboard capture time.

    For text captures ``reps`` is empty and ``text`` holds the content.
    For image/files/other captures ``reps`` maps mime-type → raw bytes and
    ``text`` holds the hidden search string (captured text, OCR result, or —
    for ``files`` — the newline-joined filenames).
    """

    kind: str  # "text" | "image" | "files" | "other"
    canonical_mime: str  # "text/plain" for text; otherwise pick_canonical_mime(reps)
    reps: dict[str, bytes] = field(default_factory=dict)  # mime → bytes (empty for text)
    text: str | None = None  # text payload (text kind) or hidden search string (other kinds)
    operation: str | None = None  # "cut" | "copy" | None (only meaningful for kind == "files")

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
        "operation",
        "pinned",
        "reps",
        "rowid",
        "search_text",
        "text",
        "width",
    )

    rowid: int | None
    kind: str  # "text" | "image" | "files" | "other"
    content_hash: str
    text: str | None  # None for non-text items
    search_text: str | None  # hidden search corpus (filenames, for "files")
    mime: str | None  # canonical mime
    blob_sha: str | None  # canonical blob SHA (None for text)
    bytes: int
    width: int | None
    height: int | None
    ocr_text: str | None
    operation: str | None  # "cut" | "copy" | None (only meaningful for kind == "files")
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
        operation: str | None = None,
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
        self.operation = operation
        self.pinned = pinned
        self.created = stamp
        self.last_used = last_used if last_used is not None else stamp
        self.copy_count = copy_count
        self.reps = reps or {}

    # --- display helpers ---

    def preview(self, max_chars: int = 120) -> str:
        """Single-line, whitespace-collapsed label for list rows."""
        if self.kind == "files":
            return self._files_label(max_chars)
        if self.kind != "text":
            return self._binary_label()
        assert self.text is not None
        collapsed = collapse_whitespace(self.text)
        if len(collapsed) <= max_chars:
            return collapsed
        return collapsed[:max_chars] + "\u2026"

    def describe(self) -> str:
        """Tooltip text."""
        if self.kind == "files":
            return self._files_label()
        if self.kind != "text":
            return self._binary_label()
        assert self.text is not None
        lines = len(self.text.split("\n"))
        size = GLib.format_size(len(self.text.encode("utf-8")))
        plural = "" if lines == 1 else "s"
        return f"{lines:d} line{plural}, {size}"

    def _files_label(self, max_chars: int | None = None) -> str:
        """E.g. ``Copied: report.pdf`` or ``Cut 3 files: a.txt, b.txt, c.txt``.

        Filenames come from ``search_text`` (newline-joined at capture time
        \u2014 see ``funes.files``), not by re-parsing the raw uri-list bytes
        on every row redraw.
        """
        names = [n for n in (self.search_text or "").split("\n") if n]
        verb = "Cut" if self.operation == "cut" else "Copied"
        if not names:
            label = f"{verb} {GLib.format_size(self.bytes)}" if self.bytes else verb
        elif len(names) == 1:
            label = f"{verb}: {names[0]}"
        else:
            shown = ", ".join(names[:3])
            more = f" +{len(names) - 3} more" if len(names) > 3 else ""
            label = f"{verb} {len(names)} files: {shown}{more}"
        if max_chars is not None and len(label) > max_chars:
            return label[:max_chars] + "\u2026"
        return label

    def _binary_label(self) -> str:
        """E.g. ``PNG x 1920x1080 x 240 kB`` for images, ``SVG x 4.1 kB`` for
        anything else classify() couldn't give a more specific presentation
        to \u2014 the guaranteed fallback so no captured format is ever left
        without at least a generic, readable label."""
        parts: list[str] = []
        if self.mime:
            parts.append(mime_subtype_label(self.mime))
        if self.width and self.height:
            parts.append(f"{self.width}\u00d7{self.height}")
        if self.bytes:
            parts.append(GLib.format_size(self.bytes))
        if parts:
            return " \u00b7 ".join(parts)
        return "Image" if self.kind == "image" else "Unsupported format"

    # (kind == "files" never reaches _binary_label — see preview()/describe())

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
