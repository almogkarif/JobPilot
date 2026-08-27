from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.auth as auth_module
from app.auth import AuthIdentity
from app.config import settings
from app.database import Base, SHARED_CATALOG_USER_ID, SessionLocal, engine, ensure_compatibility_columns, user_session
from app.main import app
from app.models import AgentDevice, AppIdentity, Application, AuditLog, Blocker, Job, JobRanking, OpenAnswerDraft, Profile, ResumeProfile, Source, UserJobState, AnswerMemory

USERS = {
    "token-a": AuthIdentity("multi-user-a", "a@example.com", "google"),
    "token-b": AuthIdentity("multi-user-b", "b@example.com", "google"),
}


def _cleanup_user(user_id: str) -> None:
    Base.metadata.create_all(engine)
    ensure_compatibility_columns()
    # Use Core/ORM unscoped cleanup in FK-safe order.
    with SessionLocal() as db:
        for model in (Blocker, OpenAnswerDraft, Application, JobRanking, UserJobState, ResumeProfile, AnswerMemory, AuditLog, AgentDevice, Profile):
            db.execute(delete(model).where(model.user_id == user_id))
        db.execute(delete(AppIdentity).where(AppIdentity.auth_user_id == user_id))
        db.commit()


def test_two_cloud_users_share_catalog_but_keep_personal_state_isolated(monkeypatch):
    for identity in USERS.values():
        _cleanup_user(identity.user_id)
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "storage_mode", "local")
    monkeypatch.setattr(settings, "owner_email", "a@example.com")
    monkeypatch.setattr(settings, "allowed_emails", "a@example.com,b@example.com")
    monkeypatch.setattr(settings, "max_users", 10)
    monkeypatch.setattr(auth_module, "verify_supabase_token", lambda token: USERS[token])
    # This test verifies tenant isolation, not background ranking. Letting the
    # daemon ranking worker write the same local SQLite file makes the result depend
    # on timing and can produce unrelated ``database is locked`` failures.
    monkeypatch.setattr("app.main._queue_profile_derived_refresh", lambda *_args, **_kwargs: None)
    test_external_id = "shared-catalog-multiuser-test"
    shared_job_id = None

    try:
        with TestClient(app) as client:
            ha = {"Authorization": "Bearer token-a"}
            hb = {"Authorization": "Bearer token-b"}

            assert client.get("/api/profile", headers=ha).status_code == 200
            assert client.get("/api/profile", headers=hb).status_code == 200
            assert client.post("/api/profile/skills", headers=ha, json={"skill": "Tenant-A-Only"}).status_code == 200
            assert "Tenant-A-Only" in client.get("/api/profile", headers=ha).json()["skills"]
            assert "Tenant-A-Only" not in client.get("/api/profile", headers=hb).json()["skills"]

            switched = client.put("/api/career-tracks/active", headers=ha, json={"track": "industrial_engineering"})
            assert switched.status_code == 200
            assert client.get("/api/career-tracks", headers=ha).json()["active_track"] == "industrial_engineering"
            assert client.get("/api/career-tracks", headers=hb).json()["active_track"] == "computer_science"
            assert client.put("/api/career-tracks/active", headers=ha, json={"track": "computer_science"}).status_code == 200

            # Sources are one shared catalog. Both users see the exact same rows.
            sources_a = client.get("/api/sources", headers=ha).json()
            sources_b = client.get("/api/sources", headers=hb).json()
            assert sources_a and sources_b
            assert {item["id"] for item in sources_a} == {item["id"] for item in sources_b}

            # A is the owner/admin and may manage the shared catalog; B may not.
            source_row = sources_a[0]
            original_enabled = source_row["enabled"]
            denied = client.patch(f'/api/sources/{source_row["id"]}', headers=hb, json={"enabled": not original_enabled})
            assert denied.status_code == 403
            toggled = client.patch(f'/api/sources/{source_row["id"]}', headers=ha, json={"enabled": not original_enabled})
            assert toggled.status_code == 200
            visible_b = {item["id"]: item for item in client.get("/api/sources", headers=hb).json()}
            assert visible_b[source_row["id"]]["enabled"] is (not original_enabled)
            assert client.patch(f'/api/sources/{source_row["id"]}', headers=ha, json={"enabled": original_enabled}).status_code == 200

            # Manual scanning is also admin-only.
            assert client.post("/api/scan", headers=hb).status_code == 403

            roster = client.get("/api/admin/users", headers=ha)
            assert roster.status_code == 200
            assert roster.json()["max_users"] == 10
            roster_ids = {item["id"] for item in roster.json()["users"]}
            assert {"multi-user-a", "multi-user-b"}.issubset(roster_ids)
            assert client.get("/api/admin/users", headers=hb).status_code == 403

        with user_session(SHARED_CATALOG_USER_ID) as db:
            source = db.scalar(select(Source).where(Source.career_track == "computer_science"))
            job = Job(source_id=source.id, career_track="computer_science", external_id=test_external_id,
                      title="Shared Catalog Job", company="SharedCo", location="Tel Aviv, Israel",
                      apply_url="https://example.com/shared")
            db.add(job); db.commit(); shared_job_id = job.id

        with TestClient(app) as client:
            ha = {"Authorization": "Bearer token-a"}
            hb = {"Authorization": "Bearer token-b"}
            assert client.get(f"/api/jobs/{shared_job_id}", headers=ha).status_code == 200
            assert client.get(f"/api/jobs/{shared_job_id}", headers=hb).status_code == 200
            assert client.post(f"/api/jobs/{shared_job_id}/save", headers=ha).status_code == 200
            assert client.post(f"/api/jobs/{shared_job_id}/skip", headers=hb).status_code == 200
            assert client.get(f"/api/jobs/{shared_job_id}", headers=ha).json()["status"] == "saved"
            assert client.get(f"/api/jobs/{shared_job_id}", headers=hb).json()["status"] == "skipped"
    finally:
        for identity in USERS.values():
            _cleanup_user(identity.user_id)
        if shared_job_id is not None:
            with SessionLocal() as db:
                db.execute(delete(Job).where(Job.id == shared_job_id))
                db.commit()

