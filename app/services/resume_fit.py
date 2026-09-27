"""Resume-specific skill coverage; no profile, document, network or database reads."""
from __future__ import annotations

from types import SimpleNamespace

from ..utils import loads
from .matching import KNOWN_SKILLS, extract_skills
from .ranking.skills import classify_job_skills

GROUP_WEIGHTS = {"required": 80, "preferred": 15, "supporting": 5}
_ALIASES = {alias.casefold(): skill for skill, aliases in KNOWN_SKILLS.items() for alias in aliases}


def normalize_skills(values) -> set[str]:
    if not isinstance(values, list):
        return set()
    result = set()
    for value in values:
        if not isinstance(value, str):
            continue
        value = " ".join(value.casefold().split())
        if value:
            # Prefer an exact canonical skill over a broader family's alias
            # (e.g. pytorch is both a skill and a machine-learning signal).
            result.add(value if value in KNOWN_SKILLS else _ALIASES.get(value, value))
    return result


def job_skill_groups(job) -> dict[str, set[str]]:
    # A title names relevant technology, but does not by itself say "mandatory".
    required, preferred, supporting = classify_job_skills(SimpleNamespace(
        title="", description=getattr(job, "description", "") or ""))
    cached = normalize_skills(loads(getattr(job, "skills_json", "[]"), []))
    supporting |= cached | set(extract_skills(str(getattr(job, "title", "") or "")))
    supporting -= required | preferred
    return {"required": required, "preferred": preferred, "supporting": supporting}


def resume_skill_evidence(resume) -> dict:
    analysis = loads(getattr(resume, "analysis_json", "{}"), {})
    if not isinstance(analysis, dict):
        analysis = {}
    extracted = normalize_skills(analysis.get("skills", []))
    stored = normalize_skills(loads(getattr(resume, "skills_json", "[]"), []))
    manual = normalize_skills(analysis.get("manual_skills", []))
    # Older uploads stored the union without a manual-skills field. Preserve
    # those version-specific additions, but never call them document evidence.
    saved_only = stored - extracted - manual
    try:
        readable = int(analysis.get("text_length", 0)) > 0
    except (ValueError, TypeError):
        readable = False
    if analysis.get("error"):
        extracted = set()
        readable = False
    elif extracted:
        readable = True
    return {"extracted": extracted, "manual": manual - extracted,
            "saved": saved_only, "readable": readable}


def resume_skill_coverage(resume, job, *, groups=None) -> dict:
    groups = job_skill_groups(job) if groups is None else groups
    evidence = resume_skill_evidence(resume)
    owned = evidence["extracted"] | evidence["manual"] | evidence["saved"]
    reasons = []
    if not any(groups.values()):
        reasons.append("job_skills_missing")
    if not evidence["readable"] and not owned:
        reasons.append("resume_unreadable")
    known = not reasons
    present_weight = sum(GROUP_WEIGHTS[key] for key, skills in groups.items() if skills)
    details = {}
    weighted = 0.0
    for key, skills in groups.items():
        matched = sorted(skills & owned)
        missing = sorted(skills - owned) if known else []
        coverage = len(matched) / len(skills) if skills and known else None
        weight = GROUP_WEIGHTS[key] / present_weight if skills and present_weight else 0.0
        if coverage is not None:
            weighted += weight * coverage
        details[key] = {"skills": sorted(skills), "matched": matched, "missing": missing,
                        "coverage": coverage, "weight": round(weight * 100, 2)}
    relevant = set().union(*groups.values())
    return {
        "score": round(weighted * 100) if known else None,
        "status": "known" if known else "insufficient_information",
        "unknown_reasons": reasons, "groups": details,
        "matched_skills": sorted(relevant & owned),
        "missing_skills": sorted(relevant - owned) if known else [],
        "document_matched_skills": sorted(relevant & evidence["extracted"]),
        "manual_matched_skills": sorted(relevant & evidence["manual"]),
        "saved_matched_skills": sorted(relevant & evidence["saved"]),
        "evidence_mode": "document" if evidence["readable"] else ("manual_only" if owned else "unavailable"),
        "recommended": False,
    }


def resume_recommendation_key(resume, fit: dict) -> tuple:
    """Mandatory coverage always outranks optional points, even before rounding."""
    groups = fit["groups"]
    required = groups["required"]["coverage"]
    weighted = sum(group["weight"] * (group["coverage"] or 0) for group in groups.values())
    created = getattr(resume, "created_at", None)
    return (fit["score"] is not None, required if required is not None else -1,
            weighted,
            bool(getattr(resume, "is_default", False)), created.isoformat() if created else "",
            getattr(resume, "id", 0) or 0)
