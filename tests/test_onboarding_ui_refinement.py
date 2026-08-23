from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/"app/static/app.js").read_text()
HTML=(ROOT/"app/static/index.html").read_text()
CSS=(ROOT/"app/static/styles.css").read_text()

def test_resume_has_clear_success_state():
    assert "onboarding-upload-success" in JS
    assert "קורות החיים מוכנים" in JS
    assert "profile.cv_filename" in JS

def test_preferences_are_choice_boxes_not_raw_primary_text_fields():
    assert "onboardingChoiceBox('title'" in JS
    assert "onboardingChoiceBox('keyword'" in JS
    assert "onboardingChoiceBox('excluded'" in JS
    assert "onboarding-choice-grid" in CSS
    assert "ob-titles-extra" in JS

def test_review_hands_off_to_personal_ranking_without_starting_a_scan():
    assert "onboarding-launchpad" in JS
    assert 'id="onboarding-ranking-status" class="scan-status onboarding-scan-status is-running"' in JS
    assert "renderOnboardingRankingStatus" in JS
    assert "onboardingWatchRanking" in JS
    assert "/api/ranking/refresh" in JS
    assert "/api/ranking/status" in JS
    assert "אין כאן סריקה חדשה" in JS
    assert "onboarding-source-scan" not in JS

def test_logo_flight_dot_uses_the_same_animated_target_geometry_as_site_logo():
    assert ".onboarding-brand .brand-flight-dot" in CSS
    assert 'onboarding-wordmark" dir="ltr">JobP<span class="brand-i">' in HTML
    assert ".onboarding-brand .brand-i-dot" in CSS
    assert "right:41px!important" not in CSS
    assert "--onboarding-mark-size" not in CSS

def test_assets_bumped():
    assert "app.js?v=0.30.0" in HTML
    assert "styles.css?v=0.50.0" in HTML
