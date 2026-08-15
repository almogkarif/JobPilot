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

def test_review_and_scan_match_product_visual_language():
    assert "onboarding-launchpad" in JS
    assert "onboarding-source-scan" in JS
    assert "onboarding-source-progress" in JS
    assert "onboarding-radar" not in JS

def test_logo_flight_dot_has_onboarding_specific_anchor():
    assert ".onboarding-brand .brand-flight-dot" in CSS
    assert "top:8px" in CSS and "right:41px" in CSS

def test_assets_bumped():
    assert "app.js?v=0.29.1" in HTML
    assert "styles.css?v=0.48.0" in HTML
