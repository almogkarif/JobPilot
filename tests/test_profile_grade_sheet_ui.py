from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text()
JS = (ROOT / "app" / "static" / "app.js").read_text()
CSS = (ROOT / "app" / "static" / "styles.css").read_text()


def test_grade_sheet_is_a_persistent_profile_document_next_to_resume():
    assert 'data-profile-document="resume"' in HTML
    assert 'data-profile-document="grade-sheet"' in HTML
    assert 'id="grade-sheet-name"' in HTML
    assert 'id="upload-grade-sheet"' in HTML
    assert 'id="grade-sheet-file"' in HTML
    assert "/api/profile/grade-sheet" in JS
    assert "נשמר בפרופיל ומשמש בכל הגשה" in HTML
    assert ".profile-documents-grid" in CSS


def test_grade_sheet_blocker_routes_to_profile_instead_of_application_scoped_upload():
    assert "grade_sheet_required" in JS
    assert "openGradeSheetProfile()" in JS
    assert "העלה גיליון ציונים בפרופיל" in JS
    assert "/api/blockers/${blockerId}/file" not in JS
    assert "הקובץ נשמר להגשה הזאת בלבד" not in JS
