from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.models import Profile
from app.services.degree_requirements import (
    allowed_job_degree_levels,
    degree_satisfies,
    extract_degree_requirement,
    extract_degree_requirement_details,
)
from app.services.matching import build_match_context
from app.services.ranking.config import RankingV2Config
from app.services.ranking.service import rank_job
from app.utils import dumps


def test_extracts_minimum_mandatory_degree_without_promoting_preferences():
    assert extract_degree_requirement("Bachelor's degree in Computer Science required") == "bachelor"
    assert extract_degree_requirement("Bachelor’s degree in Computer Science required") == "bachelor"
    assert extract_degree_requirement("B.Sc. / M.Sc. / Ph.D. in Computer Science") == "bachelor"
    assert extract_degree_requirement("M.Sc. or Ph.D. in Electrical Engineering required") == "master"
    assert extract_degree_requirement("Ph.D. required in Computer Science") == "phd"
    assert extract_degree_requirement("תואר שני או דוקטורט בהנדסת חשמל - חובה") == "master"
    assert extract_degree_requirement("תואר שלישי במדעי המחשב חובה") == "phd"
    assert extract_degree_requirement("Bachelor's degree required; Master's degree preferred") == "bachelor"
    assert extract_degree_requirement("Master's degree preferred") == ""
    assert extract_degree_requirement("Ph.D. is an advantage") == ""
    assert extract_degree_requirement("No degree required; hands-on experience is required") == ""


def test_degree_patterns_cover_all_three_career_tracks_and_engineering_abbreviations():
    # Computer Science
    assert extract_degree_requirement("Minimum Qualifications: BSc in Computer Science") == "bachelor"
    # Electrical Engineering
    assert extract_degree_requirement("Requirements: B.Eng. in Electrical Engineering") == "bachelor"
    assert extract_degree_requirement("Requirements: M.Eng. in Electrical or Computer Engineering") == "master"
    # Industrial Engineering & Management
    assert extract_degree_requirement("דרישות התפקיד: תואר ראשון בהנדסת תעשייה וניהול") == "bachelor"
    assert extract_degree_requirement("Minimum qualifications: B.Tech in Industrial Engineering") == "bachelor"
    # Practical-engineer diplomas are a different credential and must not be invented
    # as BA/MA/PhD.
    assert extract_degree_requirement("Practical Engineering diploma in electronics is required") == ""
    assert extract_degree_requirement("הנדסאי/ת אלקטרוניקה - חובה") == ""


def test_degree_hierarchy_accepts_higher_degree_but_not_lower_degree():
    assert degree_satisfies("bachelor", "bachelor")
    assert not degree_satisfies("bachelor", "master")
    assert degree_satisfies("master", "bachelor")
    assert degree_satisfies("master", "master")
    assert not degree_satisfies("master", "phd")
    assert degree_satisfies("phd", "bachelor")
    assert degree_satisfies("phd", "master")
    assert degree_satisfies("phd", "phd")
    assert allowed_job_degree_levels("bachelor") == ("bachelor",)
    assert allowed_job_degree_levels("master") == ("bachelor", "master")
    assert allowed_job_degree_levels("phd") == ("bachelor", "master", "phd")


def test_equivalent_experience_keeps_academic_path_but_never_hard_blocks_on_degree_alone():
    requirement = extract_degree_requirement_details(
        "Minimum qualifications: Master's degree or equivalent practical experience required"
    )
    assert requirement.level == "master"
    assert requirement.required is False
    assert requirement.experience_alternative is True

    phd = extract_degree_requirement_details("Ph.D. or equivalent professional experience")
    assert phd.level == "phd"
    assert phd.required is False
    assert phd.experience_alternative is True

    bachelor = extract_degree_requirement_details(
        "Bachelor’s degree in Electrical Engineering, or equivalent work experience"
    )
    assert bachelor.level == "bachelor"
    assert bachelor.required is False
    assert bachelor.experience_alternative is True


def test_collapsed_preferred_section_does_not_cancel_earlier_required_degree():
    text = (
        "Job Description: Build silicon systems. Qualifications: Bachelor's degree in Electrical Engineering. "
        "5+ years of relevant experience. Preferred Qualifications: Master's degree. Experience with UVM."
    )
    requirement = extract_degree_requirement_details(text)
    assert requirement.level == "bachelor"
    assert requirement.required is True
    assert requirement.experience_alternative is False


def test_academic_alternatives_choose_lowest_accepted_level_not_highest_mentioned_level():
    assert extract_degree_requirement("Basic qualifications: PhD in CS/EE, or MSc and 5+ years of research experience") == "master"
    assert extract_degree_requirement("Requirements: Bachelor's, Master's, or PhD in a quantitative field") == "bachelor"
    assert extract_degree_requirement("Requirements: Master's or PhD in Physics") == "master"


