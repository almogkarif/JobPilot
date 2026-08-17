from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app" / "static" / "app.js").read_text()
CSS = (ROOT / "app" / "static" / "styles.css").read_text()
MAIN = (ROOT / "app" / "main.py").read_text()
HTML = (ROOT / "app" / "static" / "index.html").read_text()


def test_user_inspector_cards_are_interactive():
    assert "data-developer-section" in JS
    assert "openDeveloperUserSection" in JS
    assert "developer-inspector-list" in CSS
    assert "app.js?v=0.29.8" in HTML
    assert "styles.css?v=0.49.1" in HTML


def test_admin_can_reopen_onboarding_and_reset_profile_for_selected_user():
    assert '/api/admin/developer/users/{user_id}/onboarding/reset' in MAIN
    assert '/api/admin/developer/users/{user_id}/profile/reset' in MAIN
    assert "הפעל Onboarding מחדש" in JS
    assert "אפס פרופיל" in JS
    assert "typed!=='RESET'" in JS


def test_admin_can_inspect_and_open_user_resumes():
    assert '/api/admin/developer/users/{user_id}/section/{section}' in MAIN
    assert '/api/admin/developer/users/{user_id}/resumes/{resume_id}/file' in MAIN
    assert "פתח קובץ" in JS
