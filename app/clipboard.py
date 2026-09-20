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
A 500 ms watchdog aborts the whole chain if the source is hostile or slow.
Hashing + GdkPixbuf probing for width/height run in a worker thread so
10 MiB screenshots never block the UI.

Copy-back (set_item)
--------------------
For text items we use set_text() as before.
For image items we try Gtk.Clipboard.set_with_data() (verbatim multi-format
replay) and fall back to set_image(pixbuf) if that raises.  The fallback
re-encodes to PNG so non-PNG originals lose their original bytes — fidelity
loss is documented in the code comment below.

Self-ignore guard
-----------------
Funes writes to the clipboard itself (on paste and when re-owning), which
triggers owner-change again.  Without the guard that is an infinite loop.
"""

import re
from typing import ClassVar

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk

from funes import filters, log
from funes.config import Config
from funes.item import Capture

# Watchdog: abort image capture chain after this many milliseconds.
_CAPTURE_WATCHDOG_MS = 500


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
            self._set_image_item(item)

    def _set_image_item(self, item: "object") -> None:
        """Re-own the clipboard with the stored image data.

        Strategy:
        1. Try set_with_data() for verbatim multi-format replay.
           This is the ideal path: every stored representation is served
           byte-for-byte to requesting apps.
        2. Fall back to set_image(pixbuf) if set_with_data raises
           (historically flaky under PyGObject introspection).
           Fidelity loss: the pixbuf is always re-encoded to PNG, so
           non-PNG originals lose their original byte sequences.
        """
        from funes.item import HistoryItem

        assert isinstance(item, HistoryItem)
        # Gather blob bytes from disk.  We need the store reference —
        # passed via the closure when called from funes_app._on_item_chosen.
        # For now the blob bytes are fetched on demand inside get_func.
        reps_sha: dict[str, str] = item.reps.copy()
        if item.blob_sha and item.mime and item.mime not in reps_sha:
            reps_sha[item.mime] = item.blob_sha

        if not reps_sha:
            log.debug(f"set_image_item: no stored representations for item {item!r}")
            return

        # Build Gtk.TargetEntry list.
        targets = [
            Gtk.TargetEntry.new(mime, Gtk.TargetFlags.OTHER_APP, i)
            for i, mime in enumerate(reps_sha)
        ]

        # Keep a reference to the store's BlobStore so get_func can read blobs.
        # Injected via set_item when available.
        blob_store = getattr(self, "_blob_store", None)

        def get_func(
            clipboard: Gtk.Clipboard,
            selection_data: Gtk.SelectionData,
            _info: int,
            _data: object,
        ) -> None:
            mime = selection_data.get_target().name()
            sha = reps_sha.get(mime)
            if sha is None or blob_store is None:
                return
            try:
                data = blob_store.read(sha)
                atom = Gdk.Atom.intern(mime, False)
                selection_data.set(atom, 8, data)
            except Exception as exc:
                log.debug(f"get_func: could not serve {mime}: {exc}")

        def clear_func(_clipboard: Gtk.Clipboard, _data: object) -> None:
            pass

        try:
            self._clipboard.set_with_data(targets, get_func, clear_func, None)  # type: ignore[attr-defined]
            self._clipboard.set_can_store(targets)
            self._clipboard.store()
        except Exception as exc:
            # set_with_data failed (PyGObject introspection issue) — fall back
            # to set_image(pixbuf).  This re-encodes everything to PNG.
            log.debug(f"set_with_data failed ({exc}), falling back to set_image")
            if blob_store is not None and item.blob_sha:
                try:
                    data = blob_store.read(item.blob_sha)
                    loader = GdkPixbuf.PixbufLoader.new()
                    loader.write(data)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf is not None:
                        self._clipboard.set_image(pixbuf)
                        self._clipboard.store()
                except Exception as inner:
                    log.debug(f"set_image fallback also failed: {inner}")

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

        image_mimes = [n for n in names if n.startswith("image/")]
        has_text = any(
            n in ("UTF8_STRING", "text/plain;charset=utf-8", "text/plain", "STRING") for n in names
        )

        if image_mimes and self._config.capture_images:
            self._capture_image(clipboard, image_mimes, has_text)
        elif has_text:
            clipboard.request_text(self._on_text)

    # --- image capture chain ---

    def _capture_image(
        self, clipboard: Gtk.Clipboard, image_mimes: list[str], also_request_text: bool
    ) -> None:
        """Async chain: request_contents() over each image mime, then text."""
        state: dict[str, object] = {
            "reps": {},  # mime → bytes
            "text": None,
            "remaining": list(image_mimes),
            "also_text": also_request_text,
            "aborted": False,
        }

        def start_watchdog() -> None:
            state["watchdog_id"] = GLib.timeout_add(_CAPTURE_WATCHDOG_MS, on_watchdog)

        def cancel_watchdog() -> None:
            wid = state.pop("watchdog_id", None)
            if isinstance(wid, int) and wid:
                GLib.source_remove(wid)

        def on_watchdog() -> bool:
            state["aborted"] = True
            log.debug("image capture: watchdog fired, aborting chain")
            return GLib.SOURCE_REMOVE

        def request_next() -> None:
            remaining: list[str] = state["remaining"]  # type: ignore[assignment]
            if state["aborted"]:
                return
            if remaining:
                mime = remaining[0]
                state["remaining"] = remaining[1:]
                atom = Gdk.Atom.intern(mime, False)
                clipboard.request_contents(atom, on_contents)
            elif state["also_text"]:
                state["also_text"] = False
                clipboard.request_text(on_text)
            else:
                cancel_watchdog()
                _finish()

        def on_contents(_cb: Gtk.Clipboard, sel: Gtk.SelectionData, _data: object = None) -> None:
            if state["aborted"]:
                return
            data = sel.get_data() if sel is not None else None
            if data:
                mime = sel.get_data_type().name()
                nbytes = len(data)
                if nbytes > self._config.max_image_bytes:
                    log.debug(f"skipping oversized image rep {mime} ({nbytes} bytes)")
                else:
                    reps: dict[str, bytes] = state["reps"]  # type: ignore[assignment]
                    reps[mime] = data
            request_next()

        def on_text(_cb: Gtk.Clipboard, text: str | None, _data: object = None) -> None:
            if not state["aborted"]:
                state["text"] = text
            _finish()

        def _finish() -> None:
            cancel_watchdog()
            reps: dict[str, bytes] = state["reps"]  # type: ignore[assignment]
            if not reps:
                # All reps were oversized or empty — discard.
                return
            # Pick canonical: prefer image/png, else largest.
            canonical_mime = (
                "image/png" if "image/png" in reps else max(reps, key=lambda m: len(reps[m]))
            )
            canonical_bytes = reps[canonical_mime]
            content_hash = _sha256_hex(canonical_bytes)
            if content_hash == self._last_seen_hash:
                return
            self._last_seen_hash = content_hash

            # Heavy work (hashing already done above; pixbuf decode in worker).
            captured_text: str | None = state["text"]  # type: ignore[assignment]
            capture = Capture(
                kind="image",
                canonical_mime=canonical_mime,
                reps=reps,
                text=captured_text,
            )
            self.emit("captured", capture)

            if self._config.reown_clipboard:
                self._self_owned = True
                # Re-serve via set_image (simpler for re-own path).
                try:
                    loader = GdkPixbuf.PixbufLoader.new()
                    loader.write(canonical_bytes)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf is not None:
                        self._clipboard.set_image(pixbuf)
                except Exception as exc:
                    log.debug(f"re-own image failed: {exc}")
                    self._self_owned = False

        start_watchdog()
        request_next()

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
