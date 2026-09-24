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

# Widest a thumbnail may get, expressed as a multiple of the row height.
# Panoramic screenshots would otherwise push the popup window wider than
# ``popup-width`` (issue #14).
MAX_ASPECT = 4


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

    The thumbnail preserves the aspect ratio and is scaled to fit inside a
    ``(px * scale * MAX_ASPECT) x (px * scale)`` box (scale-factor-aware), so
    very wide images end up shorter than the row instead of unboundedly wide.
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

        box_h = px * scale
        box_w = box_h * MAX_ASPECT
        w, h = pixbuf.get_width(), pixbuf.get_height()
        target_w, target_h = fit_box(w, h, box_w, box_h)
        scaled = pixbuf.scale_simple(target_w, target_h, GdkPixbuf.InterpType.BILINEAR)
        if scaled is None:
            return None

        scaled.savev(str(path), "png", [], [])
        path.chmod(0o600)
        return path
    except Exception as exc:
        log.debug(f"thumbnail generation failed for {sha[:8]}: {exc}")
        return None


def fit_box(
    width: int,
    height: int,
    box_w: int,
    box_h: int,
) -> tuple[int, int]:
    """Scale ``width x height`` to fit inside ``box_w x box_h``, aspect kept.

    Images taller than they are wide are height-bound; wide ones are width-
    bound and come out shorter than ``box_h``.  Never upscales beyond the box,
    never returns a zero dimension.
    """
    if width <= 0 or height <= 0:
        return max(1, box_h), max(1, box_h)
    target_h = box_h
    target_w = max(1, round(target_h * width / height))
    if target_w > box_w:
        target_w = box_w
        target_h = max(1, round(target_w * height / width))
    return max(1, target_w), max(1, target_h)


def meta_label(
    mime: str | None,
    width: int | None,
    height: int | None,
    nbytes: int,
    fallback: str = "Image",
) -> str:
    """Human-readable metadata, e.g. ``PNG x 1920x1080 x 240 kB``.

    *fallback* is returned when there's nothing to show at all (no mime, no
    dimensions, no size) \u2014 callers pass a kind-appropriate default (e.g.
    "Unsupported format" for the generic 'other' row).
    """
    from funes.item import mime_subtype_label

    parts: list[str] = []
    if mime:
        parts.append(mime_subtype_label(mime))
    if width and height:
        parts.append(f"{width}\u00d7{height}")
    if nbytes:
        parts.append(GLib.format_size(nbytes))
    return " \u00b7 ".join(parts) if parts else fallback
