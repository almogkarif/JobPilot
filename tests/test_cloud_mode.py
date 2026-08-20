from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.auth as auth_module
import app.storage as storage_module
from app.auth import AuthIdentity
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import AgentDevice, AppIdentity, Application, Job, ResumeProfile, Source, utcnow


def test_auth_config_never_exposes_server_keys(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_publishable_key", "publishable")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_SERVER_SECRET")
    monkeypatch.setattr(settings, "supabase_service_role_key", "LEGACY_SERVER_SECRET")
    with TestClient(app) as client:
        payload = client.get("/api/auth/config").json()
    assert payload["mode"] == "supabase"
    assert payload["supabase_publishable_key"] == "publishable"
    assert "SERVER_SECRET" not in str(payload)
    assert "LEGACY_SERVER_SECRET" not in str(payload)
    assert "secret" not in payload
    assert "service" not in payload


def test_cloud_mode_requires_auth_and_registers_first_user(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "owner_email", "owner@example.com")
    monkeypatch.setattr(settings, "storage_mode", "local")
    monkeypatch.setattr(auth_module, "verify_supabase_token", lambda token: AuthIdentity("user-123", "owner@example.com", "google"))
    with SessionLocal() as db:
        db.execute(delete(AppIdentity)); db.commit()
    with TestClient(app) as client:
        assert client.get("/api/profile").status_code == 401
        response = client.get("/api/profile", headers={"Authorization": "Bearer valid"})
        assert response.status_code == 200
        me = client.get("/api/auth/me", headers={"Authorization": "Bearer valid"}).json()
        assert me["user"]["id"] == "user-123"
    with SessionLocal() as db:
        owner = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == "user-123"))
        assert owner is not None
        assert owner.email == "owner@example.com"
        assert owner.role == "admin"


