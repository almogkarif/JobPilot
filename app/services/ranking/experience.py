from __future__ import annotations

import math
import re

from ...utils import loads
from ..matching import SENIORITY_LEVELS, extract_experience

SENIORITY_ORDER = {"student": 0, "entry level": 1, "junior": 2, "mid level": 3, "senior": 4, "lead": 5, "staff": 6, "manager": 6}


def parse_experience(job) -> tuple[float | None, float | None]:
    return extract_experience(f"{getattr(job, 'title', '')} {getattr(job, 'description', '')}")




def profile_experience_options(profile) -> set[str]:
    allowed = {"0", "1", "2", "3", "4", "5+"}
    values = loads(getattr(profile, "years_experience_options_json", "[]"), [])
    return {str(value).strip() for value in values if str(value).strip() in allowed}


def experience_requirement_buckets(minimum: float | None, maximum: float | None) -> set[str]:
    """Map a posting's requirement to the same buckets exposed in the profile UI.

    Ranges overlap every selectable bucket they cover. Open-ended requirements
    (for example 3+ years) cover 3, 4 and 5+. This lets the user's explicit
    multi-selection act as the hard experience filter instead of silently reducing
    it to only the highest selected number.
    """
    if minimum is None:
        return set()
    start = max(0, int(math.ceil(float(minimum))))
    if maximum is None:
        buckets = {str(value) for value in range(start, 5) if value <= 4}
        buckets.add("5+")
        return buckets
    end = max(start, int(math.floor(float(maximum))))
    buckets = {str(value) for value in range(start, min(end, 4) + 1)}
    if end >= 5:
        buckets.add("5+")
    return buckets


def detect_seniority(title: str) -> str | None:
    lowered = str(title or "").casefold()
    matches = [level for level, terms in SENIORITY_LEVELS.items() if any(term in lowered for term in terms)]
    # “Project/Product/Program Manager” names a profession, not necessarily a
    # people-management seniority band. Treat it as unknown unless another
    # explicit level (senior/lead/etc.) is present.
    if "manager" in matches and any(value in lowered for value in ("project manager", "product manager", "program manager")):
        matches.remove("manager")
    return max(matches, key=lambda value: SENIORITY_ORDER[value]) if matches else None


def profile_seniority(years: float) -> str:
    if years < 1:
        return "entry level"
    if years < 3:
        return "junior"
    if years < 5:
        return "mid level"
    return "senior"


def employment_type(job) -> str | None:
    text = f"{getattr(job, 'title', '')} {getattr(job, 'description', '')}".casefold()
    mappings = {
        "student": ("student", "סטודנט"),
        "internship": ("internship", "intern ", "מתמחה"),
        "part_time": ("part-time", "part time", "משרה חלקית"),
        "temporary": ("temporary", "temp.", "contract", "משרה זמנית", 'החלפה לחל"ד', "החלפה לחלד"),
        "full_time": ("full-time", "full time", "משרה מלאה"),
    }
    for key, variants in mappings.items():
        if any(value in text for value in variants):
            return key
    return None
