from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import delete

import app.main as main
from app.database import Base, LOCAL_USER_ID, SHARED_CATALOG_USER_ID, engine, user_session
from app.models import AuditLog
from app.services.scan_runtime import (
    SCAN_EVENT,
    create_scan_run,
    persistent_scan_status,
    scheduled_scan_due,
    update_scan_run,
)
from app.services.seed import initialize_database
from app.utils import dumps, loads


def _clear_scan_runs() -> None:
    Base.metadata.create_all(bind=engine)
    with user_session(SHARED_CATALOG_USER_ID) as db:
        db.execute(delete(AuditLog).where(AuditLog.event_type == SCAN_EVENT))
        db.commit()


def test_external_scan_endpoint_queues_and_dispatches_without_running_collectors_on_web(monkeypatch):
    _clear_scan_runs()
    calls: list[str] = []
    monkeypatch.setattr(main.settings, "scan_execution_mode", "external")
    monkeypatch.setattr(main, "dispatch_scan_workflow", lambda mode="queued": calls.append(mode))

    async def forbidden_local_scan(*_args, **_kwargs):
        raise AssertionError("Render must not execute scan collectors in external mode")

    monkeypatch.setattr(main, "_run_scan", forbidden_local_scan)
    with TestClient(main.app) as client:
        response = client.post("/api/scan")
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        assert response.json()["worker"] == "github_actions"
        assert calls == ["queued"]

        status = client.get("/api/scan/status").json()
        assert status["running"] is True
        assert status["queued"] is True
        assert status["progress"]["phase"] == "queued"
        assert status["worker"] == "github_actions"
    _clear_scan_runs()


def test_external_scan_status_survives_process_memory_and_finishes_from_database(monkeypatch):
    _clear_scan_runs()
    monkeypatch.setattr(main.settings, "scan_execution_mode", "external")
    with user_session(LOCAL_USER_ID) as db:
        profile = main.get_user_profile(db)
        track = main.active_track(profile)
        log, created = create_scan_run(db, track, trigger="manual")
        assert created is True
        update_scan_run(
            db, log.entity_id, track,
            status="running", started=True,
            progress={"phase": "scanning", "completed": 2, "total": 5, "current_source": "Example"},
        )
        running = persistent_scan_status(db, track)
        assert running["running"] is True
        assert running["progress"]["completed"] == 2
        result = {"status": "ok", "sources": 5, "new": 3, "updated": 2, "per_source": []}
        update_scan_run(
            db, log.entity_id, track, status="ok", result=result, finished=True,
            progress={"phase": "done", "completed": 5, "total": 5, "current_source": None, "active_sources": []},
        )
        finished = persistent_scan_status(db, track)
        assert finished["running"] is False
        assert finished["last_result"]["new"] == 3
        assert finished["last_finished_at"]
    _clear_scan_runs()


def test_legacy_cron_endpoint_is_safe_in_external_mode(monkeypatch):
    monkeypatch.setattr(main.settings, "scan_execution_mode", "external")
    monkeypatch.setattr(main.settings, "cron_secret", "test-cron-secret")

    async def forbidden_local_scan(*_args, **_kwargs):
        raise AssertionError("Legacy cron endpoint must not execute collectors on Render")

    monkeypatch.setattr(main, "_run_scan", forbidden_local_scan)
    with TestClient(main.app) as client:
        response = client.post("/api/cron/scan", headers={"X-JobPilot-Cron-Secret": "test-cron-secret"})
        assert response.status_code == 202
        assert response.json() == {"status": "external_worker", "worker": "github_actions"}


def test_github_workflow_runs_worker_directly_and_render_image_has_no_chromium_install():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "jobpilot-scan.yml").read_text()
    dockerfile = (root / "Dockerfile").read_text()
    assert "scripts/run_cloud_scan.py" in workflow
    assert "secrets.JOBPILOT_DATABASE_URL" in workflow
    assert "--check-only" in workflow
    assert "steps.work.outputs.needed == 'true'" in workflow
    assert "playwright install --with-deps chromium" in workflow
    assert "/api/cron/scan" not in workflow
    assert "JOBPILOT_URL" not in workflow
    assert "playwright install" not in dockerfile


