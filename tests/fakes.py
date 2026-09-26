"""Shared test doubles.

Not named `test_*` on purpose: `unittest discover` must import it, not run it.
"""

from typing import Any


class FakeGrab:
    """`app.grab.SeatGrab` stand-in: no X grab, so tests never freeze input."""

    def __init__(self, succeed: bool = True) -> None:
        self.succeed = succeed
        self.acquired = 0
        self.released = 0
        self._held = False

    @property
    def active(self) -> bool:
        return self._held

    def acquire(self, _window: Any) -> bool:
        self.acquired += 1
        self._held = self.succeed
        return self.succeed

    def release(self) -> None:
        self.released += 1
        self._held = False
