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

# Formatted-text mimes. Their presence next to a plain-text fallback is what
# makes a copy "richtext" (badge on the row, Shift+Enter pastes plain). Any
# *other* extra target next to plain text (X-SOURCE-URL, GtkTextBuffer
# serializations, app-private formats, ...) is still captured and replayed
# verbatim, but the row stays a plain "text" row. Ordered by preference for
# the canonical rep.
RICH_TEXT_MIMES = ("text/html", "text/rtf", "application/rtf", "text/richtext")

# Rep under which the plain-text fallback of a multi-target copy is stored.
# Replay serves every plain-text target (UTF8_STRING, STRING, TEXT, ...) from
# it via Gtk.SelectionData.set_text(), which converts per target, instead of
# storing each encoding's bytes verbatim under a type they may not match.
PLAIN_TEXT_REP = "text/plain;charset=utf-8"

# Kinds whose row shows ``HistoryItem.text`` (the plain-text fallback) and
# whose item can be pasted as plain text.
TEXT_KINDS = frozenset({"text", "richtext"})


def classify(reps: dict[str, bytes], text: str | None = None) -> str:
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
    files > image > richtext > text > other. A file manager deliberately
    offering uri-list (or a thumbnail image alongside it) is a more
    specific, intentional signal than an incidental fallback another kind
    might also be offering. *text* is the plain-text fallback captured
    alongside the reps: without a non-blank one a copy can't be ``richtext``
    or ``text`` (there would be nothing to show or paste as plain text).

    Never called for plain-text-only captures: those stay ``"text"`` and
    never populate ``reps`` at all (see ``Capture.from_text``).
    """
    if any(mime in FILE_MIMES for mime in reps):
        return "files"
    if any(mime.startswith("image/") for mime in reps):
        return "image"
    if text is not None and text.strip():
        if any(mime in reps for mime in RICH_TEXT_MIMES):
            return "richtext"
        return "text"
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


def pick_canonical_mime(reps: dict[str, bytes], kind: str | None = None) -> str:
    """Pick the canonical mime out of a captured representation set.

    *kind* (the result of ``classify()``) narrows the choice for kinds whose
    canonical rep isn't an image: ``richtext`` -> the first present
    ``RICH_TEXT_MIMES`` entry, ``text`` -> ``"text/plain"`` (the item is
    identified by its plain text; the reps are incidental extras), ``files``
    -> gnome-copied-files, else uri-list.

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
    if kind == "text":
        return "text/plain"
    if kind == "richtext":
        for rich_mime in RICH_TEXT_MIMES:
            if rich_mime in reps:
                return rich_mime
    if kind == "files":
        for file_mime in ("x-special/gnome-copied-files", "text/uri-list"):
            if file_mime in reps:
                return file_mime
    for vector_mime in ("image/svg+xml", "image/x-inkscape-svg"):
        if vector_mime in reps:
            return vector_mime
    if "image/png" in reps:
        return "image/png"
    images = [mime for mime in reps if mime.startswith("image/")]
    return max(images or reps, key=lambda mime: len(reps[mime]))


# ---------------------------------------------------------------------------
# Capture dataclass — capture-time payload, never persisted as-is
# ---------------------------------------------------------------------------


@dataclass
class Capture:
    """All data collected at clipboard capture time.

    For plain-text-only captures ``reps`` is empty and ``text`` holds the
    content. For ``text`` captures that came with extra targets, and for
    ``richtext``, ``reps`` holds every offered target verbatim and ``text``
    the plain-text fallback (shown, searched, pasted by Shift+Enter).
    For image/files/other captures ``reps`` maps mime-type → raw bytes and
    ``text`` holds the hidden search string (captured text, OCR result, or —
    for ``files`` — the newline-joined filenames).
    """

    kind: str  # "text" | "richtext" | "image" | "files" | "other"
    canonical_mime: str  # "text/plain" for text; otherwise pick_canonical_mime(reps)
    reps: dict[str, bytes] = field(default_factory=dict)  # mime → bytes (empty for text)
    text: str | None = None  # text payload (text kind) or hidden search string (other kinds)
    operation: str | None = None  # "cut" | "copy" | None (only meaningful for kind == "files")

    @classmethod
    def from_text(cls, text: str) -> "Capture":
        return cls(kind="text", canonical_mime="text/plain", text=text)

    def content_hash(self) -> str:
        """SHA-256 identifying the entry for deduplication.

        ``text``: the plain text only, so incidental extra targets (a
        browser's source-URL atom, ...) never split one visible string into
        several rows. ``richtext``: the plain text *plus* every formatted rep
        (``RICH_TEXT_MIMES``), so "hello" and **hello** are separate rows,
        while app-private targets (which may carry volatile data) still
        don't affect identity. Everything else: the canonical rep.
        """
        if self.kind == "text":
            assert self.text is not None
            return sha256_hex(self.text.encode("utf-8"))
        if self.kind == "richtext":
            assert self.text is not None
            digest = hashlib.sha256(self.text.encode("utf-8"))
            for mime in RICH_TEXT_MIMES:
                if mime in self.reps:
                    digest.update(b"\0" + mime.encode() + b"\0")
                    digest.update(self.reps[mime])
            return digest.hexdigest()
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
    kind: str  # "text" | "richtext" | "image" | "files" | "other"
    content_hash: str
    text: str | None  # plain text for TEXT_KINDS, None otherwise
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

    @property
    def is_rich(self) -> bool:
        """True for formatted text (HTML/RTF) that also has a plain fallback."""
        return self.kind == "richtext"

    @property
    def plain_text(self) -> str | None:
        """The plain-text fallback pasted by Shift+Enter, None if there is none."""
        return self.text if self.kind in TEXT_KINDS else None

    def preview(self, max_chars: int = 120) -> str:
        """Single-line, whitespace-collapsed label for list rows."""
        if self.kind == "files":
            return self._files_label(max_chars)
        if self.kind not in TEXT_KINDS:
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
        if self.kind not in TEXT_KINDS:
            return self._binary_label()
        assert self.text is not None
        lines = len(self.text.split("\n"))
        size = GLib.format_size(len(self.text.encode("utf-8")))
        plural = "" if lines == 1 else "s"
        described = f"{lines:d} line{plural}, {size}"
        if self.kind == "richtext" and self.mime:
            described += f" \u00b7 {mime_subtype_label(self.mime)}"
        return described

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
