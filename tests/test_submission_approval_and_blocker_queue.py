from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import ONE_TIME_SUBMIT_KEY, app
from app.models import Application, ApplicationAttempt, ApplicationEvent, Blocker
from app.utils import loads


def _make_job(client: TestClient, title: str) -> dict:
    unique = uuid4().hex
    response = client.post(
        "/api/jobs/import",
        json={
            "title": title,
            "company": f"Approval Test {unique[:8]}",
            "location": "Tel Aviv, Israel",
            "description": "Junior Python C++ software role, zero to one years experience.",
            "apply_url": f"https://example.com/apply/{unique}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_failure_diagnostics_contains_question_error_attempt_and_timeline():
    with TestClient(app) as client:
        job = _make_job(client, "Diagnostic snapshot engineer")
        application = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"}).json()
        with SessionLocal() as db:
            stored = db.get(Application, application["id"])
            stored.mode = "auto"
            stored.status = "needs_input"
            stored.last_error = "red raw failure"
            stored.answers_json = '{"Approved question":"Approved answer","__jobpilot_internal":true}'
            db.add(Blocker(
                application_id=stored.id, kind="choice_required", field_label="Python experience",
                question="Do you have Python experience?", explanation="yellow choice required",
                options_json='["Yes","No"]', page_url="https://example.com/form",
            ))
            db.add(ApplicationAttempt(
                application_id=stored.id, attempt_number=1, idempotency_key="diagnostic-attempt",
                adapter="greenhouse", worker_type="cloud", status="blocked",
                verification_state="none", error="attempt-level failure",
            ))
            db.add(ApplicationEvent(
                application_id=stored.id, event_type="blocked", from_status="applying",
                to_status="needs_input", actor="agent", message="timeline failure",
                details_json='{"stage":"details_filled"}',
            ))
            db.commit()

        response = client.get("/api/applications/failure-diagnostics")
        assert response.status_code == 200, response.text
        row = next(item for item in response.json()["applications"] if item["application_id"] == application["id"])
        assert row["yellow_question"]["question"] == "Do you have Python experience?"
        assert row["yellow_question"]["options"] == ["Yes", "No"]
        assert row["red_error"]["last_error"] == "red raw failure"
        assert row["saved_answers"] == {"Approved question": "Approved answer"}
        assert row["attempts"][0]["error"] == "attempt-level failure"
        assert row["events"][0]["details"] == {"stage": "details_filled"}


def _isolate_queue(application_id: int) -> None:
    with SessionLocal() as db:
        for application in db.scalars(select(Application)).all():
            if application.id != application_id and application.status in {"queued", "applying", "needs_input"}:
                application.status = "skipped"
                application.job.status = "skipped"
        db.commit()


def _queue_and_claim(client: TestClient, job: dict) -> tuple[int, dict]:
    queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
    assert queued.status_code == 200, queued.text
    application_id = queued.json()["id"]
    _isolate_queue(application_id)
    task_response = client.get(
        "/api/agent/tasks/next", params={"agent_id": "approval-test", "token": "change-me"}
    )
    assert task_response.status_code == 200, task_response.text
    task = task_response.json()["task"]
    assert task and task["application"]["id"] == application_id
    return application_id, task


def test_security_code_is_delivered_only_to_the_active_attempt_and_then_erased():
    with TestClient(app) as client:
        job = _make_job(client, "Greenhouse security code engineer")
        application_id, task = _queue_and_claim(client, job)
        attempt_id = task["attempt"]["id"]

        waiting = client.post(
            f"/api/agent/tasks/{application_id}/security-code",
            json={"token": "change-me", "attempt_id": attempt_id},
        )
        assert waiting.status_code == 200, waiting.text
        assert waiting.json() == {"code": "", "waiting": True}

        listed = next(item for item in client.get("/api/applications").json() if item["id"] == application_id)
        assert listed["status"] == "applying"
        assert listed["blocker"]["kind"] == "security_code_required"
        assert listed["blocker"].get("answer", "") == ""

        invalid = client.post(f"/api/applications/{application_id}/security-code", json={"code": "12-34"})
        assert invalid.status_code == 422
        accepted = client.post(
            f"/api/applications/{application_id}/security-code", json={"code": "2TXo8FkJ"}
        )
        assert accepted.status_code == 200, accepted.text

        delivered = client.post(
            f"/api/agent/tasks/{application_id}/security-code",
            json={"token": "change-me", "attempt_id": attempt_id},
        )
        assert delivered.json() == {"code": "2TXo8FkJ", "waiting": False}
        filled = client.post(
            f"/api/agent/tasks/{application_id}/progress",
            json={"token": "change-me", "attempt_id": attempt_id, "stage": "security_code_filled"},
        )
        assert filled.status_code == 200, filled.text
        with SessionLocal() as db:
            blocker = db.scalar(select(Blocker).where(
                Blocker.application_id == application_id, Blocker.kind == "security_code_required"
            ))
            assert blocker.status == "resolved"
            assert blocker.answer == ""


def test_final_review_approval_is_consumed_once_and_really_authorizes_next_attempt():
    with TestClient(app) as client:
        job = _make_job(client, "Junior One-Time Approval Engineer")
        application_id, first_task = _queue_and_claim(client, job)
        assert first_task["submit_approved_once"] is False

        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "review_before_submit",
                "field_label": "אישור הגשה",
                "question": "האם לאשר את שליחת המועמדות?",
                "explanation": "כל השדות מולאו. נדרש אישור לפני שליחה.",
                "options": ["אשר ושלח", "דלג"],
                "page_url": "https://example.com/apply/review-ready",
            },
        )
        assert blocked.status_code == 200, blocked.text
        blocker_id = blocked.json()["id"]

        applications = client.get("/api/applications").json()
        listed = next(item for item in applications if item["id"] == application_id)
        assert listed["status"] == "needs_input"
        assert listed["blocker"]["kind"] == "review_before_submit"
        assert listed["blocker"]["page_url"] == "https://example.com/apply/review-ready"
        assert listed["last_error"].startswith("[blocked:review_before_submit]")

        approved = client.post(
            f"/api/blockers/{blocker_id}/resolve",
            json={"action": "approve_submit"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["answer"] == "אשר ושלח"

        with SessionLocal() as db:
            stored = db.get(Application, application_id)
            assert loads(stored.answers_json, {})[ONE_TIME_SUBMIT_KEY] is True
            assert stored.status == "queued"

        second_task = client.get(
            "/api/agent/tasks/next", params={"agent_id": "approval-test", "token": "change-me"}
        ).json()["task"]
        assert second_task["application"]["id"] == application_id
        assert second_task["submit_approved_once"] is True
        assert ONE_TIME_SUBMIT_KEY not in second_task["answers"]

        # The approval is consumed when claimed. A failed attempt must require a new approval.
        failed = client.post(
            f"/api/agent/tasks/{application_id}/failed",
            json={"token": "change-me", "message": "Synthetic browser failure"},
        )
        assert failed.status_code == 200
        retried = client.post(f"/api/applications/{application_id}/retry")
        assert retried.status_code == 200
        third_task = client.get(
            "/api/agent/tasks/next", params={"agent_id": "approval-test", "token": "change-me"}
        ).json()["task"]
        assert third_task["application"]["id"] == application_id
        assert third_task["submit_approved_once"] is False


def test_explicit_auto_retry_reapproves_and_dispatches_failed_application(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        job = client.post("/api/jobs/import", json={
            "title": "Retry Engineer", "company": "Retry Co", "location": "Israel",
            "apply_url": "https://boards.greenhouse.io/retryco/jobs/987",
        }).json()
        application = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"}).json()
        with SessionLocal() as db:
            stored = db.get(Application, application["id"])
            stored.mode = "auto"
            stored.status = "failed"
            stored.job.status = "failed"
            db.commit()

        retried = client.post(f"/api/applications/{application['id']}/retry?auto_submit=true")
        assert retried.status_code == 200, retried.text
        assert retried.json()["status"] == "queued"
        assert dispatched == [application["id"]]
        duplicate_click = client.post(f"/api/applications/{application['id']}/retry?auto_submit=true")
        assert duplicate_click.status_code == 200, duplicate_click.text
        assert duplicate_click.json()["status"] == "queued"
        assert dispatched == [application["id"]]
        with SessionLocal() as db:
            stored = db.get(Application, application["id"])
            assert loads(stored.answers_json, {})[ONE_TIME_SUBMIT_KEY] is True


def test_verification_pending_retry_requires_explicit_no_receipt_confirmation(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        unique = uuid4().hex
        job = client.post("/api/jobs/import", json={
            "title": "Unverified submission retry engineer",
            "company": "Supported Greenhouse Retry",
            "location": "Tel Aviv, Israel",
            "description": "Software role",
            "apply_url": f"https://boards.greenhouse.io/supportedretry/jobs/{unique}",
        }).json()
        application = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"}).json()
        with SessionLocal() as db:
            stored = db.get(Application, application["id"])
            stored.mode = "auto"
            stored.status = "verification_pending"
            stored.job.status = "verification_pending"
            db.add(Blocker(
                application_id=stored.id, kind="confirmation_missing", status="open",
                field_label="אישור שליחה", question="האם המועמדות נשלחה?",
                explanation="לא התקבלה ראיה חד־משמעית",
            ))
            db.commit()
        denied = client.post(f"/api/applications/{application['id']}/retry?auto_submit=true")
        assert denied.status_code == 409
        allowed = client.post(
            f"/api/applications/{application['id']}/retry?auto_submit=true&confirm_not_submitted=true"
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["status"] == "queued"
        with SessionLocal() as db:
            blocker = db.scalar(select(Blocker).where(Blocker.application_id == application["id"]))
            assert blocker.status == "resolved"
            assert blocker.answer == "user_confirmed_no_submission_receipt"
        assert dispatched == [application["id"]]


def test_resolving_cloud_auto_blocker_dispatches_next_worker(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        job = _make_job(client, "Auto blocker dispatch engineer")
        application_id, _ = _queue_and_claim(client, job)
        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "choice_required", "field_label": "Family at Mobileye",
                "question": "Is a family member employed by Mobileye?", "explanation": "Answer required",
                "options": ["Yes", "No"],
            },
        ).json()
        listed = next(item for item in client.get("/api/applications").json() if item["id"] == application_id)
        assert listed["blocker"]["kind"] == "choice_required"
        assert listed["blocker"]["options"] == ["Yes", "No"]

        invalid = client.post(
            f"/api/blockers/{blocked['id']}/resolve", json={"answer": "Maybe", "remember": False},
        )
        assert invalid.status_code == 400
        assert next(item for item in client.get("/api/applications").json() if item["id"] == application_id)["status"] == "needs_input"

        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()

        resolved = client.post(
            f"/api/blockers/{blocked['id']}/resolve", json={"answer": "No", "remember": False},
        )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["answer"] == "No"
    assert dispatched == [application_id]


def test_auto_email_blocker_is_resolved_from_saved_profile_without_user_input(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        saved = client.patch("/api/profile", json={"email": "saved@example.com"})
        assert saved.status_code == 200
        job = _make_job(client, "Identity field engineer")
        application_id, _ = _queue_and_claim(client, job)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()
        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "unknown_field", "field_label": "Email",
                "question": "Email", "explanation": "Answer required", "options": [],
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["auto_resolved"] is True
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            assert application.status == "queued"
            assert loads(application.answers_json, {})["Email"] == "saved@example.com"
        assert dispatched == [application_id]


def test_existing_email_blocker_is_repaired_when_tracker_reads_timeline(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        client.patch("/api/profile", json={"email": "saved@example.com"})
        job = _make_job(client, "Existing identity blocker engineer")
        application_id, _ = _queue_and_claim(client, job)
        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "unknown_field", "field_label": "Email",
                "question": "Email", "explanation": "Answer required", "options": [],
            },
        )
        assert blocked.status_code == 200
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()
        timeline = client.get(f"/api/applications/{application_id}/timeline")
        assert timeline.status_code == 200, timeline.text
        assert timeline.json()["application"]["status"] == "queued"
        assert timeline.json()["application"]["blocker"] is None
        assert dispatched == [application_id]


def test_phone_blocker_is_resolved_by_the_same_saved_profile_field_system(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        saved = client.patch("/api/profile", json={"phone": "+972501234567"})
        assert saved.status_code == 200
        job = _make_job(client, "Phone field engineer")
        application_id, _ = _queue_and_claim(client, job)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()
        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "unknown_field", "field_label": "Phone,",
                "question": "Phone,", "explanation": "Answer required", "options": [],
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["auto_resolved"] is True
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            assert loads(application.answers_json, {})["Phone,"] == "+972501234567"
        assert dispatched == [application_id]


def test_referral_source_blocker_uses_safe_default_without_user_input(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        job = _make_job(client, "Referral source field engineer")
        application_id, _ = _queue_and_claim(client, job)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()
        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "unknown_field",
                "field_label": "How did you hear about this job?",
                "question": "How did you hear about this job?", "explanation": "Answer required",
                "options": ["Employee referral", "LinkedIn", "Company careers page"],
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["auto_resolved"] is True
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            assert loads(application.answers_json, {})["How did you hear about this job?"] == "Company careers page"
        assert dispatched == [application_id]


def test_hiring_process_consent_blocker_is_safely_resolved(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        job = _make_job(client, "Hiring process consent engineer")
        application_id, _ = _queue_and_claim(client, job)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()
        question = (
            "By submitting your application you consent to us sharing your information "
            "with a third party supporting us in this hiring process*"
        )
        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "unknown_field", "field_label": question,
                "question": question, "explanation": "Answer required", "options": [],
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["auto_resolved"] is True
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            assert loads(application.answers_json, {})[question] == "Yes"
        assert dispatched == [application_id]


def test_legacy_greenhouse_country_validation_is_repaired_once_without_a_loop(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        job = _make_job(client, "Greenhouse country validation engineer")
        application_id, _ = _queue_and_claim(client, job)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()
        payload = {
            "token": "change-me", "kind": "submit_not_sent", "field_label": "שליחת המועמדות",
            "question": "הטופס לא יצא מ־Greenhouse",
            "explanation": "Greenhouse עצר את השליחה לפני שנשלחה בקשת POST. שדה שלא עבר ולידציה: Country*",
            "options": [],
        }
        first = client.post(f"/api/agent/tasks/{application_id}/blocked", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["auto_resolved"] is True
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            assert loads(application.answers_json, {})["Country*"] == "Israel"

        second = client.post(f"/api/agent/tasks/{application_id}/blocked", json=payload)
        assert second.status_code == 200, second.text
        assert second.json().get("auto_resolved") is not True
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            assert application.status == "needs_input"
        assert dispatched == [application_id]


def test_safe_defaults_stop_dispatching_after_eight_server_side_repairs(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        saved = client.patch("/api/profile", json={"email": "saved@example.com"})
        assert saved.status_code == 200
        job = _make_job(client, "Loop guarded identity engineer")
        application_id, _ = _queue_and_claim(client, job)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            for index in range(8):
                db.add(ApplicationEvent(
                    application_id=application_id, event_type="profile_identity_auto_resolved",
                    actor="system", message=f"repair {index}",
                    details_json='{"field":"old_field_%d","repair_version":"identity_v2"}' % index,
                ))
            db.commit()
        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "unknown_field", "field_label": "Email",
                "question": "Email", "explanation": "Answer required", "options": [],
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json().get("auto_resolved") is not True
        with SessionLocal() as db:
            assert db.get(Application, application_id).status == "needs_input"
        assert dispatched == []


def test_verified_submission_resolves_blockers_from_earlier_attempts():
    with TestClient(app) as client:
        job = _make_job(client, "Resolved stale blocker engineer")
        application_id, task = _queue_and_claim(client, job)
        with SessionLocal() as db:
            blocker = Blocker(
                application_id=application_id, kind="file_required", status="open",
                field_label="Resume", question="Resume", explanation="Resume was missing",
            )
            db.add(blocker)
            db.commit()
            blocker_id = blocker.id
        submitted = client.post(
            f"/api/agent/tasks/{application_id}/submitted",
            json={
                "token": "change-me", "attempt_id": task["attempt"]["id"],
                "message": "Application received", "verification_state": "verified",
                "confirmation_text": "Thank you for applying",
                "evidence": [{"type": "confirmation_text", "value": "Thank you for applying"}],
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "submitted"
        with SessionLocal() as db:
            blocker = db.get(Blocker, blocker_id)
            assert blocker.status == "resolved"
            assert blocker.answer == "resolved_by_verified_submission"


def test_opaque_referral_option_group_chooses_none_of_the_above(monkeypatch):
    dispatched = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    with TestClient(app) as client:
        job = _make_job(client, "Opaque referral group engineer")
        application_id, _ = _queue_and_claim(client, job)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()
        options = ["Riskified blog", "Riskified tech blog", "Meetup", "Podcast", "Conference", "Riskified Social media", "None of the above"]
        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "unknown_field", "field_label": "Riskified blog",
                "question": "Riskified blog", "explanation": "Answer required", "options": options,
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["auto_resolved"] is True
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            assert loads(application.answers_json, {})["Riskified blog"] == "None of the above"
        assert dispatched == [application_id]


def test_captcha_is_exposed_compactly_with_exact_handoff_url_and_can_be_marked_submitted():
    with TestClient(app) as client:
        job = _make_job(client, "Junior CAPTCHA Queue Engineer")
        application_id, _ = _queue_and_claim(client, job)
        exact_url = "https://careers.example.com/application/step-3?session=abc123"

        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "captcha",
                "field_label": "CAPTCHA",
                "question": "נדרש אימות אנושי",
                "explanation": "האתר הציג CAPTCHA או בדיקת אנושיות. הסוכן לא ינסה לעקוף אותה.",
                "page_url": exact_url,
            },
        )
        assert blocked.status_code == 200, blocked.text
        blocker_id = blocked.json()["id"]

        listed = next(item for item in client.get("/api/applications").json() if item["id"] == application_id)
        assert listed["status"] == "needs_input"
        assert listed["blocker"] == {
            "id": blocker_id,
            "kind": "captcha",
            "question": "נדרש אימות אנושי",
            "explanation": "האתר הציג CAPTCHA או בדיקת אנושיות. הסוכן לא ינסה לעקוף אותה.",
            "page_url": exact_url,
            "screenshot_url": "",
        }
        assert listed["last_error"] == (
            "[blocked:captcha] האתר הציג CAPTCHA או בדיקת אנושיות. הסוכן לא ינסה לעקוף אותה."
        )

        submitted = client.post(f"/api/applications/{application_id}/mark-submitted")
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "submitted"
        assert submitted.json()["blocker"] is None
        assert all(item["id"] != blocker_id for item in client.get("/api/blockers").json())

        # Idempotent if the user clicks twice.
        repeated = client.post(f"/api/applications/{application_id}/mark-submitted")
        assert repeated.status_code == 200
        assert repeated.json()["status"] == "submitted"


def test_final_review_can_be_skipped_without_returning_to_queue():
    with TestClient(app) as client:
        job = _make_job(client, "Junior Review Skip Engineer")
        application_id, _ = _queue_and_claim(client, job)
        blocker = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "review_before_submit",
                "question": "האם לאשר את שליחת המועמדות?",
                "explanation": "Ready for final submit",
                "page_url": "https://example.com/review-skip",
            },
        ).json()
        skipped = client.post(
            f"/api/blockers/{blocker['id']}/resolve",
            json={"action": "skip"},
        )
        assert skipped.status_code == 200, skipped.text
        listed = next(item for item in client.get("/api/applications").json() if item["id"] == application_id)
        assert listed["status"] == "skipped"
        assert listed["job"]["status"] == "skipped"
        assert listed["blocker"] is None


def test_review_blocker_rejects_ambiguous_empty_resolution():
    with TestClient(app) as client:
        job = _make_job(client, "Junior Empty Review Resolution Engineer")
        application_id, _ = _queue_and_claim(client, job)
        blocker = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "review_before_submit",
                "question": "Approve?",
                "explanation": "Ready",
            },
        ).json()
        response = client.post(f"/api/blockers/{blocker['id']}/resolve", json={})
        assert response.status_code == 400
        assert client.get(f"/api/blockers/{blocker['id']}/screenshot").status_code == 404


def test_legacy_v014_review_answer_is_upgraded_to_one_time_approval():
    with TestClient(app) as client:
        job = _make_job(client, "Junior Legacy Approval Engineer")
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        application_id = queued.json()["id"]
        _isolate_queue(application_id)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.answers_json = '{"אישור הגשה":"אשר ושלח"}'
            db.commit()
        task = client.get(
            "/api/agent/tasks/next", params={"agent_id": "legacy-test", "token": "change-me"}
        ).json()["task"]
        assert task["application"]["id"] == application_id
        assert task["submit_approved_once"] is True
        assert "אישור הגשה" not in task["answers"]


def test_stress_many_approval_and_manual_handoff_cycles_do_not_leak_permissions():
    with TestClient(app) as client:
        for index in range(50):
            job = _make_job(client, f"Approval Stress {index}")
            application_id, _ = _queue_and_claim(client, job)
            blocker = client.post(
                f"/api/agent/tasks/{application_id}/blocked",
                json={
                    "token": "change-me",
                    "kind": "review_before_submit",
                    "question": "Approve submission?",
                    "explanation": "Ready for final submission",
                    "page_url": f"https://example.com/stress/review/{index}",
                },
            ).json()
            response = client.post(
                f"/api/blockers/{blocker['id']}/resolve", json={"action": "approve_submit"}
            )
            assert response.status_code == 200
            task = client.get(
                "/api/agent/tasks/next", params={"agent_id": "stress-agent", "token": "change-me"}
            ).json()["task"]
            assert task["application"]["id"] == application_id
            assert task["submit_approved_once"] is True
            submitted = client.post(
                f"/api/agent/tasks/{application_id}/submitted",
                json={"token": "change-me", "message": "stress submitted", "verification_state": "verified", "evidence": [{"type": "confirmation_page", "value": "stress submitted"}]},
            )
            assert submitted.status_code == 200
            assert submitted.json()["status"] == "submitted"

        for index in range(50):
            job = _make_job(client, f"Captcha Stress {index}")
            application_id, _ = _queue_and_claim(client, job)
            exact_url = f"https://example.com/stress/captcha/{index}?token={index}"
            response = client.post(
                f"/api/agent/tasks/{application_id}/blocked",
                json={
                    "token": "change-me",
                    "kind": "captcha",
                    "question": "Human verification",
                    "explanation": "CAPTCHA requires manual completion",
                    "page_url": exact_url,
                },
            )
            assert response.status_code == 200
            listed = next(item for item in client.get("/api/applications").json() if item["id"] == application_id)
            assert listed["blocker"]["page_url"] == exact_url
            completed = client.post(f"/api/applications/{application_id}/mark-submitted")
            assert completed.status_code == 200
            assert completed.json()["status"] == "submitted"
def test_duplicate_submission_is_verified_as_an_existing_application():
    with TestClient(app) as client:
        job = _make_job(client, "Existing Lever Application")
        application_id, task = _queue_and_claim(client, job)
        response = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "attempt_id": task["attempt"]["id"],
                "kind": "duplicate_submission", "field_label": "הגשה קיימת",
                "question": "נמצאה מועמדות קודמת",
                "explanation": "Lever מציג שהמועמדות כבר הוגשה בעבר.",
                "options": [], "page_url": "https://jobs.lever.co/acme/applied",
            },
        )
        assert response.status_code == 200, response.text
        listed = next(item for item in client.get("/api/applications").json() if item["id"] == application_id)
        assert listed["status"] == "submitted"
        assert listed["verification_state"] == "verified"
        assert listed["blocker"] is None


def test_legacy_yes_question_can_be_rediscovered_without_guessing_an_answer():
    with TestClient(app) as client:
        job = _make_job(client, "Legacy Choice Rediscovery")
        application_id, _ = _queue_and_claim(client, job)
        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "choice_required", "field_label": "Yes",
                "question": "Yes", "explanation": "Old agent stored the option as the question.",
                "options": ["Yes", "No"], "page_url": "https://example.com/apply/choice",
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["legacy_choice_question"] is True
        resolved = client.post(
            f"/api/blockers/{blocked.json()['id']}/resolve",
            json={"action": "rediscover_question"},
        )
        assert resolved.status_code == 200, resolved.text
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            assert application.status == "queued"
            assert loads(application.answers_json, {}).get("Yes") is None
