from __future__ import annotations

from datetime import timezone

from ...utils import loads
from ..location_filter import is_israel_location
from ..degree_requirements import degree_label, degree_satisfies, job_degree_requirement, profile_degree_level
from ..matching import hard_exclusion_reason, track_job_relevance
from .experience import (
    SENIORITY_ORDER, detect_seniority, employment_type, experience_requirement_buckets,
    parse_experience, profile_experience_options, profile_seniority,
)

LOCATION_ALIASES = {
    "israel": {"israel", "ישראל"},
    "tel aviv": {"tel aviv", "tel-aviv", "תל אביב", "תל-אביב"},
    "haifa": {"haifa", "חיפה"},
    "jerusalem": {"jerusalem", "ירושלים"},
}


def _location_tokens(value: str) -> set[str]:
    lowered = str(value or "").casefold().strip()
    tokens = {lowered} if lowered else set()
    for canonical, aliases in LOCATION_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            tokens.add(canonical)
    if lowered and is_israel_location(value):
        tokens.add("israel")
    return tokens


def _locations_match(job_location: str, preferred_locations: list[str]) -> bool:
    job_tokens = _location_tokens(job_location)
    city_tokens = set(LOCATION_ALIASES) - {"israel"}
    for preferred in preferred_locations:
        preferred_tokens = _location_tokens(preferred)
        preferred_specific = preferred_tokens & city_tokens
        job_specific = job_tokens & city_tokens
        if preferred_specific:
            if preferred_specific & job_specific:
                return True
        elif "israel" in preferred_tokens and "israel" in job_tokens:
            return True
        elif preferred_tokens & job_tokens:
            return True
    return False


