from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import ONE_TIME_SUBMIT_KEY, app
from app.models import Application
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
