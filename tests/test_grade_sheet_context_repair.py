from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from agent.browser import _display_field_label
from app.database import SessionLocal
from app.main import app
from app.models import Application, Blocker


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"


def _mobileye_job(client: TestClient) -> dict:
    unique = uuid4().hex
    response = client.post(
        "/api/jobs/import",
        json={
            "title": "Algorithm & Software Engineer",
            "company": "Mobileye",
            "location": "Jerusalem, Israel",
            "description": "Software role with C++ and algorithms.",
            "apply_url": f"https://jobs.eu.lever.co/mobileye/{unique}/apply",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _claim_application(client: TestClient, application_id: int) -> None:
    with SessionLocal() as db:
        for application in db.scalars(select(Application)).all():
            if application.id != application_id and application.status in {"queued", "applying", "needs_input"}:
                application.status = "skipped"
                application.job.status = "skipped"
        db.commit()
    response = client.get("/api/agent/tasks/next", params={"agent_id": "grade-context", "token": "change-me"})
    assert response.status_code == 200, response.text
    assert response.json()["task"]["application"]["id"] == application_id


def test_generic_upload_button_uses_surrounding_grade_sheet_context():
    field = {
        "type": "file",
        "label": "UPLOAD FILE",
        "file_context": "Grade Sheet Submission Please submit your grade sheet: ✱",
        "name": "",
        "placeholder": "",
    }
    assert "grade sheet" in _display_field_label(field).casefold()


def test_existing_mobileye_upload_file_blocker_reuses_profile_grade_sheet(monkeypatch):
    dispatched: list[int] = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/profile/grade-sheet",
            files={"file": ("technion-grades.pdf", _pdf_bytes(), "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text

        job = _mobileye_job(client)
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        assert queued.status_code == 200, queued.text
        application_id = queued.json()["id"]
        _claim_application(client, application_id)

        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "file_required",
                "field_label": "UPLOAD FILE",
                "question": "UPLOAD FILE",
                "explanation": "זהו קובץ חובה נוסף שלא הוגדר בפרופיל.",
                "page_url": job["apply_url"],
            },
        )
        assert blocked.status_code == 200, blocked.text
        blocker_id = blocked.json()["id"]

        # The API read-repairs the old generic Lever label for the UI.
        blocker = next(item for item in client.get("/api/blockers").json() if item["id"] == blocker_id)
        assert blocker["kind"] == "grade_sheet_required"
        assert blocker["field_label"] == "גיליון ציונים"
        assert "grade sheet" in blocker["question"].casefold()

        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()

        resolved = client.post(
            f"/api/blockers/{blocker_id}/resolve",
            json={"action": "use_profile_grade_sheet"},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] == "resolved"

        with SessionLocal() as db:
            blocker_row = db.get(Blocker, blocker_id)
            application = db.get(Application, application_id)
            assert blocker_row.kind == "grade_sheet_required"
            assert blocker_row.answer == "technion-grades.pdf"
            assert application.status == "queued"
            assert application.last_error == ""

    assert dispatched == [application_id]
