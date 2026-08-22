from __future__ import annotations

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.database import SessionLocal
from app.main import app
from app.models import Application, Blocker, Job, Source
from app.services.application_submission import automation_apply_url
from app.utils import loads

main_module = importlib.import_module("app.main")


_TEST_SOURCE_PREFIXES = ("taboola-test-", "taboola-retry-", "native-no-loop-")


def _cleanup_native_greenhouse_test_rows() -> None:
    """Remove persistent rows created by this module so later API tests stay isolated."""
    with SessionLocal() as db:
        try:
            sources = db.scalars(select(Source).order_by(Source.id)).all()
        except OperationalError:
            # Pure URL unit tests can run before TestClient has initialized the schema.
            return
        for source in sources:
            if not any(str(source.identifier or "").startswith(prefix) for prefix in _TEST_SOURCE_PREFIXES):
                continue
            for job in list(source.jobs):
                if job.application is not None:
                    db.delete(job.application)
                    db.flush()
            db.delete(source)
        db.commit()


@pytest.fixture(autouse=True)
def _isolate_native_greenhouse_rows():
    # The application test DB is intentionally shared across modules, so clean both
    # stale rows from a previous interrupted run and rows created by the current test.
    _cleanup_native_greenhouse_test_rows()
    yield
    _cleanup_native_greenhouse_test_rows()


def _clear_active_queue() -> None:
    with SessionLocal() as db:
        for row in db.scalars(select(Application)).all():
            if row.status in {"queued", "applying", "needs_input"}:
                row.status = "skipped"
                if row.job and row.job.status in {"queued", "applying", "needs_input"}:
                    row.job.status = "skipped"
        db.commit()


def test_greenhouse_company_branded_url_resolves_to_native_hosted_form():
    source = SimpleNamespace(kind="greenhouse", identifier="taboola")
    job = SimpleNamespace(
        source=source,
        external_id="8081260",
        apply_url="https://www.taboola.com/careers/job/algorithm-engineer-rtb?gh_jid=8081260",
    )
    assert automation_apply_url(job) == "https://job-boards.greenhouse.io/taboola/jobs/8081260"


def test_existing_hosted_greenhouse_url_stays_on_same_native_job():
    source = SimpleNamespace(kind="greenhouse", identifier="pagayais")
    job = SimpleNamespace(
        source=source, external_id="7811459003",
        apply_url="https://job-boards.greenhouse.io/pagayais/jobs/7811459003",
    )
    assert automation_apply_url(job) == job.apply_url


def test_non_greenhouse_url_is_left_unchanged():
    source = SimpleNamespace(kind="lever", identifier="mobileye")
    job = SimpleNamespace(source=source, external_id="abc", apply_url="https://jobs.lever.co/mobileye/abc/apply")
    assert automation_apply_url(job) == job.apply_url


def test_agent_task_uses_native_greenhouse_url_but_preserves_official_url():
    unique = uuid4().hex[:10]
    token = f"taboola-test-{unique}"
    official = "https://www.taboola.com/careers/job/algorithm-engineer-rtb?gh_jid=8081260"
    with TestClient(app) as client:
        _clear_active_queue()
        with SessionLocal() as db:
            source = Source(
                name=f"Taboola native URL {unique}", kind="greenhouse", identifier=token,
                company_name="Taboola", enabled=False,
            )
            db.add(source)
            db.flush()
            job = Job(
                source_id=source.id, external_id="8081260", title="Algorithm Engineer (RTB)", company="Taboola",
                location="Tel Aviv, Israel", description="Machine learning role", apply_url=official,
                source_url=official, is_active=True, status="queued",
            )
            db.add(job)
            db.flush()
            application = Application(job_id=job.id, status="queued", mode="auto")
            db.add(application)
            db.commit()
            application_id = application.id

        response = client.get(
            "/api/agent/tasks/next",
            params={
                "agent_id": "greenhouse-native-test", "token": "change-me",
                "worker_type": "cloud", "application_id": application_id,
            },
        )
        assert response.status_code == 200, response.text
        task = response.json()["task"]
        assert task["application"]["id"] == application_id
        assert task["job"]["official_apply_url"] == official
        assert task["job"]["apply_url"] == f"https://job-boards.greenhouse.io/{token}/jobs/8081260"


