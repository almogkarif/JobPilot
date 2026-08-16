from pathlib import Path
from app.models import Profile

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text()
JS = (ROOT / "app/static/app.js").read_text()
CSS = (ROOT / "app/static/styles.css").read_text()

def test_onboarding_assets_and_admin_preview_exist():
    assert 'id="onboarding-gate"' in HTML
    assert 'data-view="developer"' in HTML
    assert 'id="developer-preview-onboarding"' in HTML
    assert 'app.js?v=0.29.6' in HTML
    assert 'styles.css?v=0.48.8' in HTML
    assert "const ONBOARDING_VERSION = 2" in JS
    assert "maybeOpenOnboarding" in JS
    assert ".onboarding-gate" in CSS

def test_profile_has_persistent_onboarding_state():
    assert hasattr(Profile, "onboarding_version")
    assert hasattr(Profile, "onboarding_state_json")
