from __future__ import annotations

import re

from ..matching import SENIORITY_LEVELS, extract_experience

SENIORITY_ORDER = {"student": 0, "entry level": 1, "junior": 2, "mid level": 3, "senior": 4, "lead": 5, "staff": 6, "manager": 6}


def parse_experience(job) -> tuple[float | None, float | None]:
    return extract_experience(f"{getattr(job, 'title', '')} {getattr(job, 'description', '')}")


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
