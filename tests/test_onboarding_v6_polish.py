from tests.asset_versions import asset_version_at_least
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/"app/static/app.js").read_text()
CSS=(ROOT/"app/static/styles.css").read_text()
HTML=(ROOT/"app/static/index.html").read_text()

def test_seniority_has_junior_and_mid_choices():
    assert "['junior','Junior']" in JS
    assert "['mid level','Mid Level']" in JS

def test_onboarding_experience_preferences_are_a_single_explicit_filter():
    for value in ("student", "entry level", "junior", "mid level", "senior", "lead", "staff", "manager"):
        assert f"['{value}'" in JS
    assert "רמות ניסיון להצגה" in JS and "רמות ניסיון להצגה" in HTML
    assert "לא צוינה רמת ניסיון" in JS and "לא צוינה רמת ניסיון" in HTML
    assert 'data-profile-option="excluded_keywords"' not in HTML
    assert 'data-profile-option="keywords"' not in HTML
    assert "ללא סימון לא יוצגו משרות" in JS and "ללא סימון לא יוצגו משרות" in HTML

def test_all_steps_receive_shared_visual_step_class():
    assert "onboarding-step-${step}" in JS
    assert ".onboarding-step{" in CSS

def test_ranking_waits_for_personal_catalog_ranking_before_declaring_completion():
    assert "onboardingWatchRanking" in JS
    assert "status.ready" in JS
    assert "ranked/total" in JS
    assert "renderOnboardingRankingStatus" in JS
    assert "למשרות שנבחרו עבורך" in JS

def test_assets_bumped():
    assert asset_version_at_least(HTML, "app.js", "0.31.20")
    assert asset_version_at_least(HTML, "styles.css", "0.52.18")
