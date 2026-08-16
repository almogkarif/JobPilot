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

def test_review_and_scan_reuse_the_real_site_scan_component():
    assert "onboarding-launchpad" in JS
    assert 'id="onboarding-scan-status" class="scan-status onboarding-scan-status"' in JS
    assert "syncOnboardingScanStatus" in JS
    assert "renderScan(scan)" in JS
    assert "onboarding-source-scan" not in JS

def test_logo_flight_dot_uses_the_same_animated_target_geometry_as_site_logo():
    assert ".onboarding-brand .brand-flight-dot" in CSS
    assert 'onboarding-wordmark" dir="ltr">JobP<span class="brand-i">' in HTML
    assert ".onboarding-brand .brand-i-dot" in CSS
    assert "right:41px!important" not in CSS
    assert "--onboarding-mark-size" not in CSS

def test_assets_bumped():
    assert "app.js?v=0.29.7" in HTML
    assert "styles.css?v=0.49.0" in HTML
