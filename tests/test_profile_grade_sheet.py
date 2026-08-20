from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from agent.fields import is_grade_sheet_file_label, is_resume_file_label, known_value
from app.database import SessionLocal
from app.main import app
from app.models import Application, Blocker, Profile


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"


def _make_job(client: TestClient) -> dict:
    unique = uuid4().hex
    response = client.post(
        "/api/jobs/import",
        json={
            "title": "Junior Software Engineer",
            "company": f"Grade Sheet {unique[:8]}",
            "location": "Tel Aviv, Israel",
            "description": "Junior Python software role with one year of experience.",
            "apply_url": f"https://jobs.eu.lever.co/test/{unique}/apply",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _claim_review_task(client: TestClient, application_id: int) -> dict:
    with SessionLocal() as db:
        for application in db.scalars(select(Application)).all():
            if application.id != application_id and application.status in {"queued", "applying", "needs_input"}:
                application.status = "skipped"
                application.job.status = "skipped"
        db.commit()
    response = client.get("/api/agent/tasks/next", params={"agent_id": "grade-test", "token": "change-me"})
    assert response.status_code == 200, response.text
    task = response.json()["task"]
    assert task and task["application"]["id"] == application_id
    return task


def test_file_labels_distinguish_resume_from_persistent_grade_sheet():
    profile = {"cv_path": "/tmp/resume.pdf", "grade_sheet_path": "/tmp/grades.pdf"}

    assert is_resume_file_label("Resume / CV") is True
    assert is_grade_sheet_file_label("Please submit your grade sheet: ✱ UPLOAD FILE") is True
    assert is_grade_sheet_file_label("Academic transcript") is True
    assert is_grade_sheet_file_label("גיליון ציונים") is True

    resume = known_value("Resume / CV", "file", profile, {}, [])
    grade_sheet = known_value("Please submit your grade sheet", "file", profile, {}, [])
    transcript = known_value("Academic transcript", "file", profile, {}, [])
    unrelated = known_value("Cover letter", "file", profile, {}, [])

    assert resume and resume.value == "/tmp/resume.pdf"
    assert grade_sheet and grade_sheet.value == "/tmp/grades.pdf"
    assert transcript and transcript.value == "/tmp/grades.pdf"
    assert unrelated is None


def test_profile_grade_sheet_upload_persists_and_agent_can_download_it():
    with TestClient(app) as client:
        uploaded = client.post(
            "/api/profile/grade-sheet",
            files={"file": ("technion-grades.pdf", _pdf_bytes(), "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text
        payload = uploaded.json()
        assert payload["filename"] == "technion-grades.pdf"
        assert payload["profile"]["grade_sheet_filename"] == "technion-grades.pdf"
        assert payload["profile"]["grade_sheet_uploaded"] is True

        profile_payload = client.get("/api/profile").json()
        assert profile_payload["grade_sheet_filename"] == "technion-grades.pdf"
        assert profile_payload["grade_sheet_uploaded"] is True

        # Grade sheet is personal/profile-wide, unlike the track-specific CV.
        switched = client.put("/api/career-tracks/active", json={"track": "industrial_engineering"})
        assert switched.status_code == 200, switched.text
        switched_profile = client.get("/api/profile").json()
        assert switched_profile["grade_sheet_filename"] == "technion-grades.pdf"
        assert switched_profile["grade_sheet_uploaded"] is True
        switched_back = client.put("/api/career-tracks/active", json={"track": "computer_science"})
        assert switched_back.status_code == 200, switched_back.text

        job = _make_job(client)
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        assert queued.status_code == 200, queued.text
        application_id = queued.json()["id"]
        task = _claim_review_task(client, application_id)
        assert task["profile"]["grade_sheet_path"]

        download = client.get(
            f"/api/agent/tasks/{application_id}/grade-sheet",
            params={"agent_id": "grade-test", "token": "change-me"},
        )
        assert download.status_code == 200, download.text
        assert download.content == _pdf_bytes()
        assert "grade-sheet.pdf" in download.headers["content-disposition"]


def test_uploading_grade_sheet_resolves_existing_lever_grade_sheet_blocker_and_requeues(monkeypatch):
    dispatched: list[int] = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))

    with TestClient(app) as client:
        job = _make_job(client)
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        assert queued.status_code == 200, queued.text
        application_id = queued.json()["id"]
        _claim_review_task(client, application_id)

        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "grade_sheet_required",
                "field_label": "גיליון ציונים",
                "question": "Please submit your grade sheet: ✱ UPLOAD FILE",
                "explanation": "Missing grade sheet in profile",
                "options": [".pdf", ".xlsx"],
                "page_url": "https://jobs.eu.lever.co/mobileye/example/apply",
            },
        )
        assert blocked.status_code == 200, blocked.text
        blocker_id = blocked.json()["id"]

        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()

        uploaded = client.post(
            "/api/profile/grade-sheet",
            files={"file": ("grades.pdf", _pdf_bytes(), "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text
        assert application_id in uploaded.json()["resumed_application_ids"]

        with SessionLocal() as db:
            blocker = db.get(Blocker, blocker_id)
            application = db.get(Application, application_id)
            profile = db.scalar(select(Profile).order_by(Profile.id).limit(1))
            assert blocker.status == "resolved"
            assert blocker.answer == "grades.pdf"
            assert application.status == "queued"
            assert application.job.status == "queued"
            assert profile.grade_sheet_filename == "grades.pdf"
            assert profile.grade_sheet_path

    assert dispatched == [application_id]


def test_legacy_submit_not_sent_grade_sheet_blocker_is_exposed_as_profile_document_request():
    with TestClient(app) as client:
        job = _make_job(client)
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        application_id = queued.json()["id"]
        _claim_review_task(client, application_id)
        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "submit_not_sent",
                "field_label": "שליחת המועמדות",
                "question": "הטופס לא יצא מ־Lever",
                "explanation": "Lever עצר את השליחה לפני שנשלחה בקשת POST. שדה שלא עבר ולידציה: Please submit your grade sheet: ✱ UPLOAD FILE",
                "page_url": "https://jobs.eu.lever.co/mobileye/example/apply",
            },
        )
        assert blocked.status_code == 200, blocked.text
        blocker = next(item for item in client.get("/api/blockers").json() if item["application_id"] == application_id)
        assert blocker["kind"] == "grade_sheet_required"
        assert blocker["field_label"] == "גיליון ציונים"
        assert "פרטים האישיים" in blocker["explanation"]
