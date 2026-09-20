"""Image presentation helpers — thumbnails, probing, metadata labels.

Lives in ``app/`` because it imports GdkPixbuf (GTK subsystem, even though no
display is required for the headless PixbufLoader).

All functions are pure with respect to the rest of the application: they take
and return plain values so they can be unit-tested without a running GTK main
loop.
"""

import logging
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib

log = logging.getLogger(__name__)


def probe(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) by decoding *data* via PixbufLoader.

    Returns None if the data is not a recognized image format or decoding
    fails.
    """
    try:
        loader = GdkPixbuf.PixbufLoader.new()
        loader.write(data)
        loader.close()
        pixbuf = loader.get_pixbuf()
        if pixbuf is None:
            return None
        return pixbuf.get_width(), pixbuf.get_height()
    except Exception as exc:
        log.debug(f"probe failed: {exc}")
        return None


def thumbnail(
    sha: str,
    data: bytes,
    px: int,
    scale: int,
    thumb_root: Path,
) -> Path | None:
    """Return path to a pre-generated thumbnail PNG for *sha*.

    If the thumbnail does not exist yet it is generated from *data* and saved.
    The file lives at ``<thumb_root>/<sha>@<px>x<scale>.png``.
    Returns None if generation fails.

    The thumbnail is always a square crop scaled to ``px * scale`` pixels on
    each side (scale-factor-aware).
    """
    name = f"{sha}@{px}x{scale}.png"
    path = thumb_root / name
    if path.exists():
        return path

    try:
        thumb_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        loader = GdkPixbuf.PixbufLoader.new()
        loader.write(data)
        loader.close()
        pixbuf = loader.get_pixbuf()
        if pixbuf is None:
            return None

        target_h = px * scale
        # Scale preserving aspect ratio: constrain height only, width is free.
        w, h = pixbuf.get_width(), pixbuf.get_height()
        target_w = max(1, target_h * w // h) if h > 0 else target_h
        scaled = pixbuf.scale_simple(target_w, target_h, GdkPixbuf.InterpType.BILINEAR)
        if scaled is None:
            return None

        scaled.savev(str(path), "png", [], [])
        path.chmod(0o600)
        return path
    except Exception as exc:
        log.debug(f"thumbnail generation failed for {sha[:8]}: {exc}")
        return None


def meta_label(
    mime: str | None,
    width: int | None,
    height: int | None,
    nbytes: int,
) -> str:
    """Human-readable image metadata, e.g. ``PNG x 1920x1080 x 240 kB``."""
    parts: list[str] = []
    if mime:
        parts.append(mime.split("/")[-1].upper())
    if width and height:
        parts.append(f"{width}\u00d7{height}")
    if nbytes:
        parts.append(GLib.format_size(nbytes))
    return " \u00b7 ".join(parts) if parts else "Image"
