from __future__ import annotations

from urllib.parse import urlparse

from .matching import KNOWN_SKILLS, extract_skills


OFFICIAL_CAREERS: dict[str, tuple[tuple[str, ...], str]] = {
    "google": (("google", "alphabet"), "https://careers.google.com"),
    "apple": (("apple",), "https://jobs.apple.com"),
    "microsoft": (("microsoft",), "https://jobs.careers.microsoft.com"),
    "amazon": (("amazon", "aws"), "https://www.amazon.jobs"),
    "meta": (("meta", "facebook"), "https://www.metacareers.com"),
    "nvidia": (("nvidia",), "https://www.nvidia.com/en-us/about-nvidia/careers"),
    "figma": (("figma",), "https://www.figma.com/careers"),
    "redis": (("redis",), "https://redis.io/careers"),
}


def resolve_official_careers_url(company: str | None, apply_url: str | None = None) -> str:
    """Resolve a known careers page without inventing links for unknown companies."""
    company_key = (company or "").casefold().strip()
    for aliases, careers_url in OFFICIAL_CAREERS.values():
        if any(alias in company_key for alias in aliases):
            return careers_url
    parsed = urlparse(apply_url or "")
    if parsed.scheme == "https" and parsed.netloc:
        return f"https://{parsed.netloc}"
    return ""


def get_skill_suggestions(text: str, current_skills: list[str] | None = None) -> list[str]:
    """Suggest recognized skills mentioned in text but missing from the profile."""
    existing = {skill.casefold().strip() for skill in (current_skills or [])}
    return [skill for skill in extract_skills(text) if skill.casefold() not in existing and skill in KNOWN_SKILLS]
