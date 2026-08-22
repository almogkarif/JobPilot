from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.collectors.base import NormalizedJob
from app.database import Base, SessionLocal
from app.main import app
from app.models import Application, Blocker, Job, Profile, Source
from app.services import scanner
from app.services.job_cleanup import purge_foreign_jobs
from app.services.location_filter import is_israel_location
from app.utils import dumps


@pytest.mark.parametrize(
    "location",
    [
        "Israel",
        "Remote - Israel",
        "Tel Aviv, Israel",
        "Tel-Aviv Yafo",
        "Haifa",
        "Herzliya Pituach",
        "Petach Tikva",
        "Ra'anana",
        "Rishon LeZion",
        "Yokneam",
        "Beer Sheva",
        "Jerusalem / Hybrid",
        "תל אביב",
        "חיפה, ישראל",
        "פתח תקווה",
        "רמת גן",
        "ראשון לציון",
        "יקנעם עילית",
        "קריית גת",
        "רמת החייל",
    ],
)
def test_israel_location_is_accepted(location: str):
    assert is_israel_location(location) is True


@pytest.mark.parametrize(
    "location",
    [
        "",
        "Remote",
        "Worldwide Remote",
        "EMEA",
        "London, United Kingdom",
        "New York, NY",
        "Chicago, IL",  # IL is Illinois here, not Israel.
        "Paris, France",
        "Berlin, Germany",
        "Toronto, Canada",
        "Sydney, Australia",
        "Dubai, UAE",
        "Singapore",
    ],
)
def test_foreign_or_ambiguous_location_is_rejected(location: str):
    assert is_israel_location(location) is False


def _memory_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _profile() -> Profile:
    return Profile(
        id=1,
        full_name="Israel User",
        location="Israel",
        years_experience=0,
        skills_json=dumps(["Python", "C++"]),
        desired_titles_json=dumps(["software", "developer"]),
        preferred_locations_json=dumps(["Israel", "Tel Aviv", "Haifa"]),
        keywords_json=dumps(["graduate"]),
        excluded_keywords_json=dumps(["senior"]),
    )


def test_scanner_keeps_only_israel_jobs_and_reports_filtered_count(monkeypatch):
    class MixedLocationCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            now = datetime.now(timezone.utc)
            return [
                NormalizedJob(
                    external_id="israel-country",
                    title="Graduate Software Engineer",
                    company=company_name,
                    location="Israel",
                    workplace="remote",
                    description="Python graduate software role",
                    apply_url="https://example.com/israel-country",
                    published_at=now,
                ),
                NormalizedJob(
                    external_id="israel-city",
                    title="Junior C++ Developer",
                    company=company_name,
                    location="Tel Aviv",
                    workplace="hybrid",
                    description="C++ junior role",
                    apply_url="https://example.com/israel-city",
                    published_at=now,
                ),
                NormalizedJob(
                    external_id="foreign",
                    title="Software Engineer",
                    company=company_name,
                    location="London, United Kingdom",
                    workplace="onsite",
                    description="Software role",
                    apply_url="https://example.com/foreign",
                    published_at=now,
                ),
                NormalizedJob(
                    external_id="ambiguous-remote",
                    title="Remote Software Engineer",
                    company=company_name,
                    location="Remote",
                    workplace="remote",
                    description="Worldwide remote role",
                    apply_url="https://example.com/remote",
                    published_at=now,
                ),
            ]

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", MixedLocationCollector)
    db = _memory_session()
    db.add(_profile())
    source = Source(name="Mixed", kind="greenhouse", identifier="mixed", company_name="Mixed Co", enabled=True)
    db.add(source)
    db.commit()

    result = asyncio.run(scanner.scan_all_sources(db))
    assert result["status"] == "ok"
    assert result["collected"] == 4
    assert result["found"] == 2
    assert result["filtered_foreign"] == 2
    assert result["new"] == 2
    assert result["per_source"][0]["collected"] == 4
    assert result["per_source"][0]["found"] == 2
    assert result["per_source"][0]["filtered_foreign"] == 2

    jobs = db.scalars(select(Job).order_by(Job.external_id)).all()
    assert [job.external_id for job in jobs] == ["israel-city", "israel-country"]
    assert all(is_israel_location(job.location) for job in jobs)
    db.close()


