"""OCR helper for extracting text from clipboard images.

Uses Tesseract (``tesseract`` CLI) when available. Operations run in a
serialized worker thread so a burst of screenshots does not spawn N
``tesseract`` processes simultaneously.

Privacy note: recognized text is stored in plain text inside ``history.db``
alongside the image metadata. This is on by default when the binary is
installed; users can opt out via the ``ocr-enabled`` preference.
"""

import logging
import queue
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Tesseract timeout per image (seconds).
_TIMEOUT = 20


@dataclass
class _Job:
    path: Path
    callback: Callable[[str], None]


class _StopSentinel:
    pass


# Sentinel to shut down the worker thread cleanly.
_STOP = _StopSentinel()


def available() -> bool:
    """Return True if the ``tesseract`` binary is on PATH."""
    return shutil.which("tesseract") is not None


def recognize(path: Path) -> str:
    """Run ``tesseract`` on *path* and return the recognized text.

    Uses ``subprocess.run`` without ``shell=True`` (bandit-clean).
    Strips trailing whitespace from the output.

    Raises subprocess.SubprocessError / TimeoutExpired on failure.
    """
    result = subprocess.run(
        ["tesseract", str(path), "-", "-l", "eng"],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Serialized worker
# ---------------------------------------------------------------------------


class OCRWorker:
    """Single background thread that processes OCR jobs one at a time.

    This prevents a burst of copied screenshots from spawning N concurrent
    tesseract processes.

    Usage::

        worker = OCRWorker()
        worker.start()
        worker.enqueue(image_path, on_result)  # on_result called on main thread
        worker.stop()
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[object] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="ocr-worker")
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def enqueue(self, path: Path, callback: Callable[[str], None]) -> None:
        """Schedule OCR of *path*; invoke *callback(text)* on the GLib main loop."""
        self._queue.put(_Job(path, callback))

    def _run(self) -> None:
        while True:
            raw = self._queue.get()
            if isinstance(raw, _StopSentinel):
                break
            assert isinstance(raw, _Job)
            try:
                text = recognize(raw.path)
            except Exception as exc:
                log.debug(f"OCR failed for {raw.path.name}: {exc}")
                text = ""
            if text:
                # Deliver on the GLib main loop.
                try:
                    from gi.repository import GLib

                    GLib.idle_add(raw.callback, text)
                except Exception as exc:
                    log.debug(f"OCR GLib delivery failed: {exc}")
