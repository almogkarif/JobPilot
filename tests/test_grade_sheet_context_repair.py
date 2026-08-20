from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from agent.browser import (_display_field_label, _ensure_profile_documents_attached,
                           _lever_inferred_grade_sheet_field, _lever_profile_document_fallback)
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

    # A misleading control label must not beat an explicit grade-sheet question
    # from the nearest file-question container.
    field["label"] = "Resume/CV"
    assert "grade sheet" in _display_field_label(field).casefold()




def test_lever_single_unlabeled_custom_upload_uses_saved_grade_sheet_during_details():
    fields = [
        {
            "type": "file", "selector": "#resume", "label": "Resume/CV",
            "file_context": "Resume/CV", "name": "resume", "disabled": False,
        },
        {
            "type": "file", "selector": "#custom-upload", "label": "UPLOAD FILE",
            "file_context": "", "name": "cards[abc][field0]", "disabled": False,
        },
    ]
    assert _lever_inferred_grade_sheet_field(
        fields[1], fields, "https://jobs.eu.lever.co/mobileye/job-123/apply"
    ) is True
    candidate = _lever_profile_document_fallback(
        fields[1], fields, {"grade_sheet_path": "/tmp/technion-grades.pdf"},
        "https://jobs.eu.lever.co/mobileye/job-123/apply",
    )
    assert candidate is not None
    assert candidate.value == "/tmp/technion-grades.pdf"
    assert candidate.source == "profile_grade_sheet_inferred"


def test_saved_grade_sheet_is_attached_before_submit_without_playwright(tmp_path):
    resume = tmp_path / "resume.pdf"
    grades = tmp_path / "grades.pdf"
    resume.write_bytes(_pdf_bytes())
    grades.write_bytes(_pdf_bytes())

    class FakeLocator:
        def __init__(self):
            self.files = []
            self.first = self

        def evaluate(self, _script):
            return list(self.files)

        def set_input_files(self, value, timeout=0):
            self.files = [Path(value).name]

    class FakePage:
        url = "https://jobs.eu.lever.co/mobileye/job-123/apply"

        def __init__(self):
            self.locators = {"#resume": FakeLocator(), "#custom-upload": FakeLocator()}

        def locator(self, selector):
            return self.locators[selector]

    fields = [
        {
            "type": "file", "selector": "#resume", "label": "Resume/CV",
            "file_context": "Resume/CV", "name": "resume", "disabled": False,
        },
        {
            "type": "file", "selector": "#custom-upload", "label": "UPLOAD FILE",
            "file_context": "", "name": "cards[abc][field0]", "disabled": False,
        },
    ]
    page = FakePage()
    attached = _ensure_profile_documents_attached(
        page, fields, {"cv_path": str(resume), "grade_sheet_path": str(grades)}, {}, []
    )

    assert page.locators["#resume"].files == ["resume.pdf"]
    assert page.locators["#custom-upload"].files == ["grades.pdf"]
    assert {item["document"] for item in attached} == {"resume", "grade_sheet"}


def test_generic_lever_upload_is_not_inferred_for_other_employers():
    fields = [
        {"type": "file", "selector": "#resume", "label": "Resume/CV", "name": "resume", "disabled": False},
        {"type": "file", "selector": "#custom", "label": "UPLOAD FILE", "name": "cards[a][field0]", "disabled": False},
    ]
    assert _lever_profile_document_fallback(
        fields[1], fields, {"grade_sheet_path": "/tmp/grades.pdf"},
        "https://jobs.eu.lever.co/example-company/job-123/apply",
    ) is None


def test_lever_never_guesses_grade_sheet_when_multiple_unknown_uploads_exist():
    fields = [
        {"type": "file", "selector": "#resume", "label": "Resume/CV", "name": "resume", "disabled": False},
        {"type": "file", "selector": "#file-a", "label": "UPLOAD FILE", "name": "cards[a][field0]", "disabled": False},
        {"type": "file", "selector": "#file-b", "label": "UPLOAD FILE", "name": "cards[b][field0]", "disabled": False},
    ]
    profile = {"grade_sheet_path": "/tmp/technion-grades.pdf"}
    assert _lever_profile_document_fallback(
        fields[1], fields, profile, "https://jobs.eu.lever.co/mobileye/job-123/apply"
    ) is None
    assert _lever_profile_document_fallback(
        fields[2], fields, profile, "https://jobs.eu.lever.co/mobileye/job-123/apply"
    ) is None


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


