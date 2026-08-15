from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/"app/static/app.js").read_text()
CSS=(ROOT/"app/static/styles.css").read_text()
HTML=(ROOT/"app/static/index.html").read_text()

def test_excluded_has_junior_and_mid_choices():
    assert "['junior','Junior']" in JS
    assert "['mid','Mid']" in JS

def test_all_steps_receive_shared_visual_step_class():
    assert "onboarding-step-${step}" in JS
    assert ".onboarding-step{" in CSS

def test_scan_waits_for_server_before_showing_counts():
    assert "ממתין לשרת" in JS
    assert "השרת מכין את רשימת המקורות לסריקה" in JS
    assert "source-scan-progress waiting" in JS
    assert "onboardingWaitingBar" in CSS

def test_assets_bumped():
    assert "app.js?v=0.29.1" in HTML
    assert "styles.css?v=0.48.4" in HTML
