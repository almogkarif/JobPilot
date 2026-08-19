from app.models import Profile
from app.services.career_tracks import (
    COMPUTER_SCIENCE,
    ELECTRICAL_ENGINEERING,
    INDUSTRIAL_ENGINEERING,
    LEGACY_STARTER_SKILLS,
    TRACK_DEFAULTS,
    ensure_track_state,
    remove_unconfirmed_starter_skills,
)
from app.utils import dumps, loads


def test_new_track_defaults_never_claim_suggested_skills_for_user():
    assert all(loads(TRACK_DEFAULTS[track]["skills_json"], []) == [] for track in (
        COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, ELECTRICAL_ENGINEERING,
    ))


def test_untouched_legacy_profile_loses_only_exact_canned_skill_lists():
    profile = Profile(
        skills_json=dumps(LEGACY_STARTER_SKILLS[COMPUTER_SCIENCE]),
        active_career_track=COMPUTER_SCIENCE,
        onboarding_version=0,
        cv_path="",
    )
    states = ensure_track_state(profile)
    states[INDUSTRIAL_ENGINEERING]["skills_json"] = dumps(LEGACY_STARTER_SKILLS[INDUSTRIAL_ENGINEERING])
    states[ELECTRICAL_ENGINEERING]["skills_json"] = dumps(LEGACY_STARTER_SKILLS[ELECTRICAL_ENGINEERING])
    profile.track_profiles_json = dumps(states)
    assert set(remove_unconfirmed_starter_skills(profile)) == {
        COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, ELECTRICAL_ENGINEERING,
    }
    assert loads(profile.skills_json, []) == []
    assert all(loads(state["skills_json"], []) == [] for state in loads(profile.track_profiles_json, {}).values())


def test_repair_preserves_manual_edits_completed_onboarding_and_resume_profiles():
    edited = Profile(skills_json=dumps(["Python", "Rust"]), onboarding_version=0, cv_path="")
    completed = Profile(skills_json=dumps(LEGACY_STARTER_SKILLS[COMPUTER_SCIENCE]), onboarding_version=6, cv_path="")
    with_resume = Profile(skills_json=dumps(LEGACY_STARTER_SKILLS[COMPUTER_SCIENCE]), onboarding_version=0, cv_path="resume.pdf")
    assert remove_unconfirmed_starter_skills(edited) == []
    assert remove_unconfirmed_starter_skills(completed) == []
    assert remove_unconfirmed_starter_skills(with_resume) == []
    assert loads(edited.skills_json, []) == ["Python", "Rust"]
