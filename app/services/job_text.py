from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup


GENERIC_DESCRIPTIONS = {
    "apply", "apply now", "view job", "job details", "read more", "learn more",
    "הגש מועמדות", "לפרטי המשרה", "פרטים נוספים",
}


def clean_job_text(value: object) -> str:
    """Turn ATS HTML/escaped payloads into readable job text without UI noise."""
    raw = html.unescape(str(value or "")).replace("\\/", "/")
    raw = raw.replace("\\n", "\n").replace("\\r", "\n").replace("\\t", " ")
    soup = BeautifulSoup(raw, "html.parser")
    for node in soup.select("script,style,noscript,svg,form,nav,footer"):
        node.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]", "", text)
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip(" |")
        key = line.casefold().strip(" .:–—-")
        if not line or key in GENERIC_DESCRIPTIONS or key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return "\n".join(lines).strip()


def job_text_quality(value: object) -> str:
    text = clean_job_text(value)
    compact = " ".join(text.split()).strip()
    if not compact or compact.casefold().strip(" .:–—-") in GENERIC_DESCRIPTIONS:
        return "missing"
    if len(compact) < 40 or re.fullmatch(r"[0-9a-f -]{24,}", compact, re.I):
        return "partial"
    letters = sum(character.isalpha() for character in compact)
    if letters / max(1, len(compact)) < .35:
        return "partial"
    return "complete"