def test_stored_grade_sheet_auto_resolves_auto_application_without_user_click(monkeypatch):
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
        application_id = queued.json()["id"]
        _claim_application(client, application_id)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()

        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "grade_sheet_required",
                "field_label": "גיליון ציונים",
                "question": "Please submit your grade sheet: ✱ UPLOAD FILE",
                "explanation": "Missing grade sheet",
                "page_url": job["apply_url"],
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["status"] == "resolved"
        assert blocked.json()["auto_resolved"] is True

        with SessionLocal() as db:
            application = db.get(Application, application_id)
            blocker = db.get(Blocker, blocked.json()["id"])
            assert application.status == "queued"
            assert application.last_error == ""
            assert blocker.answer == "technion-grades.pdf"
            assert blocker.status == "resolved"

        timeline = client.get(f"/api/applications/{application_id}/timeline")
        assert timeline.status_code == 200, timeline.text
        event_types = [event["event_type"] for event in timeline.json()["events"]]
        assert "grade_sheet_auto_requeued" in event_types
        assert "worker_dispatched" in event_types
        assert all(not key.startswith("__jobpilot_") for key in timeline.json()["application"]["answers"])

    assert dispatched == [application_id]


def test_existing_grade_sheet_blocker_is_read_repaired_without_click(monkeypatch):
    dispatched: list[int] = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/profile/grade-sheet",
            files={"file": ("technion-grades.pdf", _pdf_bytes(), "application/pdf")},
        )
        assert uploaded.status_code == 200
        job = _mobileye_job(client)
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        application_id = queued.json()["id"]
        _claim_application(client, application_id)

        # Simulate an already-open blocker created by the previous deployment.
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
        blocker_id = blocked.json()["id"]
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()

        timeline = client.get(f"/api/applications/{application_id}/timeline")
        assert timeline.status_code == 200, timeline.text
        assert timeline.json()["application"]["status"] == "queued"
        assert timeline.json()["application"]["blocker"] is None
        with SessionLocal() as db:
            blocker = db.get(Blocker, blocker_id)
            assert blocker.status == "resolved"
            assert blocker.answer == "technion-grades.pdf"

    assert dispatched == [application_id]




def test_legacy_grade_sheet_retry_marker_does_not_keep_fixed_uploader_stuck(monkeypatch):
    dispatched: list[int] = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))

    with TestClient(app) as client:
        client.post(
            "/api/profile/grade-sheet",
            files={"file": ("technion-grades.pdf", _pdf_bytes(), "application/pdf")},
        )
        job = _mobileye_job(client)
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        application_id = queued.json()["id"]
        _claim_application(client, application_id)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            application.answers_json = '{"__jobpilot_profile_grade_sheet_auto_retry__":1}'
            db.commit()

        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "grade_sheet_required", "field_label": "גיליון ציונים",
                "question": "Please submit your grade sheet", "explanation": "Missing", "page_url": job["apply_url"],
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["status"] == "resolved"
        assert blocked.json()["auto_resolved"] is True
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            assert application.status == "queued"

    assert dispatched == [application_id]


def test_stored_grade_sheet_auto_retry_is_bounded(monkeypatch):
    dispatched: list[int] = []
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda application_id: dispatched.append(application_id))

    with TestClient(app) as client:
        client.post(
            "/api/profile/grade-sheet",
            files={"file": ("technion-grades.pdf", _pdf_bytes(), "application/pdf")},
        )
        job = _mobileye_job(client)
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        application_id = queued.json()["id"]
        _claim_application(client, application_id)
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            application.mode = "auto"
            db.commit()

        first = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "grade_sheet_required", "field_label": "גיליון ציונים",
                "question": "Please submit your grade sheet", "explanation": "Missing", "page_url": job["apply_url"],
            },
        )
        assert first.json()["auto_resolved"] is True

        claimed = client.get(
            "/api/agent/tasks/next",
            params={
                "agent_id": "grade-context-cloud", "token": "change-me", "worker_type": "cloud",
                "application_id": application_id,
            },
        )
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["task"]["application"]["id"] == application_id
        second = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me", "kind": "grade_sheet_required", "field_label": "גיליון ציונים",
                "question": "Please submit your grade sheet", "explanation": "Still missing", "page_url": job["apply_url"],
            },
        )
        assert second.status_code == 200, second.text
        assert second.json()["status"] == "open"
        assert "לולאת ניסיונות" in second.json()["explanation"]
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            assert application.status == "needs_input"
            # Keep the shared test database clean for later grade-sheet upload tests.
            blocker = db.get(Blocker, second.json()["id"])
            blocker.status = "resolved"
            application.status = "skipped"
            application.job.status = "skipped"
            db.commit()

    assert dispatched == [application_id]
