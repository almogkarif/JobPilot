from __future__ import annotations

import re

from ..matching import KNOWN_SKILLS, _contains_variant, extract_skills

REQUIRED_MARKERS = ("required", "must", "mandatory", "requirement", "חובה", "נדרש", "דרישות")
PREFERRED_MARKERS = ("preferred", "advantage", "nice to have", "יתרון", "עדיפות")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\n.!?;]+", str(text or "")) if part.strip()]


def classify_job_skills(job) -> tuple[set[str], set[str], set[str]]:
    text = f"{getattr(job, 'title', '')}. {getattr(job, 'description', '')}"
    all_skills = set(extract_skills(text))
    required: set[str] = set()
    preferred: set[str] = set()
    for sentence in _sentences(text):
        lowered = sentence.casefold()
        found = set(extract_skills(sentence))
        if found and any(marker in lowered for marker in PREFERRED_MARKERS):
            preferred.update(found)
        elif found and any(marker in lowered for marker in REQUIRED_MARKERS):
            required.update(found)
    title_skills = set(extract_skills(str(getattr(job, "title", "") or "")))
    required.update(title_skills)
    preferred.difference_update(required)
    supporting = all_skills - required - preferred
    if not required and all_skills:
        # With no explicit requirement grammar, technologies in the first half are
        # evidence but not invented mandatory requirements.
        supporting = all_skills
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
