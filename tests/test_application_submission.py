from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import ApplicationAttempt, ApplicationEvent
from app.services.application_submission import (build_submission_preview, detect_adapter, issue_preview_token,
                                                     verify_preview_token)


def _profile(**overrides):
    values = {
        "full_name": "Demo Candidate", "email": "demo@example.com", "phone": "0501234567",
        "cv_path": "resumes/demo.pdf", "linkedin_url": "https://linkedin.com/in/demo",
        "application_password": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _job(url: str):
    return SimpleNamespace(
        id=41, title="Backend Engineer", company="Example", apply_url=url,
        source=SimpleNamespace(kind="official"),
    )


def test_detects_supported_ats_families_without_trusting_company_names():
    assert detect_adapter("https://boards.greenhouse.io/acme/jobs/123").key == "greenhouse"
    assert detect_adapter("https://www.comeet.com/jobs/acme/123").key == "comeet"
    assert detect_adapter("https://jobs.lever.co/acme/123").key == "lever"
    assert detect_adapter("https://acme.wd5.myworkdayjobs.com/jobs/123").key == "workday"
    assert detect_adapter("https://careers.example.com/jobs/123").key == "custom"


def test_preview_fails_closed_when_identity_or_resume_is_missing():
    preview = build_submission_preview(
        _job("https://boards.greenhouse.io/acme/jobs/123"),
        _profile(phone="", cv_path=""),
    )
    assert preview["ready"] is False
    assert {item["field"] for item in preview["missing"]} == {"phone", "resume"}
    assert preview["adapter"]["key"] == "greenhouse"
    assert len(preview["safeguards"]) == 4


def test_preview_token_is_scoped_expires_and_rejects_tampering(monkeypatch):
    monkeypatch.setattr("app.services.application_submission.time.time", lambda: 1_000)
    token = issue_preview_token(user_id="user-a", job_id=7, resume_id=3, ready=True)
    assert verify_preview_token(token, user_id="user-a", job_id=7, resume_id=3)["ok"] is True
    assert verify_preview_token(token, user_id="user-b", job_id=7, resume_id=3) is None
    assert verify_preview_token(token, user_id="user-a", job_id=8, resume_id=3) is None
    assert verify_preview_token(token + "x", user_id="user-a", job_id=7, resume_id=3) is None
    monkeypatch.setattr("app.services.application_submission.time.time", lambda: 2_000)
    assert verify_preview_token(token, user_id="user-a", job_id=7, resume_id=3) is None


def test_application_preview_api_exposes_adapter_and_short_lived_approval():
    with TestClient(app) as client:
        job = next(item for item in client.get("/api/jobs").json() if item["status"] != "submitted")
        response = client.get(f"/api/jobs/{job['id']}/application-preview")
        assert response.status_code == 200
        payload = response.json()
        assert payload["job"]["id"] == job["id"]
        assert payload["adapter"]["execution"] in {"cloud_browser", "manual_only"}
        assert payload["expires_in_seconds"] == 600
        assert payload["preview_token"]


def test_automatic_queue_rejects_missing_or_unapproved_preview():
    with TestClient(app) as client:
        job = next(item for item in client.get("/api/jobs").json() if item["status"] != "submitted")
        response = client.post(
            f"/api/jobs/{job['id']}/queue",
            json={"mode": "auto", "approve_submit": True, "preview_token": "invalid"},
        )
        assert response.status_code == 409


def test_campaign_config_dry_run_and_activation_require_exact_preview_token():
    with TestClient(app) as client:
        configured = client.patch("/api/application-campaign", json={
            "mode": "advanced", "min_score": 77, "daily_cap": 3,
            "budget_cap": 12, "blocked_companies": ["Blocked Ltd", "Blocked Ltd"],
        })
        assert configured.status_code == 200
        assert configured.json()["blocked_companies"] == ["Blocked Ltd"]
        preview = client.post("/api/application-campaign/dry-run")
        assert preview.status_code == 200
        assert preview.json()["expires_in_seconds"] == 600
        denied = client.post(
            f"/api/application-campaign/runs/{preview.json()['run_id']}/activate",
            json={"preview_token": "wrong"},
        )
        assert denied.status_code == 403


def test_application_timeline_exposes_verification_receipt_without_private_storage_path():
    with TestClient(app) as client:
        job = client.post("/api/jobs/import", json={
            "title": "Receipt Test Engineer", "company": "Receipt Test Company",
            "location": "Israel", "apply_url": "https://boards.greenhouse.io/receipt/jobs/991",
        }).json()
        application = client.post(f"/api/jobs/{job['id']}/mark-submitted").json()
        with SessionLocal() as db:
            attempt = ApplicationAttempt(
                application_id=application["id"], attempt_number=1, idempotency_key=f"receipt-{application['id']}",
                adapter="greenhouse", status="verified", verification_state="verified",
                confirmation_text="Thank you for applying", confirmation_url="https://example.com/confirmation",
                screenshot_path="private/screenshots/evidence.png", evidence_json='[{"type":"confirmation_page","value":"Thank you"}]',
            )
            db.add(attempt)
            db.flush()
            db.add(ApplicationEvent(application_id=application["id"], event_type="submission_verified",
                                    to_status="submitted", message="Application verified"))
            db.commit()
        timeline = client.get(f"/api/applications/{application['id']}/timeline")
        assert timeline.status_code == 200
        payload = timeline.json()
        assert payload["attempts"][0]["verification_state"] == "verified"
        assert payload["attempts"][0]["confirmation_text"] == "Thank you for applying"
        assert "private/screenshots" not in str(payload)
        assert payload["events"][0]["event_type"] == "submission_verified"
