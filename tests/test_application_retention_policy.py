from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.collectors.base import NormalizedJob
from app.database import Base, SessionLocal
from app.main import app
from app.models import Application, Job, Profile, Source
from app.services import scanner
from app.services.job_cleanup import application_history_visible, purge_stale_jobs
from app.utils import dumps


def _memory_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _profile() -> Profile:
    return Profile(
        id=1,
        full_name="Retention User",
        location="Israel",
        years_experience=1,
        skills_json=dumps(["Python"]),
        desired_titles_json=dumps(["software", "developer"]),
        preferred_locations_json=dumps(["Israel"]),
        preferred_work_modes_json=dumps(["hybrid", "remote", "onsite"]),
        keywords_json=dumps([]),
        excluded_keywords_json=dumps([]),
    )


def _job(source: Source, external_id: str) -> Job:
    return Job(
        source_id=source.id,
        external_id=external_id,
        title="Software Engineer",
        company="Retention Co",
        location="Tel Aviv, Israel",
        workplace="hybrid",
        description="Python software engineering role",
        apply_url=f"https://example.com/{external_id}",
        published_at=datetime.now(timezone.utc),
    )


def test_missing_source_job_deletes_unsubmitted_application_immediately(monkeypatch):
    class EmptyCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            return []

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", EmptyCollector)
    db = _memory_session()
    db.add(_profile())
    source = Source(name="Retention", kind="greenhouse", identifier="retention", company_name="Retention Co")
    db.add(source)
    db.flush()
    job = _job(source, "queued-removed")
    db.add(job)
    db.flush()
    application = Application(job_id=job.id, status="queued", mode="auto")
    db.add(application)
    db.commit()
    job_id, application_id = job.id, application.id

    asyncio.run(scanner.scan_all_sources(db))

    assert db.get(Job, job_id) is None
    assert db.get(Application, application_id) is None
    db.close()


def test_missing_source_job_retains_submitted_application_for_30_days(monkeypatch):
    class EmptyCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            return []

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", EmptyCollector)
    db = _memory_session()
    db.add(_profile())
    source = Source(name="Retention Submitted", kind="greenhouse", identifier="retention-sub", company_name="Retention Co")
    db.add(source)
    db.flush()
    job = _job(source, "submitted-removed")
    db.add(job)
    db.flush()
    application = Application(
        job_id=job.id,
        status="submitted",
        mode="auto",
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(application)
    db.commit()
    job_id, application_id = job.id, application.id

    asyncio.run(scanner.scan_all_sources(db))

    retained = db.get(Job, job_id)
    retained_application = db.get(Application, application_id)
    assert retained is not None
    assert retained.is_active is False
    assert retained.removed_at is not None
    assert retained_application is not None
    assert application_history_visible(retained, retained_application) is True

    retained.removed_at = datetime.now(timezone.utc) - timedelta(days=31)
    # Updating the application/job status later must not silently restart retention.
    retained.updated_at = datetime.now(timezone.utc)
    db.commit()
    assert purge_stale_jobs(db, audit=False) == 1
    assert db.get(Job, job_id) is None
    assert db.get(Application, application_id) is None
    db.close()


def test_inactive_unsubmitted_application_is_never_visible_even_before_cleanup():
    db = _memory_session()
    db.add(_profile())
    source = Source(name="Hidden", kind="greenhouse", identifier="hidden", company_name="Retention Co")
    db.add(source)
    db.flush()
    job = _job(source, "hidden-unsubmitted")
    job.is_active = False
    job.removed_at = datetime.now(timezone.utc)
    db.add(job)
    db.flush()
    application = Application(job_id=job.id, status="saved", mode="review")
    db.add(application)
    db.commit()

    assert application_history_visible(job, application) is False
    assert purge_stale_jobs(db, audit=False) == 1
    assert db.get(Application, application.id) is None
    db.close()


def test_applications_api_hides_removed_unsubmitted_but_keeps_recent_submitted():
    marker = f"retention-api-{datetime.now(timezone.utc).timestamp()}"
    with TestClient(app) as client:
        unsubmitted_job_id = client.post("/api/jobs/import", json={
            "title": "Retention API Unsubmitted",
            "company": marker,
            "location": "Tel Aviv, Israel",
            "description": "Python software developer",
            "apply_url": f"https://example.com/{marker}-unsubmitted",
        }).json()["id"]
        unsubmitted_app_id = client.post(f"/api/jobs/{unsubmitted_job_id}/save").json()["id"]

        submitted_job_id = client.post("/api/jobs/import", json={
            "title": "Retention API Submitted",
            "company": marker,
            "location": "Tel Aviv, Israel",
            "description": "Python software developer",
            "apply_url": f"https://example.com/{marker}-submitted",
        }).json()["id"]
        submitted_app_id = client.post(f"/api/jobs/{submitted_job_id}/mark-submitted").json()["id"]

        with SessionLocal() as db:
            unsubmitted_job = db.get(Job, unsubmitted_job_id)
            unsubmitted_application = db.get(Application, unsubmitted_app_id)
            submitted_job = db.get(Job, submitted_job_id)
            unsubmitted_application.mode = "auto"
            unsubmitted_application.status = "queued"
            unsubmitted_job.is_active = False
            unsubmitted_job.removed_at = datetime.now(timezone.utc)
            submitted_job.is_active = False
            submitted_job.removed_at = datetime.now(timezone.utc)
            db.commit()

        auto_queue = client.get("/api/applications/auto-queue").json()
        queued_ids = ({auto_queue["current"]["id"]} if auto_queue.get("current") else set()) | {
            item["id"] for item in auto_queue.get("waiting", [])
        }
        assert unsubmitted_app_id not in queued_ids

        listed_ids = {item["id"] for item in client.get("/api/applications").json()}
        assert unsubmitted_app_id not in listed_ids
        assert submitted_app_id in listed_ids

        with SessionLocal() as db:
            submitted_job = db.get(Job, submitted_job_id)
            submitted_job.removed_at = datetime.now(timezone.utc) - timedelta(days=31)
            db.commit()

        listed_ids = {item["id"] for item in client.get("/api/applications").json()}
        assert submitted_app_id not in listed_ids

        # Clean up rows hidden by the API so this test does not leak into the suite.
        with SessionLocal() as db:
            purge_stale_jobs(db, audit=False)
