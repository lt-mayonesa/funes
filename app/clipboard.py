"""Clipboard watcher — v2 with image capture.

Uses Gtk.Clipboard's owner-change signal, which on X11 is driven by the XFixes
extension: no polling (unlike Maccy's 500ms NSPasteboard timer).

Image capture
-------------
On each owner-change we call request_targets() first, then partition the
offered atoms into ``image/*`` and text types.  If images are present and
``capture-images`` is enabled we fire an async chain:
  request_contents(mime, cb) for each image atom (NOT wait_for_contents —
  that can stall on X11 INCR transfers for >256 KB payloads).
A 500 ms watchdog finishes the chain with whatever was captured so far if
the source is hostile, slow, or never replies to a request at all for a
target it advertised but doesn't actually serve (GTK/X11 give no delivery
guarantee) \u2014 it does not just abort silently, since a target requested
before the stuck one may already have succeeded and be worth keeping.
Hashing + GdkPixbuf probing for width/height run in a worker thread so
10 MiB screenshots never block the UI.

Copy-back (set_item)
--------------------
For text items we use set_text() as before.
For image items every stored representation is replayed byte-for-byte:
Gtk.Clipboard.set_with_data() cannot be used from PyGObject (GObject
Introspection cannot bind its raw TargetEntry-array + callback signature —
PyGObject marks it ``_unsupported_data_method``), so ownership is instead
taken with the lower-level primitives GI *can* bind safely:
Gtk.selection_add_target()/Gtk.selection_owner_set() plus the
``selection-get``/``selection-clear-event`` signals on a hidden
Gtk.Invisible widget (``_own_clipboard_verbatim``). If ownership can't be
taken at all, a single rasterized image/png rep is used as a last resort.

Self-ignore guard
-----------------
Funes writes to the clipboard itself (on paste and when re-owning), which
triggers owner-change again.  Without the guard that is an infinite loop.
"""

import re
from collections.abc import Callable, Iterable
from typing import ClassVar

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk

from funes import filters, log
from funes.config import Config
from funes.item import Capture, classify
from funes.item import pick_canonical_mime as _pick_canonical

# Watchdog: abort image capture chain after this many milliseconds.
_CAPTURE_WATCHDOG_MS = 500

# X11 selection-protocol bookkeeping atoms every clipboard owner offers.
# Never real payloads — requesting them would just waste a round-trip.
_PROTOCOL_ATOMS = frozenset({"TIMESTAMP", "TARGETS", "MULTIPLE", "SAVE_TARGETS"})

# Plain-text encodings of the *same* string content. When these are the only
# payload targets offered, the cheap request_text() path is used instead of
# capturing each one as a separate (redundant) representation.
_TEXT_ATOMS = frozenset(
    {"UTF8_STRING", "COMPOUND_TEXT", "TEXT", "STRING", "text/plain;charset=utf-8", "text/plain"}
)