def test_scanner_removes_legacy_foreign_jobs(monkeypatch):
    class IsraelOnlyCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            return [
                NormalizedJob(
                    external_id="israel-1",
                    title="Junior Developer",
                    company=company_name,
                    location="Haifa, Israel",
                    workplace="hybrid",
                    description="Python junior role",
                    apply_url="https://example.com/israel-1",
                    published_at=datetime.now(timezone.utc),
                )
            ]

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", IsraelOnlyCollector)
    db = _memory_session()
    db.add(_profile())
    source = Source(name="Legacy", kind="greenhouse", identifier="legacy", company_name="Legacy Co", enabled=True)
    db.add(source)
    db.flush()
    foreign = Job(
        source_id=source.id,
        external_id="old-london",
        title="Old Foreign Job",
        company="Legacy Co",
        location="London, UK",
        workplace="onsite",
        description="Old job",
        apply_url="https://example.com/old-london",
    )
    db.add(foreign)
    db.flush()
    application = Application(job_id=foreign.id, status="needs_input")
    db.add(application)
    db.flush()
    db.add(Blocker(application_id=application.id, question="Legacy question"))
    db.commit()

    result = asyncio.run(scanner.scan_all_sources(db))
    assert result["found"] == 1
    assert db.scalar(select(func.count()).select_from(Job)) == 1
    assert db.scalar(select(func.count()).select_from(Application)) == 0
    assert db.scalar(select(func.count()).select_from(Blocker)) == 0
    only_job = db.scalar(select(Job))
    assert only_job.external_id == "israel-1"
    db.close()


def test_purge_foreign_jobs_removes_related_application_and_blockers():
    db = _memory_session()
    db.add(_profile())
    source = Source(name="Purge", kind="greenhouse", identifier="purge", company_name="Purge Co", enabled=True)
    db.add(source)
    db.flush()
    local_job = Job(
        source_id=source.id,
        external_id="local",
        title="Local",
        company="Purge Co",
        location="Jerusalem",
        apply_url="https://example.com/local",
    )
    foreign_job = Job(
        source_id=source.id,
        external_id="foreign",
        title="Foreign",
        company="Purge Co",
        location="New York, NY",
        apply_url="https://example.com/foreign",
    )
    db.add_all([local_job, foreign_job])
    db.flush()
    application = Application(job_id=foreign_job.id, status="needs_input")
    db.add(application)
    db.flush()
    db.add(Blocker(application_id=application.id, question="Question"))
    db.commit()

    deleted = purge_foreign_jobs(db)
    assert deleted == 1
    assert db.scalar(select(func.count()).select_from(Job)) == 1
    assert db.scalar(select(Job)).external_id == "local"
    assert db.scalar(select(func.count()).select_from(Application)) == 0
    assert db.scalar(select(func.count()).select_from(Blocker)) == 0
    db.close()


def test_manual_import_rejects_foreign_or_ambiguous_locations():
    with TestClient(app) as client:
        for index, location in enumerate(["London, UK", "Remote", ""]):
            response = client.post(
                "/api/jobs/import",
                json={
                    "title": f"Foreign {index}",
                    "company": "Foreign Co",
                    "location": location,
                    "description": "Software role",
                    "apply_url": f"https://example.com/manual-foreign-{index}",
                },
            )
            assert response.status_code == 400
            assert "בישראל" in response.json()["detail"]


def test_delete_job_api_deletes_job_application_and_blocker():
    with TestClient(app) as client:
        imported = client.post(
            "/api/jobs/import",
            json={
                "title": "Delete Me Junior Developer",
                "company": "Delete Test",
                "location": "Tel Aviv, Israel",
                "description": "Python developer",
                "apply_url": "https://example.com/delete-me-v014",
            },
        )
        assert imported.status_code == 200
        job_id = imported.json()["id"]
        queued = client.post(f"/api/jobs/{job_id}/queue", json={"mode": "review"})
        assert queued.status_code == 200
        application_id = queued.json()["id"]

        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "unknown_field",
                "field_label": "Test field",
                "question": "Test question",
                "explanation": "Test blocker",
            },
        )
        assert blocked.status_code == 200
        blocker_id = blocked.json()["id"]

        deleted = client.delete(f"/api/jobs/{job_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert deleted.json()["hidden"] is True

        # Jobs are shared. Deleting from one workspace only hides/skips it for that
        # user and must preserve the shared listing plus application history.
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            assert job is not None
            assert db.get(Application, application_id) is not None
            assert db.get(Blocker, blocker_id) is not None
            from app.services.user_job_state import get_user_job_state
            state = get_user_job_state(db, job_id, create=False)
            assert state is not None
            assert state.status == "skipped"



def test_delete_missing_job_returns_404():
    with TestClient(app) as client:
        assert client.delete("/api/jobs/999999999").status_code == 404
