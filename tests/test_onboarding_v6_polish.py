from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/"app/static/app.js").read_text()
CSS=(ROOT/"app/static/styles.css").read_text()
HTML=(ROOT/"app/static/index.html").read_text()

def test_excluded_has_junior_and_mid_choices():
    assert "['junior','Junior']" in JS
    assert "['mid level','Mid Level']" in JS

def test_onboarding_experience_preferences_match_main_editor_and_show_negative_x():
    for value in ("student", "entry level", "junior", "mid level", "senior", "lead", "staff", "manager"):
        assert f"['{value}'" in JS
    assert "רמות ניסיון שתרצה לראות" in JS
    assert 'רמות ניסיון ש<span class="negative-word">לא</span> לחפש עבורך' in JS
    assert "onboarding-choice-negative" in JS
    assert ".onboarding-choice-negative.selected" in CSS

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
    assert "app.js?v=0.30.0" in HTML
    assert "styles.css?v=0.50.0" in HTML
