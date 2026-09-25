"""One shared title-level filter for UI visibility and pre-scoring eligibility."""
import re
from sqlalchemy import and_, case, literal
from ..utils import loads

SENIORITY_LEVELS = {
    "student": {"student", "intern", "internship", "סטודנט"},
    "entry level": {"entry level", "entry-level", "graduate", "new grad", "בוגר", "ללא ניסיון"},
    "junior": {"junior", "jr", "ג׳וניור"},
    "mid level": {"mid level", "mid-level", "intermediate"},
    "senior": {"senior", "sr", "סניור"},
    "lead": {"lead", "team lead", "technical lead", "ראש צוות"},
    "staff": {"staff", "principal", "architect"},
    "manager": {"manager", "director", "מנהל"},
}
LEVELS = (*SENIORITY_LEVELS, "unknown")
# Resolve multiple explicit labels consistently; managerial roles take precedence.
PRIORITY = ("manager", "staff", "lead", "senior", "mid level", "junior", "entry level", "student")
PATTERNS = {level: r"(^|[^\w])(" + "|".join(re.escape(term) for term in sorted(terms)) + r")([^\w]|$)"
            for level, terms in SENIORITY_LEVELS.items()}
PROFESSION_MANAGERS = r"(^|[^\w])(project manager|product manager|program manager)([^\w]|$)"


def detect_title_level(title):
    lowered = str(title or "").lower()
    for level in PRIORITY:
        if re.search(PATTERNS[level], lowered):
            if level == "manager" and re.search(PROFESSION_MANAGERS, lowered):
                continue
            return level
    return "unknown"


def selected_seniority_levels(profile, excluded_keywords=None):
    raw = getattr(profile, "seniority_levels_json", "") or ""
    if raw:
        return [level for level in loads(raw, []) if level in LEVELS]
    positive = set(loads(getattr(profile, "keywords_json", "[]"), [])) & set(LEVELS)
    negative = set(excluded_keywords if excluded_keywords is not None else loads(getattr(profile, "excluded_keywords_json", "[]"), [])) & set(LEVELS)
    # Preserve unknown titles for legacy profiles; the new explicit choice can
    # switch them off independently without guessing a level from missing text.
    selected = (positive | {"unknown"}) if positive else set(LEVELS)
    return [level for level in LEVELS if level in selected - negative]


def seniority_visibility_condition(profile, title):
    if profile is None:
        return literal(True)
    from sqlalchemy import func
    lowered = func.lower(title)
    clauses = []
    for level in PRIORITY:
        matches = lowered.regexp_match(PATTERNS[level])
        if level == "manager":
            matches = and_(matches, ~lowered.regexp_match(PROFESSION_MANAGERS))
        clauses.append((matches, level))
    return case(*clauses, else_="unknown").in_(selected_seniority_levels(profile))