class ClipboardMonitor(GObject.Object):
    __gsignals__: ClassVar[dict[str, tuple[object, ...]]] = {
        # Carries a Capture object (text or image).
        "captured": (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self._self_owned = False
        self._last_seen_hash = ""
        self._watchdog_id: int = 0
        self._owner_widget: Gtk.Invisible | None = None
        self._clipboard.connect("owner-change", self._on_owner_change)

    def start(self) -> None:
        # Pick up whatever is already on the clipboard at startup.
        self._on_owner_change(self._clipboard, None)

    def set_text(self, text: str, also_primary: bool = False) -> None:
        """Put text on the clipboard without recording it again."""
        self._self_owned = True
        self._clipboard.set_text(text, -1)
        self._clipboard.store()
        if also_primary:
            Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY).set_text(text, -1)

    def set_item(self, item: "object") -> None:
        """Put a HistoryItem back on the clipboard (text or image)."""
        from funes.item import HistoryItem  # local to avoid circular import

        assert isinstance(item, HistoryItem)
        self._self_owned = True
        if item.kind == "text":
            text = item.text or ""
            self._clipboard.set_text(text, -1)
            self._clipboard.store()
        else:
            self._set_reps_item(item)

    def _set_reps_item(self, item: "object") -> None:
        """Re-own the clipboard, replaying every stored representation."""
        from funes.item import HistoryItem

        assert isinstance(item, HistoryItem)
        reps_sha: dict[str, str] = item.reps.copy()
        if item.blob_sha and item.mime and item.mime not in reps_sha:
            reps_sha[item.mime] = item.blob_sha

        if not reps_sha:
            log.debug(f"set_reps_item: no stored representations for item {item!r}")
            return

        # BlobStore reference injected onto the instance by the caller
        # (funes_app._on_item_chosen) so blobs can be read on demand.
        blob_store = getattr(self, "_blob_store", None)

        def get_bytes(mime: str) -> bytes | None:
            sha = reps_sha.get(mime)
            if sha is None or blob_store is None:
                return None
            try:
                return bytes(blob_store.read(sha))
            except Exception as exc:
                log.debug(f"get_bytes: could not read {mime}: {exc}")
                return None

        if self._own_clipboard_verbatim(reps_sha.keys(), get_bytes):
            return

        # Last resort: a single rasterized rep beats losing the content, but
        # only makes sense for images \u2014 there's nothing meaningful to
        # rasterize for an "other" kind (arbitrary binary data).
        if item.kind == "image" and blob_store is not None and item.blob_sha:
            self._set_image_raster_fallback(blob_store.read(item.blob_sha))

    def _own_clipboard_verbatim(
        self, mimes: Iterable[str], get_bytes: Callable[[str], bytes | None]
    ) -> bool:
        """Take clipboard ownership and serve *mimes* byte-for-byte.

        Gtk.Clipboard.set_with_data() cannot be used here: GObject
        Introspection cannot bind its raw TargetEntry-array + callback
        signature, so PyGObject marks it ``_unsupported_data_method`` and
        calling it always raises AttributeError. Ownership is instead taken
        with the lower-level primitives GI *can* bind safely:
        Gtk.selection_add_target()/Gtk.selection_owner_set() plus the
        ``selection-get``/``selection-clear-event`` signals on a hidden
        Gtk.Invisible widget.

        Returns True once ownership is taken (bytes are then served lazily,
        on request, via *get_bytes*); False if ownership could not be taken.
        """
        mimes = list(mimes)
        if not mimes:
            return False

        owner = Gtk.Invisible()
        owner.realize()

        def on_selection_get(
            _widget: Gtk.Widget, sel_data: Gtk.SelectionData, _info: int, _time: int
        ) -> None:
            mime = sel_data.get_target().name()
            data = get_bytes(mime)
            if data is not None:
                sel_data.set(sel_data.get_target(), 8, data)

        def on_selection_clear(_widget: Gtk.Widget, _event: Gdk.Event) -> bool:
            if self._owner_widget is owner:
                self._owner_widget = None
            return False

        owner.connect("selection-get", on_selection_get)
        owner.connect("selection-clear-event", on_selection_clear)
        for info, mime in enumerate(mimes):
            Gtk.selection_add_target(
                owner, Gdk.SELECTION_CLIPBOARD, Gdk.Atom.intern(mime, False), info
            )

        if not Gtk.selection_owner_set(owner, Gdk.SELECTION_CLIPBOARD, Gdk.CURRENT_TIME):
            log.debug("could not take clipboard ownership for verbatim replay")
            return False
        self._owner_widget = owner  # keep alive while we own the selection
        return True

    def _set_image_raster_fallback(self, data: bytes) -> None:
        """Put a single rasterized rep on the clipboard.

        Fidelity loss: every other representation (e.g. a vector original)
        is discarded — used only when clipboard ownership can't be taken at
        all via ``_own_clipboard_verbatim``.
        """
        try:
            loader = GdkPixbuf.PixbufLoader.new()
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            if pixbuf is not None:
                self._clipboard.set_image(pixbuf)
        except Exception as exc:
            log.debug(f"raster fallback failed: {exc}")

    # --- internal capture chain ---

    def _on_owner_change(self, _clipboard: Gtk.Clipboard, _event: Gdk.Event | None) -> None:
        if self._self_owned:
            self._self_owned = False
            return
        if self._config.ignore_enabled:
            return
        self._clipboard.request_targets(self._on_targets)

    def _on_targets(
        self, clipboard: Gtk.Clipboard, atoms: list[Gdk.Atom] | None, _data: object = None
    ) -> None:
        names = [atom.name() for atom in atoms] if atoms else []
        if filters.is_secret(names):
            log.debug("skipping clipboard entry marked as secret")
            return

        # Protocol-only atoms: never real payloads, always offered, never
        # worth requesting or counting towards "is there anything to grab".
        payload_names = [n for n in names if n not in _PROTOCOL_ATOMS]
        has_text = any(n in _TEXT_ATOMS for n in payload_names)
        image_mimes = [n for n in payload_names if n.startswith("image/")]

        # Only targets Funes has a *dedicated* presentation for (today:
        # images) should ever outrank plain text. Browsers, GTK text views
        # etc. routinely advertise extra incidental targets alongside plain
        # text (text/html, X-GTK-TEXT-BUFFER-RICH-TEXT, browser-internal
        # X-* atoms, ...) that Funes has no use for yet (that's the separate
        # "rich text support" TODO item) — grabbing those instead of the
        # plain text would both mislabel the row (shows the mime, not the
        # content) and break pasting (the real clipboard string is never
        # captured, so nothing is served back for it).
        if image_mimes and self._config.capture_images:
            self._capture_reps(clipboard, image_mimes, also_request_text=has_text)
        elif has_text:
            clipboard.request_text(self._on_text)
        elif payload_names and self._config.capture_images:
            # Nothing recognized *and* no text fallback either \u2014 capture
            # verbatim rather than silently dropping it (e.g. a pure file
            # manager copy with no text/plain fallback, or any other format
            # Funes doesn't specifically recognize).
            self._capture_reps(clipboard, payload_names, also_request_text=False)

    # --- multi-target capture chain ---
    #
    # Generic async request/cap/watchdog machinery, shared by every kind that
    # needs more than one clipboard target captured verbatim. What kind the
    # result becomes is decided *after* capture, by classify() in _finish —
    # not by which branch triggered this method — so a rep that gets dropped
    # for being oversized can never leave an item mislabeled.

    def _capture_reps(
        self,
        clipboard: Gtk.Clipboard,
        mimes: list[str],
        also_request_text: bool,
    ) -> None:
        """Fire request_contents() for every mime in *mimes* (plus text)
        concurrently, not sequentially, so one stalled/never-answered target
        can never block the others from being captured \u2014 request order no
        longer matters."""
        state: dict[str, object] = {
            "reps": {},  # mime → bytes
            "text": None,
            "pending": set(mimes),
            "pending_text": also_request_text,
            "finished": False,
        }

        def start_watchdog() -> None:
            state["watchdog_id"] = GLib.timeout_add(_CAPTURE_WATCHDOG_MS, on_watchdog)

        def cancel_watchdog() -> None:
            wid = state.pop("watchdog_id", None)
            if isinstance(wid, int) and wid:
                GLib.source_remove(wid)

        def on_watchdog() -> bool:
            # Fire _finish() directly with whatever was captured so far,
            # rather than just marking a flag: GTK/X11 give no guarantee a
            # request_contents() call ever gets a reply at all (not just a
            # slow one) if the source advertises a target it doesn't
            # actually serve. Without this, nothing still pending would ever
            # resolve and the chain would hang forever — nothing captured,
            # no signal emitted, no error — even for targets that had
            # already succeeded.
            log.debug("capture: watchdog fired, finishing with whatever was captured so far")
            _finish()
            return GLib.SOURCE_REMOVE

        def _maybe_finish() -> None:
            pending: set[str] = state["pending"]  # type: ignore[assignment]
            if not pending and not state["pending_text"]:
                _finish()

        def on_contents(_cb: Gtk.Clipboard, sel: Gtk.SelectionData, _data: object = None) -> None:
            if state["finished"]:
                # The watchdog already finished the chain; this is a late
                # reply for whatever target stalled past the deadline.
                return
            requested_mime = sel.get_target().name() if sel is not None else None
            pending: set[str] = state["pending"]  # type: ignore[assignment]
            pending.discard(requested_mime)
            data = sel.get_data() if sel is not None else None
            if data and requested_mime is not None:
                nbytes = len(data)
                if nbytes > self._config.max_image_bytes:
                    log.debug(
                        f"skipping oversized representation {requested_mime} ({nbytes} bytes)"
                    )
                else:
                    reps: dict[str, bytes] = state["reps"]  # type: ignore[assignment]
                    reps[requested_mime] = data
            _maybe_finish()

        def on_text(_cb: Gtk.Clipboard, text: str | None, _data: object = None) -> None:
            if not state["finished"]:
                state["text"] = text
            state["pending_text"] = False
            _maybe_finish()

        def _finish() -> None:
            if state["finished"]:
                return
            state["finished"] = True
            cancel_watchdog()
            reps: dict[str, bytes] = state["reps"]  # type: ignore[assignment]
            if not reps:
                # All reps were oversized or empty — discard.
                return
            canonical_mime = _pick_canonical(reps)
            canonical_bytes = reps[canonical_mime]
            content_hash = _sha256_hex(canonical_bytes)
            if content_hash == self._last_seen_hash:
                return
            self._last_seen_hash = content_hash

            # Heavy work (hashing already done above; pixbuf decode in worker).
            captured_text: str | None = state["text"]  # type: ignore[assignment]
            kind = classify(reps)
            capture = Capture(
                kind=kind,
                canonical_mime=canonical_mime,
                reps=reps,
                text=captured_text,
            )
            self.emit("captured", capture)

            if self._config.reown_clipboard:
                self._self_owned = True
                if not self._own_clipboard_verbatim(reps.keys(), reps.get):
                    # Rasterizing only makes sense for images; for "other"
                    # kinds (arbitrary binary data) there's no meaningful
                    # fallback, so just leave the original owner in place.
                    if kind == "image":
                        self._set_image_raster_fallback(canonical_bytes)
                    else:
                        self._self_owned = False

        for mime in mimes:
            atom = Gdk.Atom.intern(mime, False)
            clipboard.request_contents(atom, on_contents)
        if also_request_text:
            clipboard.request_text(on_text)
        start_watchdog()
        _maybe_finish()  # covers the (currently unreached) empty-mimes case

    # --- text capture ---

    def _on_text(self, _clipboard: Gtk.Clipboard, text: str | None, _data: object = None) -> None:
        self._handle_text(text)

    def _handle_text(self, text: str | None) -> None:
        if text is None or filters.is_blank(text):
            return
        if filters.is_too_big(text, self._config.max_item_bytes):
            log.debug("skipping oversized text clipboard entry")
            return

        def complain(pattern: str, error: re.error) -> None:
            log.warn(f"bad ignore regex /{pattern}/: {error}")

        matched = filters.matching_ignore_regex(
            text, self._config.ignore_regexes, on_bad_pattern=complain
        )
        if matched is not None:
            log.debug(f"ignoring entry matching /{matched}/")
            return

        content_hash = _sha256_hex(text.encode("utf-8"))
        if content_hash == self._last_seen_hash:
            return
        self._last_seen_hash = content_hash

        capture = Capture.from_text(text)
        self.emit("captured", capture)

        if self._config.reown_clipboard:
            self._self_owned = True
            self._clipboard.set_text(text, -1)


def _sha256_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