def test_agent_token_is_bound_to_its_user(monkeypatch):
    for identity in USERS.values():
        _cleanup_user(identity.user_id)
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "storage_mode", "local")
    monkeypatch.setattr(settings, "owner_email", "a@example.com")
    monkeypatch.setattr(settings, "application_agent_owner_email", "a@example.com")
    monkeypatch.setattr(settings, "allowed_emails", "a@example.com,b@example.com")
    monkeypatch.setattr(settings, "max_users", 10)
    monkeypatch.setattr(settings, "allow_legacy_agent_token", False)
    monkeypatch.setattr(auth_module, "verify_supabase_token", lambda token: USERS[token])

    try:
        with TestClient(app) as client:
            ha = {"Authorization": "Bearer token-a"}
            hb = {"Authorization": "Bearer token-b"}
            client.get("/api/profile", headers=ha)
            client.get("/api/profile", headers=hb)
            token_a = client.post("/api/agent-devices", headers=ha, json={"name": "Mac A"}).json()["token"]
            denied = client.post("/api/agent-devices", headers=hb, json={"name": "Mac B"})
            assert denied.status_code == 403

        app_ids = {}
        for user_id, suffix in (("multi-user-a", "a"), ("multi-user-b", "b")):
            with user_session(user_id) as db:
                source = db.scalar(select(Source).where(Source.career_track == "computer_science"))
                job = Job(source_id=source.id, career_track="computer_science", external_id=f"agent-{suffix}",
                          title=f"Agent {suffix.upper()} Job", company=suffix.upper(), location="Israel",
                          apply_url=f"https://example.com/{suffix}")
                db.add(job); db.flush()
                application = Application(job_id=job.id, status="queued", mode="review")
                db.add(application); db.commit(); app_ids[user_id] = application.id

        with TestClient(app) as client:
            task_a = client.get("/api/agent/tasks/next", params={"agent_id": "agent-a"},
                                headers={"X-JobPilot-Agent-Token": token_a}).json()["task"]
            assert task_a["application"]["id"] == app_ids["multi-user-a"]
            # B's queued item remains private and unclaimed because B cannot pair an Agent.
            with user_session("multi-user-b") as db:
                application_b = db.get(Application, app_ids["multi-user-b"])
                assert application_b.status == "queued"
                application_b.mode = "auto"
                application_b.job.apply_url = "https://boards.greenhouse.io/example/jobs/123"
                db.commit()

            # The administrator-managed cloud credential may claim the exact
            # dispatched application for B, without exposing the credential to B.
            central_task = client.get("/api/agent/tasks/next", params={
                "agent_id": "github-actions-test", "worker_type": "cloud",
                "application_id": app_ids["multi-user-b"],
            }, headers={"X-JobPilot-Agent-Token": token_a}).json()["task"]
            assert central_task["application"]["id"] == app_ids["multi-user-b"]
            assert central_task["application"]["job"]["title"] == "Agent B Job"
    finally:
        for identity in USERS.values():
            _cleanup_user(identity.user_id)


