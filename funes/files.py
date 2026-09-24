"""Parsing helpers for clipboard file-copy/cut formats.

Two targets file managers put on the clipboard for a file copy or cut:

- ``text/uri-list`` (RFC 2483): CRLF-separated URIs, lines starting with
  ``#`` are comments. Cross-desktop; carries no cut-vs-copy information.
- ``x-special/gnome-copied-files`` (Nemo/Nautilus/GNOME Files): first line
  is the operation (``"copy"`` or ``"cut"``), followed by one URI per line
  (LF-separated). GTK-specific, but that's exactly what this project targets
  (Mint/Cinnamon, per AGENTS.md).

KDE's ``application/x-kde-cutselection`` is deliberately not parsed here —
no KDE application was available to verify the format against in this
environment. See ``docs/design/CLIPBOARD.md`` for the rollout notes.

Pure functions, no GTK dependency, so they're unit-testable without a
display.
"""

from urllib.parse import unquote, urlparse


def parse_uri_list(data: bytes) -> list[str]:
    """Return the URIs in a ``text/uri-list`` payload.

    Comments (lines starting with ``#``) and blank lines are dropped, per
    RFC 2483. Both CRLF and bare-LF line endings are accepted since not
    every clipboard owner follows the RFC strictly.
    """
    text = data.decode("utf-8", errors="replace")
    uris = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        uris.append(stripped)
    return uris


def parse_gnome_copied_files(data: bytes) -> tuple[str, list[str]]:
    """Return ``(operation, uris)`` from an ``x-special/gnome-copied-files``
    payload.

    *operation* is ``"cut"`` or ``"copy"`` — ``"copy"`` is the fallback for
    anything unrecognized on the first line, since a wrongly-shown cut icon
    on an ordinary copy would be more surprising/risky-looking than the
    reverse.
    """
    text = data.decode("utf-8", errors="replace")
    lines = [line for line in text.split("\n") if line]
    if not lines:
        return "copy", []
    operation = lines[0].strip().lower()
    if operation not in ("cut", "copy"):
        operation = "copy"
    return operation, lines[1:]


def uri_to_filename(uri: str) -> str:
    """Best-effort display name for *uri*: the percent-decoded basename of
    a ``file://`` URI's path. Falls back to the raw URI for anything else
    (e.g. an ``http://`` URL some app also put on the uri-list)."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return uri
    path = unquote(parsed.path)
    return path.rsplit("/", 1)[-1] or path
