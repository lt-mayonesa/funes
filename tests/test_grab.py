"""Tests for the seat-grab seam (`app/grab.py`) with a fake seat.

No display needed: `SeatGrab` takes the seat as a constructor argument, so the
retry/give-up/release logic is exercised without touching X.
"""

import sys
import unittest
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "app"))

from grab import GRAB_SUCCESS, SeatGrab  # noqa: E402

GRAB_FAILED = 1  # Gdk.GrabStatus.ALREADY_GRABBED


class FakeSeat:
    """Fails the first `failures` grabs, then succeeds."""

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.grabs: list[Any] = []
        self.ungrabs = 0

    def grab(self, window: Any, *_args: Any) -> int:
        self.grabs.append(window)
        if self.failures > 0:
            self.failures -= 1
            return GRAB_FAILED
        return GRAB_SUCCESS

    def ungrab(self) -> None:
        self.ungrabs += 1


class SeatGrabTests(unittest.TestCase):
    def test_successful_grab_is_active(self) -> None:
        seat = FakeSeat()
        grab = SeatGrab(seat)
        self.assertFalse(grab.active)
        self.assertTrue(grab.acquire(object()))
        self.assertTrue(grab.active)
        self.assertEqual(len(seat.grabs), 1)

    def test_grab_is_retried_until_it_lands(self) -> None:
        """The WM's own keybinding grab can still hold the keyboard at map time."""
        seat = FakeSeat(failures=2)
        grab = SeatGrab(seat, timeout_ms=200)
        self.assertTrue(grab.acquire(object()))
        self.assertEqual(len(seat.grabs), 3)

    def test_grab_gives_up_after_the_timeout(self) -> None:
        seat = FakeSeat(failures=10_000)
        grab = SeatGrab(seat, timeout_ms=30)
        self.assertFalse(grab.acquire(object()))
        self.assertFalse(grab.active)

    def test_acquire_without_a_window_fails(self) -> None:
        seat = FakeSeat()
        self.assertFalse(SeatGrab(seat).acquire(None))
        self.assertEqual(seat.grabs, [])

    def test_second_acquire_does_not_regrab(self) -> None:
        seat = FakeSeat()
        grab = SeatGrab(seat)
        grab.acquire(object())
        grab.acquire(object())
        self.assertEqual(len(seat.grabs), 1)

    def test_release_ungrabs_once(self) -> None:
        seat = FakeSeat()
        grab = SeatGrab(seat)
        grab.acquire(object())
        grab.release()
        grab.release()
        self.assertFalse(grab.active)
        self.assertEqual(seat.ungrabs, 1)

    def test_release_without_a_grab_is_a_no_op(self) -> None:
        seat = FakeSeat()
        SeatGrab(seat).release()
        self.assertEqual(seat.ungrabs, 0)


if __name__ == "__main__":
    unittest.main()
