"""Assertions for cache-busted frontend assets.

Feature contract tests should require their minimum asset revision without
pinning the current revision, which changes with unrelated UI updates.
"""

import re


def asset_version_at_least(html: str, filename: str, minimum: str) -> bool:
    match = re.search(rf"/static/{re.escape(filename)}\?v=(\d+(?:\.\d+)*)", html)
    if not match:
        return False
    current = tuple(int(part) for part in match.group(1).split("."))
    floor = tuple(int(part) for part in minimum.split("."))
    return current >= floor
