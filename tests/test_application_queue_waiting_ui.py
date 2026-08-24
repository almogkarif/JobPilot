from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def test_auto_apply_queue_has_persistent_visual_waiting_state():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")

    assert "ממתינה בתור להגשה אוטומטית" in js
    assert "תופעל אוטומטית ברצף" in js
    assert "autoQueue.total_active_count" in js
    assert "otherAutoQueueItems" in js
    assert "ממתינות להגשה אוטומטית" in js
    assert "queue_position" in js
    assert "application-live-queue" in js
    assert ".application-live-queue" in css
    assert ".application-live-tracker.has-queue" in css


def test_profile_grade_sheet_reuse_is_automatic_not_a_user_confirmation():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert "grade_sheet_auto_requeued" in js
    assert "הפרטים והמסמכים מולאו" in js
    assert "גיליון הציונים (אם נדרש)" in js
    assert "גיליון הציונים קיים בפרופיל, אבל לא צורף לטופס" in js
    assert "מצרף אותו אוטומטית ומחזיר את ההגשה לתור" not in js
    assert "השתמש בגיליון הציונים השמור והמשך" not in js
    assert "latestAttemptId" in js
    assert "attemptEvents" in js


def test_auto_apply_queue_count_and_modal_include_the_running_application():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert "const autoQueueCount=autoQueue.total_active_count" in js
    assert "המשרה הירוקה היא הפעילה כעת" in js
    assert "משרות פעילות'} בתור" in js


def test_attention_tab_has_single_card_navigation_between_failed_submissions():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
    assert "function renderActiveBlocker" in js
    assert "function moveBetweenBlockers" in js
    assert "מתוך ${state.blockers.length}" in js
    assert "בדיוק מה עצר כל אחת" in js
    assert ".blocker-navigator" in css


def test_notification_tracker_navigates_all_unfinished_auto_applications_and_retries_failures():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
    assert "TRACKABLE_APPLICATION_STATUSES" in js
    assert "/api/applications/tracking-list?current_id=" in js
    assert "item.status==='queued'&&(Number(item.attempt_count||0)>0" in js
    assert ".sort((a,b)=>Number(a.id)-Number(b.id))" in js
    assert "trackingPinnedByUser=false" in js
    assert "startApplicationTracking(trackingApplications[next].id,false,true)" in js
    assert "(index+Number(direction||0)+total)%total" in js
    assert "index===total-1?'disabled'" not in js
    assert "if(!trackingPinnedByUser&&['verification_pending','failed','needs_input']" in js
    assert "trackingNavigatorMarkup(applicationTrackingData?.application?.status" in js
    assert "משרה ${index+1} מתוך ${total}" in js
    assert "title=\"הגשה מחדש\"" in js
    assert "['failed','needs_input'].includes(status)" in js
    assert "status==='queued'&&attemptCount>0" in js
    assert "/retry?auto_submit=true" in js
    assert "application-list-number" in js
    assert ".application-tracker-navigator" in css
    assert ".application-live-tracker.has-running{border:2px solid #35a66f" in css
    assert "copyApplicationFailureDiagnostics" in js
    assert "העתק אבחון של ההגשות שלא הושלמו" in js
    assert ".auto-queue-current.is-active" in css
    assert "בהכנה עכשיו" in js
    assert "המשרה הירוקה היא הפעילה כעת" in js


def test_tracking_list_is_a_compact_payload_not_full_application_history():
    with TestClient(app) as client:
        response = client.get("/api/applications/tracking-list", params={"current_id": 0})
    assert response.status_code == 200
    for row in response.json():
        assert set(row) == {"id", "status", "mode", "attempt_count", "updated_at", "job"}
        assert set(row["job"]) == {"title", "company"}
        assert "attempts" not in row
        assert "blocker" not in row
