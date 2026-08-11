from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import Profile
from ..utils import dumps, loads

COMPUTER_SCIENCE = "computer_science"
INDUSTRIAL_ENGINEERING = "industrial_engineering"
DEFAULT_TRACK = COMPUTER_SCIENCE


@dataclass(frozen=True)
class CareerTrackDefinition:
    key: str
    label: str
    short_label: str
    description: str
    accent: str
    dark_accent: str


CAREER_TRACKS: tuple[CareerTrackDefinition, ...] = (
    CareerTrackDefinition(
        key=COMPUTER_SCIENCE,
        label="מדעי המחשב",
        short_label="CS",
        description="תוכנה, אלגוריתמים, AI, תשתיות ומחקר",
        accent="blue",
        dark_accent="blue-dark",
    ),
    CareerTrackDefinition(
        key=INDUSTRIAL_ENGINEERING,
        label="תעשייה וניהול",
        short_label="IEM",
        description="תפעול, אנליזה, שרשרת אספקה, BI, תכנון ופרויקטים",
        accent="yellow",
        dark_accent="yellow-dark",
    ),
)
CAREER_TRACK_BY_KEY = {track.key: track for track in CAREER_TRACKS}

# These fields belong to the professional search track. Personal/contact/application
# answers remain shared so users never need to maintain two copies of their identity.
TRACK_FIELDS = (
    "years_experience",
    "years_experience_options_json",
    "salary_expectation",
    "skills_json",
    "desired_titles_json",
    "preferred_locations_json",
    "preferred_work_modes_json",
    "keywords_json",
    "excluded_keywords_json",
    "auto_apply_threshold",
    "auto_submit_enabled",
    "cv_path",
)

TRACK_DEFAULTS: dict[str, dict[str, Any]] = {
    COMPUTER_SCIENCE: {
        "years_experience": 0.0,
        "years_experience_options_json": dumps(["0"]),
        "salary_expectation": "",
        "skills_json": dumps(["C++", "Python", "Git", "Linux", "Data Structures", "REST API"]),
        "desired_titles_json": dumps([
            "software engineer", "backend", "r&d", "research engineer",
            "ai engineer", "machine learning engineer",
        ]),
        "preferred_locations_json": dumps(["Haifa", "Tel Aviv", "Israel", "Remote"]),
        "preferred_work_modes_json": dumps(["hybrid", "remote", "onsite"]),
        "keywords_json": dumps(["C++", "Python", "automation", "infrastructure", "graduate"]),
        "excluded_keywords_json": dumps(["manual qa", "sales", "support representative"]),
        "auto_apply_threshold": 82,
        "auto_submit_enabled": False,
        "cv_path": "",
    },
    INDUSTRIAL_ENGINEERING: {
        "years_experience": 0.0,
        "years_experience_options_json": dumps(["0"]),
        "salary_expectation": "",
        "skills_json": dumps([
            "Excel", "SQL", "Power BI", "Data Analysis", "ERP", "SAP",
            "Process Improvement", "Project Management",
        ]),
        "desired_titles_json": dumps([
            "industrial engineer", "business analyst", "data analyst", "operations analyst",
            "supply chain", "pmo", "project manager", "production planner",
            "procurement", "process improvement",
        ]),
        "preferred_locations_json": dumps(["Israel", "Central Israel", "Tel Aviv", "Haifa"]),
        "preferred_work_modes_json": dumps(["hybrid", "onsite", "remote"]),
        "keywords_json": dumps([
            "industrial engineering", "operations", "supply chain", "planning",
            "process improvement", "data analysis", "entry level", "junior",
        ]),
        "excluded_keywords_json": dumps([
            "software engineer", "frontend", "backend", "sales representative", "manual qa",
        ]),
        "auto_apply_threshold": 78,
        "auto_submit_enabled": False,
        "cv_path": "",
    },
}


def normalize_track(value: str | None) -> str:
    key = str(value or DEFAULT_TRACK).strip().casefold()
    return key if key in CAREER_TRACK_BY_KEY else DEFAULT_TRACK


def active_track(profile: Profile | None) -> str:
    if not profile:
        return DEFAULT_TRACK
    return normalize_track(getattr(profile, "active_career_track", DEFAULT_TRACK))


def _capture_current(profile: Profile) -> dict[str, Any]:
    return {field: getattr(profile, field) for field in TRACK_FIELDS}


def _normalized_saved_state(state: dict[str, Any], track: str) -> dict[str, Any]:
    defaults = TRACK_DEFAULTS[track]
    normalized: dict[str, Any] = {}
    for field in TRACK_FIELDS:
        value = state.get(field, defaults[field])
        normalized[field] = defaults[field] if value is None else value
    return normalized


def ensure_track_state(profile: Profile) -> dict[str, dict[str, Any]]:
    """Make legacy single-track profiles safe for multi-track switching.

    On first upgrade, the user's exact existing search configuration becomes the CS
    track. IEM receives deliberately separate defaults and never overwrites CS data.
    """
    track_states = loads(getattr(profile, "track_profiles_json", "{}"), {})
    if not isinstance(track_states, dict):
        track_states = {}
    current = active_track(profile)
    if COMPUTER_SCIENCE not in track_states:
        # Existing installations were all CS. Preserve them verbatim even if the
        # active-track column was added by SQLite with its default just now.
        track_states[COMPUTER_SCIENCE] = _capture_current(profile)
    if INDUSTRIAL_ENGINEERING not in track_states:
        track_states[INDUSTRIAL_ENGINEERING] = dict(TRACK_DEFAULTS[INDUSTRIAL_ENGINEERING])
    for key in CAREER_TRACK_BY_KEY:
        track_states[key] = _normalized_saved_state(track_states.get(key, {}), key)
    profile.track_profiles_json = dumps(track_states)
    profile.active_career_track = current
    return track_states


def persist_active_track(profile: Profile) -> dict[str, dict[str, Any]]:
    states = ensure_track_state(profile)
    current = active_track(profile)
    states[current] = _capture_current(profile)
    profile.track_profiles_json = dumps(states)
    return states


def switch_track(profile: Profile, target: str) -> str:
    target = normalize_track(target)
    states = persist_active_track(profile)
    if target == active_track(profile):
        return target
    target_state = _normalized_saved_state(states.get(target, {}), target)
    for field, value in target_state.items():
        setattr(profile, field, value)
    profile.active_career_track = target
    profile.track_profiles_json = dumps(states)
    return target


def profile_track_state(profile: Profile, track: str | None = None) -> dict[str, Any]:
    track = normalize_track(track or active_track(profile))
    states = ensure_track_state(profile)
    if track == active_track(profile):
        return _capture_current(profile)
    return _normalized_saved_state(states.get(track, {}), track)


def track_public_dict(track: CareerTrackDefinition, *, active: bool, enabled_sources: int = 0,
                      source_errors: int = 0, jobs: int = 0) -> dict[str, Any]:
    return {
        "key": track.key,
        "label": track.label,
        "short_label": track.short_label,
        "description": track.description,
        "accent": track.accent,
        "dark_accent": track.dark_accent,
        "active": active,
        "search_agent_active": active,
        "enabled_sources": int(enabled_sources or 0),
        "source_errors": int(source_errors or 0),
        "jobs": int(jobs or 0),
    }
