from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_auto_apply_queue_has_persistent_visual_waiting_state():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")

    assert "ממתינה בתור להגשה אוטומטית" in js
    assert "תופעל אוטומטית ברצף" in js
    assert "Number(dashboard.queued)" in js
    assert "ממתינות להגשה אוטומטית" in js
    assert "queue_position" in js
    assert "application-live-queue" in js
    assert ".application-live-queue" in css
    assert ".application-live-tracker.has-queue" in css


def test_profile_grade_sheet_reuse_is_automatic_not_a_user_confirmation():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert "grade_sheet_auto_requeued" in js
    assert "גיליון הציונים כבר נמצא בפרופיל" in js
    assert "מצרף אותו אוטומטית" in js
    assert "השתמש בגיליון הציונים השמור והמשך" not in js
