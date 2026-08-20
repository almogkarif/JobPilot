from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from app.services.matching import extract_experience, hard_exclusion_reason, score_job
from app.utils import dumps


def profile(**overrides):
    values = dict(
        skills_json=dumps(["C++", "Python", "Linux", "Git"]),
        desired_titles_json=dumps(["software", "automation", "backend"]),
        preferred_locations_json=dumps(["Haifa", "Israel"]),
        keywords_json=dumps(["graduate", "tools"]),
        excluded_keywords_json=dumps(["manual qa"]),
        years_experience=0,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def job(**overrides):
    values = dict(
        title="Graduate Software Developer",
        description="Python and C++ tools on Linux. 0-2 years experience.",
        location="Haifa, Israel",
        workplace="hybrid",
        published_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_entry_role_scores_higher_than_senior_role():
    junior = score_job(job(), profile())
    senior = score_job(job(title="Senior Staff Software Architect", description="8+ years Java"), profile())
    assert junior.score >= 80
    assert senior.score < junior.score


def test_experience_extraction():
    assert extract_experience("Requires 0-2 years experience") == (0.0, 2.0)
    assert extract_experience("At least 3 years of experience") == (3.0, None)
    assert extract_experience("8 or more years of professional experience") == (8.0, None)
    assert extract_experience("ניסיון מוכח של 3 שנים לפחות בפיתוח תוכנה משובצת מחשב") == (3.0, None)


def test_implicit_work_experience_without_years_defaults_to_one_year():
    assert extract_experience("Experience working with Python and distributed systems is required") == (1.0, None)
    assert extract_experience("Hands-on experience developing production services") == (1.0, None)
    assert extract_experience("ניסיון עבודה עם מערכות Linux בסביבת production") == (1.0, None)
    assert extract_experience("נסיון עבודה עם מערכות Linux בסביבת production") == (1.0, None)
    assert extract_experience("Experience in distributed systems is required") == (1.0, None)


def test_optional_or_explicit_no_experience_does_not_invent_one_year():
    assert extract_experience("Experience working with Kubernetes is a plus") == (None, None)
    assert extract_experience("Preferred: hands-on experience with AWS") == (None, None)
    assert extract_experience("No prior experience required") == (0.0, 1.0)
    assert extract_experience("Graduate degree required; 5 years of experience") == (5.0, None)


def test_missing_mandatory_embedded_experience_cannot_be_a_perfect_match():
    result = score_job(
        job(
            title="מפתח תוכנה משובצת",
            description=(
                "דרישות: ניסיון מוכח של 3 שנים לפחות בפיתוח תוכנה משובצת מחשב "
                "עבור מערכות מורכבות ורב תחומיות תוך הבנה מעמיקה בנושאים הטכניים."
            ),
        ),
        profile(skills_json='["python", "git"]', years_experience=0),
    )
    assert result.experience_min == 3
    assert result.score <= 69
    assert any("חסרות דרישות חובה: embedded" in reason["label"] for reason in result.reasons)


def test_incomplete_collector_text_is_never_ranked_as_a_top_match():
    result = score_job(job(description="Apply now"), profile())
    assert result.score <= 55
    assert any(reason["label"] == "פרטי המשרה נקלטו באופן חלקי" for reason in result.reasons)


def test_well_known_company_scores_higher():
    base = score_job(job(), profile())
    google = score_job(job(company="Google"), profile())
    assert google.score > base.score
    assert google.score >= base.score + 8
    assert any(reason["label"].startswith("חברה מוכרת") for reason in google.reasons)


def test_senior_role_can_be_explicitly_desired():
    result = score_job(job(title="Senior Software Engineer"), profile(keywords_json='["senior"]'))
    assert any(reason["label"].startswith("רמת ותק רצויה") for reason in result.reasons)


def test_senior_role_can_be_explicitly_excluded():
    result = score_job(job(title="Senior Software Engineer"), profile(excluded_keywords_json='["senior"]'))
    assert result.score == 0
    assert any(reason["label"].startswith("רמת ותק שהוחרגה") for reason in result.reasons)


def test_hard_exclusion_detects_seniority_and_explicit_keywords():
    assert hard_exclusion_reason(job(title="Senior Software Engineer"), profile(excluded_keywords_json='["senior"]'))
    assert hard_exclusion_reason(job(title="Manual QA Engineer"), profile(excluded_keywords_json='["manual qa"]'))
    assert hard_exclusion_reason(job(title="Backend Engineer", description="Works with the manual QA team"), profile(excluded_keywords_json='["manual qa"]')) is None
    assert hard_exclusion_reason(job(), profile(excluded_keywords_json='["senior"]')) is None


def test_short_title_exclusion_does_not_match_inside_another_word():
    excluded = profile(excluded_keywords_json='["it"]')
    assert hard_exclusion_reason(job(title="Network Security Integrations"), excluded) is None
    assert hard_exclusion_reason(job(title="IT Support Engineer"), excluded)


def test_desired_job_title_is_a_strong_sorting_preference():
    preferred = score_job(job(title="Backend Engineer"), profile(desired_titles_json='["backend", "ai engineer"]'))
    unrelated = score_job(job(title="Technical Support Specialist"), profile(desired_titles_json='["backend", "ai engineer"]'))
    assert preferred.score >= unrelated.score + 35


def test_research_role_and_modern_skills_are_recognized():
    result = score_job(
        job(title="R&D Research Engineer", description="Build LLM systems with PyTorch, Kafka and AWS"),
        profile(desired_titles_json='["research engineer"]', skills_json='["pytorch", "aws"]'),
    )
    assert {"llm", "pytorch", "kafka", "aws"}.issubset(result.skills)
    assert any(reason["label"] == "כותרת תפקיד מועדפת" for reason in result.reasons)


def test_higher_ranked_title_receives_more_points():
    high = score_job(job(title="Backend Engineer"), profile(desired_titles_json='["backend", "software"]'))
    low = score_job(job(title="Backend Engineer"), profile(desired_titles_json='["software", "backend"]'))
    high_reason = next(reason for reason in high.reasons if reason["label"] == "כותרת תפקיד מועדפת")
    low_reason = next(reason for reason in low.reasons if reason["label"] == "כותרת תפקיד מועדפת")
    assert high_reason["priority"] == 1
    assert low_reason["priority"] == 2
    assert high_reason["points"] > low_reason["points"]


def test_score_is_always_bounded_to_one_hundred():
    result = score_job(
        job(company="Google", workplace="hybrid"),
        profile(preferred_work_modes_json='["hybrid", "remote"]'),
    )
    assert 0 <= result.score <= 100


def test_preferred_work_mode_order_changes_its_bonus():
    first = score_job(job(workplace="hybrid"), profile(preferred_work_modes_json='["hybrid", "remote"]'))
    second = score_job(job(workplace="hybrid"), profile(preferred_work_modes_json='["remote", "hybrid"]'))
    first_reason = next(reason for reason in first.reasons if reason["label"].startswith("אופי עבודה מועדף"))
    second_reason = next(reason for reason in second.reasons if reason["label"].startswith("אופי עבודה מועדף"))
    assert first_reason["points"] > second_reason["points"]


def test_recently_revalidated_job_without_publish_date_is_not_freshness_50():
    result = score_job(
        job(published_at=None, updated_at=datetime.now(timezone.utc), discovered_at=datetime.now(timezone.utc)),
        profile(),
    )
    assert result.breakdown["freshness"] >= 85
    assert any("תאריך פרסום לא זמין" in reason["label"] for reason in result.reasons)


def test_old_explicit_publish_date_is_still_penalized():
    result = score_job(
        job(published_at=datetime.now(timezone.utc) - timedelta(days=45)),
        profile(),
    )
    assert result.breakdown["freshness"] < 50
    assert any(reason["label"] == "משרה ישנה יחסית" for reason in result.reasons)