def test_application_workflow_is_headless_one_shot_and_uses_repository_secrets():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "jobpilot-application.yml").read_text()
    assert "secrets.JOBPILOT_AGENT_TOKEN" in workflow
    assert "secrets.JOBPILOT_BASE_URL" in workflow
    assert "JOBPILOT_WORKER_TYPE: cloud" in workflow
    assert "JOBPILOT_AGENT_HEADLESS: 'true'" in workflow
    assert "JOBPILOT_RUN_ONCE: 'true'" in workflow
    assert "python -m agent.run_agent" in workflow


def test_background_worker_connection_check_dispatches_without_claiming_a_real_application(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "dispatch_application_workflow", lambda application_id: calls.append(application_id))
    with TestClient(main.app) as client:
        response = client.post("/api/background-worker/test")
    assert response.status_code == 202
    assert response.json() == {"status": "dispatched", "worker": "github_actions"}
    assert calls == [0]



def test_duplicate_manual_scan_request_reuses_same_active_run():
    _clear_scan_runs()
    with user_session(LOCAL_USER_ID) as db:
        profile = main.get_user_profile(db)
        track = main.active_track(profile)
        first, created_first = create_scan_run(db, track, trigger="manual")
        second, created_second = create_scan_run(db, track, trigger="manual")
        assert created_first is True
        assert created_second is False
        assert second.entity_id == first.entity_id
    _clear_scan_runs()


def _set_scan_finished_at(log: AuditLog, *, status: str, finished_at: datetime) -> None:
    details = loads(log.details_json, {})
    details["status"] = status
    details["finished_at"] = finished_at.astimezone(timezone.utc).isoformat()
    details["result"] = {"status": status}
    log.details_json = dumps(details)


def test_scheduled_due_requires_successful_run_in_current_hour(monkeypatch):
    _clear_scan_runs()
    tz = ZoneInfo("Asia/Jerusalem")
    monkeypatch.setattr(main.settings, "timezone", "Asia/Jerusalem")
    now_local = datetime(2026, 8, 12, 9, 30, tzinfo=tz)

    with user_session(SHARED_CATALOG_USER_ID) as db:
        track = "computer_science"
        failed, _ = create_scan_run(db, track, trigger="scheduled")
        _set_scan_finished_at(failed, status="failed", finished_at=datetime(2026, 8, 12, 9, 10, tzinfo=tz))
        db.commit()
        due, scheduled, _latest = scheduled_scan_due(db, track, now_local=now_local)
        assert due is True
        assert scheduled.hour == 9 and scheduled.minute == 0

        successful, _ = create_scan_run(db, track, trigger="scheduled")
        _set_scan_finished_at(successful, status="ok", finished_at=datetime(2026, 8, 12, 9, 15, tzinfo=tz))
        db.commit()
        due, _scheduled, latest = scheduled_scan_due(db, track, now_local=now_local)
        assert due is False
        assert latest is not None
    _clear_scan_runs()

def test_external_dispatch_failure_marks_durable_run_failed(monkeypatch):
    _clear_scan_runs()
    monkeypatch.setattr(main.settings, "scan_execution_mode", "external")

    def fail_dispatch(_mode="queued"):
        raise RuntimeError("forced dispatch failure")

    monkeypatch.setattr(main, "dispatch_scan_workflow", fail_dispatch)
    with TestClient(main.app) as client:
        response = client.post("/api/scan")
        assert response.status_code == 503
        status = client.get("/api/scan/status").json()
        assert status["running"] is False
        assert status["status"] == "failed"
        assert "forced dispatch failure" in status["error"]
    _clear_scan_runs()