def _profile(level: str) -> Profile:
    return Profile(
        user_id="degree-test",
        active_career_track="computer_science",
        years_experience=4,
        years_experience_options_json=dumps(["0", "1", "2", "3", "4", "5+"]),
        skills_json=dumps(["python"]),
        desired_titles_json=dumps(["backend software engineer"]),
        preferred_locations_json=dumps(["Israel"]),
        preferred_work_modes_json=dumps(["hybrid", "remote", "onsite"]),
        keywords_json="[]",
        excluded_keywords_json="[]",
        work_authorization=True,
        needs_sponsorship=False,
        application_profile_json=dumps({"degree_level": level}),
    )


def _job(requirement: str, *, required: bool = True, alternative: bool = False):
    return SimpleNamespace(
        id=991,
        title="Backend Software Engineer",
        description="Python services. 2+ years of experience. Master's degree required.",
        career_track="computer_science",
        location="Tel Aviv, Israel",
        workplace="hybrid",
        published_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        degree_requirement=requirement,
        degree_required=required,
        degree_experience_alternative=alternative,
    )


def test_v2_eligibility_excludes_candidate_below_strict_required_degree():
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    bachelor = _profile("bachelor")
    result = rank_job(
        _job("master"), bachelor, RankingV2Config(),
        context=build_match_context(bachelor, career_track="computer_science", now=now),
    )
    assert result.eligibility["degree_status"] == "mismatch"
    assert result.eligibility["required_degree"] == "master"
    assert result.eligibility["state"] == "excluded"

    master = _profile("master")
    result = rank_job(
        _job("master"), master, RankingV2Config(),
        context=build_match_context(master, career_track="computer_science", now=now),
    )
    assert result.eligibility["degree_status"] == "match"
    assert result.eligibility["state"] != "excluded"


def test_v2_does_not_exclude_lower_degree_when_posting_explicitly_accepts_equivalent_experience():
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    bachelor = _profile("bachelor")
    result = rank_job(
        _job("master", required=False, alternative=True), bachelor, RankingV2Config(),
        context=build_match_context(bachelor, career_track="computer_science", now=now),
    )
    assert result.eligibility["degree_status"] == "alternative"
    assert result.eligibility["degree_experience_alternative"] is True
    assert result.eligibility["state"] != "excluded"


def test_master_planner_language_is_not_mistaken_for_a_masters_degree():
    text = (
        "The Site Master Planner owns the site Master Plan and planning strategy. "
        "Qualifications: Bachelor's degree in Civil Engineering or Architecture."
    )
    assert extract_degree_requirement(text) == "bachelor"



def test_short_business_abbreviations_and_plain_english_are_not_degrees():
    assert extract_degree_requirement("You will be part of a multidisciplinary engineering team") == ""
    assert extract_degree_requirement("Experience with MS Office and Excel is required") == ""
    assert extract_degree_requirement("Experience as a BA in product and operations teams") == ""
    assert extract_degree_requirement("Requirements: B.E. in Electrical Engineering") == "bachelor"
    assert extract_degree_requirement("Requirements: B.S. in Computer Engineering") == "bachelor"
    assert extract_degree_requirement("Requirements: BS in Computer Engineering") == "bachelor"
    assert extract_degree_requirement("Requirements: M.S. in Industrial Engineering") == "master"
    assert extract_degree_requirement("Requirements: MS in Industrial Engineering") == "master"


def test_real_elbit_hebrew_requirements_detect_bachelor_as_mandatory():
    text = (
        "במסגרת התפקיד:\n"
        "פיתוח תוכנה ב-C++ עבור מערכות משובצות זמן אמת (Embedded)\n"
        "דרישות :\n"
        "תואר ראשון בהנדסת תוכנה / מדעי המחשב / הנדסת חשמל או תחום רלוונטי אחר\n"
        "ניסיון של שנתיים בפיתוח ב-C++ בדגש על גרסאות מודרניות C++11\n"
        "ניסיון בפיתוח על גבי פלטפורמות Embedded עדיפות ל-Jetson או Qualcomm - יתרון משמעותי\n"
        "הכרות עם OpenCV, CUDA או frameworks דומים - יתרון משמעותי"
    )
    requirement = extract_degree_requirement_details(text)
    assert requirement.level == "bachelor"
    assert requirement.required is True
    assert requirement.experience_alternative is False
    assert "תואר ראשון" in requirement.evidence
