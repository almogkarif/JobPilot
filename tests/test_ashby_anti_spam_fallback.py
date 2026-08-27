from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Application, Blocker, Job
from app.services.application_queue_recovery import queue_health


SPAM_MESSAGE = (
    "Ashby rejected the application (GraphQL error): Your application submission was "
    "flagged as possible spam. If you believe this was a mistake, please submit your application again."
)


def _make_ashby_job(client: TestClient, title: str) -> dict:
    unique = uuid4().hex
    response = client.post(
        "/api/jobs/import",
        json={
            "title": title,
            "company": f"Ashby Guard {unique[:8]}",
            "location": "Tel Aviv, Israel",
            "description": "Junior software engineering role in Israel.",
            "apply_url": f"https://jobs.ashbyhq.com/acme/{unique}/application",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _queue_and_claim_review(client: TestClient, job_id: int) -> tuple[int, dict]:
    queued = client.post(f"/api/jobs/{job_id}/queue", json={"mode": "review"})
    assert queued.status_code == 200, queued.text
    application_id = queued.json()["id"]
    task_response = client.get(
        "/api/agent/tasks/next", params={"agent_id": "ashby-spam-test", "token": "change-me"}
    )
    assert task_response.status_code == 200, task_response.text
    task = task_response.json()["task"]
    assert task and task["application"]["id"] == application_id
    return application_id, task


def test_ashby_spam_rejection_becomes_manual_required_and_disables_retry(monkeypatch):
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: None)
    with TestClient(app) as client:
        job = _make_ashby_job(client, "Ashby spam fallback engineer")
        application_id, task = _queue_and_claim_review(client, job["id"])
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()

        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "attempt_id": task["attempt"]["id"],
                "kind": "submit_rejected",
                "field_label": "שליחת המועמדות",
                "question": "Ashby לא קיבל את המועמדות",
                "explanation": SPAM_MESSAGE,
                "page_url": job["apply_url"],
                "diagnostics": {"graphql_error_messages": [SPAM_MESSAGE]},
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["kind"] == "anti_automation_blocked"

        listed = next(item for item in client.get("/api/applications").json() if item["id"] == application_id)
        assert listed["status"] == "manual_required"
        assert listed["agent_stage"] == "נדרשת הגשה ידנית"
        assert listed["blocker"]["kind"] == "anti_automation_blocked"
        assert "לא ינסה שוב אוטומטית" in listed["blocker"]["explanation"]

        retry = client.post(f"/api/applications/{application_id}/retry?auto_submit=true")
        assert retry.status_code == 409
        assert "ידנית" in retry.text

        resolve = client.post(
            f"/api/blockers/{blocked.json()['id']}/resolve",
            json={"answer": "retry", "remember": False},
        )
        assert resolve.status_code == 409

        tracking = client.get("/api/applications/tracking-list").json()
        assert next(item for item in tracking if item["id"] == application_id)["status"] == "manual_required"

        diagnostics = client.get("/api/applications/failure-diagnostics").json()
        row = next(item for item in diagnostics["applications"] if item["application_id"] == application_id)
        assert row["status"] == "manual_required"
        assert row["yellow_question"]["kind"] == "anti_automation_blocked"
        assert diagnostics["status_summary"]["manual_required"] >= 1

        marked = client.post(f"/api/applications/{application_id}/mark-submitted")
        assert marked.status_code == 200, marked.text
        assert marked.json()["status"] == "submitted"


def test_existing_ashby_spam_rejection_is_repaired_without_one_more_retry():
    with TestClient(app) as client:
        job = _make_ashby_job(client, "Existing Ashby spam repair engineer")
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        assert queued.status_code == 200, queued.text
        application_id = queued.json()["id"]
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            application.status = "needs_input"
            application.job.status = "needs_input"
            application.last_error = f"[blocked:submit_rejected] {SPAM_MESSAGE}"
            db.add(Blocker(
                application_id=application_id,
                kind="submit_rejected",
                field_label="שליחת המועמדות",
                question="Ashby לא קיבל את המועמדות",
                explanation=SPAM_MESSAGE,
                page_url=job["apply_url"],
            ))
            db.commit()

        diagnostics = client.get("/api/applications/failure-diagnostics")
        assert diagnostics.status_code == 200, diagnostics.text
        row = next(item for item in diagnostics.json()["applications"] if item["application_id"] == application_id)
        assert row["status"] == "manual_required"
        assert row["yellow_question"]["kind"] == "anti_automation_blocked"

        with SessionLocal() as db:
            stored = db.get(Application, application_id)
            assert stored.status == "manual_required"
            blocker = db.scalar(select(Blocker).where(Blocker.application_id == application_id, Blocker.status == "open"))
            assert blocker and blocker.kind == "anti_automation_blocked"


def test_recent_ashby_spam_block_pauses_new_ashby_auto_apply():
    with TestClient(app) as client:
        first = _make_ashby_job(client, "Ashby cooldown seed engineer")
        queued = client.post(f"/api/jobs/{first['id']}/queue", json={"mode": "review"}).json()
        with SessionLocal() as db:
            application = db.get(Application, queued["id"])
            application.mode = "auto"
            application.status = "needs_input"
            application.job.status = "needs_input"
            application.last_error = f"[blocked:submit_rejected] {SPAM_MESSAGE}"
            db.add(Blocker(
                application_id=application.id, kind="submit_rejected", field_label="שליחת המועמדות",
                question="Ashby לא קיבל את המועמדות", explanation=SPAM_MESSAGE,
                page_url=first["apply_url"],
            ))
            db.commit()
        # Any normal API read repairs the known production shape and starts the cooldown.
        client.get("/api/applications")

        second = _make_ashby_job(client, "Ashby cooldown protected engineer")
        preview = client.get(f"/api/jobs/{second['id']}/application-preview")
        assert preview.status_code == 200, preview.text
        payload = preview.json()
        assert payload["ready"] is False
        assert payload["automatic_pause"]["kind"] == "anti_automation_blocked"
        assert payload["automatic_pause"]["manual_fallback"] is True
        assert any("השהה זמנית" in warning for warning in payload["warnings"])

        direct_auto_queue = client.post(f"/api/jobs/{second['id']}/queue", json={"mode": "auto"})
        assert direct_auto_queue.status_code == 409
        assert "Ashby" in direct_auto_queue.text

        # A job that was already queued before the spam signal must not cause the
        # hourly recovery loop to launch empty GitHub workers throughout the cooldown.
        with SessionLocal() as db:
            queued_job = db.get(Job, second["id"])
            queued_application = Application(job_id=queued_job.id, mode="auto", status="queued")
            db.add(queued_application)
            db.commit()
            db.refresh(queued_application)
            health = queue_health(db, queued_job.career_track)
            assert health[queued_application.id]["needs_dispatch"] is False
            assert health[queued_application.id]["stuck"] is False
