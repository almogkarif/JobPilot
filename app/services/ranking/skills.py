from __future__ import annotations

import re

from ..matching import KNOWN_SKILLS, _contains_variant, extract_skills
from ..job_requirements import iter_requirement_clauses

REQUIRED_MARKERS = (
    "required", "must", "mandatory", "requirement", "at least", "minimum",
    "חובה", "נדרש", "נדרשת", "נדרשים", "דרישות", "לפחות", "ניסיון מוכח",
)
PREFERRED_MARKERS = ("preferred", "advantage", "nice to have", "יתרון", "עדיפות")

# Some requirement bullets contain a mandatory core plus a narrower preferred
# qualifier, for example: "Experience with Embedded platforms, preference for
# Jetson" / "ניסיון ב-Embedded, עדיפות ל-Jetson".  Do not downgrade the whole
# bullet merely because the suffix is preferred.
_SCOPED_PREFERENCE_RE = re.compile(
    r"(?i)(?:\bpreference\s+for\b|\bpreferably\b|עדיפות\s+ל(?:-|\s)*)"
)
_WHOLE_CLAUSE_PREFERRED_RE = re.compile(
    r"(?ix)(?:"
    r"^\s*(?:preferred|nice[- ]to[- ]have|advantage|bonus|יתרון|רצוי|מועדף|מועדפת)\b|"
    r"(?:[-–—,:]\s*)?(?:is\s+)?(?:preferred|an?\s+advantage|a\s+plus|nice[- ]to[- ]have)\s*$|"
    r"(?:[-–—,:]\s*)?(?:מהווה\s+)?יתרון(?:\s+משמעותי)?\s*$|"
    r"(?:[-–—,:]\s*)?רצוי\s*$"
    r")"
)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\n.!?;]+", str(text or "")) if part.strip()]


def classify_job_skills(job) -> tuple[set[str], set[str], set[str]]:
    title = str(getattr(job, "title", "") or "")
    description = str(getattr(job, "description", "") or "")
    all_skills = set(extract_skills(f"{title}. {description}"))
    required: set[str] = set()
    preferred: set[str] = set()
    supporting: set[str] = set()

    for kind, clause in iter_requirement_clauses(
        description, include_required=True, include_preferred=True,
        include_responsibilities=True, include_unknown=True,
    ):
        found = set(extract_skills(clause))
        if not found:
            continue
        lowered = clause.casefold()
        if kind == "preferred":
            preferred.update(found)
            continue

        scoped_preference = _SCOPED_PREFERENCE_RE.search(clause)
        if scoped_preference:
            core_found = set(extract_skills(clause[:scoped_preference.start()]))
            preferred_found = set(extract_skills(clause[scoped_preference.start():]))
            if kind == "required" or any(marker in lowered[:scoped_preference.start()] for marker in REQUIRED_MARKERS):
                required.update(core_found)
            else:
                supporting.update(core_found)
            preferred.update(preferred_found)
            remaining = found - core_found - preferred_found
            supporting.update(remaining)
            continue

        if _WHOLE_CLAUSE_PREFERRED_RE.search(clause) or any(
            lowered.lstrip().startswith(marker) for marker in PREFERRED_MARKERS
        ):
            preferred.update(found)
        elif kind == "required" or any(marker in lowered for marker in REQUIRED_MARKERS):
            required.update(found)
        else:
            # Responsibilities and unheaded narrative are evidence that a technology
            # matters to the role, but not enough to invent a hard requirement.
            supporting.update(found)

    title_skills = set(extract_skills(title))
    required.update(title_skills)
    preferred.difference_update(required)
    supporting.update(all_skills - required - preferred)
    supporting.difference_update(required | preferred)
    return required, preferred, supporting


def score_skills(job, candidate_skills: set[str], maximum: int, required_share: float) -> dict:
    required, preferred, supporting = classify_job_skills(job)
    matched_required = sorted(required & candidate_skills)
    missing_required = sorted(required - candidate_skills)
    matched_preferred = sorted((preferred | supporting) & candidate_skills)
    required_points = round(maximum * required_share)
    preferred_points = maximum - required_points
    if required:
        required_ratio = len(matched_required) / len(required)
    else:
        required_ratio = .65 if not (preferred or supporting) else 1.0
    optional_pool = preferred | supporting
    optional_ratio = len(matched_preferred) / len(optional_pool) if optional_pool else .7
    score = round(required_points * required_ratio + preferred_points * optional_ratio)
    reasons = []
    if matched_required:
        reasons.append(f"Matched required/core: {', '.join(matched_required)}")
    if missing_required:
        reasons.append(f"Missing required/core: {', '.join(missing_required)}")
    if matched_preferred:
        reasons.append(f"Matched preferred/supporting: {', '.join(matched_preferred)}")
    if not required and not optional_pool:
        reasons.append("No technologies could be extracted")
    return {
        "score": max(0, min(maximum, score)), "max": maximum,
        "matched_required": matched_required, "missing_required": missing_required,
        "matched_preferred": matched_preferred, "required": sorted(required),
        "preferred": sorted(preferred), "supporting": sorted(supporting), "reasons": reasons,
    }
