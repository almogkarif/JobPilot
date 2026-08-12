from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event

import app.main as main_module
from app.auth import AuthIdentity, _touch_account
from app.config import settings
from app.database import engine
from app.main import app
from app.models import AppIdentity, utcnow
from app.services.career_tracks import COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING


def _query_count(callable_):
    count = 0

    def before_cursor_execute(*_args, **_kwargs):
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        result = callable_()
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return count, result


def test_career_switch_does_not_recompute_every_job_or_resume(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("career switching must not trigger full recomputation")

    monkeypatch.setattr(main_module, "_rescore_all_jobs", forbidden)
    monkeypatch.setattr(main_module, "_refresh_resume_analyses", forbidden)
    with TestClient(app) as client:
        client.put("/api/career-tracks/active", json={"track": COMPUTER_SCIENCE})
        response = client.put("/api/career-tracks/active", json={"track": INDUSTRIAL_ENGINEERING})
        assert response.status_code == 200, response.text
        client.put("/api/career-tracks/active", json={"track": COMPUTER_SCIENCE})


def test_common_read_endpoints_have_bounded_database_round_trips():
    with TestClient(app) as client:
        jobs_queries, jobs = _query_count(lambda: client.get("/api/jobs", params={
            "paginated": "true", "page": 1, "page_size": 20,
        }))
        applications_queries, applications = _query_count(lambda: client.get("/api/applications"))
        tracks_queries, tracks = _query_count(lambda: client.get("/api/career-tracks"))

        assert jobs.status_code == applications.status_code == tracks.status_code == 200
        assert jobs_queries <= 4
        assert applications_queries <= 4
        assert tracks_queries <= 4


def test_last_seen_write_is_throttled_without_delaying_real_identity_changes(monkeypatch):
    monkeypatch.setattr(settings, "owner_email", "")
    seen = utcnow()
    account = AppIdentity(
        auth_user_id="perf-user",
        email="same@example.com",
        role="user",
        claimed_at=seen - timedelta(days=1),
        last_seen_at=seen,
    )
    verified = AuthIdentity("perf-user", "same@example.com", "google")
    assert _touch_account(account, verified) is False
    assert account.last_seen_at == seen

    changed_identity = AuthIdentity("perf-user", "new@example.com", "google")
    assert _touch_account(account, changed_identity) is True
    assert account.email == "new@example.com"
