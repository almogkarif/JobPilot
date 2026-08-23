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
    source = Path(main.__file__).read_text()
    assert "commit_every=25" in source
    assert "commit_every=10" in source
    assert "yield_per(50)" in source
    assert "_global_profile_refresh_semaphore" in source
    assert "stale_only=not rescore_jobs" in source

def test_admin_preview_uses_regular_user_permissions_with_only_return_control_extra():
    assert 'id="developer-preview-non-admin"' in HTML
    assert 'id="admin-preview-exit"' in HTML
    assert "jobpilot-preview-non-admin" in JS
    assert "X-JobPilot-Preview-Role" in JS
    assert "authState.capabilities?.developer_tools === true" in JS
    assert ".preview-non-admin .admin-only-nav" not in CSS
    assert ".preview-non-admin #view-developer" not in CSS
    assert "הרשאות השרת שלך נשארו Admin" not in JS

def test_assets_bumped():
    assert "app.js?v=0.30.0" in HTML
    assert "styles.css?v=0.50.0" in HTML
