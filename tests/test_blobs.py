"""Tests for blob storage."""

import tempfile
from pathlib import Path

import pytest

from funes.blobs import BlobStore


@pytest.fixture
def tmpdir_blob() -> Path:
    """Create a temporary blob store directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_put_and_read(tmpdir_blob: Path) -> None:
    """Test storing and reading blobs."""
    store = BlobStore(str(tmpdir_blob))
    data = b"hello world"

    sha = store.put(data)
    assert len(sha) == 64  # sha256 hex

    read_back = store.read(sha)
    assert read_back == data


def test_put_idempotent(tmpdir_blob: Path) -> None:
    """Storing the same data twice returns the same sha."""
    store = BlobStore(str(tmpdir_blob))
    data = b"test data"

    sha1 = store.put(data)
    sha2 = store.put(data)
    assert sha1 == sha2


def test_put_different_data(tmpdir_blob: Path) -> None:
    """Different data produces different shas."""
    store = BlobStore(str(tmpdir_blob))

    sha1 = store.put(b"data1")
    sha2 = store.put(b"data2")
    assert sha1 != sha2


def test_delete(tmpdir_blob: Path) -> None:
    """Delete removes a blob."""
    store = BlobStore(str(tmpdir_blob))
    sha = store.put(b"delete me")

    assert store.path(sha).exists()
    store.delete(sha)
    with pytest.raises(FileNotFoundError):
        store.path(sha)


def test_delete_idempotent(tmpdir_blob: Path) -> None:
    """Deleting a non-existent blob doesn't error."""
    store = BlobStore(str(tmpdir_blob))
    store.delete("nonexistent")  # Should not raise


def test_permissions(tmpdir_blob: Path) -> None:
    """Blobs are created with 0600 permissions."""
    store = BlobStore(str(tmpdir_blob))
    sha = store.put(b"secure data")

    path = store.path(sha)
    # Check file permissions.
    perms = path.stat().st_mode & 0o777
    assert perms == 0o600, f"Expected 0o600, got {oct(perms)}"


def test_sweep(tmpdir_blob: Path) -> None:
    """Sweep deletes unreferenced blobs."""
    store = BlobStore(str(tmpdir_blob))

    sha1 = store.put(b"keep this")
    sha2 = store.put(b"delete this")
    sha3 = store.put(b"also keep")

    deleted = store.sweep({sha1, sha3})
    assert deleted == 1

    # sha1 and sha3 should exist.
    assert store.path(sha1).exists()
    assert store.path(sha3).exists()

    # sha2 should be gone.
    with pytest.raises(FileNotFoundError):
        store.path(sha2)


def test_sweep_empty_set(tmpdir_blob: Path) -> None:
    """Sweep with empty set deletes everything."""
    store = BlobStore(str(tmpdir_blob))

    sha1 = store.put(b"data1")
    sha2 = store.put(b"data2")

    deleted = store.sweep(set())
    assert deleted == 2

    with pytest.raises(FileNotFoundError):
        store.path(sha1)
    with pytest.raises(FileNotFoundError):
        store.path(sha2)


def test_sharding(tmpdir_blob: Path) -> None:
    """Blobs are sharded by 2-char prefix."""
    store = BlobStore(str(tmpdir_blob))

    sha = store.put(b"test")
    path = store.path(sha)

    # Path should be blobs/<sha[:2]>/<sha>.
    assert path.parent.name == sha[:2]
    assert path.name == sha


def test_large_blob(tmpdir_blob: Path) -> None:
    """Test storing a large blob (10 MB)."""
    store = BlobStore(str(tmpdir_blob))
    large_data = b"x" * (10 * 1024 * 1024)

    sha = store.put(large_data)
    read_back = store.read(sha)
    assert read_back == large_data
    assert len(read_back) == 10 * 1024 * 1024