def test_old_submit_button_missing_blocker_is_requeued_once_on_native_greenhouse_url(monkeypatch):
    dispatched: list[int] = []
    monkeypatch.setattr(main_module, "dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    unique = uuid4().hex[:10]
    token = f"taboola-retry-{unique}"
    official = "https://www.taboola.com/careers/job/algorithm-engineer-rtb?gh_jid=8081260"
    with TestClient(app) as client:
        _clear_active_queue()
        with SessionLocal() as db:
            source = Source(
                name=f"Taboola retry {unique}", kind="greenhouse", identifier=token,
                company_name="Taboola", enabled=False,
            )
            db.add(source)
            db.flush()
            job = Job(
                source_id=source.id, external_id="8081260", title="Algorithm Engineer (RTB)", company="Taboola",
                location="Tel Aviv, Israel", description="Machine learning role", apply_url=official,
                source_url=official, is_active=True, status="needs_input",
            )
            db.add(job)
            db.flush()
            application = Application(job_id=job.id, status="needs_input", mode="auto", last_error="submit missing")
            db.add(application)
            db.flush()
            blocker = Blocker(
                application_id=application.id, status="open", kind="submit_button_missing",
                field_label="כפתור הגשה", question="איפה נמצא כפתור ההגשה?",
                explanation="מולאו 0 שדות, אך לא זוהה כפתור המשך או שליחה סופית.", page_url=official,
            )
            db.add(blocker)
            db.commit()
            application_id, blocker_id = application.id, blocker.id

        timeline = client.get(f"/api/applications/{application_id}/timeline")
        assert timeline.status_code == 200, timeline.text
        assert dispatched == [application_id]
        with SessionLocal() as db:
            application = db.get(Application, application_id)
            blocker = db.get(Blocker, blocker_id)
            assert application.status == "queued"
            assert application.job.status == "queued"
            assert blocker.status == "resolved"
            assert loads(application.answers_json, {}).get(main_module.GREENHOUSE_NATIVE_URL_AUTO_RETRY_KEY) == 1

        # Read-repair is idempotent: a second timeline read must not dispatch again.
        second = client.get(f"/api/applications/{application_id}/timeline")
        assert second.status_code == 200
        assert dispatched == [application_id]


def test_native_greenhouse_submit_missing_is_not_auto_retried_again(monkeypatch):
    dispatched: list[int] = []
    monkeypatch.setattr(main_module, "dispatch_application_workflow", lambda application_id: dispatched.append(application_id))
    unique = uuid4().hex[:10]
    token = f"native-no-loop-{unique}"
    native = f"https://job-boards.greenhouse.io/{token}/jobs/8081260"
    official = "https://www.taboola.com/careers/job/algorithm-engineer-rtb?gh_jid=8081260"
    with TestClient(app) as client:
        _clear_active_queue()
        with SessionLocal() as db:
            source = Source(name=f"Native no loop {unique}", kind="greenhouse", identifier=token, company_name="Taboola", enabled=False)
            db.add(source); db.flush()
            job = Job(source_id=source.id, external_id="8081260", title="Algorithm Engineer (RTB)", company="Taboola",
                      location="Tel Aviv, Israel", description="ML", apply_url=official, source_url=official,
                      is_active=True, status="needs_input")
            db.add(job); db.flush()
            application = Application(job_id=job.id, status="needs_input", mode="auto")
            db.add(application); db.flush()
            blocker = Blocker(application_id=application.id, status="open", kind="submit_button_missing",
                              field_label="כפתור הגשה", question="איפה נמצא כפתור ההגשה?",
                              explanation="native form issue", page_url=native)
            db.add(blocker); db.commit()
            application_id = application.id

        timeline = client.get(f"/api/applications/{application_id}/timeline")
        assert timeline.status_code == 200
        assert dispatched == []
        with SessionLocal() as db:
            assert db.get(Application, application_id).status == "needs_input"
