from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.collectors.base import NormalizedJob, PreserveExistingJobs
from app.database import Base
from app.models import Job, Profile, Source
from app.services import scanner
from app.utils import dumps


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _profile() -> Profile:
    return Profile(
        id=1,
        full_name="Stress User",
        location="Israel",
        years_experience=0,
        skills_json=dumps(["Python", "C++", "Git"]),
        desired_titles_json=dumps(["software", "developer", "automation"]),
        preferred_locations_json=dumps(["Israel", "Haifa", "Tel Aviv"]),
        keywords_json=dumps(["Python", "C++", "graduate"]),
        excluded_keywords_json=dumps(["manual qa", "sales"]),
    )


def test_repeated_large_scans_do_not_duplicate_jobs(monkeypatch):
    class BulkCollector:
        limit = 40

        async def collect(self, identifier: str, company_name: str = ""):
            return [
                NormalizedJob(
                    external_id=f"{identifier}-{index}",
                    title=("Graduate Python Developer" if index % 2 == 0 else "Junior C++ Automation Engineer"),
                    company=company_name,
                    location=("Haifa, Israel" if index % 3 else "Tel Aviv, Israel"),
                    workplace="hybrid",
                    description="Python C++ Git software automation. 0-1 years experience.",
                    apply_url=f"https://example.com/{identifier}/{index}",
                    published_at=datetime.now(timezone.utc),
                )
                for index in range(self.limit)
            ]

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", BulkCollector)
    db = _session()
    db.add(_profile())
    for index in range(12):
        db.add(Source(
            name=f"Bulk {index}", kind="greenhouse", identifier=f"bulk-{index}",
            company_name=f"Company {index}", enabled=True,
        ))
    db.commit()

    first = asyncio.run(scanner.scan_all_sources(db))
    assert first["status"] == "ok"
    assert first["found"] == 480
    assert first["new"] == 480
    assert db.scalar(select(func.count()).select_from(Job)) == 480

    for _ in range(20):
        repeated = asyncio.run(scanner.scan_all_sources(db))
        assert repeated["status"] == "ok"
        assert repeated["found"] == 480
        assert repeated["new"] == 0
        assert repeated["updated"] == 480
        assert db.scalar(select(func.count()).select_from(Job)) == 480

    BulkCollector.limit = 20
    reduced = asyncio.run(scanner.scan_all_sources(db))
    assert reduced["found"] == 240
    assert db.scalar(select(func.count()).select_from(Job).where(Job.is_active.is_(True))) == 240
    assert db.scalar(select(func.count()).select_from(Job).where(Job.is_active.is_(False))) == 240
    db.close()


def test_one_broken_source_does_not_cancel_successful_sources(monkeypatch):
    class MixedCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            if identifier == "broken":
                raise RuntimeError("simulated upstream timeout")
            return [
                NormalizedJob(
                    external_id=f"{identifier}-1",
                    title="Graduate Software Engineer",
                    company=company_name,
                    location="Israel",
                    workplace="hybrid",
                    description="Python software role. 0-1 years experience.",
                    apply_url=f"https://example.com/{identifier}/1",
                    published_at=datetime.now(timezone.utc),
                )
            ]

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", MixedCollector)
    db = _session()
    db.add(_profile())
    db.add_all([
        Source(name="Good A", kind="greenhouse", identifier="good-a", company_name="A", enabled=True),
        Source(name="Broken", kind="greenhouse", identifier="broken", company_name="B", enabled=True),
        Source(name="Good C", kind="greenhouse", identifier="good-c", company_name="C", enabled=True),
    ])
    db.commit()

    result = asyncio.run(scanner.scan_all_sources(db))
    assert result["status"] == "partial"
    assert result["sources"] == 3
    assert result["successful_sources"] == 2
    assert result["failed_sources"] == 1
    assert result["found"] == 2
    assert result["new"] == 2
    assert result["errors"][0]["source"] == "Broken"
    assert db.scalar(select(func.count()).select_from(Job)) == 2
    db.close()


def test_temporary_access_block_preserves_last_good_source_snapshot(monkeypatch):
    class BlockedCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            raise PreserveExistingJobs("temporary bot protection")

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", BlockedCollector)
    db = _session()
    db.add(_profile())
    source = Source(name="Rafael", kind="greenhouse", identifier="rafael", company_name="Rafael", enabled=True)
    db.add(source)
    db.flush()
    job = Job(
        source_id=source.id, external_id="12345", title="FPGA Engineer", company="Rafael",
        location="Haifa, Israel", workplace="onsite", description="FPGA hardware",
        apply_url="https://career.rafael.co.il/job/12345/", is_active=True,
    )
    db.add(job)
    db.commit()

    result = asyncio.run(scanner.scan_all_sources(db))

    assert result["status"] == "ok"
    assert result["errors"] == []
    assert result["per_source"][0]["deferred"] is True
    assert db.get(Job, job.id).is_active is True
    assert db.get(Source, source.id).last_error == ""
    db.close()


def test_targeted_scan_refreshes_only_selected_sources(monkeypatch):
    class SelectedCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            return [NormalizedJob(
                external_id=f"{identifier}-1", title="Graduate Software Engineer", company=company_name,
                location="Tel Aviv, Israel", workplace="hybrid", description="Python C++ graduate role",
                apply_url=f"https://example.com/{identifier}/1", published_at=datetime.now(timezone.utc),
            )]

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", SelectedCollector)
    db = _session()
    db.add(_profile())
    source_a = Source(name="A", kind="greenhouse", identifier="a", company_name="A", enabled=True)
    source_b = Source(name="B", kind="greenhouse", identifier="b", company_name="B", enabled=True)
    db.add_all([source_a, source_b])
    db.commit()

    result = asyncio.run(scanner.scan_all_sources(db, source_ids={source_a.id}))
    assert result["sources"] == 1
    assert result["new"] == 1
    assert db.scalar(select(func.count()).select_from(Job).where(Job.source_id == source_a.id)) == 1
    assert db.scalar(select(func.count()).select_from(Job).where(Job.source_id == source_b.id)) == 0
    db.close()
