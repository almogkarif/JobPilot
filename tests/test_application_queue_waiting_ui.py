from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Job

ROOT = Path(__file__).resolve().parents[1]


def test_auto_apply_queue_has_persistent_visual_waiting_state():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")

    assert "ממתינה בתור להגשה אוטומטית" in js
    assert "תופעל אוטומטית ברצף" in js
    assert "autoQueue.total_active_count" in js
    assert "otherAutoQueueItems" in js
    assert "משרות ממתינות בתור" in js
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
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
    assert "const autoQueueCount=autoQueue.total_active_count" in js
    assert "items.push({ view:'applications', count:autoQueueCount, queue:true, persistent:true })" in js
    assert "משרות ממתינות בתור" in js
    assert "אין כרגע משרות בתור — לחץ כדי לפתוח את התור" in js
    assert "אין הגשות פעילות" in js
    assert "actionableItems=items.filter(item=>!item.queue||Number(item.count)>0)" in js
    assert "queueNotices=items.filter(item=>item.queue).map(notificationMarkup).join('')" in js
    assert "root.innerHTML=tracker+queueNotices+otherNotices" in js
    assert "notification-queue-shortcut" in js
    assert ".notification-queue-shortcut" in css
    assert ".notification-queue-shortcut { position:relative" in css
    assert "הגשות שרצות, ממתינות או דורשות טיפול" in js
    assert "דורשות טיפול" in js
    assert "attention:Array.isArray" in js
    assert "data-choice-blocker" in js
    assert "workers פעילים" in js
    assert "queue.running" in js
    assert "function combinedApplicationQueue" in js
    assert "Promise.all([refreshAutoApplyQueue(),refreshTrackingApplications()])" in js
    assert "הרשימה כוללת את כל ההגשות שמופיעות במרכז ההתראות" in js
    assert "running_count" in js
    assert "tone-${tone}" in js
    assert ".auto-apply-queue-list article.tone-danger" in css
    assert "כפילות אפשרית" in js
    assert ".application-live-tracker.has-duplicate" in css
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
    assert "if(!trackingPinnedByUser&&['verification_pending','failed','needs_input','manual_required']" in js
    assert "trackingNavigatorMarkup(applicationTrackingData?.application?.status" in js
    assert "משרה ${index+1} מתוך ${total}" in js
    assert "title=\"הגשה מחדש\"" in js
    assert "['failed','needs_input','verification_pending'].includes(status)" in js
    assert "manual_required" in js
    assert "anti_automation_blocked" in js
    assert "פתח להגשה ידנית" in js
    assert "פתח בדיקה מונחית" in js
    assert "openInteractiveBlockedApplication(${data.application.id},this)" in js
    assert "פתח צפייה חיה" in js
    assert "viewInteractiveApplication(${data.application.id})" in js
    assert "blindRetryBlocked=['submit_not_sent','anti_automation_blocked'].includes(blockerKind)" in js
    assert "guidedFailureAction=failed&&!manualRequired&&['submit_not_sent','anti_automation_blocked'].includes(blocker?.kind)" in js
    assert "data.application?.live_view_ready?'':`<button" in js
    assert "JobPilot לא יבצע retry אוטומטי נוסף" in js
    assert "status==='queued'&&attemptCount>0" in js
    assert "/retry?auto_submit=true" in js
    assert "application-list-number" in js
    assert ".application-tracker-navigator" in css
    assert ".application-live-tracker.has-running{border:2px solid #35a66f" in css
    assert "copyApplicationFailureDiagnostics" in js
    assert "העתק אבחון של ההגשות שלא הושלמו" in js
    assert "/api/applications/failure-diagnostics" in js
    assert "await refreshTrackingApplications()" in js
    assert "?application_ids=${ids.join(',')}" in js
    assert "needs_input: ${Number(summary.needs_input||0)}" in js
    assert "YELLOW_QUESTION" in js
    assert "RED_ERROR" in js
    assert "recent_timeline" in js
    assert "recent_attempts" in js
    assert "blocker_diagnostics" in js
    assert "profile_readiness" in js
    assert "security_code_required" in js
    assert "/security-code" in js
    assert "autocomplete=\"one-time-code\"" in js
    assert "applicationSecurityCodeDrafts" in js
    assert ".auto-queue-current.is-active" in css
    assert "ממתינה להפעלת שירות ההגשה ברקע" in js
    assert "בקשת ההפעלה התקבלה" in js
    assert "GitHub קיבל את הבקשה" in js
    assert "technicalDetailsAllowed()" in js
    assert "dispatch_sent_waiting" in js
    assert "needs_redispatch" in js
    assert "הגשות שרצות, ממתינות או דורשות טיפול" in js
    assert "autoQueueAttentionMarkup" in js
    assert "retryAutomaticApplication" in js
    assert "automaticRetryInFlight" in js
    assert "retryAllAutoQueueApplications" in js
    assert "הפעל מחדש את כולן" in js
    assert "application-tracker-retry auto-queue-retry" in js
    assert ".auto-queue-row-actions .auto-queue-retry" in css
    assert "function clearApplicationTracking()" in js
    assert "async function reconcileTrackingAfterSubmitted(applicationId)" in js
    assert "localStorage.removeItem('jobpilot-tracked-application')" in js
    assert "await reconcileTrackingAfterSubmitted(id)" in js