def test_cloud_user_limit_is_enforced(monkeypatch):
    identities = {
        "limit-a": AuthIdentity("limit-user-a", "limit-a@example.com", "google"),
        "limit-b": AuthIdentity("limit-user-b", "limit-b@example.com", "google"),
        "limit-c": AuthIdentity("limit-user-c", "limit-c@example.com", "google"),
    }
    for identity in identities.values():
        _cleanup_user(identity.user_id)
    with SessionLocal() as db:
        db.execute(delete(AppIdentity))
        db.commit()
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "storage_mode", "local")
    monkeypatch.setattr(settings, "owner_email", "limit-a@example.com")
    monkeypatch.setattr(settings, "allowed_emails", ",".join(item.email for item in identities.values()))
    monkeypatch.setattr(settings, "max_users", 2)
    monkeypatch.setattr(auth_module, "verify_supabase_token", lambda token: identities[token])
    try:
        with TestClient(app) as client:
            assert client.get("/api/profile", headers={"Authorization": "Bearer limit-a"}).status_code == 200
            assert client.get("/api/profile", headers={"Authorization": "Bearer limit-b"}).status_code == 200
            assert client.get("/api/profile", headers={"Authorization": "Bearer limit-c"}).status_code == 403
    finally:
        for identity in identities.values():
            _cleanup_user(identity.user_id)


def test_cloud_unscoped_private_insert_is_blocked(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    Base.metadata.create_all(engine)
    ensure_compatibility_columns()
    with SessionLocal() as db:
        db.add(Profile(user_id="forged-user", full_name="Should Not Persist"))
        try:
            db.commit()
        except RuntimeError as exc:
            db.rollback()
            assert "authenticated user scope" in str(exc)
        else:
            raise AssertionError("Unscoped cloud insert unexpectedly succeeded")


def test_scan_progress_state_is_isolated_per_user():
    import app.main as main_module

    user_a = "scan-state-a"
    user_b = "scan-state-b"
    main_module.scan_states_by_user.pop(user_a, None)
    main_module.scan_states_by_user.pop(user_b, None)
    main_module._update_scan_progress(user_a, "computer_science", {
        "phase": "scanning", "current": 2, "completed": 1, "total": 5,
        "current_source": "A Source", "active_sources": ["A Source"],
    })
    main_module._update_scan_progress(user_b, "computer_science", {
        "phase": "scanning", "current": 7, "completed": 6, "total": 9,
        "current_source": "B Source", "active_sources": ["B Source"],
    })
    state_a = main_module._user_scan_states(user_a)["computer_science"]["progress"]
    state_b = main_module._user_scan_states(user_b)["computer_science"]["progress"]
    assert state_a["current_source"] == "A Source"
    assert state_a["completed"] == 1
    assert state_b["current_source"] == "B Source"
    assert state_b["completed"] == 6
    assert state_a is not state_b


def test_first_cloud_user_claims_legacy_migrated_workspace(monkeypatch):
    legacy_user = "legacy-owner"
    new_user = "claim-user-a"
    _cleanup_user(new_user)
    # Ensure the synthetic legacy workspace is clean without touching local-owner data.
    with SessionLocal() as db:
        for model in (Blocker, OpenAnswerDraft, Application, JobRanking, UserJobState, ResumeProfile, AnswerMemory, AuditLog, AgentDevice, Profile):
            db.execute(delete(model).where(model.user_id == legacy_user))
        db.execute(delete(AppIdentity))
        db.commit()
    with user_session(legacy_user) as db:
        db.add(Profile(full_name="Migrated Person", email="migrated@example.com"))
        db.commit()

    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "storage_mode", "local")
    monkeypatch.setattr(settings, "owner_email", "migrated@example.com")
    monkeypatch.setattr(settings, "allowed_emails", "migrated@example.com")
    monkeypatch.setattr(settings, "max_users", 10)
    monkeypatch.setattr(auth_module, "verify_supabase_token", lambda token: AuthIdentity(new_user, "migrated@example.com", "google"))
    try:
        with TestClient(app) as client:
            payload = client.get("/api/profile", headers={"Authorization": "Bearer claim"}).json()
            assert payload["full_name"] == "Migrated Person"
        with user_session(new_user) as db:
            profile = db.scalar(select(Profile))
            assert profile is not None
            assert profile.user_id == new_user
            assert profile.full_name == "Migrated Person"
        with SessionLocal() as db:
            assert db.scalar(select(Profile).where(Profile.user_id == legacy_user)) is None
    finally:
        _cleanup_user(new_user)
        with SessionLocal() as db:
            for model in (Blocker, OpenAnswerDraft, Application, JobRanking, UserJobState, ResumeProfile, AnswerMemory, AuditLog, AgentDevice, Profile):
                db.execute(delete(model).where(model.user_id == legacy_user))
            db.commit()


