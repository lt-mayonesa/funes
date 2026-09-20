"""Content-addressed blob storage for clipboard payloads (images, etc).

Blobs are stored under $XDG_DATA_HOME/funes/blobs, sharded by hash prefix
(2-char) for filesystem efficiency. Each blob is written atomically via
tempfile + os.replace with 0600 permissions. Orphan sweep at startup reclaims
unreferenced blobs.
"""

import contextlib
import hashlib
import tempfile
from pathlib import Path

from gi.repository import GLib


def default_root() -> str:
    return str(Path(GLib.get_user_data_dir()) / "funes" / "blobs")


class BlobStore:
    """Content-addressed blob storage, keyed by sha256 hex of bytes."""

    def __init__(self, root: str | None = None) -> None:
        self._root = Path(root if root is not None else default_root())
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def put(self, data: bytes) -> str:
        """Write data to the store. Return sha256 hex.

        Raises: OSError on write failure.
        """
        sha = hashlib.sha256(data).hexdigest()
        target = self._path(sha)

        # Quick check: blob already exists.
        if target.exists():
            return sha

        # Write atomically: tempfile in the target shard dir, then rename.
        shard = target.parent
        shard.mkdir(mode=0o700, parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(dir=shard, mode="wb", delete=False, prefix=".tmp-") as tmp:
            try:
                tmp.write(data)
                tmp.flush()
                # Ensure valid FD
                tmp.file.fileno()
            except OSError as e:
                Path(tmp.name).unlink(missing_ok=True)
                raise e

        # Rename is atomic on POSIX. If the target appeared (race), it's fine.
        try:
            Path(tmp.name).chmod(0o600)
            Path(tmp.name).replace(target)
        except OSError:
            Path(tmp.name).unlink(missing_ok=True)
            raise

        return sha

    def _path(self, sha: str) -> Path:
        """Internal: full path for a sha (no existence check)."""
        if not sha or len(sha) < 2:
            raise ValueError(f"invalid sha: {sha!r}")
        return self._root / sha[:2] / sha

    def path(self, sha: str) -> Path:
        """Return the Path for a blob by sha, if it exists."""
        target = self._path(sha)
        if not target.exists():
            raise FileNotFoundError(f"blob not found: {sha}")
        return target

    def read(self, sha: str) -> bytes:
        """Read blob by sha. Raises FileNotFoundError if not present."""
        return self.path(sha).read_bytes()

    def delete(self, sha: str) -> None:
        """Delete a blob by sha. Idempotent (no error if missing)."""
        with contextlib.suppress(FileNotFoundError):
            self._path(sha).unlink()

    def sweep(self, known: set[str]) -> int:
        """Delete all blobs not in the known set. Return count deleted."""
        count = 0
        with contextlib.suppress(OSError, FileNotFoundError):
            for shard_dir in self._root.iterdir():
                if not shard_dir.is_dir():
                    continue
                for blob_path in shard_dir.iterdir():
                    if blob_path.is_file():
                        sha = blob_path.name
                        if sha not in known:
                            blob_path.unlink()
                            count += 1
                # Clean up empty shard dirs.
                with contextlib.suppress(OSError):
                    shard_dir.rmdir()
        return count
