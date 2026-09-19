"""Fuzzy search for clipboard history items.

Uses fzy algorithm (FZF-style): character-by-character matching with scoring
that prefers contiguous matches. Driven by pfzy (Python port of fzy).

Reference: https://github.com/kazhala/pfzy
"""

import asyncio


async def _fuzzy_match_async(query: str, items: list[str]) -> set[str]:
    """Async fuzzy match using pfzy (fzy algorithm).

    Returns set of matched items. Case-insensitive.
    """
    try:
        from pfzy import fuzzy_match

        # Create a mapping of lowercase items to original items
        lower_to_original = {item.lower(): item for item in items}
        lowercase_items = list(lower_to_original.keys())

        # Perform fuzzy match on lowercase versions
        results = await fuzzy_match(query.lower(), lowercase_items)

        # Map matched lowercase items back to originals
        matched_lowers = {r["value"] for r in results}
        return {lower_to_original[lower] for lower in matched_lowers}
    except ImportError:
        # Fallback: simple substring match
        query_lower = query.lower()
        return {item for item in items if query_lower in item.lower()}


def filter_matches(haystack: list[str], needle: str) -> list[str]:
    """Filter haystack by fuzzy match, preserving order.

    Args:
        haystack: Items to filter (e.g., item.text values)
        needle: Search query (case-insensitive)

    Returns:
        List of matching items in original order.
    """
    if not needle.strip() or not haystack:
        return haystack

    matched = asyncio.run(_fuzzy_match_async(needle.strip(), haystack))
    # Preserve original order
    return [item for item in haystack if item in matched]