def test_cloud_mode_allowlist_rejects_uninvited_email(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "owner_email", "owner@example.com")
    monkeypatch.setattr(settings, "allowed_emails", "owner@example.com,friend@example.com")
    monkeypatch.setattr(auth_module, "verify_supabase_token", lambda token: AuthIdentity("intruder", "other@example.com", "google"))
    with TestClient(app) as client:
        response = client.get("/api/profile", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 403


def test_agent_device_tokens_are_one_time_hashed_and_revocable(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "owner_email", "owner@example.com")
    monkeypatch.setattr(settings, "application_agent_owner_email", "owner@example.com")
    monkeypatch.setattr(settings, "allow_legacy_agent_token", False)
    monkeypatch.setattr(auth_module, "verify_supabase_token", lambda token: AuthIdentity("user-123", "owner@example.com", "google"))
    with SessionLocal() as db:
        db.execute(delete(AgentDevice)); db.execute(delete(AppIdentity)); db.commit()
    headers = {"Authorization": "Bearer valid"}
    with TestClient(app) as client:
        created = client.post("/api/agent-devices", headers=headers, json={"name": "Primary Mac"})
        assert created.status_code == 200
        raw = created.json()["token"]
        device_id = created.json()["device"]["id"]
        assert raw.startswith("jp_agent_")
        with SessionLocal() as db:
            stored = db.get(AgentDevice, device_id)
            assert stored.token_hash != raw
            assert raw not in stored.token_hash
        assert client.get("/api/agent/tasks/next", params={"agent_id": "pytest"}, headers={"X-JobPilot-Agent-Token": raw}).status_code == 200
        assert client.delete(f"/api/agent-devices/{device_id}", headers=headers).status_code == 200
        assert client.get("/api/agent/tasks/next", params={"agent_id": "pytest"}, headers={"X-JobPilot-Agent-Token": raw}).status_code == 401


def test_agent_devices_list_connected_worker_before_unused_duplicate(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "owner_email", "owner@example.com")
    monkeypatch.setattr(settings, "application_agent_owner_email", "owner@example.com")
    monkeypatch.setattr(auth_module, "verify_supabase_token", lambda token: AuthIdentity("user-123", "owner@example.com", "google"))
    with SessionLocal() as db:
        db.execute(delete(AgentDevice)); db.execute(delete(AppIdentity)); db.commit()
    headers = {"Authorization": "Bearer valid"}
    with TestClient(app) as client:
        connected = client.post("/api/agent-devices", headers=headers, json={"name": "GitHub Actions Worker"}).json()
        client.get("/api/agent/tasks/next", params={"agent_id": "github-actions-test", "worker_type": "cloud", "application_id": 0},
                   headers={"X-JobPilot-Agent-Token": connected["token"]})
        unused = client.post("/api/agent-devices", headers=headers, json={"name": "GitHub Actions Worker"}).json()

        devices = client.get("/api/agent-devices", headers=headers).json()["devices"]

    assert devices[0]["id"] == connected["device"]["id"]
    assert devices[0]["last_seen_at"] is not None
    assert devices[1]["id"] == unused["device"]["id"]
    assert devices[1]["last_seen_at"] is None


def test_local_storage_adapter_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_mode", "local")
    monkeypatch.setattr(storage_module, "LOCAL_RESUMES", tmp_path / "resumes")
    ref = storage_module.save_bytes("resumes", "cv.txt", b"hello", "text/plain")
    assert Path(ref).is_file()
    assert storage_module.read_bytes(ref) == b"hello"
    storage_module.delete_ref(ref)
    assert not Path(ref).exists()


def test_supabase_storage_adapter_round_trip_contract(monkeypatch):
    monkeypatch.setattr(settings, "storage_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_SERVER_SECRET")
    monkeypatch.setattr(settings, "supabase_service_role_key", "")
    monkeypatch.setattr(settings, "supabase_storage_bucket", "jobpilot-private")
    monkeypatch.setattr(storage_module, "ensure_cloud_bucket", lambda: None)
    calls = []

    class FakeResponse:
        def __init__(self, status_code=200, content=b""):
            self.status_code = status_code
            self.content = content
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    def fake_post(url, **kwargs):
        calls.append(("POST", url, kwargs))
        return FakeResponse(200)

    def fake_get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        return FakeResponse(200, b"private-cv")

    def fake_delete(url, **kwargs):
        calls.append(("DELETE", url, kwargs))
        return FakeResponse(200)

    monkeypatch.setattr(storage_module.httpx, "post", fake_post)
    monkeypatch.setattr(storage_module.httpx, "get", fake_get)
    monkeypatch.setattr(storage_module.httpx, "delete", fake_delete)

    ref = storage_module.save_bytes("resumes", "resume test.pdf", b"private-cv", "application/pdf")
    assert ref == "supabase://jobpilot-private/resumes/resume test.pdf"
    assert storage_module.read_bytes(ref) == b"private-cv"
    storage_module.delete_ref(ref)

    assert [call[0] for call in calls] == ["POST", "GET", "DELETE"]
    assert "/storage/v1/object/jobpilot-private/resumes/resume%20test.pdf" in calls[0][1]
    assert "/storage/v1/object/authenticated/jobpilot-private/resumes/resume%20test.pdf" in calls[1][1]
    assert calls[2][2]["json"] == {"prefixes": ["resumes/resume test.pdf"]}
    for _, _, kwargs in calls:
        headers = kwargs["headers"]
        assert headers["apikey"] == "sb_secret_SERVER_SECRET"
        assert "Authorization" not in headers


def test_supabase_storage_legacy_service_role_uses_bearer(monkeypatch):
    monkeypatch.setattr(settings, "storage_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "")
    monkeypatch.setattr(settings, "supabase_service_role_key", "legacy.jwt.key")
    monkeypatch.setattr(settings, "supabase_storage_bucket", "jobpilot-private")
    headers = storage_module._cloud_headers("application/json")
    assert headers["apikey"] == "legacy.jwt.key"
    assert headers["Authorization"] == "Bearer legacy.jwt.key"


def test_agent_can_download_selected_resume_without_web_session(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "agent_token", "agent-test-token")
    resume_file = tmp_path / "private-cv.txt"
    resume_file.write_bytes(b"cloud-agent-resume")
    with TestClient(app) as client:
        with SessionLocal() as db:
            source = Source(name="Cloud Agent Test", kind="demo", identifier="cloud-agent-test", enabled=False)
            db.add(source); db.flush()
            job = Job(source_id=source.id, external_id="agent-resume", title="Test Role", company="Test",
                      location="Tel Aviv, Israel", apply_url="https://example.com/apply")
            db.add(job); db.flush()
            resume = ResumeProfile(label="Cloud CV", filename="קורות חיים מועמד.txt", path=str(resume_file), is_default=False)
            db.add(resume); db.flush()
            application = Application(job_id=job.id, resume_id=resume.id, resume_path=str(resume_file), status="queued")
            db.add(application); db.commit()
            application_id, source_id, resume_id = application.id, source.id, resume.id

        try:
            response = client.get(
                f"/api/agent/tasks/{application_id}/resume",
                params={"agent_id": "pytest-agent"},
                headers={"X-JobPilot-Agent-Token": "agent-test-token"},
            )
            assert response.status_code == 200
            assert response.content == b"cloud-agent-resume"
            disposition = response.headers["content-disposition"]
            assert 'filename="resume.txt"' in disposition
            assert "filename*=UTF-8''%D7%A7%D7%95%D7%A8%D7%95%D7%AA%20%D7%97%D7%99%D7%99%D7%9D%20%D7%9E%D7%95%D7%A2%D7%9E%D7%93.txt" in disposition
        finally:
            with SessionLocal() as db:
                application = db.get(Application, application_id)
                if application:
                    db.delete(application)
                    db.flush()
                resume = db.get(ResumeProfile, resume_id)
                if resume:
                    db.delete(resume)
                    db.flush()
                source = db.get(Source, source_id)
                if source:
                    db.delete(source)
                db.commit()


def test_cron_endpoint_rejects_missing_or_wrong_secret(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "storage_mode", "local")
    monkeypatch.setattr(settings, "cron_secret", "cron-secret")
    with TestClient(app) as client:
        assert client.post("/api/cron/scan").status_code == 401
        assert client.post("/api/cron/scan", headers={"X-JobPilot-Cron-Secret": "wrong"}).status_code == 401


def test_supabase_storage_namespaces_objects_by_user(monkeypatch):
    monkeypatch.setattr(settings, "storage_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_SERVER_SECRET")
    monkeypatch.setattr(settings, "supabase_service_role_key", "")
    monkeypatch.setattr(settings, "supabase_storage_bucket", "jobpilot-private")
    monkeypatch.setattr(storage_module, "ensure_cloud_bucket", lambda: None)

    class FakeResponse:
        status_code = 200
        content = b""
        def raise_for_status(self):
            return None

    calls = []
    monkeypatch.setattr(storage_module.httpx, "post", lambda url, **kwargs: calls.append(url) or FakeResponse())
    ref_a = storage_module.save_bytes("resumes", "cv.pdf", b"a", "application/pdf", owner_key="user-a")
    ref_b = storage_module.save_bytes("resumes", "cv.pdf", b"b", "application/pdf", owner_key="user-b")
    assert ref_a != ref_b
    assert "/users/user-a/resumes/cv.pdf" in ref_a
    assert "/users/user-b/resumes/cv.pdf" in ref_b
    assert any("users/user-a/resumes/cv.pdf" in url for url in calls)
    assert any("users/user-b/resumes/cv.pdf" in url for url in calls)


def test_worker_credentials_are_admin_only_but_regular_users_can_access_submission_flow(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "storage_mode", "local")
    monkeypatch.setattr(settings, "owner_email", "owner@example.com")
    monkeypatch.setattr(settings, "application_agent_owner_email", "owner@example.com")
    monkeypatch.setattr(settings, "allowed_emails", "owner@example.com,friend@example.com")
    monkeypatch.setattr(settings, "max_users", 10)
    monkeypatch.setattr(auth_module, "verify_supabase_token", lambda token: AuthIdentity("friend-agent-block", "friend@example.com", "google"))
    with SessionLocal() as db:
        db.execute(delete(AgentDevice).where(AgentDevice.user_id == "friend-agent-block"))
        db.execute(delete(AppIdentity).where(AppIdentity.auth_user_id == "friend-agent-block"))
        db.commit()
    try:
        headers = {"Authorization": "Bearer friend-token"}
        with TestClient(app) as client:
            assert client.get("/api/profile", headers=headers).status_code == 200
            me = client.get("/api/auth/me", headers=headers).json()
            assert me["capabilities"]["application_agent"] is True
            devices = client.get("/api/agent-devices", headers=headers)
            assert devices.status_code == 200
            assert devices.json()["available"] is False
            assert client.post("/api/agent-devices", headers=headers, json={"name": "Friend Mac"}).status_code == 403
            assert client.post("/api/jobs/999999/queue", headers=headers, json={"mode": "review"}).status_code == 404
    finally:
        with SessionLocal() as db:
            db.execute(delete(AgentDevice).where(AgentDevice.user_id == "friend-agent-block"))
            db.execute(delete(AppIdentity).where(AppIdentity.auth_user_id == "friend-agent-block"))
            db.commit()
