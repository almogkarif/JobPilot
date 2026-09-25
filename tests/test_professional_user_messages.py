from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")


def test_regular_users_receive_professional_errors_while_admin_keeps_diagnostics():
    assert "function professionalMessage(value = '')" in JS
    assert "technicalDetailsAllowed()" in JS
    assert "מנהל המערכת יקבל את הפרטים הטכניים" in JS
    assert "professionalMessage(source.last_error)" in JS
    assert "professionalMessage(item.error)" in JS
    assert "professionalMessage(event.message)" in JS


def test_regular_application_copy_describes_outcomes_instead_of_infrastructure():
    assert "אם אתר הגיוס דורש אימות אנושי" in HTML
    assert "ההגשה תיעצר ותבקש את עזרתך" in HTML
    assert "הגשה מאובטחת ברקע" in JS
    assert "הדפדפן המאובטח עדיין לא מוכן" in JS
    assert "שירות ההגשה הופעל" in JS


def test_admin_only_sections_keep_technical_controls_and_terms():
    assert 'class="panel settings-card settings-integration-card admin-worker-setting"' in HTML
    assert "GitHub Actions Worker" in JS
    assert "loadDeveloperSources" in JS
