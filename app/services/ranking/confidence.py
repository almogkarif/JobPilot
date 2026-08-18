def recommendation_confidence(job, eligibility: dict, breakdown: dict) -> str:
    signals = 1  # title
    description = str(getattr(job, "description", "") or "").strip()
    if len(description) >= 120:
        signals += 2
    elif description:
        signals += 1
    if getattr(job, "location", None):
        signals += 1
    if getattr(job, "published_at", None):
        signals += 1
    if eligibility.get("required_experience_min") is not None:
        signals += 1
    if breakdown.get("skills", {}).get("required") or breakdown.get("skills", {}).get("supporting"):
        signals += 1
    return "high" if signals >= 6 else "medium" if signals >= 4 else "low"
