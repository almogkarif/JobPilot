from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Application, ApplicationAttempt, ApplicationEvent, Blocker
from app.services.application_submission import (build_submission_preview, detect_adapter, issue_preview_token,
                                                     lever_confirmation_from_url, verify_preview_token)


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



def test_lever_confirmation_url_parser_accepts_only_strong_success_urls():
    evidence, application_id = lever_confirmation_from_url("https://jobs.eu.lever.co/mobileye/job-1/thanks")
    assert evidence
    assert application_id == ""
    evidence, application_id = lever_confirmation_from_url("https://www.lever.co/hp-b?LeverAppId=lever-123")
    assert "Lever accepted" in evidence
    assert application_id == "lever-123"
    assert lever_confirmation_from_url("https://jobs.eu.lever.co/mobileye/job-1/apply") == ("", "")


def test_timeline_reconciles_existing_pending_lever_confirmation_url():
    with TestClient(app) as client:
        job = client.post("/api/jobs/import", json={
            "title": "Lever Reconcile Engineer", "company": "Mobileye", "location": "Israel",
            "apply_url": "https://jobs.eu.lever.co/mobileye/reconcile-job/apply",
        }).json()
        application = client.post(f"/api/jobs/{job['id']}/mark-submitted").json()
        with SessionLocal() as db:
            row = db.get(Application, application["id"])
            row.status = "verification_pending"
            row.job.status = "verification_pending"
            row.submitted_at = None
            attempt = ApplicationAttempt(
                application_id=row.id, attempt_number=1, idempotency_key=f"lever-pending-{row.id}",
                adapter="lever", status="pending_verification", verification_state="uncertain",
                confirmation_url="https://jobs.eu.lever.co/mobileye/reconcile-job/thanks",
            )
            blocker = Blocker(
                application_id=row.id, kind="confirmation_missing", question="האם המועמדות נשלחה?",
                explanation="לא זוהה אישור", page_url="https://jobs.eu.lever.co/mobileye/reconcile-job/thanks",
            )
            db.add_all([attempt, blocker])
            db.commit()

        timeline = client.get(f"/api/applications/{application['id']}/timeline")
        assert timeline.status_code == 200
        payload = timeline.json()
        assert payload["application"]["status"] == "submitted"
        assert payload["application"]["blocker"] is None
        assert payload["attempts"][0]["verification_state"] == "verified"
        assert any(event["event_type"] == "submission_verified" for event in payload["events"])

def test_detects_supported_ats_families_without_trusting_company_names():
    assert detect_adapter("https://careers.wix.com/position/REF123-7440001").key == "wix"
    assert detect_adapter("https://boards.greenhouse.io/acme/jobs/123").key == "greenhouse"
    assert detect_adapter("https://www.comeet.com/jobs/acme/123").key == "comeet"
    assert detect_adapter("https://jobs.lever.co/acme/123").key == "lever"
    assert detect_adapter("https://acme.wd5.myworkdayjobs.com/jobs/123").key == "workday"
    assert detect_adapter("https://careers.example.com/jobs/123").key == "custom"


def test_intel_and_applied_materials_are_manual_only_even_on_supported_workday():
    for company, url in (
        ("Intel", "https://intel.wd1.myworkdayjobs.com/External/job/Israel/Test_R1"),
        ("Applied Materials", "https://amat.wd1.myworkdayjobs.com/External/job/Israel/Test_R2"),
    ):
        preview = build_submission_preview(
            SimpleNamespace(id=41, title="Engineer", company=company, apply_url=url,
                            source=SimpleNamespace(kind="workday")),
            _profile(application_password="saved-password"),
        )
        assert preview["ready"] is False
        assert preview["adapter"]["key"] == "workday"
        assert preview["adapter"]["execution"] == "manual_only"
        assert preview["adapter"]["supports_automatic_submit"] is False
        assert preview["adapter"]["exclusion_reason"]


def test_short_form_adapters_are_exposed_separately_from_multistep_workday():
    assert detect_adapter("https://careers.wix.com/position/REF123-7440001").form_flow == "single_page"
    assert detect_adapter("https://boards.greenhouse.io/acme/jobs/1").form_flow == "single_page"
    assert detect_adapter("https://jobs.lever.co/acme/1").form_flow == "single_page"
    assert detect_adapter("https://www.comeet.com/jobs/acme/1").form_flow == "single_page"
    assert detect_adapter("https://acme.wd1.myworkdayjobs.com/jobs/1").form_flow == "multi_step"


def test_excluded_employer_cannot_enter_visible_or_background_automation():
    with TestClient(app) as client:
        job = client.post("/api/jobs/import", json={
            "title": "Excluded Workday Test", "company": "Intel", "location": "Israel",
            "apply_url": "https://intel.wd1.myworkdayjobs.com/External/job/Israel/Test_R1",
        }).json()
        fetched = client.get(f"/api/jobs/{job['id']}").json()
        assert fetched["application_adapter"]["supports_automatic_submit"] is False
        assert fetched["application_adapter"]["execution"] == "manual_only"
        response = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"})
        assert response.status_code == 409
        assert "Intel" in response.json()["detail"]


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


def test_jobs_api_exposes_automatic_submission_capability():
    with TestClient(app) as client:
        jobs = client.get("/api/jobs").json()
    assert jobs
    assert all("application_adapter" in job for job in jobs)
    assert all(isinstance(job["application_adapter"]["supports_automatic_submit"], bool) for job in jobs)


def test_automatic_queue_rejects_missing_or_unapproved_preview():
    with TestClient(app) as client:
        job = next(item for item in client.get("/api/jobs").json() if item["status"] != "submitted")
        response = client.post(
            f"/api/jobs/{job['id']}/queue",
            json={"mode": "auto", "approve_submit": True, "preview_token": "invalid"},
        )
        assert response.status_code == 409


def test_campaign_config_dry_run_and_activation_require_exact_preview_token(monkeypatch):
    monkeypatch.setattr("app.main.dispatch_application_workflow", lambda _application_id: None)
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
        activated = client.post(
            f"/api/application-campaign/runs/{preview.json()['run_id']}/activate",
            json={"preview_token": preview.json()["preview_token"]},
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["activated"] is True
        assert activated.json()["queued_count"] == len(activated.json()["queued_job_ids"])


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
