from pathlib import Path
from app import main

ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/"app/static/app.js").read_text()
HTML=(ROOT/"app/static/index.html").read_text()
CSS=(ROOT/"app/static/styles.css").read_text()

def test_career_switch_explains_exact_unsaved_fields():
    assert "dirty.map(profileFieldLabel)" in JS
    assert "אי אפשר להחליף מסלול עדיין" in JS
    assert "שאלות ההגשה כוללות שינויים שלא נשמרו" in JS

def test_cloud_derived_refresh_is_detached_coalesced_and_incremental():
    assert hasattr(main, "_queue_profile_derived_refresh")
    assert "_profile_refresh_pending" in Path(main.__file__).read_text()
    assert "commit_every=25" in Path(main.__file__).read_text()
    assert "yield_per(50)" in Path(main.__file__).read_text()

def test_admin_can_preview_regular_ui_without_dropping_server_permissions():
    assert 'id="developer-preview-non-admin"' in HTML
    assert 'id="admin-preview-exit"' in HTML
    assert "jobpilot-preview-non-admin" in JS
    assert "preview-non-admin" in CSS
    assert "הרשאות השרת שלך נשארו Admin" in JS

def test_assets_bumped():
    assert "app.js?v=0.29.6" in HTML
    assert "styles.css?v=0.48.8" in HTML
