from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import Profile
from app.services.matching import build_match_context
from app.services.ranking.config import RankingV2Config
from app.services.ranking.service import rank_job


NOW = datetime(2026, 8, 18, tzinfo=timezone.utc)


def profile(track="computer_science", *, years=3, skills=None, titles=None, excluded=None, locations=None):
    return Profile(
        user_id="ranking-test", active_career_track=track, years_experience=years,
        skills_json=repr(skills or []).replace("'", '"'),
        desired_titles_json=repr(titles or []).replace("'", '"'),
        excluded_keywords_json=repr(excluded or []).replace("'", '"'),
        preferred_locations_json=repr(locations or ["Israel"]).replace("'", '"'),
        preferred_work_modes_json='["hybrid","remote","onsite"]', keywords_json="[]",
        years_experience_options_json=f'["{years}"]', work_authorization=True, needs_sponsorship=False,
    )


def job(title, description, *, track="computer_science", location="Tel Aviv, Israel", workplace="hybrid", age=1):
    return SimpleNamespace(
        id=1, title=title, description=description, career_track=track, location=location,
        workplace=workplace, published_at=NOW - timedelta(days=age), updated_at=NOW,
    )


def score(candidate, opening, config=None):
    context = build_match_context(candidate, career_track=candidate.active_career_track, now=NOW)
    return rank_job(opening, candidate, "v2", config or RankingV2Config(), context=context)


@pytest.mark.parametrize(("track", "title", "description", "expected"), [
    ("computer_science", "Backend Software Engineer", "Python APIs and distributed systems", True),
    ("computer_science", "Frontend Developer", "React TypeScript web application", True),
    ("computer_science", "Machine Learning Engineer", "Python deep learning computer science", True),
    ("computer_science", "RF Hardware Engineer", "RF circuit board electronics", False),
    ("computer_science", "Procurement Specialist", "supply chain purchasing", False),
    ("electrical_engineering", "RTL Design Engineer", "SystemVerilog ASIC VLSI", True),
    ("electrical_engineering", "FPGA Engineer", "VHDL RTL electrical engineering", True),
    ("electrical_engineering", "RF Engineer", "microwave radio frequency electronics", True),
    ("electrical_engineering", "Backend Software Engineer", "Python Django cloud", False),
    ("electrical_engineering", "Supply Chain Planner", "inventory procurement logistics", False),
    ("industrial_engineering", "Supply Chain Planner", "inventory procurement logistics", True),
    ("industrial_engineering", "PMO Project Manager", "project planning and operations", True),
    ("industrial_engineering", "BI Data Analyst", "Power BI business intelligence SQL", True),
    ("industrial_engineering", "RTL Verification Engineer", "UVM SystemVerilog ASIC", False),
    ("industrial_engineering", "Frontend Developer", "React TypeScript", False),
])
def test_track_eligibility_matrix(track, title, description, expected):
    candidate = profile(track)
    result = score(candidate, job(title, description, track=track))
    assert result.eligibility["career_track_status"] == ("match" if expected else "mismatch")
    assert result.eligibility["eligible"] is expected


@pytest.mark.parametrize(("name", "opening", "candidate", "state", "field"), [
    ("explicit exclusion", job("Senior Backend Software Engineer", "Python"), profile(excluded=["senior"]), "excluded", "explicit_exclusion"),
    ("experience realistic", job("Backend Software Engineer", "Python. 4 years experience"), profile(years=3), "realistic", "experience_status"),
    ("experience stretch", job("Backend Software Engineer", "Python. 6 years experience"), profile(years=3), "stretch", "experience_status"),
    ("experience excluded", job("Backend Software Engineer", "Python. 8 years experience"), profile(years=3), "excluded", "experience_status"),
    ("old opening", job("Backend Software Engineer", "Python", age=60), profile(), "excluded", "recency_status"),
    ("location alias", job("Backend Software Engineer", "Python", location="תל-אביב"), profile(locations=["Tel Aviv"]), "realistic", "location_status"),
    ("soft location mismatch", job("Backend Software Engineer", "Python", location="Haifa"), profile(locations=["Tel Aviv"]), "realistic", "location_status"),
    ("unknown location", job("Backend Software Engineer", "Python", location=""), profile(), "realistic", "location_status"),
    ("unknown date", SimpleNamespace(id=1, title="Backend Software Engineer", description="Python", career_track="computer_science", location="Israel", workplace="hybrid", published_at=None, updated_at=NOW), profile(), "realistic", "recency_status"),
    ("work mode mismatch", job("Backend Software Engineer", "Python", workplace="onsite"), profile(), "realistic", "work_mode_status"),
])
def test_eligibility_edge_cases(name, opening, candidate, state, field):
    result = score(candidate, opening)
    assert result.eligibility["state"] == state, name
    assert field in result.eligibility


def test_strict_location_turns_preference_mismatch_into_exclusion():
    candidate = profile(locations=["Tel Aviv"])
    result = score(candidate, job("Backend Software Engineer", "Python", location="Haifa"), RankingV2Config(strict_location=True))
    assert result.tier == "excluded"


def test_exact_role_outweighs_unrelated_role_with_more_supporting_skills():
    candidate = profile(skills=["python", "sql", "docker"], titles=["backend software engineer"])
    exact = score(candidate, job("Backend Software Engineer", "Python required. SQL and Docker preferred"))
    unrelated = score(candidate, job("Frontend Developer", "Python SQL Docker React TypeScript"))
    assert exact.breakdown["role"]["score"] > unrelated.breakdown["role"]["score"]
    assert exact.score > unrelated.score


def test_missing_required_cpp_is_not_hidden_by_python_advantage():
    candidate = profile(skills=["python"], titles=["software engineer"])
    result = score(candidate, job("C++ Software Engineer", "C++ is required. Python is an advantage."))
    skills = result.breakdown["skills"]
    assert "c++" in skills["missing_required"]
    assert "python" in skills["matched_preferred"]
    assert skills["penalty"] > 0


def test_unknown_data_reduces_confidence_without_inventing_mismatch():
    opening = SimpleNamespace(id=1, title="Backend Software Engineer", description="", career_track="computer_science", location="", workplace="unknown", published_at=None, updated_at=NOW)
    result = score(profile(titles=["backend software engineer"]), opening)
    assert result.eligibility["state"] == "realistic"
    assert {"experience", "location", "publication_date", "work_mode"}.issubset(result.eligibility["unknown_fields"])
    assert result.confidence == "low"


def test_configuration_requires_exact_weight_total_and_ordered_thresholds():
    with pytest.raises(ValueError, match="total 100"):
        RankingV2Config(role_weight=50).validate()
    with pytest.raises(ValueError, match="strictly descending"):
        RankingV2Config(top_match_threshold=80, strong_match_threshold=90).validate()