def evaluate_eligibility(job, profile, config, *, career_track: str, now) -> dict:
    state = "realistic"
    reasons: list[str] = []
    warnings: list[str] = []
    unknown: list[str] = []

    track_ok, track_reason = track_job_relevance(job, career_track)
    track_status = "match" if track_ok else "mismatch"
    if not track_ok:
        state = "excluded"
        reasons.append(f"Career track mismatch: {track_reason}")
    else:
        reasons.append("Career track matches")

    exclusion = hard_exclusion_reason(job, profile)
    if exclusion:
        state = "excluded"
        reasons.append(exclusion)

    exp_min, exp_max = parse_experience(job)
    years = float(getattr(profile, "years_experience", 0) or 0)
    gap = None if exp_min is None else max(0.0, exp_min - years)
    selected_experience = profile_experience_options(profile)
    requirement_buckets = experience_requirement_buckets(exp_min, exp_max)
    experience_status = "unknown"
    if exp_min is None:
        unknown.append("experience")
    elif selected_experience:
        # The profile UI intentionally allows several experience values. Treat
        # those choices as the hard filter instead of collapsing them to max()
        # and then quietly allowing an additional configured gap.
        matching_buckets = sorted(selected_experience & requirement_buckets)
        if matching_buckets:
            experience_status = "match"
            reasons.append(
                "Experience requirement matches selected profile range: "
                + ", ".join(matching_buckets)
            )
        else:
            experience_status = "mismatch"
            state = "excluded"
            required_label = ", ".join(sorted(requirement_buckets)) or f"{exp_min:g}+"
            selected_label = ", ".join(sorted(selected_experience))
            reasons.append(
                f"Experience requirement ({required_label}) is outside selected profile values ({selected_label})"
            )
    elif gap <= config.realistic_experience_gap:
        # Legacy/fallback profiles without the multi-select field keep the old
        # gap-based behavior so upgrades never fail closed unexpectedly.
        experience_status = "match"
        reasons.append(f"Experience realistic: requires {exp_min:g}, profile {years:g}")
    elif gap < config.exclude_experience_gap:
        experience_status = "stretch"
        state = "stretch" if state != "excluded" else state
        warnings.append(f"Experience gap of {gap:g} years")
    else:
        experience_status = "mismatch"
        state = "excluded"
        reasons.append(f"Experience gap of {gap:g} years exceeds configured limit")

    degree_requirement = job_degree_requirement(job)
    required_degree = degree_requirement.level
    candidate_degree = profile_degree_level(profile)
    degree_status = "unknown"
    if not required_degree:
        unknown.append("degree")
    elif not candidate_degree:
        degree_status = "not_configured"
        unknown.append("profile_degree")
        if degree_requirement.experience_alternative:
            warnings.append(
                f"Job accepts {degree_label(required_degree)} or equivalent experience; profile degree is not configured"
            )
        else:
            warnings.append(f"Job requires {degree_label(required_degree)}; profile degree is not configured")
    elif degree_satisfies(candidate_degree, required_degree):
        degree_status = "match"
        reasons.append(f"Degree requirement matches: {degree_label(required_degree)}")
    elif degree_requirement.experience_alternative:
        degree_status = "alternative"
        warnings.append(
            f"Academic path is {degree_label(required_degree)}, but equivalent experience is explicitly accepted"
        )
    elif degree_requirement.required:
        degree_status = "mismatch"
        state = "excluded"
        reasons.append(
            f"Degree requirement mismatch: requires {degree_label(required_degree)}, "
            f"profile has {degree_label(candidate_degree)}"
        )
    else:
        degree_status = "unknown"
        unknown.append("degree")

    job_level = detect_seniority(getattr(job, "title", ""))
    user_level = profile_seniority(years)
    seniority_status = "unknown" if not job_level else "match"
    if not job_level:
        unknown.append("seniority")
    elif SENIORITY_ORDER[job_level] - SENIORITY_ORDER[user_level] >= 3:
        seniority_status = "mismatch"
        state = "excluded"
        reasons.append(f"Seniority mismatch: {user_level} profile vs {job_level} role")
    elif SENIORITY_ORDER[job_level] > SENIORITY_ORDER[user_level]:
        seniority_status = "stretch"
        state = "stretch" if state != "excluded" else state
        warnings.append(f"Role seniority is {job_level}")

    preferred_locations = loads(getattr(profile, "preferred_locations_json", "[]"), [])
    job_location = str(getattr(job, "location", "") or "").strip()
    location_status = "unknown"
    if not job_location:
        unknown.append("location")
    elif not preferred_locations:
        location_status = "not_configured"
    else:
        location_status = "match" if _locations_match(job_location, preferred_locations) else "preference_mismatch"
        if location_status != "match":
            if config.strict_location:
                state = "excluded"
                reasons.append("Strict location constraint not met")
            else:
                warnings.append("Location is outside preferred locations")

    published = getattr(job, "published_at", None)
    recency_status = "unknown"
    age_days = None
    if not published:
        unknown.append("publication_date")
    else:
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_days = max(0, (now - published.astimezone(timezone.utc)).days)
        recency_status = "fresh" if age_days <= config.maximum_job_age_days else "old"
        if recency_status == "old":
            state = "excluded"
            reasons.append(f"Job is {age_days} days old; maximum is {config.maximum_job_age_days}")

    workplace = str(getattr(job, "workplace", "") or "").casefold()
    preferred_modes = {str(value).casefold() for value in loads(getattr(profile, "preferred_work_modes_json", "[]"), [])}
    work_mode_status = "unknown" if workplace in {"", "unknown"} else ("match" if not preferred_modes or workplace in preferred_modes else "preference_mismatch")
    if work_mode_status == "unknown":
        unknown.append("work_mode")
    elif work_mode_status == "preference_mismatch":
        if config.strict_work_mode:
            state = "excluded"
            reasons.append("Strict work-mode constraint not met")
        else:
            warnings.append("Work mode is outside preferences")

    detected_employment = employment_type(job)
    employment_status = "unknown" if not detected_employment else "match"
    if not detected_employment:
        unknown.append("employment_type")
    elif config.employment_types and detected_employment not in config.employment_types:
        employment_status = "mismatch"
        if config.strict_employment_type:
            state = "excluded"
        else:
            warnings.append("Employment type is outside preferences")

    confidence = "high" if len(unknown) <= 1 else "medium" if len(unknown) <= 3 else "low"
    return {
        "eligible": state != "excluded", "state": state, "tier": state,
        "career_track_status": track_status, "experience_status": experience_status,
        "experience_gap": gap, "required_experience_min": exp_min, "required_experience_max": exp_max,
        "required_experience_buckets": sorted(requirement_buckets),
        "profile_experience": years, "profile_experience_options": sorted(selected_experience),
        "degree_status": degree_status, "required_degree": required_degree or None,
        "degree_required": degree_requirement.required,
        "degree_experience_alternative": degree_requirement.experience_alternative,
        "profile_degree_level": candidate_degree or None,
        "seniority_status": seniority_status,
        "job_seniority": job_level, "profile_seniority": user_level,
        "location_status": location_status, "job_location": job_location or None,
        "recency_status": recency_status, "age_days": age_days,
        "work_mode_status": work_mode_status, "employment_type_status": employment_status,
        "employment_type": detected_employment, "explicit_exclusion": exclusion,
        "reasons": reasons, "warnings": warnings, "unknown_fields": unknown, "confidence": confidence,
    }