def test_verified_submission_tracker_is_cleared_but_attention_states_remain_trackable():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")

    # A verified/finished submission should not remain as the live tracker when
    # there is no next queued or attention item.
    assert "async function advanceTrackingToNextAutoQueue()" in js
    assert "refreshTrackingApplications()" in js
    assert "if(currentStatus==='submitted'){clearApplicationTracking();renderNotificationCenter();return}" in js

    # States that are still waiting for user feedback/action stay in the
    # tracking list and therefore can become the next tracker instead of being
    # discarded as completed.
    assert "TRACKABLE_APPLICATION_STATUSES=new Set(['applying','needs_input','manual_required','verification_pending','failed'])" in js
    assert "const feedbackNext=trackingApplications.find(item=>Number(item.id)!==finishedId)" in js


def test_tracking_list_is_a_compact_payload_not_full_application_history():
    with TestClient(app) as client:
        response = client.get("/api/applications/tracking-list", params={"current_id": 0})
    assert response.status_code == 200
    for row in response.json():
        assert set(row) == {"id", "status", "mode", "attempt_count", "updated_at", "job"}
        assert set(row["job"]) == {"title", "company"}
        assert "attempts" not in row
        assert "blocker" not in row


def test_tracking_list_includes_active_interactive_review_application(monkeypatch):
    monkeypatch.setattr("app.main.dispatch_interactive_application_workflow", lambda _application_id: None)
    with TestClient(app) as client:
        unique = uuid4().hex
        job = client.post("/api/jobs/import", json={
            "title": "Interactive tracking regression",
            "company": "Paragon",
            "apply_url": f"https://boards.greenhouse.io/paragon/jobs/{unique}",
            "location": "Tel Aviv",
        }).json()
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"})
        assert queued.status_code == 200, queued.text
        application_id = queued.json()["id"]

        response = client.get("/api/applications/tracking-list", params={"current_id": application_id})
        assert response.status_code == 200
        tracked = next(item for item in response.json() if item["id"] == application_id)
        assert tracked["mode"] == "audit"
        assert tracked["status"] == "queued"


def test_tracking_list_excludes_interactive_rows_for_unsupported_companies(monkeypatch):
    monkeypatch.setattr("app.main.dispatch_interactive_application_workflow", lambda _application_id: None)
    with TestClient(app) as client:
        unique = uuid4().hex
        job = client.post("/api/jobs/import", json={
            "title": "Unsupported interactive tracking regression",
            "company": "Supported Before Policy Change",
            "apply_url": f"https://boards.greenhouse.io/example/jobs/{unique}",
            "location": "Rehovot",
        }).json()
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"})
        assert queued.status_code == 200, queued.text
        with SessionLocal() as db:
            stored_job = db.get(Job, job["id"])
            stored_job.company = "Applied Materials"
            stored_job.apply_url = f"https://amat.wd1.myworkdayjobs.com/jobs/{unique}"
            db.commit()

        response = client.get("/api/applications/tracking-list", params={"current_id": queued.json()["id"]})
        assert response.status_code == 200
        assert all(item["id"] != queued.json()["id"] for item in response.json())
