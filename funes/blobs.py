"""Content-addressed blob store for clipboard image payloads.

Blobs are keyed by the SHA-256 hex digest of their content and stored on disk
at ``$XDG_DATA_HOME/funes/blobs/<sha[:2]>/<sha>``.

Design principles
-----------------
- **GTK-free**: no gi.repository imports; pathlib + hashlib only.
- **Atomic writes**: tmpfile in the same directory, then os.replace() — no
  partially-written blobs are ever visible.
- **Strict permissions**: blob files are 0600, directories are 0700 so only
  the owner can read clipboard images.
- **Refcount-free deletion**: callers (store.py) handle the refcount check;
  this module is a pure content-addressed storage layer.
"""

import contextlib
import hashlib
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


class BlobStore:
    """Content-addressed, SHA-256-keyed binary blob storage."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)

    # --- public API ---

    def put(self, data: bytes) -> str:
        """Store *data* and return its SHA-256 hex digest.

        Idempotent: if the blob already exists the write is skipped and the
        digest is returned unchanged. Uses a tmpfile + os.replace() so a crash
        mid-write never leaves a partial file.
        """
        sha = hashlib.sha256(data).hexdigest()
        dest = self.path(sha)
        if dest.exists():
            return sha

        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Write to a temp file in the same directory so os.replace() is atomic
        # across the rename (same filesystem).
        fd, tmp = tempfile.mkstemp(dir=dest.parent)
        try:
            os.write(fd, data)
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        Path(tmp).replace(dest)
        return sha

    def path(self, sha: str) -> Path:
        """Return the filesystem path for *sha* (may not exist yet)."""
        return self._root / sha[:2] / sha

    def read(self, sha: str) -> bytes:
        """Read and return the blob for *sha*.

        Raises FileNotFoundError if the blob does not exist.
        """
        return self.path(sha).read_bytes()

    def delete(self, sha: str) -> None:
        """Delete the blob for *sha* if it exists (no-op otherwise)."""
        p = self.path(sha)
        with contextlib.suppress(FileNotFoundError):
            p.unlink()
        # Opportunistically remove the now-empty shard directory.
        with contextlib.suppress(OSError):
            p.parent.rmdir()

    def sweep(self, known: set[str]) -> int:
        """Delete any blobs whose SHA is not in *known*.

        Returns the number of orphan files removed. Called once at startup to
        recover from a previous crash that left blobs without metadata rows.
        """
        removed = 0
        if not self._root.is_dir():
            return 0
        for shard in self._root.iterdir():
            if not shard.is_dir() or len(shard.name) != 2:
                continue
            for blob in shard.iterdir():
                if blob.name not in known:
                    log.debug("sweep: removing orphan blob %s", blob.name[:16])
                    try:
                        blob.unlink()
                        removed += 1
                    except OSError as exc:
                        log.warning("sweep: could not remove %s: %s", blob, exc)
            with contextlib.suppress(OSError):
                shard.rmdir()
        return removed
