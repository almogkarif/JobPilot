from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/"app/static/app.js").read_text()
HTML=(ROOT/"app/static/index.html").read_text()
CSS=(ROOT/"app/static/styles.css").read_text()

def test_locations_are_choice_boxes():
    assert "['Israel','ישראל']" in JS
    assert "['Haifa','חיפה']" in JS
    assert "['Tel Aviv','תל אביב']" in JS
    assert "['Jerusalem','ירושלים']" in JS
    assert "onboardingChoiceBox('location'" in JS
    assert "preferred_locations:selected('location')" in JS
    assert 'id="ob-locations"' not in JS

def test_ready_screen_is_launchpad_style():
    assert 'onboarding-launchpad' in JS
    assert 'ready-spotlight' in JS
    assert 'ready-facts' in JS
    assert 'ready-next' in JS
    assert '.ready-spotlight' in CSS

def test_assets_bumped_v5():
    assert 'app.js?v=0.29.1' in HTML
    assert 'styles.css?v=0.48.3' in HTML
