"""Fuzzy search for clipboard history items.

Implements the fzy algorithm inline — no external dependencies.

fzy is a subsequence matcher with DP scoring that rewards:
  - contiguous matches (SCORE_MATCH_CONSECUTIVE)
  - matches at word boundaries (/, -, _, space, .)
  - matches at the start of a string

Reference: https://github.com/jhawthorn/fzy (C original)
           https://github.com/kazhala/pfzy (Python port, MIT)
"""

# ---------------------------------------------------------------------------
# Constants (ported from fzy / pfzy)
# ---------------------------------------------------------------------------
_SCORE_MIN = float("-inf")
_SCORE_GAP_LEADING = -0.005
_SCORE_GAP_TRAILING = -0.005
_SCORE_GAP_INNER = -0.01
_SCORE_MATCH_CONSECUTIVE = 1.0
_SCORE_MATCH_SLASH = 0.9
_SCORE_MATCH_WORD = 0.8
_SCORE_MATCH_CAPITAL = 0.7
_SCORE_MATCH_DOT = 0.6

_BONUS_MAP: dict[str, float] = {
    "/": _SCORE_MATCH_SLASH,
    "-": _SCORE_MATCH_WORD,
    "_": _SCORE_MATCH_WORD,
    " ": _SCORE_MATCH_WORD,
    ".": _SCORE_MATCH_DOT,
}


# ---------------------------------------------------------------------------
# Core fzy functions
# ---------------------------------------------------------------------------


def _bonus(haystack: str) -> list[float]:
    """Per-character bonus based on preceding character."""
    prev = "/"
    result = []
    for ch in haystack:
        if prev in _BONUS_MAP:
            result.append(_BONUS_MAP[prev])
        elif prev.islower() and ch.isupper():
            result.append(_SCORE_MATCH_CAPITAL)
        else:
            result.append(0.0)
        prev = ch
    return result


def _is_subsequence(needle: str, haystack: str) -> bool:
    """Return True if every char of needle appears in order in haystack."""
    needle = needle.lower()
    haystack = haystack.lower()
    offset = 0
    for ch in needle:
        offset = haystack.find(ch, offset)
        if offset < 0:
            return False
        offset += 1
    return True


def _fzy_compute(needle: str, haystack: str) -> tuple[float, list[int] | None]:
    """Run fzy DP and backtrack to find score + matched char indices.

    Returns:
        (score, indices) where indices is a list of haystack char positions
        that correspond to each needle char, or None if no match.
    """
    if not _is_subsequence(needle, haystack):
        return _SCORE_MIN, None

    n, m = len(needle), len(haystack)
    if n == 0:
        return float("inf"), []
    if n == m:
        return float("inf"), list(range(n))

    bonus = _bonus(haystack)
    cmp_haystack = haystack.lower() if needle.islower() else haystack

    running: list[list[float]] = [[0.0] * m for _ in range(n)]
    result: list[list[float]] = [[0.0] * m for _ in range(n)]

    for i in range(n):
        prev = _SCORE_MIN
        gap = _SCORE_GAP_TRAILING if i == n - 1 else _SCORE_GAP_INNER

        for j in range(m):
            if needle[i] == cmp_haystack[j]:
                score = _SCORE_MIN
                if i == 0:
                    score = j * _SCORE_GAP_LEADING + bonus[j]
                elif j != 0:
                    score = max(
                        result[i - 1][j - 1] + bonus[j],
                        running[i - 1][j - 1] + _SCORE_MATCH_CONSECUTIVE,
                    )
                running[i][j] = score
                result[i][j] = prev = max(score, prev + gap)
            else:
                running[i][j] = _SCORE_MIN
                result[i][j] = prev = prev + gap

    # Backtrack through the DP matrices to recover the optimal match positions.
    indices = [0] * n
    match_required = False
    j = m - 1
    for i in range(n - 1, -1, -1):
        while j >= 0:
            # A cell is chosen when it is a genuine match AND either we're
            # looking for a consecutive continuation or it equals the result.
            if (match_required or running[i][j] == result[i][j]) and running[i][j] != _SCORE_MIN:
                match_required = (
                    i > 0
                    and j > 0
                    and result[i][j] == running[i - 1][j - 1] + _SCORE_MATCH_CONSECUTIVE
                )
                indices[i] = j
                j -= 1
                break
            j -= 1

    return result[n - 1][m - 1], indices


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def match_indices(needle: str, haystack: str) -> list[int] | None:
    """Return optimal fzy match positions of needle chars inside haystack.

    Args:
        needle: Search query (case-insensitive when all-lowercase).
        haystack: Text to search in.

    Returns:
        List of haystack character indices (one per needle char) in ascending
        order, or None if needle is not a subsequence of haystack.

    Example:
        >>> match_indices("ghb", "https://github.com")
        [8, 9, 14]   # g, h, b positions inside the URL
    """
    needle = needle.strip()
    if not needle:
        return []
    _score, indices = _fzy_compute(needle, haystack)
    return indices  # None when no match


def filter_matches(haystack: list[str], needle: str) -> list[str]:
    """Filter haystack by fzy fuzzy match, preserving original order.

    Matches items where needle is a subsequence of the item text.
    This naturally handles:
      - typos handled as best-effort subsequence ('ghb' -> 'github')
      - partial matches anywhere in the string
      - case-insensitive matching when needle is lowercase

    Args:
        haystack: Items to filter (e.g. clipboard item text values).
        needle: Search query typed by the user.

    Returns:
        Matching items in their original order.
    """
    needle = needle.strip()
    if not needle or not haystack:
        return haystack

    return [item for item in haystack if _fzy_compute(needle, item)[0] > _SCORE_MIN]
