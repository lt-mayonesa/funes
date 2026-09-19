"""Monitor placement policy for the popup.

GTK-free on purpose: the caller resolves the candidate monitors (focused
window / pointer / primary) and this module only decides which one wins, so
the ordering logic is unit-testable without an X server.

The order comes from the `popup-monitor-order` GSettings key, a user-sortable
list of the three strategies. Unknown or duplicated entries are dropped and
missing ones are appended in default order, so a hand-edited key can never
leave the popup without a placement rule.
"""

from collections.abc import Iterable, Mapping
from typing import TypeVar

FOCUSED = "focused"
POINTER = "pointer"
PRIMARY = "primary"

STRATEGIES: tuple[str, ...] = (FOCUSED, POINTER, PRIMARY)

# Fixes the reported bug: the monitor holding the window you were typing in
# wins over the one the pointer happens to rest on.
DEFAULT_ORDER: tuple[str, ...] = (FOCUSED, POINTER, PRIMARY)

T = TypeVar("T")


def normalize_order(values: Iterable[str] | None) -> list[str]:
    """Return a sane, complete strategy order from raw settings input."""
    order: list[str] = []
    for value in values or ():
        name = str(value).strip().lower()
        if name in STRATEGIES and name not in order:
            order.append(name)
    order.extend(name for name in DEFAULT_ORDER if name not in order)
    return order


def move(order: Iterable[str], name: str, delta: int) -> list[str]:
    """Return `order` with `name` shifted by `delta`, clamped to the ends."""
    result = normalize_order(order)
    if name not in result:
        return result
    index = result.index(name)
    target = max(0, min(len(result) - 1, index + delta))
    if target != index:
        result.insert(target, result.pop(index))
    return result


def pick(order: Iterable[str] | None, candidates: Mapping[str, T | None]) -> T | None:
    """First non-None candidate following the user's strategy order."""
    for name in normalize_order(order):
        candidate = candidates.get(name)
        if candidate is not None:
            return candidate
    return None