def test_configured_owner_keeps_admin_and_legacy_data_even_if_friend_logs_in_first(monkeypatch):
    legacy_user = "legacy-owner"
    friend_id = "friend-first-user"
    owner_id = "owner-second-user"
    for uid in (friend_id, owner_id):
        _cleanup_user(uid)
    with SessionLocal() as db:
        for model in (Blocker, OpenAnswerDraft, Application, JobRanking, UserJobState, ResumeProfile, AnswerMemory, AuditLog, AgentDevice, Profile):
            db.execute(delete(model).where(model.user_id == legacy_user))
        db.execute(delete(AppIdentity))
        db.commit()
    with user_session(legacy_user) as db:
        db.add(Profile(full_name="Original Local Owner", email="owner2@example.com"))
        db.commit()

    identities = {
        "friend-first": AuthIdentity(friend_id, "friend2@example.com", "google"),
        "owner-second": AuthIdentity(owner_id, "owner2@example.com", "google"),
    }
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "storage_mode", "local")
    monkeypatch.setattr(settings, "owner_email", "owner2@example.com")
    monkeypatch.setattr(settings, "allowed_emails", "owner2@example.com,friend2@example.com")
    monkeypatch.setattr(settings, "max_users", 10)
    monkeypatch.setattr(auth_module, "verify_supabase_token", lambda token: identities[token])
    try:
        with TestClient(app) as client:
            friend_headers = {"Authorization": "Bearer friend-first"}
            owner_headers = {"Authorization": "Bearer owner-second"}
            friend_profile = client.get("/api/profile", headers=friend_headers).json()
            friend_me = client.get("/api/auth/me", headers=friend_headers).json()
            assert friend_me["user"]["role"] == "user"
            assert friend_profile["full_name"] != "Original Local Owner"
            assert client.get("/api/admin/users", headers=friend_headers).status_code == 403

            owner_profile = client.get("/api/profile", headers=owner_headers).json()
            owner_me = client.get("/api/auth/me", headers=owner_headers).json()
            assert owner_me["user"]["role"] == "admin"
            assert owner_profile["full_name"] == "Original Local Owner"
            assert client.get("/api/admin/users", headers=owner_headers).status_code == 200
    finally:
        for uid in (friend_id, owner_id):
            _cleanup_user(uid)
        with SessionLocal() as db:
            for model in (Blocker, OpenAnswerDraft, Application, JobRanking, UserJobState, ResumeProfile, AnswerMemory, AuditLog, AgentDevice, Profile):
                db.execute(delete(model).where(model.user_id == legacy_user))
            db.commit()
