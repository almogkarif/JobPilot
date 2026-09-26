"""Validate public Ashby board identifiers without making network requests."""
from __future__ import annotations

import re
from urllib.parse import urlsplit


def normalize_ashby_identifier(value: str) -> str:
    value = str(value or "").strip()
    if "://" in value:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc != "jobs.ashbyhq.com"
                or len(parsed.path.strip("/").split("/")) != 1):
            raise ValueError("Ashby requires a board name or https://jobs.ashbyhq.com/<board>; "
                             "an employer careers URL is not an Ashby board")
        value = parsed.path.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}", value):
        raise ValueError("Invalid Ashby board name")
    return value
